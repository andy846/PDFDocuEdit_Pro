from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from core.annotations import (
    AnnotationOp,
    AnnotationStyle,
    add_freetext,
    add_circle,
    add_highlight,
    add_ink,
    add_line,
    add_note,
    add_polygon,
    add_rect,
    add_stamp,
    add_strikeout,
    add_underline,
    add_watermark_image,
    add_watermark_text,
    apply_annotation,
    insert_image,
    list_annotations,
    redact,
    remove_annotation,
)


def make_doc(tmp_path: Path) -> tuple[fitz.Document, Path]:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 96), "Sensitive secret text for redaction tests")
    image = tmp_path / "stamp.png"
    try:
        from PIL import Image

        Image.new("RGB", (80, 30), (200, 30, 30)).save(image)
    except ImportError:
        image.write_bytes(b"")
    return doc, image


def annot_count(page: fitz.Page) -> int:
    return len(list(page.annots()))


def test_markup_annotations(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    rects = [fitz.Rect(60, 80, 200, 105)]
    add_highlight(doc, 0, rects)
    add_underline(doc, 0, rects)
    add_strikeout(doc, 0, rects)
    add_note(doc, 0, (300, 400), "hello note")
    assert annot_count(page) == 4
    kinds = {str(annot.type[1]) for annot in page.annots()}
    assert {"Highlight", "Underline", "StrikeOut", "Text"} <= kinds


def test_drawing_annotations(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_ink(doc, 0, [(100, 100), (110, 120), (130, 110)], color="red", width=2.0)
    add_rect(doc, 0, fitz.Rect(50, 50, 150, 120))
    add_line(doc, 0, (10, 10), (90, 10))
    add_circle(doc, 0, fitz.Rect(200, 200, 280, 280))
    add_polygon(doc, 0, [(300, 300), (360, 300), (330, 360)])
    add_stamp(doc, 0, fitz.Rect(400, 300, 520, 340), "Draft")
    assert annot_count(page) == 6
    assert any(str(a.type[1]) == "Stamp" for a in page.annots())


def test_redact_removes_underlying_text(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    assert "Sensitive" in page.get_text()
    redact(doc, 0, [fitz.Rect(60, 80, 240, 105)])
    assert "Sensitive" not in page.get_text()


def test_insert_image_and_watermarks(tmp_path: Path) -> None:
    doc, image = make_doc(tmp_path)
    page = doc.load_page(0)
    insert_image(doc, 0, fitz.Rect(60, 200, 260, 300), str(image))
    assert page.get_images()

    add_watermark_text(doc, [0], "WATERMARK", fontsize=40, opacity=0.3, rotation=45)
    assert len(page.get_images()) >= 2

    add_watermark_image(doc, [0], str(image), opacity=0.5)
    assert len(page.get_images()) >= 3


def test_list_and_remove_annotations(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_rect(doc, 0, fitz.Rect(10, 10, 60, 60))
    add_note(doc, 0, (100, 100), "n")
    entries = list_annotations(page)
    assert len(entries) == 2
    assert entries[0]["kind"] == "Square"
    remove_annotation(page, 0)
    assert annot_count(page) == 1


def test_apply_annotation_dispatch(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    apply_annotation(
        doc,
        AnnotationOp(kind="highlight", page=0, rects=(fitz.Rect(60, 80, 200, 105),)),
    )
    apply_annotation(
        doc, AnnotationOp(kind="note", page=0, points=((200, 300),), text="x")
    )
    assert annot_count(page) == 2
    with pytest.raises(ValueError):
        apply_annotation(doc, AnnotationOp(kind="unknown", page=0))


def test_text_box_and_callout_have_distinct_pdf_structures(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    style = AnnotationStyle(stroke="red", fill="", width=2.0)
    add_freetext(
        doc,
        0,
        fitz.Rect(120, 60, 260, 120),
        "Text box",
        style,
        boxed=True,
    )
    callout_points = ((35.0, 220.0), (75.0, 170.0), (120.0, 140.0))
    add_freetext(
        doc,
        0,
        fitz.Rect(120, 140, 260, 200),
        "Callout",
        style,
        callout=callout_points,
        boxed=True,
    )

    page = doc.load_page(0)
    text_box, callout = list(page.annots())
    text_box_object = doc.xref_object(text_box.xref)
    callout_object = doc.xref_object(callout.xref)
    assert "/FreeTextCallout" not in text_box_object
    assert "/CL [" not in text_box_object
    assert "/LE /OpenArrow" not in text_box_object
    assert "/IT /FreeTextCallout" in callout_object
    assert "/CL [" in callout_object
    assert "/LE /OpenArrow" in callout_object
    assert callout.vertices == list(callout_points)
