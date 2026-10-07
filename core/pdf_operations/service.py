"""Analyse-approved plans, generate privately, validate, then publish a job bundle."""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

import fitz
from PIL import Image, ImageChops

from composition.production.model import new_job_id
from core.io_atomic import atomic_output
from core.pdf_io import set_safe_pdf_metadata, validate_pdf_file
from core.pdf_runtime import qpdf_executable
from core.platform_service import PlatformService
from core.variables import VariableContext, resolve_filename

from .analysis import analyse, check_cancel, file_hash, open_pdf, recover_source, structure_check
from .appearances import flatten_page
from .model import PdfOperationError


@contextmanager
def _owned_document(document):
    try:
        yield document
    finally:
        if not document.is_closed:
            document.close()


def _raster_page(doc, index, dpi):
    page = doc[index]
    rotation = page.rotation
    page.set_rotation(0)
    try:
        width = math.ceil(page.rect.width * dpi / 72)
        height = math.ceil(page.rect.height * dpi / 72)
        if width * height > 40_000_000:
            raise PdfOperationError(f"Page {index + 1}: raster exceeds 40 million pixels; reduce the resolution.")
        pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
        for xref in [a.xref for a in page.annots() or []]:
            page.delete_annot(page.load_annot(xref))
        for xref in [w.xref for w in page.widgets() or []]:
            page.delete_widget(page.load_widget(xref))
        for link in page.get_links():
            page.delete_link(link)
        doc.xref_set_key(page.xref, "Contents", "[]")
        doc.xref_set_key(page.xref, "Resources", "<< >>")
        page = doc.reload_page(page)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        del pixmap
    finally:
        doc[index].set_rotation(rotation)


def _preflight(path, cancel, progress):
    from core.analysis import AnalysisRequest, inspect_and_analyze
    report = inspect_and_analyze(str(path), "pdf-operation", 0,
                                AnalysisRequest(preflight_profile="production"),
                                is_cancelled=cancel, progress=progress)
    findings = [asdict(f) for f in report.finding_set.findings]
    return {"errors": sum(f["severity"] == "error" for f in findings),
            "warnings": sum(f["severity"] == "warning" for f in findings), "findings": findings,
            "coverage": "Existing Production Preflight; not full PDF semantic validation."}


def _scrub(doc, options):
    # Never use scrub's defaults: they reset forms, remove hidden OCR text,
    # links and comments, and apply redactions.
    doc.scrub(attached_files=False, clean_pages=False, embedded_files=options.remove_attachments,
              hidden_text=False, javascript=options.remove_javascript, metadata=options.remove_metadata,
              redactions=False, remove_links=False, reset_fields=False, reset_responses=False,
              thumbnails=False, xml_metadata=options.remove_metadata)
    if options.remove_attachments:
        for index in range(doc.page_count):
            page = doc[index]
            for xref in [a.xref for a in page.annots() or [] if a.type[0] == fitz.PDF_ANNOT_FILE_ATTACHMENT]:
                page.delete_annot(page.load_annot(xref))


def _visual_qc(source, output, password, pages, *, output_password="", compare_visual=True, preserve_text=True,
               is_cancelled=None, progress=None):
    with open_pdf(source, password) as before, open_pdf(output, output_password) as after:
        if before.page_count != after.page_count:
            raise PdfOperationError("Output page count differs from the approved source.")
        for index in range(before.page_count):
            check_cancel(is_cancelled)
            old, new = before[index], after[index]
            if old.rotation != new.rotation or tuple(old.mediabox) != tuple(new.mediabox):
                raise PdfOperationError(f"Page {index + 1}: page size or rotation changed unexpectedly.")
            if compare_visual:
                if tuple(old.cropbox) != tuple(new.cropbox):
                    raise PdfOperationError(f"Page {index + 1}: CropBox changed unexpectedly.")
                for page in (old, new):
                    if page.rect.width * page.rect.height > 20_000_000:
                        raise PdfOperationError("Visual QC page is too large to inspect safely.")
                first, second = old.get_pixmap(alpha=False), new.get_pixmap(alpha=False)
                if (first.width, first.height) != (second.width, second.height):
                    raise PdfOperationError(f"Page {index + 1}: visible bounds changed.")
                delta = ImageChops.difference(Image.frombytes("RGB", (first.width, first.height), first.samples),
                                             Image.frombytes("RGB", (second.width, second.height), second.samples))
                if max(high for _, high in delta.getextrema()) > 3:
                    raise PdfOperationError(f"Page {index + 1}: visible appearance changed; output was not published.")
            if preserve_text or index not in pages:
                old_words, new_words = Counter(old.get_text().split()), Counter(new.get_text().split())
                if old_words - new_words:
                    raise PdfOperationError(f"Page {index + 1}: original searchable text was lost.")
            if progress:
                progress(index + 1, before.page_count, f"Validating page {index + 1}/{before.page_count}")


def _execute(plan, output_dir, *, password="", output_password="", output_permissions=None,
            output_name=None, job_id=None, progress=None, is_cancelled=None):
    options = plan.options
    options.validate(plan.page_count)
    if plan.issues:
        raise PdfOperationError("Resolve analysis issues before generation:\n" + "\n".join(plan.issues[:30]))
    if plan.signed and not options.acknowledge_signatures:
        raise PdfOperationError("Confirm that the derived copy cannot retain the original digital signature validity.")
    raster = options.rasterise or (options.operation == "repair" and options.mode == "maximum")
    if raster and not options.acknowledge_raster:
        raise PdfOperationError("Confirm rasterisation: vectors, searchable text and page interactions may be lost.")
    recovered_source = bool(plan.diagnostics.get("recovery", {}).get("original_unrenderable"))
    if recovered_source and not options.acknowledge_recovery:
        raise PdfOperationError("Confirm recovery limitations: the original PDF could not be rendered for appearance comparison.")
    if plan.encrypted and not output_password:
        raise PdfOperationError("Encrypted sources need an explicit output password; silent decryption is not permitted.")
    if file_hash(plan.source, is_cancelled) != plan.source_sha256:
        raise PdfOperationError("Source changed since analysis. Analyze and approve again.")
    root = Path(output_dir).expanduser().resolve()
    identity = job_id or new_job_id()
    if not identity or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in identity) or len(identity) > 80:
        raise PdfOperationError("Invalid PDF job identity.")
    root.mkdir(parents=True, exist_ok=True)
    final = root / identity
    if final.exists():
        raise PdfOperationError("That output job already exists. Choose a new job.")
    context = VariableContext.for_job(input_path=plan.source, job_id=identity)
    naming = output_name or ("{{input.stem}}_flattened.pdf" if options.operation == "flatten" else "{{input.stem}}_repaired.pdf")
    resolved = resolve_filename(naming, context, extension=".pdf")
    output = final / resolved.value
    if len(str(output).encode("utf-16-le")) // 2 > 240:
        raise PdfOperationError("Output path is too long. Choose a shorter output folder.")
    changes, warnings = [], list(resolved.issues)
    if plan.diagnostics.get("hidden_appearances"):
        warnings.append(plan.diagnostics["hidden_appearances"]["message"])
    if plan.signed:
        warnings.append("Derived PDF does not retain original digital-signature validity.")
    if recovered_source:
        warnings.append("Original PDF was unreadable by MuPDF. QC compares against qpdf's recovered baseline, not the original appearance.")
    with tempfile.TemporaryDirectory(prefix=".pdf-operation-", dir=root) as folder:
        staging = Path(folder)
        unlocked = staging / "source-snapshot.pdf"
        candidate = staging / "candidate.pdf"
        reference_source = plan.source
        if recovered_source:
            reference_source = str(staging / "recovered-source.pdf")
            recover_source(plan.source, reference_source, is_cancelled=is_cancelled)
        with _owned_document(open_pdf(reference_source, password)) as doc:
            if doc.page_count != plan.page_count:
                raise PdfOperationError("Source page count differs from the approved analysis.")
            doc.save(unlocked, garbage=0, deflate=False, clean=False, encryption=fitz.PDF_ENCRYPT_NONE)
            permissions = doc.permissions if output_permissions is None else output_permissions
            before = _preflight(unlocked, is_cancelled, progress) if options.preflight else None
            selected = options.pages if options.pages is not None else tuple(range(doc.page_count))
            if options.operation == "repair" and not raster:
                diagnostics = structure_check(unlocked, is_cancelled=is_cancelled)
                if diagnostics["status"] == "Not checked":
                    raise PdfOperationError(diagnostics["message"])
                if progress:
                    progress(0, 0, "Rewriting PDF structure with qpdf")
                result = PlatformService.run_cancellable(
                    [str(qpdf_executable()), str(unlocked), str(candidate)], is_cancelled=is_cancelled)
                if result.returncode not in (0, 3):
                    raise PdfOperationError("Structural rewrite failed: " + result.stderr[-4000:])
                if result.returncode == 3:
                    warnings.append("qpdf rewrite completed with warnings: " + result.stderr[-2000:])
                doc.close()
                doc = open_pdf(candidate)
                changes.append({"action": "structural_rewrite", "backend": "qpdf", "scope": "document"})
            try:
                if options.operation == "repair" and options.mode == "normalise":
                    if options.remove_javascript or options.remove_attachments or options.remove_metadata:
                        _scrub(doc, options)
                    for key in ("remove_javascript", "remove_attachments", "remove_metadata"):
                        if getattr(options, key):
                            changes.append({"action": key, "scope": "document"})
                    if options.normalise_boxes:
                        for index in selected:
                            page = doc[index]
                            media = page.mediabox
                            crop = page.cropbox & media
                            if crop.is_empty:
                                raise PdfOperationError(f"Page {index + 1}: page boxes cannot be safely normalised.")
                            if crop != page.cropbox:
                                page.set_cropbox(crop)
                                changes.append({"action": "cropbox_clipped_to_mediabox", "page": index + 1})
                transform = options.operation == "flatten" or options.mode == "normalise" or raster
                for ordinal, index in enumerate(selected, 1):
                    check_cancel(is_cancelled)
                    if transform:
                        if raster:
                            _raster_page(doc, index, options.dpi)
                            changes.append({"action": "rasterised", "page": index + 1, "dpi": options.dpi})
                        else:
                            count = flatten_page(doc, index, annotations=options.annotations, widgets=options.forms)
                            if count:
                                changes.append({"action": "appearances_flattened", "page": index + 1, "objects": count})
                    if progress:
                        progress(ordinal, len(selected), f"Processing page {index + 1}")
                if options.operation == "repair" and options.mode == "safe":
                    cleaned = {k: v for k, v in doc.metadata.items() if k in ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate", "trapped")}
                    from core.pdf_io import sanitize_pdf_metadata
                    if cleaned != sanitize_pdf_metadata(cleaned):
                        set_safe_pdf_metadata(doc, cleaned)
                        changes.append({"action": "metadata_encoding_normalised", "scope": "Info dictionary"})
                garbage = 4 if options.operation == "repair" and options.mode == "normalise" else 1
                save = {"garbage": garbage, "deflate": True, "clean": False}
                if options.operation == "repair":
                    changes.append({"action": "garbage_collection", "level": garbage,
                                    "scope": "document", "removed_object_count": None})
                if output_password:
                    save.update(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=output_password,
                                owner_pw=output_password, permissions=int(permissions))
                published_pdf = staging / resolved.value
                doc.save(published_pdf, **save)
            finally:
                doc.close()
        check_cancel(is_cancelled)
        validate_pdf_file(published_pdf, password=output_password or None, expected_page_count=plan.page_count)
        syntax = structure_check(published_pdf, is_cancelled=is_cancelled) if not output_password else {
            "status": "Not checked", "message": "Encrypted output validated by authenticated MuPDF; qpdf needs a private password channel."}
        if syntax["status"] == "Error":
            raise PdfOperationError("Output failed structural validation: " + syntax.get("message", ""))
        if syntax["status"] == "Warning":
            warnings.append("Output structural check has warnings: " + syntax.get("message", ""))
        _visual_qc(reference_source, published_pdf, password, set(selected) if transform else set(),
                   output_password=output_password, preserve_text=not raster,
                   compare_visual=not raster and not options.normalise_boxes and not options.remove_attachments,
                   is_cancelled=is_cancelled, progress=progress)
        after = None
        if options.preflight:
            with open_pdf(published_pdf, output_password) as validated:
                validated.save(staging / "preflight.pdf", encryption=fitz.PDF_ENCRYPT_NONE)
            after = _preflight(staging / "preflight.pdf", is_cancelled, progress)
            if after["errors"] and not options.allow_preflight_errors:
                raise PdfOperationError(f"Production Preflight found {after['errors']} error(s). Review or explicitly save a Needs review copy.")
            (staging / "preflight.pdf").unlink()
        if file_hash(plan.source, is_cancelled) != plan.source_sha256:
            raise PdfOperationError("Source changed during generation. Output was not published.")
        report = {"report_version": 1, "job_id": identity, "status": "needs_review" if recovered_source or (after and after["errors"]) else "completed",
                  "operation": options.operation, "source": plan.source, "source_sha256": plan.source_sha256,
                  "output_pdf": str(output), "report_dir": str(final), "pages": plan.page_count,
                  "options": asdict(options), "changes": changes, "warnings": warnings,
                  "diagnostics": plan.diagnostics, "preflight_before": before, "preflight_after": after,
                  "structure_after": syntax,
                  "validation": {"readable": True, "visual_comparison": "recovered baseline only" if recovered_source else
                                 "not performed" if raster or options.normalise_boxes or options.remove_attachments else "passed",
                                 "backend": "MuPDF " + fitz.VersionBind}}
        with atomic_output(staging / "job.json") as temp:
            temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with (staging / "control.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Job ID", "Source", "Output", "Operation", "Status", "Pages", "Changes"])
            values = [identity, plan.source, str(output), options.operation, report["status"], plan.page_count,
                      json.dumps(changes, ensure_ascii=False)]
            writer.writerow(["'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for v in values])
        unlocked.unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        if recovered_source:
            Path(reference_source).unlink()
        check_cancel(is_cancelled)
        os.rename(staging, final)
    return report


def execute(plan, output_dir, **kwargs):
    """Retain a failure audit; never publish an unsuccessful PDF."""
    identity = kwargs.get("job_id") or new_job_id()
    kwargs["job_id"] = identity
    try:
        return _execute(plan, output_dir, **kwargs)
    except Exception as exc:
        # Audit creation is best effort if the folder itself is inaccessible;
        # it must not hide the actual production failure or write passwords.
        try:
            root = Path(output_dir).expanduser().resolve()
            folder = root / ("failed-" + new_job_id())
            folder.mkdir(parents=True, exist_ok=False)
            from .analysis import PdfCancelled
            report = {"report_version": 1, "job_id": identity,
                      "status": "cancelled" if isinstance(exc, PdfCancelled) else "failed",
                      "source": plan.source, "source_sha256": plan.source_sha256,
                      "options": asdict(plan.options), "output_pdf": "", "report_dir": str(folder),
                      "error": str(exc), "changes": [], "published_files": 0}
            with atomic_output(folder / "job.json", overwrite=False) as temp:
                temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            exc.report_dir = str(folder)
        except (OSError, ValueError, AttributeError):
            pass
        raise


def run(source, output_dir, options=None, *, password="", **kwargs):
    plan = analyse(source, options, password=password, progress=kwargs.get("progress"),
                   is_cancelled=kwargs.get("is_cancelled"))
    return execute(plan, output_dir, password=password, **kwargs)
