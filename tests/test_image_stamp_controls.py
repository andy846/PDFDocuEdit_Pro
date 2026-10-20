"""Observable proportions and arbitrary-angle image/stamp editing."""
import fitz
import numpy as np
import pytest
from PIL import Image, ImageDraw
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest

from core.annotations import AnnotationOp, apply_annotation, list_annotations, update_annotation_geometry
from tests.test_document_windows import documents
from tests.test_document_windows import editor as editor
from ui.page_overlay import PageOverlay


@pytest.fixture
def asymmetric_image(tmp_path):
    path = tmp_path / "asymmetric.png"
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 80, 30), fill="red")
    draw.rectangle((160, 50, 199, 99), fill="blue")
    image.save(path)
    return path


def test_unchecking_proportions_changes_drag_policy_without_apply(editor, tmp_path, asymmetric_image):
    session = documents(editor, tmp_path, count=1)[0]
    editor._handle_annotation(AnnotationOp(kind="image", page=0,
        rects=(fitz.Rect(100, 100, 300, 200),), image_path=str(asymmetric_image)))
    entry = list_annotations(session.engine.document[0])[0]
    editor._canvas_annotation_selected(session, 0, entry["xref"])
    editor.context_panel._image_dimensions["width"].setValue(90)
    editor.context_panel._image_keep_aspect.setChecked(False)
    assert editor.context_panel._image_dimensions["width"].value() == 90
    entry = list_annotations(session.engine.document[0])[0]
    assert entry["keep_aspect"] is False
    assert entry["image_size"] == pytest.approx((200, 100))
    assert editor._undo()
    assert list_annotations(session.engine.document[0])[0]["keep_aspect"] is True
    assert editor._redo()
    assert list_annotations(session.engine.document[0])[0]["keep_aspect"] is False


@pytest.mark.parametrize("tool", ["image", "stamp"])
def test_angle_controls_reach_new_and_selected_objects(editor, tmp_path, asymmetric_image, tool):
    session = documents(editor, tmp_path, count=1)[0]
    editor._activate_annotation_tool(tool)
    editor._set_annot_image(str(asymmetric_image))
    editor.context_panel._annot_rotation.setValue(27.5)
    if tool == "image":
        editor.context_panel._new_image_keep_aspect.setChecked(False)
    canvas = session.canvas
    canvas._on_selection(0, QRectF(100, 100, 190, 50))
    entry = list_annotations(session.engine.document[0])[0]
    assert entry["rotation"] == pytest.approx(27.5)
    editor._canvas_annotation_selected(session, 0, entry["xref"])
    editor.context_panel._object_rotation.setValue(-12.5)
    editor.context_panel._apply_selected_annotation()
    entry = list_annotations(session.engine.document[0])[0]
    assert entry["rotation"] == pytest.approx(-12.5)


@pytest.mark.parametrize("keep", [False, True])
def test_insert_image_respects_proportions_in_output(asymmetric_image, keep):
    with fitz.open() as doc:
        doc.new_page(width=595, height=842)
        apply_annotation(doc, AnnotationOp(kind="image", page=0,
            rects=(fitz.Rect(100, 100, 300, 300),), image_path=str(asymmetric_image),
            keep_aspect=keep))
        box = doc[0].get_image_info()[0]["bbox"]
        assert box == pytest.approx((100, 150, 300, 250) if keep else (100, 100, 300, 300))
        assert list_annotations(doc[0])[0]["keep_aspect"] is keep


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", ["image", "stamp"])
def test_angle_changes_output_pixels_and_survives_reopen(asymmetric_image, page_rotation, kind):
    with fitz.open() as doc, fitz.open() as reference, fitz.open() as image_pdf:
        page = doc.new_page(width=595 if page_rotation % 180 == 0 else 842,
                            height=842 if page_rotation % 180 == 0 else 595)
        page.set_rotation(page_rotation)
        apply_annotation(doc, AnnotationOp(kind=kind, page=0,
            rects=(fitz.Rect(100, 100, 300, 200) * page.derotation_matrix,),
            image_path=str(asymmetric_image), visual_rotation=page_rotation, rotation=30))
        ref = reference.new_page(width=595, height=842)
        image_pdf.new_page(width=200, height=100).insert_image(
            fitz.Rect(0, 0, 200, 100), filename=str(asymmetric_image))
        # Hand-derived bounding box: rotate a 200 x 100 object 30 degrees
        # counterclockwise about (200, 150), keeping its physical dimensions.
        target = fitz.Rect(88.3974596, 56.6987298, 311.6025404, 243.3012702)
        ref.show_pdf_page(target, image_pdf, 0, rotate=30)
        actual = np.frombuffer(page.get_pixmap().samples, np.uint8).astype(float)
        expected = np.frombuffer(ref.get_pixmap().samples, np.uint8).astype(float)
        assert np.abs(actual - expected).mean() < .2
        with fitz.open(stream=doc.tobytes(garbage=4), filetype="pdf") as reopened:
            entry = list_annotations(reopened[0])[0]
            assert entry["rotation"] == pytest.approx(30)
            changed = update_annotation_geometry(reopened[0], entry["xref"],
                                                 rect=entry["rect"], rotation=27.5)
            assert changed is not None
            assert list_annotations(reopened[0])[0]["rotation"] == pytest.approx(27.5)
            assert update_annotation_geometry(reopened[0], changed,
                rect=list_annotations(reopened[0])[0]["rect"], rotation=0) is not None
            entry = list_annotations(reopened[0])[0]
            visual = entry["rect"] * reopened[0].rotation_matrix
            assert tuple(visual) == pytest.approx((100, 100, 300, 200), abs=.02)


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
def test_native_stamp_fractional_angle_is_editable_without_drift(page_rotation):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.set_rotation(page_rotation)
        apply_annotation(doc, AnnotationOp(kind="stamp", page=0,
            rects=(fitz.Rect(100, 100, 290, 150) * page.derotation_matrix,),
            visual_rotation=page_rotation, rotation=27.5))
        for angle in (90., -12.5, 27.5, 0.):
            entry = list_annotations(page)[0]
            assert update_annotation_geometry(page, entry["xref"], rect=entry["rect"], rotation=angle)
            entry = list_annotations(page)[0]
            assert entry["rotation"] == pytest.approx(angle)
        assert tuple(entry["rect"] * page.rotation_matrix) == pytest.approx((100, 100, 290, 150), abs=.02)


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
def test_native_stamp_angle_matches_independent_native_reference_after_save(page_rotation):
    with fitz.open() as doc, fitz.open() as reference:
        page = doc.new_page(width=595 if page_rotation % 180 == 0 else 842,
                            height=842 if page_rotation % 180 == 0 else 595)
        page.set_rotation(page_rotation)
        apply_annotation(doc, AnnotationOp(kind="stamp", page=0,
            rects=(fitz.Rect(100, 100, 290, 150) * page.derotation_matrix,),
            visual_rotation=page_rotation, rotation=30))
        ref = reference.new_page(width=595, height=842)
        stamp = ref.add_stamp_annot(fitz.Rect(100, 100, 290, 150), stamp=fitz.STAMP_Draft)
        stamp.set_rotation(30)
        stamp.update()
        expected = np.frombuffer(ref.get_pixmap().samples, np.uint8).astype(float)
        with fitz.open(stream=doc.tobytes(garbage=4), filetype="pdf") as reopened:
            actual = np.frombuffer(reopened[0].get_pixmap().samples, np.uint8).astype(float)
            assert np.abs(actual - expected).mean() < .15
            assert list_annotations(reopened[0])[0]["rotation"] == pytest.approx(30)


def test_rotated_insertion_guide_tracks_output_orientation(qt_application):
    overlay = PageOverlay(0)
    pixmap = QPixmap(400, 350)
    pixmap.fill()
    overlay.set_pixmap(pixmap)
    overlay.set_geometry_info(fitz.Rect(0, 0, 400, 350), 1.)
    overlay.set_annotation_preview_style("image", color="#0000ff", rotation=30)
    overlay._marquee = QRectF(100, 100, 200, 100)
    overlay.show()
    qt_application.processEvents()
    try:
        image = overlay.grab().toImage()
        # The upper-right corner rotates counterclockwise from (300, 100)
        # to (261.6, 56.7), outside the original unrotated guide.
        dpr = image.devicePixelRatio()
        color = image.pixelColor(round(262 * dpr), round(57 * dpr))
        assert color.blue() > color.red() + 50
    finally:
        overlay.close()
        overlay.deleteLater()


@pytest.mark.parametrize("kind", ["image", "stamp"])
@pytest.mark.parametrize("angle", [float("nan"), float("inf"), 361])
def test_invalid_angle_is_rejected_before_pdf_mutation(asymmetric_image, kind, angle):
    with fitz.open() as doc:
        doc.new_page(width=595, height=842)
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(ValueError, match="angle"):
            apply_annotation(doc, AnnotationOp(kind=kind, page=0,
                rects=(fitz.Rect(100, 100, 290, 150),),
                image_path=str(asymmetric_image), rotation=angle))
        assert doc.tobytes(no_new_id=True) == before


def test_stamp_with_shared_indirect_appearance_edits_only_selected():
    with fitz.open() as doc:
        page = doc.new_page()
        first = page.add_stamp_annot(fitz.Rect(100, 100, 290, 150), stamp=fitz.STAMP_Draft)
        second = page.add_stamp_annot(fitz.Rect(100, 300, 290, 350), stamp=fitz.STAMP_Draft)
        appearance = doc.get_new_xref()
        doc.update_object(appearance, doc.xref_get_key(first.xref, "AP")[1])
        for stamp in (first, second):
            doc.xref_set_key(stamp.xref, "AP", f"{appearance} 0 R")
        before = page.get_pixmap(clip=fitz.Rect(80, 280, 310, 370)).samples
        assert update_annotation_geometry(page, first.xref, rect=first.rect, rotation=27.5)
        assert page.get_pixmap(clip=fitz.Rect(80, 280, 310, 370)).samples == before
        with fitz.open(stream=doc.tobytes(), filetype="pdf") as reopened:
            entries = list_annotations(reopened[0])
            assert entries[0]["rotation"] == pytest.approx(27.5)
            assert entries[1]["rotation"] == pytest.approx(0)


def test_rotated_image_width_edit_preserves_angle_and_local_height(editor, tmp_path, asymmetric_image):
    session = documents(editor, tmp_path, count=1)[0]
    editor._handle_annotation(AnnotationOp(kind="image", page=0,
        rects=(fitz.Rect(100, 100, 300, 200),), image_path=str(asymmetric_image), rotation=27.5))
    entry = list_annotations(session.engine.document[0])[0]
    editor._canvas_annotation_selected(session, 0, entry["xref"])
    editor.context_panel._image_keep_aspect.setChecked(False)
    editor.context_panel._image_dimensions["width"].setValue(250 * 25.4 / 72)
    editor.context_panel._apply_selected_annotation()
    changed = list_annotations(session.engine.document[0])[0]
    assert changed["image_size"] == pytest.approx((250, 100), abs=.02)
    assert changed["rotation"] == pytest.approx(27.5)
    assert (changed["rect"].x0, changed["rect"].y0) == pytest.approx((entry["rect"].x0, entry["rect"].y0), abs=.02)


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
def test_slanted_image_drag_resizes_local_axes_without_angle_drift(qt_application, asymmetric_image, keep, page_rotation):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.set_cropbox(fitz.Rect(20, 30, 575, 812))
        page.set_rotation(page_rotation)
        apply_annotation(doc, AnnotationOp(kind="image", page=0,
            rects=(fitz.Rect(100, 100, 300, 200) * page.derotation_matrix,), image_path=str(asymmetric_image),
            rotation=27.5, visual_rotation=page_rotation, keep_aspect=keep))
        entry = list_annotations(doc[0])[0]
        overlay = PageOverlay(0)
        pixmap = QPixmap(int(page.rect.width), int(page.rect.height))
        pixmap.fill()
        overlay.set_pixmap(pixmap)
        overlay.set_geometry_info(page.rect, 1., rotation_matrix=page.rotation_matrix,
                                  derotation_matrix=page.derotation_matrix)
        overlay.set_annotations([entry])
        overlay.select_annotation(entry["xref"])
        overlay.show()
        qt_application.processEvents()
        edits = []
        overlay.annotationGeometryChanged.connect(lambda page, xref, payload: edits.append(payload))
        # Move the bottom-right corner 50 pt along the image's width axis.
        visual = fitz.Point(entry["image_quad"][3]) * page.rotation_matrix
        point = QPointF(visual.x, visual.y)
        moved = point + QPointF(44.3505417, -23.0874307)
        try:
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=point.toPoint())
            QTest.mouseMove(overlay, moved.toPoint())
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=moved.toPoint())
            assert edits
            assert update_annotation_geometry(doc[0], entry["xref"], **edits[-1])
            changed = list_annotations(doc[0])[0]
            assert changed["rotation"] == pytest.approx(27.5, abs=.001)
            assert changed["image_size"] == pytest.approx((250, 125 if keep else 100), abs=1.5)
            assert changed["image_quad"][0] == pytest.approx(entry["image_quad"][0], abs=1.5)
            u = fitz.Point(changed["image_quad"][1]) - fitz.Point(changed["image_quad"][0])
            v = fitz.Point(changed["image_quad"][2]) - fitz.Point(changed["image_quad"][0])
            assert u.x * v.x + u.y * v.y == pytest.approx(0, abs=.1)
        finally:
            overlay.close()
            overlay.deleteLater()
