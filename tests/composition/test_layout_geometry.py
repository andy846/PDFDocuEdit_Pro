from __future__ import annotations

import copy
import math
from dataclasses import asdict

import fitz
import pytest
from PIL import Image
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.canvas import Canvas
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.engine.renderer import render_preview
from composition.overlay.generator import generate
from composition.overlay.model import EnvelopeSpec, OverlayJob
from composition.overlay.renderer import render_preview as overlay_preview
from composition.template.geometry import element_bounds
from composition.template.model import CompositionError, Element, Template
from composition.template.serializer import load_project, save_project
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def bounded_ui(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)


@pytest.mark.parametrize("angle", [0, 90, 180, 270, 37])
def test_vector_rotation_all_element_types_and_next_text_unaffected(tmp_path, angle):
    image = tmp_path / "image.png"
    Image.new("RGB", (40, 20), (0, 120, 255)).save(image)
    template = Template(elements=[
        Element(value="Rotated {{Value}}", x_mm=60, y_mm=80, height_mm=20, rotation_deg=angle),
        Element(type="rectangle", x_mm=130, y_mm=150, width_mm=20, height_mm=15, fill="#ff0000", rotation_deg=angle),
        Element(type="line", x_mm=65, y_mm=165, width_mm=40, height_mm=2, rotation_deg=angle),
        Element(type="image", image=str(image), x_mm=90, y_mm=180, width_mm=30, height_mm=25, rotation_deg=angle),
        Element(value="Unrotated next", y_mm=230),
    ])
    raw = render_preview(template, {"Value": "text"})
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        assert "Rotated text" in pdf[0].get_text()
        assert "Unrotated next" in pdf[0].get_text()
        lines = [line for block in pdf[0].get_text("dict")["blocks"] if "lines" in block for line in block["lines"]]
        first = next(line for line in lines if "Rotated" in "".join(s["text"] for s in line["spans"]))
        second = next(line for line in lines if "Unrotated" in "".join(s["text"] for s in line["spans"]))
        assert first["dir"] == pytest.approx((math.cos(math.radians(angle)), math.sin(math.radians(angle))), abs=1e-6)
        assert second["dir"] == (1, 0)
        assert len(pdf[0].get_drawings()) >= 2
        transform = pdf[0].get_image_info()[0]["transform"]
        direction = math.atan2(transform[1], transform[0])
        assert math.cos(direction) == pytest.approx(math.cos(math.radians(angle)), abs=1e-5)
        assert math.sin(direction) == pytest.approx(math.sin(math.radians(angle)), abs=1e-5)


@pytest.mark.parametrize("kind", ["code128", "i25", "qr"])
def test_rotated_overlay_barcodes_decode_and_preview_matches_output(tmp_path, kind):
    spec = sample_spec(tmp_path)
    barcode = spec.objects[1].element
    barcode.type = kind
    barcode.x_mm, barcode.y_mm = 60, 90
    barcode.width_mm, barcode.height_mm = (40, 40) if kind == "qr" else (90, 16)
    barcode.rotation_deg = 90
    raw, _fields = overlay_preview(spec, 1, 1)
    result = generate(OverlayJob(spec.to_dict(), str(tmp_path / "output"), chunk_size=3))
    assert result.status == "completed", result.error
    assert result.expected_barcodes == result.decoded_barcodes == 6
    with fitz.open(stream=raw, filetype="pdf") as preview, fitz.open(result.output_pdf) as output:
        assert preview[0].get_pixmap().samples == output[0].get_pixmap().samples


def test_format_migration_roundtrip_and_rotated_bounds(tmp_path):
    template = Template(elements=[Element(value="Saved", x_mm=60, y_mm=80, rotation_deg=37)])
    path = save_project(template, tmp_path / "rotated.pdcx")
    assert load_project(path).elements[0].rotation_deg == 37
    assert load_project(path).template_version == 11
    legacy = Template(elements=[Element()]).to_dict()
    legacy["template_version"] = 6
    del legacy["pages"][0]["elements"][0]["rotation_deg"]
    migrated = Template.from_dict(legacy)
    assert migrated.template_version == 11 and migrated.elements[0].rotation_deg == 0
    assert "rotation_deg" not in legacy["pages"][0]["elements"][0]
    legacy["pages"][0]["elements"][0]["rotation_deg"] = 37
    with pytest.raises(CompositionError, match="version 7"):
        Template.from_dict(legacy)
    element = Element(x_mm=20, y_mm=20, width_mm=70, height_mm=12, rotation_deg=90)
    with pytest.raises(CompositionError, match="page height"):
        Template.from_dict(Template(elements=[element]).to_dict())
    element.rotation_deg = float("nan")
    with pytest.raises(CompositionError, match="Rotation"):
        Template.from_dict(Template(elements=[element]).to_dict())


def test_overlay_legacy_migration_requires_new_version_for_rotation(tmp_path):
    raw = sample_spec(tmp_path).to_dict()
    raw["overlay_version"] = 1
    for obj in raw["objects"]:
        obj["element"].pop("rotation_deg")
    original = copy.deepcopy(raw)
    migrated = EnvelopeSpec.from_dict(raw)
    assert migrated.overlay_version == 7
    assert raw == original
    assert all(obj.element.rotation_deg == 0 for obj in migrated.objects)
    raw["objects"][0]["element"]["rotation_deg"] = 90
    with pytest.raises(CompositionError, match="version 2"):
        EnvelopeSpec.from_dict(raw)


def test_template_batch_size_rotation_preserves_text_fonts_and_one_undo(app):
    window = CompositionWindow()
    try:
        elements = [Element(value="First", x_mm=30, y_mm=70, width_mm=50, height_mm=20),
                    Element(value="Second", x_mm=100, y_mm=130, width_mm=60, height_mm=25),
                    Element(type="rectangle", x_mm=60, y_mm=210, width_mm=30, height_mm=20),
                    Element(value="Unselected", y_mm=260)]
        window._apply_template(Template(elements=elements).to_dict())
        window.undo.clear()
        before = [asdict(e) for e in window.template.elements]
        window.canvas.select_ids([e.id for e in elements[:3]])
        assert window.properties.geometry_apply.isEnabled()
        window.properties.numbers["width_mm"].setValue(55)
        window.properties.numbers["height_mm"].setValue(23)
        window.properties.geometry_apply.click()
        expected = copy.deepcopy(before)
        for element in expected[:3]:
            element.update(width_mm=55, height_mm=23)
        assert [asdict(e) for e in window.template.elements] == expected
        assert window.undo.count() == 1
        window.undo.undo()
        assert [asdict(e) for e in window.template.elements] == before
        window.undo.redo()
        window.properties.numbers["rotation_deg"].setValue(37)
        window.properties.geometry_apply.click()
        assert [e.rotation_deg for e in window.template.elements] == [37, 37, 37, 0]
        assert [e.value for e in window.template.elements] == [e["value"] for e in before]
        window.undo.undo()
        assert [asdict(e) for e in window.template.elements] == expected
    finally:
        close_window(window)


def test_batch_geometry_rejects_invalid_size_atomically_and_shape_only_selection(app):
    window = CompositionWindow()
    try:
        elements = [Element(type="rectangle", x_mm=20, y_mm=50, width_mm=20),
                    Element(type="line", x_mm=180, y_mm=100, width_mm=20)]
        window._apply_template(Template(elements=elements).to_dict())
        window.undo.clear()
        window.canvas.select_ids([e.id for e in elements])
        assert not window.properties.bulk_ids and len(window.properties.geometry_ids) == 2
        before = window.template.to_dict()
        window.properties.numbers["width_mm"].setValue(80)
        window.properties.geometry_apply.click()
        assert window.template.to_dict() == before and window.undo.count() == 0
        assert "page width" in window.message.text()
    finally:
        close_window(window)


def test_overlay_batch_size_and_rotation_undo(app, tmp_path):
    window = OverlayWindow()
    try:
        spec = sample_spec(tmp_path)
        window.apply_spec(spec.to_dict())
        window.canvas.select_ids([obj.element.id for obj in spec.objects])
        assert window.actions["rotate_cw"].isEnabled()
        window.canvas.select_ids([])
        assert not window.actions["rotate_cw"].isEnabled()
        window.canvas.select_ids([obj.element.id for obj in spec.objects])
        assert window.actions["rotate_cw"].isEnabled()
        window.properties.numbers["width_mm"].setValue(85)
        window.properties.geometry_apply.click()
        assert [obj.element.width_mm for obj in window.spec.objects] == [85, 85]
        assert window.undo.count() == 1
        window.actions["rotate_cw"].trigger()
        assert all(obj.element.rotation_deg == 90 for obj in window.spec.objects)
        assert all(element_bounds(obj.element)[1] >= -.01 for obj in window.spec.objects)
        window.undo.undo()
        assert all(obj.element.rotation_deg == 0 for obj in window.spec.objects)
    finally:
        finish(window)


def test_snap_guides_group_spacing_alt_bypass_and_page_edges(app):
    canvas = Canvas()
    elements = [Element(type="rectangle", x_mm=20, y_mm=30, width_mm=20, height_mm=10),
                Element(type="rectangle", x_mm=50, y_mm=60, width_mm=20, height_mm=10),
                Element(type="rectangle", x_mm=100, y_mm=130, width_mm=20, height_mm=10)]
    canvas.set_template(Template(elements=elements))
    canvas.set_zoom(1)
    canvas.select_ids([elements[0].id, elements[1].id])
    first, second, target = canvas.element_items
    first.moveBy(29, 0)
    second.moveBy(29, 0)
    canvas.snap_drag(first)
    assert first.pos().x() == pytest.approx(50)
    assert second.pos().x()-first.pos().x() == 30
    assert ("x", 100) in canvas.guides
    first.moveBy(-1, 0)
    second.moveBy(-1, 0)
    canvas.snap_drag(first, Qt.KeyboardModifier.AltModifier)
    assert first.pos().x() == 49 and not canvas.guides
    first.moveBy(-100, 0)
    second.moveBy(-100, 0)
    canvas.keep_group_on_page()
    assert first.pos().x() == 0 and second.pos().x() == 30
    canvas.close()


def test_rulers_measurement_zoom_pan_and_layout_menu(app):
    window = CompositionWindow()
    try:
        window.show()
        window.resize(960, 640)
        window.canvas.set_zoom(1.5)
        QApplication.processEvents()
        canvas = window.canvas
        assert canvas.horizontal_ruler.isVisible() and canvas.vertical_ruler.isVisible()
        assert window.layout_tools_button.menu()
        window._apply_template(Template(elements=[Element(value="First"), Element(value="Second", y_mm=50)]).to_dict())
        canvas.select_ids([e.id for e in window.page.elements])
        window.left_panel.setCurrentWidget(window.properties_scroll)
        QApplication.processEvents()
        assert window.properties_scroll.horizontalScrollBar().maximum() == 0
        assert window.properties.geometry_apply.isVisible()
        window.actions["measure"].setChecked(True)
        events = []
        canvas.measurementChanged.connect(lambda *values: events.append(values))
        canvas.measure_start, canvas.measure_end = QPointF(20, 20), QPointF(50, 60)
        canvas.report_measurement()
        assert events[-1] == (50, 30, 40)
        before = window.template.to_dict()
        start, end = canvas.mapFromScene(QPointF(20, 20)), canvas.mapFromScene(QPointF(50, 60))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert events[-1][0] == pytest.approx(50, abs=.5)
        assert window.template.to_dict() == before
        window.actions["rulers"].setChecked(False)
        assert canvas.horizontal_ruler.isHidden() and canvas.viewportMargins().top() == 0
        window.actions["snap_guides"].setChecked(False)
        assert not canvas.snap_guides_enabled
    finally:
        close_window(window)


def test_rotated_drag_resize_keyboard_geometry_matches_model(app):
    canvas = Canvas()
    canvas.resize(700, 700)
    canvas.show()
    element = Element(value="Move", x_mm=60, y_mm=80, width_mm=40, height_mm=20, rotation_deg=90)
    canvas.set_template(Template(elements=[element]), [element.id])
    canvas.set_zoom(1)
    QApplication.processEvents()
    item = canvas.element_items[0]
    bounds = item.mapRectToScene(item.rect())
    assert (bounds.left(), bounds.top(), bounds.right(), bounds.bottom()) == pytest.approx(element_bounds(element))
    canvas.set_snap_guides(False)
    original = canvas.snapshot()
    commits = []
    canvas.editCommitted.connect(lambda before, after: commits.append((before, after)))
    start = canvas.mapFromScene(item.mapToScene(QPointF(8, 8)))
    end = start + canvas.mapFromScene(QPointF(10, 0))-canvas.mapFromScene(QPointF(0, 0))
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), end, 20)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert commits and commits[-1][0] == original
    assert element.x_mm > 65 and element.rotation_deg == 90
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Down)
    assert element.rotation_deg == 90
    canvas.close()
