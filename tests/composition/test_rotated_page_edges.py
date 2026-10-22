"""Rotated boxes use visible page edges, without changing saved model positions."""
from dataclasses import asdict

import fitz
import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.canvas import Canvas
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.engine.renderer import render_preview
from composition.template.geometry import element_bounds
from composition.template.layout import arrange_elements
from composition.template.model import CompositionError, Element, Template
from composition.template.serializer import load_project, save_project
from tests.composition.test_i25 import decoded_i25
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def quiet_preview(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)


def barcode():
    return Element(type="i25", value="0001234560", x_mm=0, y_mm=52.81,
                   width_mm=42.5, height_mm=9.4, rotation_deg=90)


@pytest.mark.parametrize("angle", [90, 270, 37])
def test_rotated_box_can_align_to_left_and_save(tmp_path, angle):
    element = barcode()
    element.rotation_deg = angle
    element.x_mm -= element_bounds(element)[0]
    template = Template.from_dict(Template(elements=[element]).to_dict())
    restored = load_project(save_project(template, tmp_path / "edge.pdcx"))
    assert element_bounds(restored.elements[0])[0] == pytest.approx(0)
    assert restored.to_dict() == template.to_dict()
    element.x_mm -= 1
    with pytest.raises(CompositionError, match="page width"):
        Template.from_dict(Template(elements=[element]).to_dict())


def test_canvas_clamps_visible_bounds_and_keyboard_moves_rotated_box(app):
    canvas = Canvas()
    try:
        element = barcode()
        canvas.set_template(Template(elements=[element]), [element.id])
        item = canvas.element_items[0]
        item.moveBy(-100, 0)
        canvas.keep_group_on_page()
        assert item.mapRectToScene(item.rect()).left() == pytest.approx(0)
        assert item.pos().x() == pytest.approx(-16.55)
        QTest.keyClick(canvas, Qt.Key.Key_Right)
        assert element_bounds(element)[0] == pytest.approx(.5)
        QTest.keyClick(canvas, Qt.Key.Key_Left)
        assert element_bounds(element)[0] == pytest.approx(0)
        QTest.keyClick(canvas, Qt.Key.Key_Left)
        assert element_bounds(element)[0] == pytest.approx(0)
    finally:
        canvas.close()


@pytest.mark.parametrize("overlay", [False, True])
def test_properties_visible_position_one_undo_and_no_drift(app, tmp_path, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        element = barcode()
        if overlay:
            spec = sample_spec(tmp_path)
            spec.objects[1].element = element
            window.apply_spec(spec.to_dict())
            def current():
                return window.spec.objects[1].element
        else:
            window._apply_template(Template(elements=[element]).to_dict())
            def current():
                return window.template.elements[0]
        window.undo.clear()
        window.canvas.select_ids([element.id])
        assert window.properties.numbers["x_mm"].value() == pytest.approx(16.55)
        assert window.properties.numbers["y_mm"].value() == pytest.approx(36.26)
        before = asdict(current())
        window.properties.apply()
        assert asdict(current()) == before
        window.properties.numbers["x_mm"].setValue(0)
        window.properties.apply_field("x_mm")
        assert element_bounds(current())[0] == pytest.approx(0)
        assert current().y_mm == before["y_mm"]
        assert window.undo.count() == 1
        saved = asdict(current())
        window.properties.apply()
        assert asdict(current()) == saved
        window.undo.undo()
        assert asdict(current()) == before
        window.undo.redo()
        assert asdict(current()) == saved
        assert window.properties.numbers["x_mm"].value() == 0
    finally:
        (finish if overlay else close_window)(window)


def test_arrange_left_uses_rotated_edge():
    element = barcode()
    result = arrange_elements([asdict(element)], [element.id], "left", (210, 297), reference="page")
    assert result[0]["x_mm"] == pytest.approx(-16.55)
    assert element_bounds(result[0])[0] == pytest.approx(0)


def test_render_negative_model_origin_preserves_rotated_pdf_position():
    element = Element(type="rectangle", x_mm=-16.55, y_mm=52.81,
                      width_mm=42.5, height_mm=9.4, rotation_deg=90, fill="#000000")
    template = Template.from_dict(Template(elements=[element]).to_dict())
    raw = render_preview(template, {})
    with fitz.open(stream=raw, filetype="pdf") as document:
        bounds = document[0].get_drawings()[0]["rect"]
        expected = [value * 72 / 25.4 for value in element_bounds(element)]
        assert tuple(bounds) == pytest.approx(expected, abs=.001)


@pytest.mark.parametrize("angle", [90, 270])
def test_rotated_i25_at_left_edge_decodes(angle):
    element = barcode()
    element.rotation_deg = angle
    element.x_mm -= element_bounds(element)[0]
    raw = render_preview(Template.from_dict(Template(elements=[element]).to_dict()), {})
    with fitz.open(stream=raw, filetype="pdf") as document:
        assert decoded_i25(document[0]) == [element.value]


def test_mouse_drag_can_commit_rotated_barcode_at_left_edge(app):
    canvas = Canvas()
    try:
        canvas.resize(700, 800)
        canvas.show()
        element = barcode()
        canvas.set_template(Template(elements=[element]), [element.id])
        canvas.set_zoom(1)
        canvas.set_snap_guides(False)
        app.processEvents()
        item = canvas.element_items[0]
        centre = item.mapToScene(item.rect().center())
        start = canvas.mapFromScene(centre)
        end = canvas.mapFromScene(centre - QPointF(16.55, 0))
        commits = []
        canvas.editCommitted.connect(lambda before, after: commits.append(after))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end, 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert len(commits) == 1
        assert element.x_mm < -16
        assert element_bounds(element)[0] == pytest.approx(0, abs=.2)
        Template.from_dict(commits[0])
    finally:
        canvas.close()


def test_rotated_top_edge_and_unrotated_offpage_validation():
    element = Element(type="rectangle", x_mm=50, y_mm=-16.55,
                      width_mm=9.4, height_mm=42.5, rotation_deg=90)
    restored = Template.from_dict(Template(elements=[element]).to_dict())
    assert element_bounds(restored.elements[0])[1] == pytest.approx(0)
    element.rotation_deg = 0
    with pytest.raises(CompositionError, match="page height"):
        Template.from_dict(Template(elements=[element]).to_dict())


@pytest.mark.parametrize("overlay", [False, True])
def test_y_property_can_position_rotated_tall_object_at_top(app, tmp_path, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        element = Element(type="rectangle", x_mm=50, y_mm=0, width_mm=9.4,
                          height_mm=42.5, rotation_deg=90)
        if overlay:
            spec = sample_spec(tmp_path)
            spec.objects[0].element = element
            window.apply_spec(spec.to_dict())
        else:
            window._apply_template(Template(elements=[element]).to_dict())
        window.canvas.select_ids([element.id])
        assert window.properties.numbers["y_mm"].value() == pytest.approx(16.55)
        window.properties.numbers["y_mm"].setValue(0)
        window.properties.apply_field("y_mm")
        item = next(item for item in window.canvas.element_items if item.element.id == element.id)
        assert item.element.y_mm == pytest.approx(-16.55)
        assert element_bounds(item.element)[1] == pytest.approx(0)
    finally:
        (finish if overlay else close_window)(window)


def test_overlay_at_left_edge_saves_and_production_barcodes_decode(tmp_path):
    from composition.overlay.model import OverlayJob
    from composition.overlay.serializer import load_project, save_project
    from tests.production_approval import overlay_generate

    spec = sample_spec(tmp_path)
    element = barcode()
    element.x_mm -= element_bounds(element)[0]
    spec.objects[1].element = element
    restored = load_project(save_project(spec, tmp_path / "edge-overlay.pdcx"))
    assert restored.to_dict() == spec.to_dict()
    result = overlay_generate(OverlayJob(restored.to_dict(), str(tmp_path / "output"), chunk_size=3))
    assert result.status == "completed", result.error
    assert result.expected_barcodes == result.decoded_barcodes == 6
