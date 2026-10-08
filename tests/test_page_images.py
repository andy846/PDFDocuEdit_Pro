from __future__ import annotations

import fitz
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QHBoxLayout, QScrollArea, QWidget

from core.annotation_io import annotation_payload
from core.annotations import (
    AnnotationOp,
    apply_annotation,
    list_annotations,
    remove_annotation,
    update_annotation_geometry,
)
from core.page_images import PageImageError, list_page_images
from ui.context_panel import ContextPanel
from ui.page_overlay import PageOverlay


@pytest.fixture
def image_file(tmp_path):
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), True)
    pixmap.clear_with(180)
    path = tmp_path / "image.png"
    pixmap.save(path)
    return path


def add_image(doc, image_file, rect=None):
    rect = fitz.Rect(40, 50, 140, 150) if rect is None else rect
    apply_annotation(doc, AnnotationOp(kind="image", page=0, rects=(rect,), image_path=str(image_file)))
    return list_page_images(doc.load_page(0))[-1]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_image_fit_move_resize_crop_rotation_and_save(image_file, tmp_path, rotation):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.set_cropbox(fitz.Rect(20, 30, 280, 380))
        page.set_rotation(rotation)
        page.insert_text((30, 30), "Searchable original")
        entry = add_image(doc, image_file)
        assert entry["rect"] == fitz.Rect(40, 75, 140, 125)
        image_xref = page.get_images()[0][0]
        # Rendered placement, not just our saved position metadata.
        assert tuple(page.get_image_rects(image_xref)[0]) == pytest.approx(tuple(entry["rect"]))
        target = fitz.Rect(80, 120, 200, 180)
        changed = update_annotation_geometry(page, entry["xref"], rect=target)
        assert changed is not None
        page = doc.load_page(0)
        assert tuple(page.get_image_rects(image_xref)[0]) == pytest.approx(tuple(target))
        assert "Searchable original" in page.get_text()
        assert not list(page.annots() or [])  # remains printable page content
        output = tmp_path / f"edited-{rotation}.pdf"
        doc.save(output, garbage=4, deflate=True)
    with fitz.open(output) as saved:
        entry = list_annotations(saved[0])[0]
        assert tuple(entry["rect"]) == pytest.approx(tuple(target))
        assert saved[0].rotation == rotation
        assert update_annotation_geometry(saved[0], entry["xref"], rect=fitz.Rect(20, 20, 80, 50)) is not None


def test_duplicate_page_and_shared_image_are_isolated(image_file):
    with fitz.open() as doc:
        doc.new_page(width=300, height=400).insert_text((20, 20), "Keep content")
        entry = add_image(doc, image_file)
        doc.fullcopy_page(0)
        # Also exercise the case where another page directly shares our stream.
        doc.load_page(1).set_contents(entry["xref"])
        doc.new_page(width=300, height=400).insert_image(fitz.Rect(10, 10, 70, 40), filename=str(image_file))
        before = [doc.load_page(i).get_pixmap().samples for i in (1, 2)]
        new_xref = update_annotation_geometry(doc.load_page(0), entry["xref"], rect=fitz.Rect(20, 20, 220, 120))
        assert new_xref != entry["xref"]
        assert [doc.load_page(i).get_pixmap().samples for i in (1, 2)] == before
        assert remove_annotation(doc.load_page(0), new_xref)
        assert list_page_images(doc.load_page(0)) == []
        assert "Keep content" in doc[0].get_text()
        assert [doc.load_page(i).get_pixmap().samples for i in (1, 2)] == before


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_after_image_keeps_selection_aligned(image_file, rotation):
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        entry = add_image(doc, image_file)
        page = doc[0]
        page.set_cropbox(fitz.Rect(20, 30, 280, 380))
        page.set_rotation(rotation)
        entry = list_page_images(doc[0])[0]
        assert entry["rect"] == fitz.Rect(20, 45, 120, 95)
        target = fitz.Rect(40, 50, 180, 120)
        assert update_annotation_geometry(doc[0], entry["xref"], rect=target) is not None
        page = doc[0]
        assert tuple(page.get_image_rects(page.get_images()[0][0])[0]) == pytest.approx(tuple(target))


def test_bad_size_wrong_page_and_interchange(image_file):
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        doc.new_page(width=300, height=400)
        entry = add_image(doc, image_file)
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(ValueError, match="inside the page"):
            update_annotation_geometry(doc[0], entry["xref"], rect=fitz.Rect(0, 0, 400, 100))
        assert update_annotation_geometry(doc[1], entry["xref"], rect=fitz.Rect(10, 10, 50, 30)) is None
        assert not remove_annotation(doc[1], entry["xref"])
        assert doc.tobytes(no_new_id=True) == before
        assert annotation_payload(doc)["annotations"] == []


@pytest.mark.parametrize("multiple_streams", [False, True])
def test_external_unwrapped_pdf_image_insert_preserves_original_content(image_file, tmp_path, multiple_streams):
    source = tmp_path / "external.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=400)
        streams = [b"0 0 0 rg 10 10 30 30 re f"]
        if multiple_streams:
            # The original document's last stream leaves a graphics transform.
            streams.append(b"2 0 0 2 12 8 cm 0 0 1 rg 10 10 10 10 re f")
        refs = []
        for stream in streams:
            xref = doc.get_new_xref()
            doc.update_object(xref, "<<>>")
            doc.update_stream(xref, stream)
            refs.append(xref)
        doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{ref} 0 R" for ref in refs) + "]")
        doc.save(source)
    with fitz.open(source) as doc:
        page = doc[0]
        assert not page.is_wrapped
        before = page.get_pixmap().samples
        entry = add_image(doc, image_file)
        images = list_page_images(doc[0])
        assert len(images) == 1
        page = doc[0]
        assert tuple(page.get_image_rects(page.get_images()[0][0])[0]) == pytest.approx(tuple(entry["rect"]))
        new_xref = update_annotation_geometry(page, entry["xref"], rect=fitz.Rect(100, 200, 200, 250))
        assert new_xref is not None
        assert remove_annotation(doc[0], new_xref)
        # Both wrapping streams stay intact: deleting the image must not alter
        # the customer's original graphics or the state isolation around them.
        assert doc[0].get_pixmap().samples == before


def test_image_selection_drag_resize_and_precise_properties(qt_application, image_file):
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        entry = add_image(doc, image_file)
        overlay = PageOverlay(0)
        overlay.set_pixmap(QPixmap(300, 400))
        overlay.set_geometry_info(doc[0].rect, 1.0)
        overlay.set_annotations([entry])
        overlay.show()
        changes = []
        overlay.annotationGeometryChanged.connect(lambda page, xref, payload: changes.append(payload))
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPointF(90, 100).toPoint())
        QTest.mouseMove(overlay, QPointF(110, 130).toPoint())
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPointF(110, 130).toPoint())
        assert changes[-1]["rect"] == fitz.Rect(60, 105, 160, 155)
        # A corner handle enlarges both dimensions while preserving proportions.
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPointF(140, 125).toPoint())
        QTest.mouseMove(overlay, QPointF(180, 145).toPoint())
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPointF(180, 145).toPoint())
        assert changes[-1]["rect"] == fitz.Rect(40, 75, 180, 145)
        panel = ContextPanel()
        panel.refresh_annotation_list([dict(entry, page=0)])
        panel.select_annotation(0, entry["xref"])
        assert not panel._image_geometry.isHidden()
        assert panel._apply_properties.text() == "Apply Position && Size"
        panel._image_dimensions["width"].setValue(50)
        assert panel._image_dimensions["height"].value() == 25
        edits = []
        panel.editAnnotationRequested.connect(lambda page, xref, payload: edits.append(payload))
        panel._apply_selected_annotation()
        assert edits[-1]["rect"].width == pytest.approx(50 * 72 / 25.4)
        assert edits[-1]["keep_aspect"]
        panel.refresh_annotation_list([dict(entry, rect=fitz.Rect(20, 30, 100, 70), page=0)])
        assert panel._image_dimensions["x"].value() == pytest.approx(20 * 25.4 / 72, abs=0.01)
        overlay.close()
        overlay.deleteLater()
        panel.deleteLater()


def test_modified_stream_cannot_delete_unrelated_content(image_file):
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        entry = add_image(doc, image_file)
        doc.update_stream(entry["xref"], doc.xref_stream(entry["xref"]) + b"0 0 20 20 re f\n")
        before = doc.tobytes(no_new_id=True)
        with pytest.raises(PageImageError, match="protect page content"):
            remove_annotation(doc[0], entry["xref"])
        with pytest.raises(PageImageError, match="protect page content"):
            update_annotation_geometry(doc[0], entry["xref"], rect=fitz.Rect(50, 50, 150, 100))
        assert doc.tobytes(no_new_id=True) == before


@pytest.mark.parametrize("kind", ["Image", "Signature Image"])
def test_precise_bounds_and_empty_list_disable_image_properties(qt_application, kind):
    panel = ContextPanel()
    rect = fitz.Rect(13.123456, 26.987654, 595.275591, 841.889764)
    panel.refresh_annotation_list([{"page": 0, "kind": kind, "xref": 42, "rect": rect}])
    panel.select_annotation(0, 42)
    edits = []
    panel.editAnnotationRequested.connect(lambda page, xref, payload: edits.append(payload))
    panel._apply_selected_annotation()
    assert tuple(edits[-1]["rect"]) == pytest.approx(tuple(rect), abs=1e-8)
    panel._image_keep_aspect.setChecked(False)
    panel._image_dimensions["x"].setValue(10)
    panel._apply_selected_annotation()
    assert edits[-1]["rect"].x0 == pytest.approx(10 * 72 / 25.4)
    assert edits[-1]["rect"].height == pytest.approx(rect.height)
    panel.refresh_annotation_list([])
    assert not panel._apply_properties.isEnabled()
    assert not panel._remove_selected.isEnabled()
    assert panel._image_geometry.isHidden()
    panel.deleteLater()


def test_blank_click_clears_selection(qt_application, image_file):
    from ui.pdf_canvas import PdfCanvas
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        entry = add_image(doc, image_file)
        canvas = PdfCanvas()
        overlay = PageOverlay(0)
        overlay.set_pixmap(QPixmap(300, 400))
        overlay.set_geometry_info(doc[0].rect, 1.0)
        overlay.set_annotations([entry])
        overlay.annotationSelected.connect(canvas._on_annotation_selected)
        overlay.annotationSelectionCleared.connect(canvas._on_annotation_selection_cleared)
        overlay.show()
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPointF(90, 100).toPoint())
        assert canvas.selected_annotation() == (0, entry["xref"])
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPointF(250, 300).toPoint())
        assert canvas.selected_annotation() is None
        assert overlay._selected_xref is None
        overlay.close()
        overlay.deleteLater()
        canvas.deleteLater()


def test_image_properties_keyboard_focus_reveals_full_control(qt_application):
    window = QWidget()
    layout = QHBoxLayout(window)
    panel = ContextPanel()
    panel.set_animations_enabled(False)
    layout.addWidget(panel)
    panel.show_tool("annotate", "Image Position & Size")
    panel.refresh_annotation_list([{"page": 0, "kind": "Image", "xref": 42,
                                    "rect": fitz.Rect(40, 75, 140, 125)}])
    panel.select_annotation(0, 42)
    window.resize(420, 400)
    window.show()
    qt_application.processEvents()
    try:
        for field in panel._image_dimensions.values():
            field.setFocus()
            qt_application.processEvents()
            ancestor = field.parentWidget()
            while ancestor is not None:
                if isinstance(ancestor, QScrollArea):
                    origin = field.mapTo(ancestor.viewport(), QPoint(0, 0))
                    assert ancestor.viewport().rect().contains(origin)
                    assert ancestor.viewport().rect().contains(
                        origin + QPoint(field.width() - 1, field.height() - 1))
                ancestor = ancestor.parentWidget()
        button = panel._apply_properties
        origin = button.mapTo(window, QPoint(0, 0))
        assert window.rect().contains(origin + QPoint(button.width() - 1, button.height() - 1))
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_signature_image_is_editable_and_persistent(image_file, tmp_path, rotation):
    output = tmp_path / "signature.pdf"
    with fitz.open() as doc:
        doc.new_page(width=300, height=400)
        doc[0].set_rotation(rotation)
        apply_annotation(doc, AnnotationOp(kind="signature", page=0,
                                          rects=(fitz.Rect(40, 50, 140, 150),), image_path=str(image_file)))
        entry = list_annotations(doc[0])[0]
        assert entry["kind"] == "Signature Image"
        assert update_annotation_geometry(doc[0], entry["xref"], rect=fitz.Rect(50, 50, 150, 100)) is not None
        doc.save(output, garbage=4, deflate=True)
    with fitz.open(output) as saved:
        entry = list_annotations(saved[0])[0]
        assert entry["kind"] == "Signature Image"
        assert not list(saved[0].widgets() or [])
        assert remove_annotation(saved[0], entry["xref"])
