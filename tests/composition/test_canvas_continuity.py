"""Canvas continuity, latest preview delivery and shared Designer surfaces."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
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


def test_preview_quality_tracks_zoom_dpi_and_avoids_duplicate_requests(app, monkeypatch):
    canvas = Canvas()
    canvas.set_template(Template())
    requested = []
    canvas.previewScaleChanged.connect(lambda: requested.append(canvas.preview_scale()))
    canvas.set_zoom(.5)
    requested.clear()
    canvas.set_zoom(2)
    assert len(requested) == 1
    scale = requested[0]
    for _ in range(10):
        canvas.set_zoom(2)
        canvas.set_template(Template(), context="same-document")
    assert requested == [scale]
    canvas.set_zoom(.5)
    requested.clear()
    monkeypatch.setattr(canvas.viewport(), "devicePixelRatioF", lambda: 4.0)
    app.sendEvent(canvas, QEvent(QEvent.Type.DevicePixelRatioChange))
    assert len(requested) == 1 and requested[0] >= 4
    assert canvas.renderHints() & QPainter.RenderHint.SmoothPixmapTransform
    canvas.set_preview(image())
    assert canvas.preview_item.transformationMode() == Qt.TransformationMode.SmoothTransformation
    canvas.close()


@pytest.mark.parametrize("overlay", [False, True])
def test_zoom_background_refreshes_sharp_pixels_without_resetting_edit_state(app, tmp_path, overlay):
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        if overlay:
            window.apply_spec(sample_spec(tmp_path).to_dict())
        else:
            window.add_element("text", "Small, sharp production text")
        timer = window.timer if overlay else window.preview_timer
        window.canvas.set_zoom(.5)
        wait(lambda: window.canvas.preview_item is not None and window.preview_worker is None and not timer.isActive())
        preview = window.canvas.preview_item
        item = window.canvas.element_items[0]
        window.canvas.select_ids([item.element.id])
        old_width, undo_index = preview.pixmap().width(), window.undo.index()
        for zoom in (1, 2, 3, 2):
            window.canvas.set_zoom(zoom)
            assert window.canvas.preview_item is preview
        view = window.canvas.transform()
        wait(lambda: window.preview_worker is None and not timer.isActive() and preview.pixmap().width() > old_width)
        assert preview.pixmap().width() > old_width * 1.5
        assert window.canvas.preview_item is preview and window.canvas.element_items[0] is item
        assert window.canvas.selected_ids() == [item.element.id]
        assert window.canvas.transform() == view and window.undo.index() == undo_index
        assert not list(window.directory.glob("preview-*"))
        window.canvas.set_zoom(2)
        assert not timer.isActive() and window.preview_worker is None
    finally:
        finish(window) if overlay else cleanup(window)


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


@pytest.mark.parametrize("size", [(960, 640), (1240, 820)])
def test_clicking_textbox_reveals_properties_without_stealing_canvas_focus(app, size):
    window = CompositionWindow()
    try:
        window.resize(*size)
        window.show()
        window.add_element("text", "First textbox")
        first = window.page.elements[0].id
        window.add_element("text", "Second textbox", x=100, y=70)
        second = window.page.elements[1].id
        window.preview_timer.stop()
        window._adjust_inspector()
        window.canvas.select_ids([])
        window.actions["properties"].setChecked(False)
        window._show_properties(False)
        window.left_panel.setCurrentWidget(window.data_panel)
        window.canvas.fit_page()
        app.processEvents()
        item = next(item for item in window.canvas.element_items if item.element.id == first)
        point = window.canvas.mapFromScene(item.mapToScene(QPointF(10, 4)))
        QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert window.canvas.selected_ids() == [first]
        assert window.properties.content.toPlainText() == "First textbox"
        assert window.properties.isVisible()
        assert window.actions["properties"].isChecked()
        assert window.canvas.hasFocus()
        assert window.splitter.indexOf(window.properties_scroll) == 2
        assert window.left_panel.currentWidget() is window.data_panel
        window.canvas.select_ids([first, second])
        assert window.properties.isVisible()
        assert set(window.properties.bulk_ids) == {first, second}
        window.properties.numbers["width_mm"].setValue(85)
        window.properties.apply_geometry()
        window.preview_timer.stop()
        assert all(element.width_mm == 85 for element in window.page.elements)
        window.undo.undo()
        window.preview_timer.stop()
        assert window.properties.isVisible()
    finally:
        cleanup(window)


def test_properties_toolbar_reopens_right_panel_and_returns_to_design(app):
    window = CompositionWindow()
    try:
        window.resize(960, 640)
        window.show()
        window.add_element("text", "Textbox")
        window.preview_timer.stop()
        window._adjust_inspector()
        window.left_panel.setCurrentWidget(window.data_panel)
        window._adjust_inspector()
        assert window.data_panel.isVisible()
        button = window.project_toolbar.widgetForAction(window.actions["properties"])
        button.click()
        assert not window.properties_scroll.isVisible()
        assert button.isVisible()
        button.click()
        assert window.properties.isVisible()
        assert window.splitter.indexOf(window.properties_scroll) == 2
        assert window.left_panel.currentWidget() is window.data_panel
        button.click()
        assert not window.properties.isVisible()
        button.click()
        assert window.properties.isVisible()
        window.tabs.setCurrentIndex(2)
        window.preview_timer.stop()
        assert not window.properties.isVisible()
        button.click()
        window.preview_timer.stop()
        assert window.tabs.currentIndex() == 1 and window.properties.isVisible()
    finally:
        cleanup(window)


def test_selecting_overlay_text_reopens_hidden_inspector_without_focus_change(app, tmp_path):
    window = OverlayWindow()
    try:
        window.resize(960, 640)
        window.show()
        window.apply_spec(sample_spec(tmp_path).to_dict())
        window.timer.stop()
        app.processEvents()
        window.inspector.hide()
        window.canvas.select_ids([])
        window.canvas.setFocus()
        window.canvas.select_ids([window.spec.objects[0].element.id])
        assert window.inspector.isVisible()
        assert window.properties.element.id == window.spec.objects[0].element.id
        assert window.canvas.hasFocus()
    finally:
        finish(window)


@pytest.mark.parametrize("overlay", [False, True])
@pytest.mark.parametrize("font_size", [9, 14])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_field_sidebar_footer_and_controls_are_reachable(app, overlay, font_size, theme):
    previous_style, previous_font = app.styleSheet(), app.font()
    apply_theme(app, theme)
    app.setStyleSheet(global_style())
    app.setFont(QFont("Segoe UI", font_size))
    window = OverlayWindow() if overlay else CompositionWindow()
    try:
        window.resize(960 if overlay else 760, 640 if overlay else 580)
        window.show()
        if not overlay:
            window._adjust_inspector()
            window.left_panel.setCurrentWidget(window.data_panel)
        app.processEvents()
        requested_height = window.height()
        scroll = window.source_scroll if overlay else window.data_panel
        source = window.source_summary if overlay else window.source_label
        source.setText("Customer source data with extra file details\n" * 12)
        window.fields.addItems([f"Customer_Field_{index:03d}" for index in range(200)])
        app.processEvents()
        assert window.height() == requested_height
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.ensureWidgetVisible(window.fields_help, 0, 0)
        app.processEvents()
        footer = window.fields_help
        assert footer.height() >= footer.heightForWidth(footer.width())
        top = footer.mapTo(scroll.viewport(), footer.rect().topLeft()).y()
        bottom = footer.mapTo(scroll.viewport(), footer.rect().bottomLeft()).y()
        assert 0 <= top <= bottom < scroll.viewport().height()
        assert window.fields.height() >= (1 if overlay else 84)
        scroll.ensureWidgetVisible(window.fields, 0, 0)
        window.fields.scrollToItem(window.fields.item(window.fields.count()-1))
        assert window.fields.visualItemRect(window.fields.item(window.fields.count()-1)).intersects(window.fields.viewport().rect())
        assert window.fields.dragEnabled()
        if not overlay:
            scroll.verticalScrollBar().setValue(0)
            app.processEvents()
            for button in (window.import_button, window.sequence_button):
                assert button.mapTo(scroll.viewport(), button.rect().bottomRight()).x() < scroll.viewport().width()
                assert button.mapTo(scroll.viewport(), button.rect().topLeft()).y() >= 0
    finally:
        finish(window) if overlay else cleanup(window)
        app.setFont(previous_font)
        apply_theme(app, "light")
        app.setStyleSheet(previous_style)


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
