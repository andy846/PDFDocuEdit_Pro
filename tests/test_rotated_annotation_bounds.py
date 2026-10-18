"""Annotation bounds use unrotated, CropBox-relative MuPDF coordinates."""
from __future__ import annotations

import fitz
import pytest

from core.annotations import (
    AnnotationOp,
    AnnotationValidationError,
    apply_annotation,
    apply_redaction_marks,
    update_annotation_geometry,
    validate_annotation_op,
)
from ui.page_overlay import pdf_rect_to_widget, widget_point_to_pdf


def make_page(doc, rotation, cropped, landscape=False):
    width, height = (842, 595) if landscape else (595, 842)
    page = doc.new_page(width=width, height=height)
    if cropped:
        page.set_cropbox(fitz.Rect(20, 30, width - 40, height - 50))
    page.set_rotation(rotation)
    return page


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize("landscape", [False, True])
def test_visible_corners_remain_selectable(rotation, cropped, landscape):
    with fitz.open() as doc:
        page = make_page(doc, rotation, cropped, landscape)
        bounds = page.rect * page.derotation_matrix
        for x in (bounds.x0 + 2, bounds.x1 - 52):
            for y in (bounds.y0 + 2, bounds.y1 - 42):
                source = fitz.Rect(x, y, x + 50, y + 40)
                for zoom in (0.5, 1.0, 2.0):
                    visual = pdf_rect_to_widget(source, page.rect, 1 / zoom, page.rotation_matrix)
                    requested = fitz.Rect(
                        widget_point_to_pdf(visual.topLeft(), page.rect, 1 / zoom, page.derotation_matrix),
                        widget_point_to_pdf(visual.bottomRight(), page.rect, 1 / zoom, page.derotation_matrix),
                    ).normalize()
                    for kind in ("redact", "rect", "ellipse", "highlight", "underline",
                                 "strikeout", "squiggly", "freetext_box", "stamp"):
                        checked = validate_annotation_op(doc, AnnotationOp(
                            kind=kind, page=0, rects=(requested,), text="Example"))
                        assert tuple(checked.rects[0]) == pytest.approx(tuple(source))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
def test_redaction_removes_only_selected_content_at_rotated_page_edge(rotation, cropped):
    with fitz.open() as doc:
        page = make_page(doc, rotation, cropped)
        bounds = page.rect * page.derotation_matrix
        page.insert_text((40, bounds.height - 30), "REMOVE")
        page.insert_text((40, 90), "KEEP")
        selected = page.search_for("REMOVE")[0] + (-2, -2, 2, 2)
        boxes = tuple(page.mediabox), tuple(page.cropbox)
        apply_annotation(doc, AnnotationOp(kind="redact", page=0, rects=(selected,)))
        assert tuple(next(page.annots()).rect) == pytest.approx(tuple(selected), abs=0.001)
        assert apply_redaction_marks(doc) == 1
        with fitz.open(stream=doc.tobytes(), filetype="pdf") as saved:
            page = saved[0]
            assert "REMOVE" not in page.get_text()
            assert "KEEP" in page.get_text()
            assert not list(page.annots() or [])
            assert page.rotation == rotation
            assert (tuple(page.mediabox), tuple(page.cropbox)) == boxes


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_moving_redaction_to_page_edge_uses_same_bounds(rotation):
    with fitz.open() as doc:
        page = make_page(doc, rotation, True)
        annot = page.add_redact_annot(fitz.Rect(40, 50, 100, 90))
        xref = annot.xref
        bounds = page.rect * page.derotation_matrix
        destination = fitz.Rect(10, bounds.y1 - 70, 100, bounds.y1 - 2)
        assert update_annotation_geometry(page, xref, rect=destination) == xref
        assert tuple(page.load_annot(xref).rect) == pytest.approx(tuple(destination))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_outside_rectangles_are_rejected_and_partial_overlap_is_clipped(rotation):
    with fitz.open() as doc:
        page = make_page(doc, rotation, True)
        bounds = page.rect * page.derotation_matrix
        original = fitz.Rect(40, 50, 100, 90)
        xref = page.add_redact_annot(original).xref
        outside = (
            fitz.Rect(-40, 10, -10, 50),
            fitz.Rect(bounds.x1 + 10, 10, bounds.x1 + 40, 50),
            fitz.Rect(10, -40, 50, -10),
            fitz.Rect(10, bounds.y1 + 10, 50, bounds.y1 + 40),
        )
        for rect in outside:
            with pytest.raises(AnnotationValidationError):
                validate_annotation_op(doc, AnnotationOp(kind="redact", page=0, rects=(rect,)))
            assert update_annotation_geometry(page, xref, rect=rect) is None
            assert tuple(page.load_annot(xref).rect) == pytest.approx(tuple(original))
        partial = fitz.Rect(-20, bounds.y1 - 30, 40, bounds.y1 + 20)
        expected = fitz.Rect(0, bounds.y1 - 30, 40, bounds.y1)
        # Reversed drag direction is normalized before clipping.
        reversed_rect = fitz.Rect(partial.br, partial.tl)
        checked = validate_annotation_op(doc, AnnotationOp(kind="redact", page=0, rects=(reversed_rect,)))
        assert tuple(checked.rects[0]) == pytest.approx(tuple(expected))
        assert update_annotation_geometry(page, xref, rect=reversed_rect) == xref
        assert tuple(page.load_annot(xref).rect) == pytest.approx(tuple(expected))
