"""Measurement gestures must preserve coordinates without endpoint jumps."""
import fitz
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from ui.page_overlay import PageOverlay


def mouse(overlay, kind, position, *, shift=False):
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    QApplication.sendEvent(overlay, QMouseEvent(
        kind, QPointF(position), QPointF(overlay.mapToGlobal(position.toPoint())), button, buttons,
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def overlay(qt_application):
    value = PageOverlay(0)
    value.set_geometry_info(fitz.Rect(0, 0, 300, 300), 1)
    value.resize(300, 300)
    value.set_measure_mode(True)
    value.show()
    yield value
    value.close()
    value.deleteLater()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("zoom", [.5, 2])
def test_drag_release_and_shift_follow_displayed_axes(overlay, rotation, zoom):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.set_rotation(rotation)
        overlay.set_geometry_info(page.rect, 1/zoom, page.rotation_matrix, page.derotation_matrix)
        overlay.resize(int(300*zoom), int(300*zoom))
        drawn = []
        overlay.measurementDrawn.connect(lambda _, points: drawn.append(points))
        start = QPointF(40, 40)
        end = QPointF(110, 55)
        mouse(overlay, QEvent.Type.MouseButtonPress, start)
        mouse(overlay, QEvent.Type.MouseMove, end, shift=True)
        mouse(overlay, QEvent.Type.MouseButtonRelease, end, shift=True)
        assert len(drawn) == 1
        first, last = (overlay.pdf_point_to_widget(point) for point in drawn[0])
        assert first.x() == pytest.approx(40)
        assert last.x() == pytest.approx(110)
        assert first.y() == last.y() == pytest.approx(40)
        assert overlay._measure_origin is None


def test_two_clicks_and_cancel_still_work(overlay):
    drawn = []
    overlay.measurementDrawn.connect(lambda _, points: drawn.append(points))
    for point in (QPointF(40, 40), QPointF(140, 70)):
        mouse(overlay, QEvent.Type.MouseButtonPress, point)
        mouse(overlay, QEvent.Type.MouseButtonRelease, point)
    assert drawn == [((40, 40), (140, 70))]
    mouse(overlay, QEvent.Type.MouseButtonPress, QPointF(60, 60))
    mouse(overlay, QEvent.Type.MouseMove, QPointF(200, 120))
    overlay.cancel_measurement()
    mouse(overlay, QEvent.Type.MouseButtonRelease, QPointF(200, 120))
    assert len(drawn) == 1


def test_endpoint_nearby_grab_preserves_offset_and_cancel(overlay):
    original = ((40, 40), (140, 40))
    overlay.set_measurements([original])
    moved = []
    overlay.measurementMoved.connect(lambda _, key, points: moved.append((key, points)))
    grab, target = QPointF(147, 44), QPointF(197, 84)
    mouse(overlay, QEvent.Type.MouseButtonPress, grab)
    mouse(overlay, QEvent.Type.MouseMove, grab)
    assert overlay._measurements[0] == original
    mouse(overlay, QEvent.Type.MouseMove, target)
    assert overlay._measurements[0] == ((40, 40), (190, 80))
    overlay.cancel_measurement()
    assert overlay._measurements[0] == original
    mouse(overlay, QEvent.Type.MouseButtonRelease, target)
    assert moved == []
    mouse(overlay, QEvent.Type.MouseButtonPress, grab)
    # Release must capture the final coordinate even without a move event.
    mouse(overlay, QEvent.Type.MouseButtonRelease, target)
    assert moved == [(0, ((40, 40), (190, 80)))]
