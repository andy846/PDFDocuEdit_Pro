"""Visible stamp placement and appearance, rather than annotation existence."""
from dataclasses import replace

import numpy as np
import pytest
from PyQt6.QtCore import QRectF

from core.annotations import apply_annotation
from core.pdf_backend import fitz
from tests.test_open_performance import wait_until
from ui.pdf_canvas import PdfCanvas, ToolMode


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("custom", [False, True])
def test_stamp_visible_drag_matches_upright_output(qt_application, tmp_path, rotation, custom):
    path = tmp_path / "asymmetric.png"
    if custom:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (190, 50), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 60, 15), fill="red")
        draw.rectangle((160, 20, 189, 49), fill="blue")
        image.save(path)
    doc = fitz.open()
    page = doc.new_page(width=595 if rotation % 180 == 0 else 842,
                        height=842 if rotation % 180 == 0 else 595)
    page.set_rotation(rotation)
    canvas = PdfCanvas()
    canvas.resize(850, 800)
    canvas.show()
    try:
        canvas.load_doc(doc)
        wait_until(lambda: 0 in canvas._page_views)
        canvas.set_tool_mode(ToolMode.STAMP)
        canvas._annot_options["stamp_kind"] = "Draft"
        canvas._annot_options["stamp_image_path"] = str(path) if custom else ""
        ops = []
        canvas.annotationRequested.connect(ops.append)
        canvas._on_selection(0, QRectF(100, 100, 190, 50))
        assert len(ops) == 1
        visible = ops[0].rects[0] * page.rotation_matrix
        assert tuple(visible) == pytest.approx((100, 100, 290, 150), abs=.1)
        canvas.wait_for_renders()
        apply_annotation(doc, ops[0])
        actual = page.get_pixmap().samples
        with fitz.open() as reference:
            ref = reference.new_page(width=595, height=842)
            if custom:
                ref.insert_image(fitz.Rect(100, 100, 290, 150), filename=str(path))
            else:
                ref.add_stamp_annot(fitz.Rect(100, 100, 290, 150), stamp=fitz.STAMP_Draft).update()
            expected = ref.get_pixmap().samples
        # Rasterization differs slightly after quarter-turn CTMs; compare
        # pixels with a small mean tolerance, not bytes/padding or text counts.
        error = np.abs(np.frombuffer(actual, np.uint8).astype(float)
                       - np.frombuffer(expected, np.uint8).astype(float)).mean()
        assert error < .15
    finally:
        canvas.clear()
        canvas.close()
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("font", ["Helv", "Arial"])
@pytest.mark.parametrize("kind", [ToolMode.FREETEXT_BOX, ToolMode.FREETEXT_CALLOUT])
def test_freetext_visible_orientation_matches_unrotated_reference(qt_application, rotation, font, kind):
    doc = fitz.open()
    page = doc.new_page(width=595 if rotation % 180 == 0 else 842,
                        height=842 if rotation % 180 == 0 else 595)
    page.set_rotation(rotation)
    canvas = PdfCanvas()
    canvas.resize(850, 800)
    canvas.show()
    try:
        canvas.load_doc(doc)
        wait_until(lambda: 0 in canvas._page_views)
        canvas.set_tool_mode(kind)
        canvas._annot_options.update(font=font, font_size=22, color="#000000")
        ops = []
        canvas.annotationRequested.connect(ops.append)
        canvas._on_selection(0, QRectF(100, 100, 200, 70))
        if kind == ToolMode.FREETEXT_CALLOUT:
            for point, expected in zip(ops[0].points, ((372, 165), (328.8, 135), (300, 135)), strict=True):
                assert tuple(fitz.Point(point) * page.rotation_matrix) == pytest.approx(expected, abs=.01)
        canvas.wait_for_renders()
        apply_annotation(doc, replace(ops[0], text="ABC -> XYZ"))
        with fitz.open() as ref:
            ref.new_page(width=595, height=842)
            apply_annotation(ref, replace(ops[0], rects=(fitz.Rect(100, 100, 300, 170),),
                                          visual_rotation=0, text="ABC -> XYZ",
                                          points=((372., 165.), (328.8, 135.), (300., 135.))
                                          if kind == ToolMode.FREETEXT_CALLOUT else ()))
            actual = np.frombuffer(doc[0].get_pixmap().samples, np.uint8).astype(float)
            expected = np.frombuffer(ref[0].get_pixmap().samples, np.uint8).astype(float)
            assert np.abs(actual - expected).mean() < .15
    finally:
        canvas.clear()
        canvas.close()
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", ["image", "signature_image", "stamp"])
def test_rotated_image_resize_changes_actual_pixels_with_selection(tmp_path, rotation, kind):
    from PIL import Image

    from core.annotations import AnnotationOp, list_annotations, update_annotation_geometry
    path = tmp_path / "red.png"
    Image.new("RGB", (200, 100), "red").save(path)
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.set_rotation(rotation)
        rect = fitz.Rect(100, 100, 300, 200) * page.derotation_matrix
        apply_annotation(doc, AnnotationOp(kind=kind, page=0, rects=(rect,),
                                          image_path=str(path), visual_rotation=rotation))
        entry = list_annotations(page)[0]
        old = entry["rect"]
        target = fitz.Rect(old.x0, old.y0, old.x0 + old.width / 2, old.y0 + old.height / 2)
        assert update_annotation_geometry(page, entry["xref"], rect=target) is not None
        actual = page.get_image_info()[0]["bbox"]
        assert tuple(actual) == pytest.approx(tuple(target), abs=.01)
        pix = page.get_pixmap()
        rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
        ys, xs = np.where((rgb[:, :, 0] > 200) & (rgb[:, :, 1] < 30))
        visual = target * page.rotation_matrix
        assert (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) == pytest.approx(tuple(visual), abs=1)
