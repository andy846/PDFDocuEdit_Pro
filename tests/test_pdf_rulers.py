from __future__ import annotations

import fitz
import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.measurement import set_page_scale
from ui.page_overlay import PageOverlay
from ui.pdf_canvas import LayoutMode, PdfCanvas, ToolMode
from ui.pdf_rulers import MM_PER_POINT, major_interval


@pytest.fixture
def canvas(qt_application, monkeypatch):
    value = PdfCanvas()
    # Rulers must work before pixmaps arrive and do not need PDF rendering.
    monkeypatch.setattr(value, "_request_render", lambda *_: None)
    value.resize(960, 640)
    value.show()
    yield value
    value.clear()
    value.close()
    value.deleteLater()
    qt_application.processEvents()


def settle():
    QTest.qWait(100)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("zoom", [.25, 1, 4])
def test_paper_coordinates_crop_rotation_zoom_and_units(canvas, rotation, zoom):
    doc = fitz.open()
    page = doc.new_page(width=640, height=880)
    page.set_cropbox(fitz.Rect(20, 40, 620, 840))
    page.set_rotation(rotation)
    set_page_scale(doc[0], 100)
    canvas.load_doc(doc, zoom)
    canvas.set_tool_mode(ToolMode.MEASURE)
    settle()
    try:
        rulers = canvas.rulers
        rect, width, height = rulers.state
        assert width == pytest.approx(doc[0].rect.width*MM_PER_POINT)
        assert height == pytest.approx(doc[0].rect.height*MM_PER_POINT)
        assert rulers.horizontal.position_mm(rect.left()) == pytest.approx(0)
        assert rulers.vertical.position_mm(rect.top()) == pytest.approx(0)
        assert rulers.horizontal.position_mm(rect.right()) == pytest.approx(width)
        assert rulers.vertical.position_mm(rect.bottom()) == pytest.approx(height)
        assert rulers.horizontal.position_mm(rect.left()+72*zoom) == pytest.approx(25.4)
        assert rulers.vertical.position_mm(rect.top()+72*zoom) == pytest.approx(25.4)
        canvas.set_measure_unit("cm")
        assert rulers.corner.text() == "P1\ncm"
        assert rulers.horizontal.position_mm(rect.right()) == pytest.approx(width)
        assert canvas.page_measure_scale(0).real_per_paper == 100
        assert "Paper" in rulers.corner.toolTip()
        assert not rulers.horizontal.grab().isNull()
    finally:
        canvas.clear()
        doc.close()


@pytest.mark.parametrize("layout", [LayoutMode.SINGLE, LayoutMode.CONTINUOUS, LayoutMode.FACING])
def test_hover_reference_scroll_and_exit_fallback(canvas, layout):
    doc = fitz.open()
    for width, height in ((300, 400), (320, 420), (310, 410), (300, 400)):
        doc.new_page(width=width, height=height)
    canvas.load_doc(doc)
    canvas.set_layout_mode(layout)
    canvas.set_tool_mode(ToolMode.MEASURE)
    settle()
    try:
        target = 1 if layout == LayoutMode.FACING else 0
        overlay = canvas._page_views[target].overlay
        QApplication.sendEvent(overlay, QMouseEvent(
            QEvent.Type.MouseMove, QPointF(80, 80), QPointF(overlay.mapToGlobal(QPoint(80, 80))),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        QTest.qWait(50)
        assert canvas.rulers.reference_page == target
        assert canvas.rulers.pointer is not None
        rect = canvas.rulers.state[0]
        assert canvas.rulers.horizontal.position_mm(canvas.rulers.pointer.x()) == pytest.approx(80*MM_PER_POINT, abs=.1)
        generation = canvas._generation
        canvas.horizontalScrollBar().setValue(20)
        canvas.verticalScrollBar().setValue(30)
        canvas.rulers.reset_pointer()
        assert canvas.rulers.reference_page == canvas.current_page
        assert canvas.rulers.pointer is None
        assert canvas._generation == generation
        canvas.set_page(2)
        settle()
        assert canvas.rulers.reference_page == 2
        assert canvas.rulers.state[0] != rect
    finally:
        canvas.clear()
        doc.close()


def test_toggle_keeps_page_measurements_zoom_and_view_anchor(canvas):
    doc = fitz.open()
    doc.new_page(width=900, height=1200)
    canvas.load_doc(doc, 2)
    settle()
    canvas.horizontalScrollBar().setValue(300)
    canvas.verticalScrollBar().setValue(500)
    canvas._measurements[0] = [((10, 20), (100, 20))]
    original = doc.tobytes(no_new_id=True)
    anchor = canvas._view_anchor()
    generation = canvas._generation
    try:
        for _ in range(3):
            canvas.set_tool_mode(ToolMode.MEASURE)
            settle()
            assert canvas.rulers.horizontal.isVisible() and canvas.viewportMargins().left() == 40
            assert canvas._view_anchor() == pytest.approx(anchor, abs=.002)
            canvas.set_tool_mode(ToolMode.BROWSE)
            settle()
            assert not canvas.rulers.horizontal.isVisible() and canvas.viewportMargins().left() == 0
            assert canvas._view_anchor() == pytest.approx(anchor, abs=.002)
        assert canvas._zoom == 2
        assert canvas.current_page == 0 and canvas._generation == generation
        assert canvas._measurements[0] == [((10, 20), (100, 20))]
        assert doc.tobytes(no_new_id=True) == original
    finally:
        canvas.clear()
        doc.close()


def test_empty_clear_reload_and_mouse_do_not_request_pdf_renders(canvas, monkeypatch):
    canvas.set_tool_mode(ToolMode.MEASURE)
    assert canvas.rulers.state is None
    doc = fitz.open()
    doc.new_page()
    canvas.load_doc(doc)
    settle()
    try:
        # Drain initial layout before isolating cursor/unit-only updates.
        canvas._resize_timer.stop()
        canvas._apply_pending_relayout()
        requests = []
        monkeypatch.setattr(canvas, "_request_render", lambda *args: requests.append(args))
        for point in (QPoint(30, 40), QPoint(50, 60), QPoint(100, 80)):
            QTest.mouseMove(canvas._page_views[0].overlay, point)
            canvas.rulers.horizontal.grab()
        canvas.set_measure_unit("cm")
        QTest.qWait(50)
        assert requests == []
        canvas.clear()
        assert canvas.rulers.state is None and canvas.rulers.reference_page is None
        canvas.set_tool_mode(ToolMode.BROWSE)
    finally:
        canvas.clear()
        doc.close()


def test_endpoint_tick_is_fine_and_hit_radius_is_unchanged(qt_application):
    image = QImage(80, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    PageOverlay._paint_measure_endpoint(painter, QPointF(40, 40), "#0066ff")
    painter.end()
    assert image.pixelColor(40, 40) != QColor("white")
    assert image.pixelColor(43, 43) == QColor("white")
    overlay = PageOverlay(0)
    overlay.set_geometry_info(fitz.Rect(0, 0, 100, 100), 1)
    overlay.set_measurements([((40, 40), (70, 40))])
    assert overlay._measure_target(QPointF(48, 43))[:3] == ("temporary", 0, 0)
    overlay.close()


@pytest.mark.parametrize("subject,count", [("Measurement", 2), ("", 0)])
def test_saved_measurement_annotation_uses_precision_ticks_only(qt_application, monkeypatch, subject, count):
    overlay = PageOverlay(0)
    overlay.set_geometry_info(fitz.Rect(0, 0, 100, 100), 1)
    overlay.set_annotations([{"kind": "Line", "subject": subject, "xref": 10,
                              "vertices": [(20, 20), (70, 20)]}])
    overlay.select_annotation(10)
    seen = []
    monkeypatch.setattr(overlay, "_paint_measure_endpoint", lambda *args: seen.append(args[1]))
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    overlay._paint_selected_annotation(painter, {"primary": "#0066ff"})
    painter.end()
    assert len(seen) == count
    overlay.close()


@pytest.mark.parametrize("scale", [.05, .5, 1, 4, 20])
def test_tick_density_is_bounded_and_labels_readable(scale):
    interval = major_interval(scale)
    assert interval*scale >= 65
    assert interval/10*scale >= 6.5
