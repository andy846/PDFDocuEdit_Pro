"""Document-level annotation interchange, summaries and flattening."""

from __future__ import annotations

import json
import os
from pathlib import Path

import fitz

from core.diagnostics import log_failure

from .annotations import (
    AnnotationOp,
    AnnotationStyle,
    apply_annotation,
    list_document_annotations,
    validate_annotation_op,
)
from .io_atomic import atomic_output
from .pdf_engine import DOCUMENT_LOCK
from .pdf_io import validate_pdf_file

SCHEMA = "pdfdocuedit.annotations"
SCHEMA_VERSION = 1


def _color_hex(value) -> str:
    if not value or len(value) < 3:
        return ""
    channels = [max(0, min(255, round(float(channel) * 255))) for channel in value[:3]]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _json_record(entry: dict) -> dict:
    rect = fitz.Rect(entry["rect"])
    return {
        "page": int(entry["page"]),
        "xref": int(entry["xref"]),
        "pdf_kind": str(entry["kind"]),
        "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
        "vertices": [list(point) for point in entry.get("vertices", ())],
        "line_ends": list(entry.get("line_ends", ())),
        "text": str(entry.get("text") or ""),
        "author": str(entry.get("title") or ""),
        "subject": str(entry.get("subject") or ""),
        "creation_date": str(entry.get("creation_date") or ""),
        "modified_date": str(entry.get("modified_date") or ""),
        "style": {
            "stroke": _color_hex(entry.get("stroke")) or "yellow",
            "fill": _color_hex(entry.get("fill")),
            "opacity": float(entry.get("opacity", 1.0)),
            "width": max(0.5, float(entry.get("width", 1.5) or 1.5)),
        },
    }


def annotation_payload(doc: fitz.Document) -> dict:
    with DOCUMENT_LOCK:
        return {
            "schema": SCHEMA,
            "version": SCHEMA_VERSION,
            "page_count": doc.page_count,
            "annotations": [
                _json_record(entry) for entry in list_document_annotations(doc)
            ],
        }


def export_annotations_json(
    doc: fitz.Document, output_path: str | os.PathLike[str]
) -> Path:
    target = Path(output_path).expanduser().resolve()
    payload = json.dumps(annotation_payload(doc), ensure_ascii=False, indent=2)
    with atomic_output(target) as staged:
        staged.write_text(payload, encoding="utf-8")
    return target


def _style(record: dict) -> AnnotationStyle:
    values = record.get("style") if isinstance(record.get("style"), dict) else {}
    return AnnotationStyle(
        stroke=str(values.get("stroke") or "yellow"),
        fill=str(values.get("fill") or ""),
        opacity=float(values.get("opacity", 1.0)),
        width=float(values.get("width", 1.5)),
    )


def _op_from_record(record: dict) -> AnnotationOp | None:
    pdf_kind = str(record.get("pdf_kind") or "")
    page = int(record.get("page", -1))
    raw_rect = record.get("rect")
    rects = (
        (fitz.Rect(*(float(value) for value in raw_rect)),)
        if isinstance(raw_rect, list) and len(raw_rect) == 4
        else ()
    )
    raw_vertices = record.get("vertices")
    points = (
        tuple((float(point[0]), float(point[1])) for point in raw_vertices)
        if isinstance(raw_vertices, list)
        else ()
    )
    style = _style(record)
    text = str(record.get("text") or "")
    mapping = {
        "Highlight": "highlight",
        "Underline": "underline",
        "StrikeOut": "strikeout",
        "Squiggly": "squiggly",
        "Text": "note",
        "Ink": "ink",
        "Square": "rect",
        "Circle": "ellipse",
        "Polygon": "polygon",
        "Redact": "redact",
    }
    if pdf_kind == "Line":
        line_ends = record.get("line_ends") or []
        arrow_end = getattr(fitz, "PDF_ANNOT_LE_OPEN_ARROW", 4)
        kind = "arrow" if len(line_ends) > 1 and int(line_ends[1]) == arrow_end else "line"
        return AnnotationOp(kind=kind, page=page, points=points[:2], text=text, style=style)
    if pdf_kind == "FreeText":
        return AnnotationOp(
            kind="freetext_box",
            page=page,
            rects=rects,
            text=text,
            style=style,
        )
    kind = mapping.get(pdf_kind)
    if kind is None:
        return None
    if kind == "note":
        point = (
            ((rects[0].x0, rects[0].y0),)
            if rects
            else points[:1]
        )
        return AnnotationOp(kind=kind, page=page, points=point, text=text or "Note")
    if kind in {"ink", "polygon"}:
        return AnnotationOp(kind=kind, page=page, points=points, style=style)
    return AnnotationOp(kind=kind, page=page, rects=rects, text=text, style=style)


def import_annotations_json(
    doc: fitz.Document, input_path: str | os.PathLike[str],
    *, strict_mutations: bool = False,
) -> dict[str, object]:
    """Import supported records; strict callers must own a document transaction.

    Invalid records are skipped before mutation. Strict mode propagates actual
    mutation failures so an outer transaction can restore the complete batch.
    The default preserves the legacy best-effort import API.
    """
    source = Path(input_path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("This is not a PDFDocuEdit annotation JSON file.")
    if int(payload.get("version", 0)) != SCHEMA_VERSION:
        raise ValueError("Unsupported annotation JSON schema version.")
    records = payload.get("annotations")
    if not isinstance(records, list):
        raise ValueError("Annotation JSON must contain an annotations list.")

    imported = 0
    skipped: list[dict] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            skipped.append({"index": index, "reason": "record is not an object"})
            continue
        try:
            op = _op_from_record(record)
            if op is None:
                skipped.append(
                    {
                        "index": index,
                        "pdf_kind": str(record.get("pdf_kind") or ""),
                        "reason": "unsupported annotation subtype",
                    }
                )
                continue
            with DOCUMENT_LOCK:
                op = validate_annotation_op(doc, op)
        except Exception as exc:
            log_failure('annotation_io.import_annotations_json: fallback after failure', 10)
            skipped.append({"index": index, "reason": str(exc)})
            continue
        try:
            apply_annotation(doc, op)
            imported += 1
        except Exception as exc:
            log_failure('annotation_io.import_annotations_json: fallback after failure', 10)
            if strict_mutations:
                raise
            skipped.append({"index": index, "reason": str(exc)})
    return {"imported": imported, "skipped": skipped}


def export_annotation_summary(
    doc: fitz.Document, output_path: str | os.PathLike[str]
) -> Path:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    records = list_document_annotations(doc)
    lines = [
        "# Annotation Summary",
        "",
        f"Total annotations: {len(records)}",
        "",
    ]
    current_page = -1
    for entry in records:
        page = int(entry["page"])
        if page != current_page:
            current_page = page
            lines.extend((f"## Page {page + 1}", ""))
        kind = str(entry.get("kind") or "Unknown")
        text = str(entry.get("text") or "").replace("\n", " ").strip()
        author = str(entry.get("title") or "").strip()
        detail = f" — {text}" if text else ""
        attribution = f" ({author})" if author else ""
        lines.append(f"- {kind}{attribution}{detail}")
    with atomic_output(target) as staged:
        staged.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def flatten_annotations(
    doc: fitz.Document,
    output_path: str | os.PathLike[str],
    *,
    widgets: bool = False,
) -> Path:
    """Bake annotations into a separate PDF, never replacing the live document."""

    target = Path(output_path).expanduser().resolve()
    with atomic_output(target, suffix=".pdf") as staged:
        temp_name = str(staged)
        with DOCUMENT_LOCK:
            source = doc.tobytes(garbage=0, deflate=False)
            expected_page_count = doc.page_count
        with fitz.open(stream=source, filetype="pdf") as flattened:
            flattened.bake(annots=True, widgets=widgets)
            flattened.save(temp_name, garbage=4, deflate=True)
        validate_pdf_file(
            temp_name, expected_page_count=expected_page_count
        )
    return target
