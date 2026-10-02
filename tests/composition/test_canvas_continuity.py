"""Canvas continuity, latest preview delivery and shared Designer surfaces."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.canvas import Canvas
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.template.model import Element, Template
from styles.components import global_style
from styles.theme import apply_theme, get_colors
from tests.composition.test_designer_controls import cleanup, wait
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def quiet_fonts(monkeypatch):
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)


def image(color="orange"):
    result = QPixmap(200, 280)
    result.fill(QColor(color))
    return result


def test_scene_edit_preserves_pixels_items_selection_and_view(app):
    canvas = Canvas()
    template = Template(elements=[Element(value="One"), Element(value="Two", y_mm=65)])
    first, second = [element.id for element in template.elements]
    canvas.set_template(template, [first, second])
    canvas.resize(500, 500)
    canvas.show()
    canvas.set_zoom(2)
    canvas.set_preview(image())
    scene, page, preview = canvas.scene(), canvas.page_item, canvas.preview_item
    objects = list(canvas.element_items)
    view = canvas.transform()
    scroll = (canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value())
    for offset in range(1, 30):
        raw = template.to_dict()
        raw["pages"][0]["elements"][0].update(x_mm=20+offset, width_mm=85, rotation_deg=20)
        raw["pages"][0]["elements"][1]["font"]["size_pt"] = 12
        canvas.set_template(Template.from_dict(raw), [first, second])
        assert canvas.scene() is scene and canvas.page_item is page
        assert canvas.preview_item is preview
        assert canvas.element_items == objects
        assert set(canvas.selected_ids()) == {first, second}
        assert canvas.transform() == view
        assert (canvas.horizontalScrollBar().value(), canvas.verticalScrollBar().value()) == scroll
    assert objects[0].rotation() == 20 and objects[0].pos().x() == 49
    assert preview.pixmap().toImage().pixelColor(20, 20) == QColor("orange")
    raw["pages"][0]["elements"].pop()
    canvas.set_template(Template.from_dict(raw), [first])
    assert canvas.element_items == [objects[0]] and objects[1].scene() is None
    assert canvas.preview_item is preview
    canvas.close()


def test_preview_replacement_is_atomic_and_context_change_clears(app):
    canvas = Canvas()
    template = Template(elements=[Element(value="Text")])
    canvas.set_template(template)
    canvas.set_preview(image())
    previous = canvas.preview_item
    canvas.set_preview(image("blue"))
    assert canvas.preview_item is previous
    assert previous.pixmap().toImage().pixelColor(10, 10) == QColor("blue")
    canvas.set_preview("missing-image.png")
    assert canvas.preview_item is previous
    canvas.set_template(Template(elements=[Element(value="Other page")]), context="other-document")
    assert canvas.preview_item is None
    assert canvas.page_item is not None
    canvas.close()


def test_template_moves_typography_and_undo_do_not_blank_canvas(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Client text")
        window.preview_timer.stop()
        window.canvas.set_preview(image())
        preview, item = window.canvas.preview_item, window.canvas.element_items[0]
        window.canvas.set_zoom(1.7)
        view = window.canvas.transform()
        QTest.keyClick(window.canvas, Qt.Key.Key_Right)
        window._property_edit({"font": {"size_pt": 15}})
        window.preview_timer.stop()
        assert window.canvas.preview_item is preview
        assert window.canvas.element_items[0] is item
        assert window.page.elements[0].font.size_pt == 15
        window.undo.undo()
        window.undo.undo()
        window.preview_timer.stop()
        assert window.canvas.preview_item is preview
        assert window.canvas.element_items[0] is item
        assert window.canvas.transform() == view
        assert window.page.elements[0].x_mm == 20
        assert window.page.elements[0].font.size_pt == 10
        window.properties.content.setPlainText("{{unfinished")
        assert window.content_invalid and window.canvas.preview_item is None
        window.revert_content_draft()
        window.preview_timer.stop()
    finally:
        cleanup(window)


def test_overlay_edits_keep_source_preview_but_page_change_clears(app, tmp_path):
    window = OverlayWindow()
    try:
        spec = sample_spec(tmp_path)
        window.apply_spec(spec.to_dict())
        window.timer.stop()
        window.canvas.select_ids([spec.objects[0].element.id])
        window.canvas.set_preview(image())
        preview, item = window.canvas.preview_item, window.canvas.element_items[0]
        window.property_edit({"x_mm": 25, "width_mm": 85})
        window.timer.stop()
        assert window.canvas.preview_item is preview and window.canvas.element_items[0] is item
        window.undo.undo()
        window.timer.stop()
        assert window.canvas.preview_item is preview
        assert item.pos().x() == 20
        window.print_page.setValue(2)
        window.timer.stop()
        assert window.canvas.preview_item is None
    finally:
        finish(window)


@pytest.mark.parametrize("overlay", [False, True])
def test_superseded_previews_wait_for_worker_exit_and_render_latest(app, tmp_path, monkeypatch, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    timer = window.timer if overlay else window.preview_timer
    ended = window.worker_ended if overlay else window._worker_ended
    render = window.render_preview if overlay else window._render_preview
    calls, stopped = [], []
    if overlay:
        window.apply_spec(sample_spec(tmp_path).to_dict())
    else:
        window.add_element("text", "Initial")
    timer.stop()

    def launch(request, *args, **kwargs):
        worker = SimpleNamespace(stop_preview=lambda: stopped.append(True))
        window.workers.append(worker)
        calls.append(request)
        return worker

    monkeypatch.setattr(window, "worker" if overlay else "_worker", launch)
    try:
        render()
        first = window.preview_worker
        for size in (11, 12, 13):
            if overlay:
                window.canvas.select_ids([window.spec.objects[0].element.id])
                window.property_edit({"font": {"size_pt": size}})
            else:
                window._property_edit({"font": {"size_pt": size}})
            timer.stop()
            render()
        assert len(calls) == 1 and window.preview_worker is first
        assert window.preview_pending and stopped
        ended(first)
        timer.stop()
        render()
        assert len(calls) == 2 and len(window.workers) == 1
        request = calls[-1]
        element = (request["project"]["objects"][0]["element"] if overlay else
                   request["template"]["pages"][0]["elements"][0])
        assert element["font"]["size_pt"] == 13
        assert not window.preview_pending
    finally:
        window.workers.clear()
        window.preview_worker = None
        window.preview_pending = False
        timer.stop()
        finish(window) if overlay else cleanup(window)


def test_real_preview_swaps_image_in_place_after_edit(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original text")
        wait(lambda: window.canvas.preview_item is not None and window.preview_worker is None)
        preview, item = window.canvas.preview_item, window.canvas.element_items[0]
        pixels = preview.pixmap().cacheKey()
        window._property_edit({"x_mm": 45})
        assert window.canvas.preview_item is preview
        wait(lambda: window.preview_worker is None and not window.preview_timer.isActive()
             and preview.pixmap().cacheKey() != pixels)
        assert window.canvas.preview_item is preview and window.canvas.element_items[0] is item
        assert window.preview_state.text().startswith("Design layout")
        assert not list(window.directory.glob("preview-*"))
    finally:
        cleanup(window)


def test_new_project_does_not_reuse_previous_preview(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Old project")
        window.preview_timer.stop()
        window.canvas.set_preview(image())
        old_page = window.page.id
        window.undo.setClean()
        window.new_project()
        window.preview_timer.stop()
        assert window.page.id == old_page
        assert window.canvas.preview_item is None
    finally:
        cleanup(window)


@pytest.mark.parametrize("overlay", [False, True])
def test_real_rapid_edits_keep_canvas_and_deliver_latest_preview(app, tmp_path, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        if overlay:
            window.apply_spec(sample_spec(tmp_path).to_dict())
        else:
            window.add_element("text", "Continuous preview")
        timer = window.timer if overlay else window.preview_timer
        render = window.render_preview if overlay else window._render_preview
        wait(lambda: window.canvas.preview_item is not None and window.preview_worker is None)
        preview = window.canvas.preview_item
        item = window.canvas.element_items[0]
        window.canvas.select_ids([item.element.id])
        pixels = preview.pixmap().cacheKey()
        for x in (30, 35, 40, 45):
            (window.property_edit if overlay else window._property_edit)({"x_mm": x})
            timer.stop()
            render()
            assert window.canvas.preview_item is preview
            assert window.canvas.element_items[0] is item
        wait(lambda: window.preview_worker is None and not timer.isActive()
             and preview.pixmap().cacheKey() != pixels)
        assert not window.preview_pending
        assert item.pos().x() == 45
        assert not list(window.directory.glob("preview-*"))
        assert not window.workers
    finally:
        finish(window) if overlay else cleanup(window)


def test_narrow_overlay_properties_remain_accessible(app):
    window = OverlayWindow()
    try:
        window.resize(960, 640)
        window.show()
        app.processEvents()
        assert not window.inspector.isVisible()
        action = window.actions["properties"]
        assert window.layout_toolbar.widgetForAction(action) is not None
        action.trigger()
        app.processEvents()
        assert window.inspector.isVisible()
        window.resize(980, 650)
        app.processEvents()
        assert window.inspector.isVisible()
        assert action.isChecked()
        action.trigger()
        assert not window.inspector.isVisible()
    finally:
        finish(window)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_shared_palette_updates_canvas_and_chrome_without_reset(app, theme):
    previous = app.styleSheet()
    apply_theme(app, "light")
    app.setStyleSheet(global_style())
    window = CompositionWindow()
    try:
        window.add_element("text", "Stable")
        window.preview_timer.stop()
        window.canvas.set_preview(image())
        scene, preview = window.canvas.scene(), window.canvas.preview_item
        apply_theme(app, theme)
        app.setStyleSheet(global_style())
        window.resize(960, 640)
        window.show()
        app.processEvents()
        assert window.canvas.backgroundBrush().color() == QColor(get_colors()["canvas"])
        assert window.canvas.scene() is scene and window.canvas.preview_item is preview
        assert not window.project_toolbar.styleSheet()
        assert window.left_panel.objectName() == "designerPanelTabs"
        assert window.project_toolbar.height() <= 42
        assert window.canvas.viewport().height() >= 450
    finally:
        cleanup(window)
        apply_theme(app, "light")
        app.setStyleSheet(previous)
