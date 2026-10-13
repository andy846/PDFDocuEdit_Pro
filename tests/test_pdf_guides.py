"""Reference guides stay on paper, snap in screen pixels, and never alter PDFs."""
import fitz
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QInputDialog

from ui.pdf_canvas import LayoutMode, PdfCanvas, ToolMode
from ui.pdf_rulers import MM_PER_POINT


@pytest.fixture
def canvas(qt_application, monkeypatch):
    value = PdfCanvas()
    monkeypatch.setattr(value, "_request_render", lambda *_: None)
    value.resize(960, 640)
    value.show()
    yield value
    value.clear()
    value.close()
    value.deleteLater()


def load(canvas, rotation=0, zoom=1):
    doc = fitz.open()
    page = doc.new_page(width=340, height=460)
    page.set_cropbox(fitz.Rect(20, 30, 320, 430))
    page.set_rotation(rotation)
    doc.new_page(width=350, height=450)
    canvas.load_doc(doc, zoom)
    canvas.set_tool_mode(ToolMode.MEASURE)
    QTest.qWait(100)
    return doc


def mouse(widget, kind, point, modifiers=Qt.KeyboardModifier.NoModifier):
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    QApplication.sendEvent(widget, QMouseEvent(kind, point,
        QPointF(widget.mapToGlobal(point.toPoint())), button, buttons, modifiers))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("zoom", [.5, 2])
def test_guide_snap_paper_coordinates_and_alt_shift(canvas, rotation, zoom):
    doc = load(canvas, rotation, zoom)
    try:
        overlay = canvas._page_views[0].overlay
        guide = canvas.rulers.add_guide(0, "x", 25.4)
        canvas.rulers.add_guide(0, "y", 38.1)
        first, last = (overlay.pdf_point_to_widget(point) for point in guide.points)
        assert first.x() == last.x() == pytest.approx(72*zoom)
        assert first.y() == pytest.approx(0)
        point = QPointF(72*zoom+7, 108*zoom-7)
        snapped = overlay._measure_point(point, Qt.KeyboardModifier.NoModifier)
        displayed = overlay.pdf_point_to_widget(snapped)
        assert displayed.x() == pytest.approx(72*zoom)
        assert displayed.y() == pytest.approx(108*zoom)
        raw = overlay.pdf_point_to_widget(overlay._measure_point(point, Qt.KeyboardModifier.AltModifier))
        assert raw.x() == pytest.approx(point.x())
        assert raw.y() == pytest.approx(point.y())
        unsnapped = overlay.pdf_point_to_widget(overlay._measure_point(
            QPointF(72*zoom+9, 108*zoom+9), Qt.KeyboardModifier.NoModifier))
        assert unsnapped.x() == pytest.approx(72*zoom+9)
        anchor = overlay.widget_to_pdf(QPointF(20*zoom, 100*zoom))
        constrained = overlay.pdf_point_to_widget(overlay._measure_point(
            point, Qt.KeyboardModifier.ShiftModifier, anchor))
        assert constrained.x() == pytest.approx(72*zoom)
        assert constrained.y() == pytest.approx(100*zoom)
        assert overlay.pdf_point_to_widget(overlay._measure_point(
            QPointF(6, 80), Qt.KeyboardModifier.NoModifier)).x() == pytest.approx(0)
    finally:
        canvas.clear()
        doc.close()


def test_ruler_drag_existing_move_escape_and_drag_outside(canvas):
    doc = load(canvas)
    try:
        rulers = canvas.rulers
        overlay = canvas._page_views[0].overlay
        original_bytes = doc.tobytes(no_new_id=True)
        drawn = []
        overlay.measurementDrawn.connect(lambda *args: drawn.append(args))
        mouse(rulers.horizontal, QEvent.Type.MouseButtonPress, QPointF(80, 10))
        target = QPointF(overlay.mapToGlobal(QPointF(100, 80).toPoint()))
        # While mouse is grabbed by the ruler, the local point lies outside it.
        local = QPointF(rulers.horizontal.mapFromGlobal(target.toPoint()))
        mouse(rulers.horizontal, QEvent.Type.MouseMove, local)
        mouse(rulers.horizontal, QEvent.Type.MouseButtonRelease, local)
        original = rulers.guides[0][0]
        assert overlay.pdf_point_to_widget(original.points[0]).y() == pytest.approx(80)
        assert drawn == []
        alt = Qt.KeyboardModifier.AltModifier
        mouse(overlay, QEvent.Type.MouseButtonPress, QPointF(100, 83), alt)
        mouse(overlay, QEvent.Type.MouseMove, QPointF(100, 123), alt)
        assert overlay.pdf_point_to_widget(rulers.guides[0][0].points[0]).y() == pytest.approx(120)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(overlay, event)
        assert rulers.guides[0] == [original]
        assert rulers.guide_drag is None
        mouse(overlay, QEvent.Type.MouseButtonPress, QPointF(100, 80), alt)
        mouse(overlay, QEvent.Type.MouseButtonRelease, QPointF(100, -30), alt)
        assert rulers.guides[0] == []
        assert drawn == []
        assert doc.tobytes(no_new_id=True) == original_bytes
    finally:
        canvas.clear()
        doc.close()


def test_measurement_clicks_on_guide_snap_without_moving_it(canvas):
    doc = load(canvas)
    try:
        rulers = canvas.rulers
        guide = rulers.add_guide(0, "y", 80*MM_PER_POINT)
        overlay = canvas._page_views[0].overlay
        for point in (QPointF(40, 84), QPointF(180, 78)):
            mouse(overlay, QEvent.Type.MouseButtonPress, point)
            mouse(overlay, QEvent.Type.MouseButtonRelease, point)
        measurement = canvas._measurements[0][0]
        assert measurement == ((40, 80), (180, 80))
        assert rulers.guides[0] == [guide]
        # Endpoint drag uses the same snap service.
        mouse(overlay, QEvent.Type.MouseButtonPress, QPointF(180, 80))
        mouse(overlay, QEvent.Type.MouseButtonRelease, QPointF(220, 85))
        assert canvas._measurements[0][0] == ((40, 80), (220, 80))
    finally:
        canvas.clear()
        doc.close()


def test_guides_modes_zoom_layout_visibility_clear_and_reload(canvas):
    doc = load(canvas)
    try:
        rulers = canvas.rulers
        guide = rulers.add_guide(0, "x", 25.4)
        rulers.set_guides_visible(False)
        assert canvas._page_views[0].overlay._reference_guides == ()
        rulers.set_guides_visible(True)
        canvas.set_tool_mode(ToolMode.BROWSE)
        assert rulers.guides[0] == [guide]
        assert canvas._page_views[0].overlay._reference_guides == ()
        canvas.set_tool_mode(ToolMode.MEASURE)
        canvas.set_zoom(2)
        QTest.qWait(100)
        overlay = canvas._page_views[0].overlay
        assert overlay._reference_guides == (guide.points,)
        assert overlay.pdf_point_to_widget(guide.points[0]).x() == pytest.approx(144)
        canvas.set_layout_mode(LayoutMode.FACING)
        QTest.qWait(100)
        assert canvas._page_views[0].overlay._reference_guides == (guide.points,)
        assert canvas._page_views[1].overlay._reference_guides == ()
        canvas.load_doc(doc)
        assert rulers.guides == {}
        rulers.add_guide(0, "y", 20)
        canvas.clear()
        assert rulers.guides == {} and rulers.guide_drag is None
    finally:
        canvas.clear()
        doc.close()


def test_numeric_position_uses_paper_units_and_settings(canvas, monkeypatch):
    doc = load(canvas)
    try:
        rulers = canvas.rulers
        canvas.set_measure_unit("cm")
        monkeypatch.setattr(QInputDialog, "getDouble", lambda *args: (2.54, True))
        rulers.edit_position(0, "x")
        guide = rulers.guides[0][0]
        overlay = canvas._page_views[0].overlay
        assert overlay.pdf_point_to_widget(guide.points[0]).x() == pytest.approx(72)
        rulers.snap_enabled = False
        assert rulers.snap_point(overlay, QPointF(77, 80), Qt.KeyboardModifier.NoModifier).x() == 77
        assert rulers.add_guide(0, "x", -1) is None
        assert rulers.add_guide(0, "x", float("nan")) is None
        assert rulers.add_guide(0, "x", 9999) is None
        monkeypatch.setattr(QInputDialog, "getDouble", lambda *args: (3, False))
        rulers.edit_position(0, "x", guide)
        assert rulers.guides[0] == [guide]
        rulers.clear_guides(0)
        assert overlay._reference_guides == ()
    finally:
        canvas.clear()
        doc.close()


def test_ruler_drop_targets_facing_page_and_zoom_cancels_drag(canvas):
    doc = load(canvas)
    try:
        canvas.set_layout_mode(LayoutMode.FACING)
        QTest.qWait(100)
        rulers = canvas.rulers
        second = canvas._page_views[1].overlay
        rulers.begin_guide(rulers.vertical, "x", page=0)
        target = QPointF(second.mapToGlobal(QPointF(80, 100).toPoint()))
        rulers.finish_guide(target)
        guide = rulers.guides[1][0]
        assert second._reference_guides == (guide.points,)
        assert not rulers.guides.get(0)
        first, last = (second.pdf_point_to_widget(p) for p in guide.points)
        assert first.x() == last.x() == pytest.approx(80)
        rulers.begin_guide(second, "x", page=1, original=guide)
        rulers.move_guide(QPointF(second.mapToGlobal(QPointF(120, 100).toPoint())))
        canvas.set_zoom(1.5)
        QTest.qWait(100)
        assert rulers.guide_drag is None and rulers.guides[1] == [guide]
    finally:
        canvas.clear()
        doc.close()


def test_page_replacement_does_not_inherit_guides(canvas):
    doc = load(canvas)
    try:
        canvas.rulers.add_guide(0, "x", 20)
        doc.select([1, 0])
        canvas.refresh()
        QTest.qWait(100)
        assert not canvas.rulers.guides.get(0)
        assert canvas._page_views[0].overlay._reference_guides == ()
    finally:
        canvas.clear()
        doc.close()
