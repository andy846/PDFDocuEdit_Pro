from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from core.annotation_io import (
    export_annotation_summary,
    export_annotations_json,
    flatten_annotations,
    import_annotations_json,
)
from core.annotations import (
    AnnotationOp,
    AnnotationStyle,
    AnnotationValidationError,
    add_circle,
    add_freetext,
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
    apply_redaction_marks,
    freetext_visual_metrics,
    insert_image,
    list_annotations,
    redact,
    remove_annotation,
    update_annotation,
    update_annotation_geometry,
    update_annotation_text,
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


def test_custom_image_stamp_is_inserted(tmp_path: Path) -> None:
    doc, image = make_doc(tmp_path)
    page = doc.load_page(0)
    apply_annotation(
        doc,
        AnnotationOp(
            kind="stamp",
            page=0,
            rects=(fitz.Rect(80, 180, 240, 240),),
            stamp_kind="Draft",
            image_path=str(image),
        ),
    )
    assert page.get_images()


def test_signature_image_kind_is_dispatched(tmp_path: Path) -> None:
    doc, image = make_doc(tmp_path)
    page = doc.load_page(0)
    apply_annotation(
        doc,
        AnnotationOp(
            kind="signature",
            page=0,
            rects=(fitz.Rect(80, 180, 240, 240),),
            image_path=str(image),
        ),
    )
    assert page.get_images()


def test_redact_marks_before_explicitly_removing_underlying_text(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    assert "Sensitive" in page.get_text()
    redact(doc, 0, [fitz.Rect(60, 80, 240, 105)])
    assert "Sensitive" in page.get_text()
    assert any("Redact" in str(annot.type) for annot in page.annots())
    assert apply_redaction_marks(doc, [0]) == 1
    assert "Sensitive" not in page.get_text()


@pytest.mark.parametrize(
    "op",
    [
        AnnotationOp(kind="unknown", page=0),
        AnnotationOp(kind="rect", page=0),
        AnnotationOp(kind="line", page=0, points=((10, 10),)),
        AnnotationOp(kind="polygon", page=0, points=((10, 10), (20, 20))),
        AnnotationOp(
            kind="rect",
            page=0,
            rects=(fitz.Rect(10, 10, 40, 40),),
            style=AnnotationStyle(stroke="not-a-color"),
        ),
    ],
)
def test_malformed_annotation_ops_raise_typed_error_before_mutation(
    tmp_path: Path, op: AnnotationOp
) -> None:
    doc, _ = make_doc(tmp_path)
    with pytest.raises(AnnotationValidationError):
        apply_annotation(doc, op)
    assert annot_count(doc.load_page(0)) == 0


def test_insert_image_and_watermarks(tmp_path: Path) -> None:
    doc, image = make_doc(tmp_path)
    page = doc.load_page(0)
    insert_image(doc, 0, fitz.Rect(60, 200, 260, 300), str(image))
    assert page.get_images()

    add_watermark_text(doc, [0], "WATERMARK", fontsize=40, opacity=0.3, rotation=45)
    assert len(page.get_images()) == 1
    assert "WATERMARK" in page.get_text()

    add_watermark_image(doc, [0], str(image), opacity=0.5)
    assert len(page.get_images()) >= 2


def test_list_and_remove_annotations(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_rect(doc, 0, fitz.Rect(10, 10, 60, 60))
    add_note(doc, 0, (100, 100), "n")
    entries = list_annotations(page)
    assert len(entries) == 2
    assert entries[0]["kind"] == "Square"
    # A missing xref must never be reinterpreted as a list index.
    remove_annotation(page, 0)
    assert annot_count(page) == 2
    remove_annotation(page, entries[0]["xref"])
    assert annot_count(page) == 1


def test_update_annotation_geometry_handles_line_endpoints_and_rects(
    tmp_path: Path,
) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_line(doc, 0, (40, 50), (180, 210), color="red", width=3.0)
    add_rect(doc, 0, fitz.Rect(200, 220, 300, 320))
    line, square = list_annotations(page)

    new_line_xref = update_annotation_geometry(
        page, line["xref"], points=((60, 70), (240, 260))
    )
    assert new_line_xref is not None
    moved_line = next(
        entry for entry in list_annotations(page) if entry["xref"] == new_line_xref
    )
    assert moved_line["vertices"] == pytest.approx([(60, 70), (240, 260)])

    same_square_xref = update_annotation_geometry(
        page, square["xref"], rect=fitz.Rect(250, 280, 390, 430)
    )
    assert same_square_xref == square["xref"]
    moved_square = next(
        entry for entry in list_annotations(page) if entry["xref"] == same_square_xref
    )
    # MuPDF expands Square.rect by half its border width around the requested box.
    assert tuple(moved_square["rect"]) == pytest.approx(
        (250, 280, 390, 430), abs=1.1
    )


def test_inline_annotation_text_update_is_limited_to_text_kinds(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_note(doc, 0, (100, 100), "before")
    add_rect(doc, 0, fitz.Rect(200, 200, 300, 300))
    note, square = list_annotations(page)
    assert update_annotation_text(page, note["xref"], "after")
    assert next(page.annots()).info["content"] == "after"
    assert not update_annotation_text(page, square["xref"], "ignored")


def test_freetext_box_keeps_text_and_background_colors_distinct(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    page = doc.load_page(0)
    add_freetext(
        doc,
        0,
        fitz.Rect(50, 150, 420, 260),
        "VISIBLE TEXT",
        AnnotationStyle(
            stroke="#0000ff", fill="#ffcccc", width=2.0, font_size=24
        ),
        boxed=True,
    )
    entry = list_annotations(page)[0]
    assert entry["stroke"] == pytest.approx((0.0, 0.0, 1.0))
    assert entry["fill"] == pytest.approx((1.0, 0.8, 0.8))
    rendered = page.get_pixmap(colorspace=fitz.csRGB, alpha=False, annots=True)
    samples = rendered.samples
    assert any(
        samples[index] < 30
        and samples[index + 1] < 30
        and samples[index + 2] > 180
        for index in range(0, len(samples), rendered.n)
    ), "blue text pixels must remain visible"
    assert any(
        samples[index] > 240
        and 150 < samples[index + 1] < 230
        and 150 < samples[index + 2] < 230
        for index in range(0, len(samples), rendered.n)
    ), "pink box pixels must remain distinct from the text"

    assert update_annotation(
        page,
        entry["xref"],
        AnnotationStyle(
            stroke="#008000", fill="#ffff00", width=3.0, font_size=24
        ),
        text="STILL VISIBLE",
    )
    updated = list_annotations(page)[0]
    assert updated["stroke"] == pytest.approx((0.0, 128 / 255, 0.0))
    assert updated["fill"] == pytest.approx((1.0, 1.0, 0.0))
    assert updated["text"] == "STILL VISIBLE"


def test_system_font_is_embedded_and_survives_content_edit(
    tmp_path: Path, monkeypatch
) -> None:
    candidates = (
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    )
    font_path = next((path for path in candidates if path.is_file()), None)
    if font_path is None:
        pytest.skip("No predictable system test font is installed")
    monkeypatch.setattr(
        "core.annotations.resolve_system_font", lambda _family: font_path
    )

    doc, _ = make_doc(tmp_path)
    path = tmp_path / "embedded-system-font.pdf"
    add_freetext(
        doc,
        0,
        fitz.Rect(50, 150, 420, 240),
        "Embedded system font",
        AnnotationStyle(font="Test System Font", font_size=24, stroke="#123456"),
    )
    entry = list_annotations(doc.load_page(0))[0]
    assert entry["font"] == "Test System Font"
    assert update_annotation_text(
        doc.load_page(0), entry["xref"], "Edited embedded font"
    )
    doc.save(path)
    doc.close()

    with fitz.open(path) as reopened:
        entry = list_annotations(reopened.load_page(0))[0]
        assert entry["font"] == "Test System Font"
        assert entry["text"] == "Edited embedded font"
        base_fonts = [
            reopened.xref_object(xref)
            for xref in range(1, reopened.xref_length())
            if "/BaseFont" in reopened.xref_object(xref)
        ]
        assert any("Arial" in value or "DejaVuSans" in value for value in base_fonts)


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


@pytest.mark.parametrize("kind", ["rect", "ellipse", "polygon"])
def test_shape_style_applies_fill_and_opacity(tmp_path: Path, kind: str) -> None:
    doc, _ = make_doc(tmp_path)
    style = AnnotationStyle(
        stroke="#e57373",
        fill="#81c784",
        opacity=0.4,
        width=2.5,
    )
    if kind == "polygon":
        op = AnnotationOp(
            kind=kind,
            page=0,
            points=((120, 180), (220, 180), (170, 260)),
            style=style,
        )
    else:
        op = AnnotationOp(
            kind=kind,
            page=0,
            rects=(fitz.Rect(120, 180, 260, 280),),
            style=style,
        )

    apply_annotation(doc, op)

    page = doc.load_page(0)
    annot = next(page.annots())
    assert annot.colors["fill"] == pytest.approx((129 / 255, 199 / 255, 132 / 255))
    assert annot.opacity == pytest.approx(0.4, abs=0.01)
    assert float(annot.border["width"]) == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("kind", "rects", "points"),
    [
        ("highlight", (fitz.Rect(60, 80, 200, 105),), ()),
        ("ink", (), ((100, 150), (140, 190), (180, 160))),
        ("line", (), ((100, 220), (240, 220))),
        ("arrow", (), ((100, 260), (240, 300))),
    ],
)
def test_non_shape_style_applies_opacity(
    tmp_path: Path,
    kind: str,
    rects: tuple[fitz.Rect, ...],
    points: tuple[tuple[float, float], ...],
) -> None:
    doc, _ = make_doc(tmp_path)
    apply_annotation(
        doc,
        AnnotationOp(
            kind=kind,
            page=0,
            rects=rects,
            points=points,
            style=AnnotationStyle(stroke="red", opacity=0.35, width=2.0),
        ),
    )

    page = doc.load_page(0)
    annot = next(page.annots())
    assert annot.opacity == pytest.approx(0.35, abs=0.01)


def test_annotation_json_summary_and_flatten_round_trip(tmp_path: Path) -> None:
    source, _ = make_doc(tmp_path)
    apply_annotation(
        source,
        AnnotationOp(
            kind="rect",
            page=0,
            rects=(fitz.Rect(100, 160, 220, 240),),
            style=AnnotationStyle(stroke="red", fill="#81c784", opacity=0.5),
        ),
    )
    apply_annotation(
        source,
        AnnotationOp(kind="note", page=0, points=((260, 220),), text="Review this"),
    )

    json_path = export_annotations_json(source, tmp_path / "annotations.json")
    summary_path = export_annotation_summary(source, tmp_path / "summary.md")
    assert '"schema": "pdfdocuedit.annotations"' in json_path.read_text(encoding="utf-8")
    assert "Review this" in summary_path.read_text(encoding="utf-8")

    target, _ = make_doc(tmp_path)
    result = import_annotations_json(target, json_path)
    assert result == {"imported": 2, "skipped": []}
    assert annot_count(target.load_page(0)) == 2

    flattened_path = flatten_annotations(source, tmp_path / "flattened.pdf")
    with fitz.open(flattened_path) as flattened:
        assert list(flattened.load_page(0).annots() or []) == []


def test_annotation_json_reports_unsupported_subtypes(tmp_path: Path) -> None:
    doc, _ = make_doc(tmp_path)
    payload = tmp_path / "unsupported.json"
    payload.write_text(
        """{
  "schema": "pdfdocuedit.annotations",
  "version": 1,
  "annotations": [{"page": 0, "pdf_kind": "FileAttachment"}]
}""",
        encoding="utf-8",
    )
    result = import_annotations_json(doc, payload)
    assert result["imported"] == 0
    assert result["skipped"][0]["pdf_kind"] == "FileAttachment"


@pytest.mark.parametrize("font_name", ["Helv", "Cour", "Times-Roman"])
def test_freetext_visual_metrics_align_visible_glyph_centre(
    font_name: str,
) -> None:
    document = fitz.open()
    document.new_page(width=400, height=300)
    midpoint, line_height = freetext_visual_metrics(font_name, 14.0)
    expected_centre = 120.0
    add_freetext(
        document,
        0,
        fitz.Rect(
            80,
            expected_centre - midpoint,
            280,
            expected_centre - midpoint + line_height,
        ),
        "Alignment",
        AnnotationStyle(stroke="#000000", font=font_name, font_size=14.0),
    )

    word = next(
        item
        for item in document.load_page(0).get_text("words")
        if item[4] == "Alignment"
    )
    visible_centre = (float(word[1]) + float(word[3])) / 2.0
    assert visible_centre == pytest.approx(expected_centre, abs=0.15)
    document.close()
