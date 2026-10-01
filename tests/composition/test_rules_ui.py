from __future__ import annotations

from dataclasses import asdict

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog

from composition.designer.rules_dialog import ConditionEditor, RulesDialog
from composition.designer.workspace import CompositionWindow
from composition.template.model import (
    ConditionGroup,
    DataConfig,
    Element,
    ElementRules,
    RuleCondition,
)
from tests.composition.test_designer_controls import cleanup, wait


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def close(window):
    window.production_worker = None
    if window.content_invalid:
        window.revert_content_draft()
    cleanup(window)


def condition_controls(editor, field, operator="eq", data_type="text", value="", row=0):
    editor.setChecked(True)
    field_widget, operator_widget, type_widget, value_widget = (
        editor.table.cellWidget(row, col) for col in range(4)
    )
    field_widget.setCurrentText(field)
    type_widget.setCurrentIndex(type_widget.findData(data_type))
    operator_widget.setCurrentIndex(operator_widget.findData(operator))
    value_widget.setText(value)


def test_real_rules_menu_dialog_apply_clear_undo_preserves_font(app):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "Client standard")
        original = asdict(window.page.elements[0].font)

        def choose():
            dialog = QApplication.activeModalWidget()
            condition_controls(dialog.visibility, "Scheme_Code", value="GS")
            dialog.apply_rules()

        QTimer.singleShot(0, choose)
        window.actions["edit_rules"].trigger()
        assert window.page.elements[0].rules.visible_when.conditions[0].value == "GS"
        assert "[Rule]" in window.layers.item(0).text()
        assert "Scheme_Code" in window.properties.rules_summary.text()
        window.undo.undo()
        assert window.page.elements[0].rules == ElementRules()
        window.undo.redo()
        window.actions["clear_rules"].trigger()
        assert window.page.elements[0].rules == ElementRules()
        window.undo.undo()
        assert window.page.elements[0].rules.visible_when is not None
        assert asdict(window.page.elements[0].font) == original
    finally:
        close(window)


def test_dialog_numeric_validation_and_sample_results(app):
    element = Element(value="Normal")
    sample = [{"Scheme_Code": "GS", "Balance": "200"}, {"Scheme_Code": "IS", "Balance": "0"}]
    dialog = RulesDialog(element, ["Scheme_Code", "Balance"], sample)
    dialog.show()
    condition_controls(dialog.visibility, "Balance", "gt", "number", "1,000")
    dialog.apply_rules()
    assert dialog.choice is None and dialog.isVisible() and "decimal" in dialog.error.text()
    condition_controls(dialog.visibility, "Balance", "gt", "number", "100")
    condition_controls(dialog.variant, "Scheme_Code", value="GS")
    dialog.alt_text.setPlainText("GS message")
    dialog.check_sample()
    assert "Sample 1: visible / alternative content" in dialog.sample_status.toPlainText()
    assert "Sample 2: hidden" in dialog.sample_status.toPlainText()
    dialog.apply_rules()
    assert dialog.choice.alternative.value == "GS message"
    assert dialog.result() == RulesDialog.DialogCode.Accepted
    dialog.deleteLater()


def test_condition_row_limit_and_empty_checks(app):
    editor = ConditionEditor("Visible", ["Name"])
    editor.setChecked(True)
    assert editor.table.height() < 100
    for _ in range(25):
        editor.add_condition()
    assert editor.table.rowCount() == 20 and not editor.add_button.isEnabled()
    assert editor.table.height() == 220
    editor.remove_condition()
    assert editor.table.rowCount() == 19 and editor.add_button.isEnabled()
    condition_controls(editor, "Name", "is_empty", value="ignored")
    assert not editor.table.cellWidget(0, 3).isEnabled()
    assert editor.read_group().conditions[0].value == ""
    editor.close()


def test_cancelled_rule_dialog_leaves_model_unchanged(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original")
        original = window.template.to_dict()
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        window.actions["edit_rules"].trigger()
        assert window.template.to_dict() == original
    finally:
        close(window)


def test_record_preview_and_design_modes_apply_rules_consistently(app, tmp_path):
    window = CompositionWindow()
    try:
        window.show()
        window.add_element("text", "Normal")
        source = tmp_path / "data.csv"
        source.write_text("Scheme_Code,Balance\nGS,200\nIS,0\n", encoding="utf-8")
        window._start_import(DataConfig(path=str(source)))
        wait(lambda: window.import_worker is None)
        dialog = RulesDialog(window.properties.element, ["Scheme_Code", "Balance"], parent=window)
        condition_controls(dialog.visibility, "Balance", "gt", "number", "100")
        condition_controls(dialog.variant, "Scheme_Code", value="GS")
        dialog.alt_text.setPlainText("GS content")
        window.apply_object_rules(dialog.build_rules())
        window.tabs.setCurrentIndex(2)
        wait(lambda: window.canvas.preview_item is not None)
        assert not window.actions["edit_rules"].isEnabled() and not window.properties.rules_button.isEnabled()
        assert "0 hidden / 1 alternative" in window.preview_state.text()
        window.record.setValue(2)
        wait(lambda: window.canvas.preview_item is not None)
        assert "1 hidden / 0 alternative" in window.preview_state.text()
        window.tabs.setCurrentIndex(1)
        wait(lambda: window.canvas.preview_item is not None)
        assert window.actions["edit_rules"].isEnabled() and window.properties.rules_button.isEnabled()
        assert "Design layout" in window.preview_state.text()
        assert len(window.canvas.element_items) == 1
        dialog.deleteLater()
    finally:
        close(window)


def test_rules_survive_duplicate_page_and_cross_page_copy(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original")
        rules = ElementRules(ConditionGroup("all", [RuleCondition("Scheme_Code", value="GS")]))
        window.apply_object_rules(rules)
        first = window.page.elements[0].id
        window.add_template_page(duplicate=True)
        assert window.page.elements[0].rules == rules and window.page.elements[0].id != first
        window.canvas.select_ids([window.page.elements[0].id])
        window.object_command("copy")
        window.select_template_page(0)
        window.object_command("paste")
        assert len(window.page.elements) == 2 and all(e.rules == rules for e in window.page.elements)
    finally:
        close(window)


def test_busy_or_invalid_draft_disables_rules_without_mutation(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Original")
        rules = ElementRules(ConditionGroup("all", [RuleCondition("Scheme_Code", value="GS")]))
        before = window.template.to_dict()
        window.properties.content.setPlainText("{{unfinished")
        assert not window.actions["edit_rules"].isEnabled()
        assert not window.properties.rules_button.isEnabled()
        window.apply_object_rules(rules)
        assert window.template.to_dict() == before
        window.revert_content_draft()
        window.production_worker = object()
        window._busy()
        assert not window.actions["edit_rules"].isEnabled()
        window.apply_object_rules(rules)
        assert window.template.to_dict() == before
    finally:
        close(window)


def test_alternative_image_control_keeps_primary_asset(app, tmp_path, monkeypatch):
    from PIL import Image

    normal = tmp_path / "normal.png"
    alternate = tmp_path / "alternate.png"
    Image.new("RGB", (10, 10), "red").save(normal)
    Image.new("RGB", (10, 10), "blue").save(alternate)
    element = Element(type="image", image=str(normal))
    dialog = RulesDialog(element, ["Scheme_Code"])
    assert dialog.alt_text.isHidden() and not dialog.image_row.isHidden()
    condition_controls(dialog.variant, "Scheme_Code", value="GS")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(alternate), ""))
    dialog.choose_image()
    rule = dialog.build_rules()
    assert rule.alternative.image == str(alternate) and element.image == str(normal)
    dialog.reject()
    dialog.deleteLater()
