"""Declarative provenance and immutable PDF handoffs; no Qt dependencies."""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import fitz

from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.production.generator import check_cancel
from core.pdf_engine import DOCUMENT_LOCK


def validate_link(link):
    from composition.template.model import CompositionError
    if not isinstance(link, dict):
        raise CompositionError("Invalid PDF source link.")
    if not link:
        return
    version = link.get("version")
    if (type(version) is not int or version not in (1, 2)
            or link.get("purpose") not in (("overlay", "template_background") if version == 1 else ("mail_merge_template",))
            or type(link.get("managed")) is not bool or type(link.get("review_required")) is not bool):
        raise CompositionError("Unsupported PDF source link.")
    for key in ("transfer_id", "label", "original_path", "captured_at", "sha256"):
        if not isinstance(link.get(key), str) or len(link[key]) > 4096:
            raise CompositionError("Invalid PDF source provenance.")
    if not re.fullmatch(r"[0-9a-f]{64}", link["sha256"]):
        raise CompositionError("Invalid PDF source digest.")
    if link.get("selection", "pages") not in ("all", "pages"):
        raise CompositionError("Invalid source page selection.")
    pages = link.get("page_map")
    if (not isinstance(pages, list) or not 1 <= len(pages) <= 1_000_000
            or any(type(page) is not int or page < 0 for page in pages)
            or pages != sorted(set(pages))):
        raise CompositionError("Invalid handoff page mapping.")
    if version == 2:
        mapping = link.get("template_page_map")
        if (not isinstance(mapping, dict) or not 1 <= len(mapping) <= 100 or len(pages) > 100
                or any(not isinstance(key, str) or not key or type(value) is not int or value not in pages
                       for key, value in mapping.items()) or len(set(mapping.values())) != len(mapping)):
            raise CompositionError("Invalid template/source page mapping.")


@dataclass
class CapturedTemplatePdf:
    pages: list
    link: dict


def capture_template_pdf(engine, target, identity, *, pages=None, source_label="PDF",
                         original_path="", is_cancelled=None, progress=None):
    """Build vector, single-page backgrounds from an immutable editor revision."""
    from composition.engine.renderer import import_background
    from composition.template.model import (
        MAX_TEMPLATE_PAGES,
        CompositionError,
        PageSpec,
        Template,
        validate_template,
    )
    from composition.template.serializer import file_hash

    target = Path(target)
    created = []
    working = target / f"working-{uuid.uuid4().hex}.pdf"
    try:
        check_cancel(is_cancelled)
        target.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0, 0, "Capturing current PDF edits for Mail Merge")
        with DOCUMENT_LOCK:
            if identity != (engine.document_id, engine.revision) or not engine.is_loaded():
                raise CompositionError("PDF changed before handoff. Send the current revision again.")
            chosen = list(range(engine.page_count)) if pages is None else sorted(set(pages))
            if not chosen or any(type(page) is not int or not 0 <= page < engine.page_count for page in chosen):
                raise CompositionError("Selected pages are no longer available. Review the source.")
            if len(chosen) > MAX_TEMPLATE_PAGES:
                raise CompositionError(f"A Mail Merge template supports at most {MAX_TEMPLATE_PAGES} pages. Select a smaller range.")
            if engine.document.get_sigflags() > 0:
                raise CompositionError("Signed/signature-field PDF requires review; handoff cannot preserve signature validity.")
            engine.snapshot(working)
            created.append(working)
            if identity != (engine.document_id, engine.revision):
                raise CompositionError("PDF changed during handoff.")
        check_cancel(is_cancelled)
        with fitz.open(working) as pdf:
            chosen = list(range(pdf.page_count)) if pages is None else sorted(set(pages))
            if not chosen or any(type(page) is not int or not 0 <= page < pdf.page_count for page in chosen):
                raise CompositionError("Selected pages are no longer available. Review the source.")
        captured = []
        for index, page_number in enumerate(chosen):
            check_cancel(is_cancelled)
            background = target / f"background-{index+1:03}.pdf"
            width, height = import_background(working, page_number, background)
            created.append(background)
            captured.append(PageSpec(name=f"Page {index+1}", width_mm=width, height_mm=height,
                                     background=str(background)))
            if progress:
                progress(index+1, len(chosen), "Preparing Mail Merge template pages")
        check_cancel(is_cancelled)
        link = {"version": 2, "transfer_id": uuid.uuid4().hex, "purpose": "mail_merge_template",
                "label": source_label, "original_path": original_path, "captured_at": datetime.now(UTC).isoformat(),
                "sha256": file_hash(working), "page_map": chosen, "managed": True,
                "selection": "all" if pages is None else "pages", "review_required": False,
                "template_page_map": {page.id: number for page, number in zip(captured, chosen, strict=True)}}
        validate_template(Template(name=source_label, pages=captured, source_link=link))
        return CapturedTemplatePdf(captured, link)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        working.unlink(missing_ok=True)


def detach_template_page(raw, page_id):
    """Keep unrelated linked backgrounds when one page is removed/replaced."""
    link = raw.get("source_link", {})
    if link.get("version") == 2:
        link["template_page_map"].pop(page_id, None)
        if not link["template_page_map"]:
            raw["source_link"] = {}
    elif link and link.get("page_id", page_id) == page_id:
        raw["source_link"] = {}


def capture_pdf(engine, target, identity, *, pages=None, purpose="overlay", source_label="PDF",
                original_path="", is_cancelled=None, progress=None):
    """Snapshot one revision under the existing engine lock; inspect independent readers."""
    from composition.engine.renderer import import_background
    from composition.template.model import CompositionError
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    working, result = target / "working.pdf", target / "source.pdf"
    check_cancel(is_cancelled)
    if progress:
        progress(0, 3, "Capturing current PDF edits")
    with DOCUMENT_LOCK:
        if identity != (engine.document_id, engine.revision) or not engine.is_loaded():
            raise CompositionError("PDF changed before handoff. Send the current revision again.")
        if engine.document.get_sigflags() > 0:
            raise CompositionError("Signed/signature-field PDF requires review; handoff cannot preserve signature validity.")
        engine.snapshot(working)
        if identity != (engine.document_id, engine.revision):
            raise CompositionError("PDF changed during handoff.")
    check_cancel(is_cancelled)
    with fitz.open(working) as pdf:
        chosen = list(range(pdf.page_count)) if pages is None else sorted(set(pages))
        if not chosen or any(type(page) is not int or not 0 <= page < pdf.page_count for page in chosen):
            raise CompositionError("Selected pages are no longer available. Review the source.")
        if purpose == "template_background":
            if len(chosen) != 1:
                raise CompositionError("Choose one page for the template background.")
            import_background(working, chosen[0], result)
        elif purpose == "overlay":
            if chosen == list(range(pdf.page_count)):
                shutil.copyfile(working, result)
            else:
                with fitz.open() as selected:
                    for index, page in enumerate(chosen):
                        check_cancel(is_cancelled)
                        selected.insert_pdf(pdf, from_page=page, to_page=page)
                        if progress and index % 100 == 0:
                            progress(index, len(chosen), "Copying selected PDF pages")
                    selected.save(result)
        else:
            raise CompositionError("Unknown PDF handoff purpose.")
    working.unlink(missing_ok=True)
    check_cancel(is_cancelled)
    source = inspect_source(result, EnvelopeSettings(pages_per_envelope=1), is_cancelled=is_cancelled,
                            progress=progress, uniform=True)
    link = {"version": 1, "transfer_id": uuid.uuid4().hex, "purpose": purpose, "label": source_label,
            "original_path": original_path, "captured_at": datetime.now(UTC).isoformat(),
            "sha256": source.sha256, "page_map": chosen, "managed": True,
            "selection": "all" if pages is None else "pages",
            "review_required": purpose == "overlay"}
    validate_link(link)
    return source, link
