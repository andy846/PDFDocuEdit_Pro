"""Bounded diagnosis. Unsupported checks are reported, never inferred as OK."""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import replace
from pathlib import Path

import fitz

from core.pdf_runtime import qpdf_executable
from core.platform_service import PlatformService

from .appearances import AppearanceError, normal_appearance
from .model import PdfOperationError, PdfOperationPlan, PdfOptions, checked_source


class PdfCancelled(PdfOperationError):
    pass


def check_cancel(is_cancelled):
    if is_cancelled and is_cancelled():
        raise PdfCancelled("PDF operation cancelled; unpublished temporary output was removed.")


def file_hash(path, is_cancelled=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            check_cancel(is_cancelled)
            digest.update(block)
    return digest.hexdigest()


def open_pdf(path, password=""):
    doc = fitz.open(path)
    if not doc.is_pdf or not doc.page_count:
        doc.close()
        raise PdfOperationError("Use a PDF with at least one readable page.")
    encrypted = bool(doc.needs_pass)
    if encrypted and (not password or not doc.authenticate(password)):
        doc.close()
        raise PdfOperationError("This PDF requires its correct password.")
    # MuPDF 1.26.6 can damage decrypted annotation strings when needs_pass is
    # queried again after authentication. Capture it once before unlocking.
    doc._pdf_operation_encrypted = encrypted
    return doc


def structure_check(source, *, is_cancelled=None):
    try:
        result = PlatformService.run_cancellable([str(qpdf_executable()), "--check", str(source)],
                                                 is_cancelled=is_cancelled)
        return {"status": {0: "OK", 3: "Warning"}.get(result.returncode, "Error"),
                "backend": "qpdf", "message": (result.stdout + result.stderr)[-8000:],
                "coverage": "Syntax/structure only; not visual or semantic validation."}
    except (RuntimeError, OSError, ValueError) as exc:
        check_cancel(is_cancelled)
        return {"status": "Not checked", "backend": "qpdf", "message": str(exc)}


def recover_source(source, output, *, is_cancelled=None):
    result = PlatformService.run_cancellable([str(qpdf_executable()), str(source), str(output)],
                                             is_cancelled=is_cancelled)
    if result.returncode not in (0, 3) or not Path(output).is_file():
        raise PdfOperationError("Neither backend could recover a readable PDF: " + result.stderr[-3000:])
    return result.stderr[-3000:]


def analyse(source, options=None, *, password="", progress=None, is_cancelled=None):
    source = checked_source(source)
    options = options or PdfOptions()
    options.validate()
    digest = file_hash(source, is_cancelled)
    issues, annotations, widgets, signed, retained_hidden = [], 0, 0, False, 0
    try:
        opened = open_pdf(source, password)
    except (RuntimeError, PdfOperationError) as exc:
        if options.operation != "repair" or "password" in str(exc).lower():
            raise
        with tempfile.TemporaryDirectory(prefix="pdf-recovery-analysis-") as folder:
            recovered = Path(folder) / "recovered.pdf"
            message = recover_source(source, recovered, is_cancelled=is_cancelled)
            with open_pdf(recovered):
                pass
            plan = analyse(recovered, options, progress=progress, is_cancelled=is_cancelled)
            if file_hash(source, is_cancelled) != digest:
                raise PdfOperationError("Source changed during recovery analysis.") from exc
            diagnostics = {**plan.diagnostics, "recovery": {"status": "Warning", "original_unrenderable": True,
                            "message": "qpdf recovered a readable candidate. Original appearance cannot be compared. " + message}}
            return replace(plan, source=str(source), source_sha256=digest, diagnostics=diagnostics)
    with opened as doc:
        options.validate(doc.page_count)
        pages = set(options.pages) if options.pages is not None else range(doc.page_count)
        page_count = doc.page_count
        encrypted = doc._pdf_operation_encrypted
        diagnostics = {"structure": {"status": "Warning" if doc.is_repaired else "OK",
                                      "backend": "MuPDF", "opened_with_repair": bool(doc.is_repaired)},
                       "transparency": {"status": "Not checked", "message": "No exhaustive transparency inventory."},
                       "actions": {"status": "Not checked", "message": "Analysis is not a security audit."}}
        _, xfa = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/XFA")
        if xfa != "null" and (options.forms or options.operation == "repair"):
            issues.append("XFA forms are unsupported; their dynamic values cannot be safely normalised.")
        for index in range(page_count):
            check_cancel(is_cancelled)
            page = doc[index]
            all_widgets = list(page.widgets() or [])
            for widget in all_widgets:
                if widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    kind, _ = doc.xref_get_key(widget.xref, "V")
                    signed = signed or bool(widget.field_value) or kind not in ("null", "none")
            if index not in pages:
                continue
            all_annotations = [a.xref for a in page.annots() or []]
            entries = all_annotations if options.annotations else []
            form_entries = [w.xref for w in all_widgets] if options.forms else []
            annotations += len(all_annotations)
            widgets += len(all_widgets)
            if options.operation == "flatten" or options.mode == "normalise":
                if not options.rasterise:
                    for xref in [*entries, *form_entries]:
                        _, flags = doc.xref_get_key(xref, "F")
                        if flags.lstrip("-").isdigit() and int(flags) & (1 | 2 | 32):
                            retained_hidden += 1
                            continue
                        _, subtype = doc.xref_get_key(xref, "Subtype")
                        if subtype == "/Redact":
                            issues.append(f"Page {index + 1}, object {xref}: apply redactions before flattening.")
                        else:
                            try:
                                normal_appearance(doc, xref)
                            except AppearanceError as exc:
                                issues.append(f"Page {index + 1}: {exc}")
            if progress:
                progress(index + 1, page_count, f"Analyzing page {index + 1}/{page_count}")
        if retained_hidden:
            diagnostics["hidden_appearances"] = {"status": "Warning", "count": retained_hidden,
                "message": "Hidden/Invisible/NoView elements are retained, including their interaction. Only visible appearances will be flattened."}
        try:
            diagnostics["embedded_files"] = {"status": "OK", "count": doc.embfile_count(),
                                             "coverage": "Document embedded-file name tree; page attachment annotations separate."}
        except (RuntimeError, ValueError, SystemError) as exc:
            diagnostics["embedded_files"] = {"status": "Not checked", "message": str(exc)}
    if options.operation == "repair" and not encrypted:
        diagnostics["qpdf"] = structure_check(source, is_cancelled=is_cancelled)
    if file_hash(source, is_cancelled) != digest:
        raise PdfOperationError("Source changed during analysis. Analyze it again.")
    return PdfOperationPlan(str(source), digest, options, page_count, annotations, widgets,
                            signed, encrypted, tuple(issues), diagnostics)
