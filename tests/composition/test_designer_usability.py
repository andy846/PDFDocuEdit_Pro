from __future__ import annotations

from dataclasses import asdict

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog

from composition.designer.workspace import CompositionWindow
from composition.template.model import DataConfig
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="module")
def app(qt_application):
    return qt_application


def close(window):
    if window.content_invalid:
        window.revert_content_draft()
    window.production_worker = None
    cleanup(window)


def test_incomplete_variable_survives_typing_and_blocks_stale_output(app, tmp_path, monkeypatch):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "Original")
        original_font = asdict(window.page.elements[0].font)
        window.properties.content.setFocus()
        window.properties.content.selectAll()
        QTest.keyClicks(window.properties.content, "Hello {{Name")
        assert window.properties.content.toPlainText() == "Hello {{Name"
        assert window.content_invalid
        assert not window.actions["save"].isEnabled() and not window.actions["generate"].isEnabled()
        assert not window.canvas.editable and window.canvas.preview_item is None
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: pytest.fail("Invalid draft opened Save"))
        assert window.save_project() is False
        window.start_production(str(tmp_path/"output"))
        assert not (tmp_path/"output").exists()
        QTest.keyClicks(window.properties.content, "}}")
        assert not window.content_invalid
        assert window.page.elements[0].value == "Hello {{Name}}"
        assert asdict(window.page.elements[0].font) == original_font
        assert window.actions["save"].isEnabled() and window.canvas.editable
    finally:
        close(window)


def test_draft_selection_and_page_guard_then_revert(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "First")
        first = window.page.elements[0].id
        window.add_element("text", "Second")
        second = window.page.elements[1].id
        window.add_template_page()
        window.select_template_page(0)
        window.canvas.select_ids([first])
        window.properties.content.setPlainText("{{unfinished")
        window.canvas.select_ids([second])
        assert window.canvas.selected_ids() == [first]
        assert window.properties.content.toPlainText() == "{{unfinished"
        window.select_template_page(1)
        assert window.page_index == 0
        window.properties.revert_content.click()
        assert window.properties.content.toPlainText() == "First" and not window.content_invalid
        window.select_template_page(1)
        assert window.page_index == 1
    finally:
        close(window)


def test_text_undo_groups_and_save_boundary_without_scene_rebuild(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original")
        item = window.canvas.element_items[0]
        window.canvas.set_zoom(1.5)
        window.properties.content.selectAll()
        count = window.undo.count()
        QTest.keyClicks(window.properties.content, "Replacement")
        assert window.undo.count() == count+1
        assert window.canvas.element_items[0] is item
        assert window.canvas.transform().m11() == pytest.approx(1.5*96/25.4)
        window.undo.undo()
        assert window.page.elements[0].value == "Original"
        window.undo.redo()
        assert window.page.elements[0].value == "Replacement"
        window.undo.setClean()
        QTest.keyClicks(window.properties.content, " next")
        window.undo.undo()
        assert window.page.elements[0].value == "Replacement" and window.undo.isClean()
    finally:
        close(window)


def test_each_page_remembers_zoom_and_selection(app):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "First")
        first = window.page.elements[0].id
        window.canvas.set_zoom(1.5)
        first_zoom = window.canvas.transform().m11()
        window.add_template_page()
        window.add_element("text", "Second")
        second = window.page.elements[0].id
        window.canvas.set_zoom(2)
        second_zoom = window.canvas.transform().m11()
        window.page_buttons["page_previous"].click()
        assert window.page_index == 0 and window.canvas.selected_ids() == [first]
        assert window.canvas.transform().m11() == pytest.approx(first_zoom)
        window.page_buttons["page_next"].click()
        assert window.page_index == 1 and window.canvas.selected_ids() == [second]
        assert window.canvas.transform().m11() == pytest.approx(second_zoom)
        assert "page_up" not in window.page_buttons, "Flip arrows must never reorder pages"
        assert [page.elements[0].value for page in window.template.pages] == ["First", "Second"]
    finally:
        close(window)


def test_right_inspector_survives_resize_preview_and_view_toggle(app):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "Font standard")
        saved = window.template.to_dict()
        window.resize(960, 640)
        window._adjust_inspector()
        assert window.splitter.indexOf(window.properties_scroll) == 2
        assert window.left_panel.indexOf(window.properties_scroll) == -1
        window.focus_properties()
        app.processEvents()
        assert window.properties_scroll.parentWidget() is window.splitter
        assert window.properties.isVisible() and window.properties.content.width() > 30
        window.tabs.setCurrentIndex(2)
        assert not window.properties_scroll.isVisible()
        window.tabs.setCurrentIndex(1)
        assert window.properties_scroll.isVisible()
        window.actions["properties"].setChecked(False)
        window._show_properties(False)
        assert not window.properties_scroll.isVisible()
        window.focus_properties()
        assert window.properties_scroll.isVisible()
        window.resize(1240, 820)
        window._adjust_inspector()
        app.processEvents()
        assert window.splitter.indexOf(window.properties_scroll) == 2
        assert window.properties.isVisible() and window.properties_scroll.width() >= 260
        assert window.template.to_dict() == saved
    finally:
        close(window)


def test_text_shortcuts_do_not_delete_or_duplicate_objects(app):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "Client text")
        object_id = window.page.elements[0].id
        window.properties.content.setFocus()
        QTest.keyClick(window.properties.content, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        assert len(window.page.elements) == 1
        window.properties.content.selectAll()
        QTest.keyClick(window.properties.content, Qt.Key.Key_Delete)
        assert len(window.page.elements) == 1 and window.page.elements[0].id == object_id
        assert window.page.elements[0].value == ""
        window.canvas.setFocus()
        QTest.keyClick(window.canvas, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        assert len(window.page.elements) == 2
    finally:
        close(window)


def test_busy_canvas_keyboard_is_read_only(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Production snapshot")
        saved = window.template.to_dict()
        window.production_worker = object()
        window._busy()
        QTest.keyClick(window.canvas, Qt.Key.Key_Right)
        QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
        window.object_command("duplicate")
        assert window.template.to_dict() == saved
        assert not window.properties.isEnabled() and not window.actions["undo"].isEnabled()
        window.production_worker = None
        window._busy()
        assert window.canvas.editable and window.properties.isEnabled()
    finally:
        close(window)


def test_field_filter_and_data_list_survive_editing(app, tmp_path):
    window = CompositionWindow()
    try:
        window.add_field("Name", 20, 20)
        source = tmp_path/"data.csv"
        source.write_text("Name,Account\nAlice,001\nBob,002\n", encoding="utf-8")
        window._start_import(DataConfig(path=str(source)))
        wait(lambda: window.import_worker is None)
        original = window.fields.item(0)
        window.field_filter.setText("aCcOuNt")
        assert original.isHidden() and not window.fields.item(1).isHidden()
        window.properties.content.setPlainText("Dear {{Name}}")
        assert window.fields.item(0) is original and window.field_filter.text() == "aCcOuNt"
        window.properties.numbers["x_mm"].setValue(30)
        window.properties.apply()
        assert window.fields.item(0) is original
        window.properties.content.setPlainText("{{unfinished")
        assert not window.next.isEnabled()
        window.properties.content.setPlainText("{{Name}}")
        assert window.next.isEnabled() and window.record.isEnabled()
    finally:
        close(window)


def test_geometry_validation_can_be_corrected_without_losing_draft(app):
    window = CompositionWindow()
    try:
        window.add_element("rectangle")
        window.properties.numbers["x_mm"].setValue(205)
        window.properties.apply()
        assert window.content_invalid
        assert window.properties.geometry.isEnabled()
        assert not window.properties.draft_status.isHidden()
        window.properties.numbers["x_mm"].setValue(20)
        window.properties.apply()
        assert not window.content_invalid
    finally:
        close(window)


def test_unfinished_draft_guards_insert_arrange_and_font_changes(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Customer standard")
        saved = window.template.to_dict()
        window.properties.content.setPlainText("{{unfinished")
        window.object_command("copy")  # An action-state refresh must retain the draft lock.
        for key in ("insert_text", "variable", "arrange_front", "cjk", "repair_glyph", "paste", "delete"):
            assert not window.actions[key].isEnabled(), key
        window.add_element("rectangle")
        window.arrange_objects("front")
        window.use_cjk_font()
        window._request_font({"element_id": window.page.elements[0].id, "file": "unused.ttf"})
        assert not window.font_requests
        assert window.template.to_dict() == saved
        assert window.properties.content.toPlainText() == "{{unfinished"
        window.revert_content_draft()
        assert window.actions["insert_text"].isEnabled()
    finally:
        close(window)


def test_pending_geometry_is_validated_before_page_actions_or_generation(app, monkeypatch):
    window = CompositionWindow()
    try:
        window.add_element("rectangle")
        window.add_template_page()
        window.select_template_page(0)
        window.canvas.select_ids([window.page.elements[0].id])
        window.properties.numbers["x_mm"].setValue(205)
        assert not window.content_invalid  # editingFinished has not yet fired.
        window.select_template_page(1)
        assert window.content_invalid and window.page_index == 0
        assert window.properties.numbers["x_mm"].value() == 205
        window.revert_content_draft()
        window.properties.numbers["x_mm"].setValue(205)
        window.add_template_page()
        assert window.content_invalid and len(window.template.pages) == 2
        window.revert_content_draft()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: pytest.fail("Invalid edit opened production dialog"))
        window.properties.numbers["x_mm"].setValue(205)
        window.generate_pdf()
        assert window.content_invalid and window.production_worker is None
    finally:
        close(window)


def test_invalid_draft_rejects_late_preview_and_manual_correction_refreshes(app, tmp_path):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original")
        generation = window.preview_generation
        window.properties.content.setPlainText("{{unfinished")
        window._preview_ready({"image": str(tmp_path/"unused.png"), "pdf": str(tmp_path/"unused.pdf")}, generation)
        assert window.canvas.preview_item is None
        assert "Edit needs attention" in window.preview_state.text()
        window.properties.content.setPlainText("Original")
        assert not window.content_invalid and window.preview_timer.isActive()
        assert window.preview_state.text().startswith("Updating")
    finally:
        close(window)


def test_text_undo_from_another_object_restores_selection_and_font_controls(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "First")
        first = window.page.elements[0].id
        window.add_field("Name", 20, 40)
        second = window.page.elements[1].id
        window.canvas.select_ids([first])
        first_font = asdict(window.page.elements[0].font)
        window.properties.content.setPlainText("Changed first")
        window.canvas.select_ids([second])
        assert window.properties.element.font.family == "Noto Sans CJK HK"
        window.undo.undo()
        assert window.canvas.selected_ids() == [first]
        assert window.properties.element.id == first
        assert window.properties.font_choice == first_font
        assert window.properties.font_family.currentText() == first_font["family"]
        window.properties.apply()
        assert asdict(window.page.elements[0].font) == first_font
        assert window.page.elements[0].value == "First"
    finally:
        close(window)
