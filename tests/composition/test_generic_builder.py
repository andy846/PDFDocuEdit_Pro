import copy
import sys
import traceback
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialogButtonBox, QLineEdit

from composition.designer.barcode_setup import BarcodeSetupDialog
from composition.engine.barcode_profiles import BarcodeProfile, BarcodeToken
from composition.engine.generic_layout import CONTEXT_KEY, BarcodeContext, BarcodeSegment


@pytest.fixture(autouse=True)
def readable_offscreen_fonts(qt_application):
    # Windows offscreen Qt does not enumerate native fonts. This matches the
    # existing Inserter UI checks without changing production font preferences.
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    old = qt_application.font()
    if path.exists():
        from PyQt6.QtGui import QFont, QFontDatabase
        QFontDatabase.addApplicationFont(str(path))
        qt_application.setFont(QFont("Segoe UI", 9))
    yield
    qt_application.setFont(old)


@pytest.fixture(autouse=True)
def native_callbacks(monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append("".join(traceback.format_exception(*args))))
    yield
    assert not errors, errors


def valid_profile():
    return BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Envelope", length=2, source="system", value="EnvelopeSeq", format="numeric"),
        BarcodeSegment(name="Fixed", length=2, value="00")])


def fields():
    return {"EnvelopeSeq": "000000000000000001", "EnvelopeIndex": "1", "SheetNo": "1", "OutputPage": "1"}


def test_numeric_error_fixed_and_positions_order_drafts(qt_application):
    original = valid_profile()
    before = copy.deepcopy(original.to_dict())
    dialog = BarcodeSetupDialog(original, fields(), symbology="i25")
    try:
        b = dialog.generic.builder
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert ok.isEnabled(), dialog.status.text()
        assert "0100" in b.preview.text()
        assert b.table.item(0, 1).text() == "1–2" and b.table.item(1, 1).text() == "3–4"
        b.total.setValue(6)
        assert not ok.isEnabled() and "Configured length 4" in dialog.status.text()
        b.table.setCurrentCell(1, 0)
        b.length.setValue(4)
        b.value.setCurrentText("0000")
        assert ok.isEnabled(), dialog.status.text()
        b.up.click()
        assert dialog.candidate().payload(fields()) == "000001"
        assert b.table.item(1, 1).text() == "5–6"
        b.length.setValue(3)
        b.table.setCurrentCell(1, 0)
        b.table.setCurrentCell(0, 0)
        assert b.length.value() == 3 and not ok.isEnabled()
        assert original.to_dict() == before
    finally:
        dialog.close()
        dialog.deleteLater()


def test_table_length_edit_repairs_zero_draft_and_updates_preview(qt_application):
    original = valid_profile()
    original.segments[0].length = 0
    dialog = BarcodeSetupDialog(original, fields(), symbology="i25")
    try:
        dialog.resize(960, 640)
        dialog.show()
        b = dialog.generic.builder
        dialog.scroll.ensureWidgetVisible(b.table)
        qt_application.processEvents()
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert not ok.isEnabled()
        cell = b.table.item(0, 2)
        b.table.setCurrentItem(cell)
        b.table.editItem(cell)
        qt_application.processEvents()
        editor = b.table.findChild(QLineEdit)
        assert editor is not None and editor.isVisible()
        editor.selectAll()
        QTest.keyClicks(editor, "2")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        qt_application.processEvents()
        assert b.draft.segments[0].length == b.length.value() == 2
        assert b.table.item(0, 1).text() == "1–2"
        assert b.table.item(1, 1).text() == "3–4"
        assert ok.isEnabled(), dialog.status.text()
        assert "0100" in b.preview.text()
        assert dialog.candidate().payload(fields()) == "0100"
        assert original.segments[0].length == 0
        assert editor.width() <= b.table.columnWidth(2)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_table_name_source_and_readonly_computed_columns(qt_application):
    dialog = BarcodeSetupDialog(valid_profile(), fields(), symbology="i25")
    try:
        b = dialog.generic.builder
        for col in (1, 4):
            assert not b.table.item(0, col).flags() & Qt.ItemFlag.ItemIsEditable
        for col in (0, 2, 3):
            assert b.table.item(0, col).flags() & Qt.ItemFlag.ItemIsEditable
        b.table.item(1, 0).setText("Counter")
        assert b.draft.segments[1].name == b.segment_name.text() == "Counter"
        index = b.table.model().index(1, 3)
        delegate = b.table.itemDelegate()
        from PyQt6.QtWidgets import QStyleOptionViewItem
        editor = delegate.createEditor(b.table, QStyleOptionViewItem(), index)
        delegate.setEditorData(editor, index)
        editor.setCurrentIndex(editor.findData("system"))
        delegate.setModelData(editor, b.table.model(), index)
        assert b.draft.segments[1].source == b.source.currentData() == "system"
        assert b.draft.segments[1].value == "EnvelopeIndex"
        assert dialog.candidate().payload(fields()) == "0101"
        editor.deleteLater()
        b.table.item(1, 2).setText("bad")
        assert b.table.item(1, 2).text() == "2"
        assert b.draft.segments[1].length == 2
    finally:
        dialog.close()
        dialog.deleteLater()


def test_edit_selected_reveals_details_in_small_dialog(qt_application):
    dialog = BarcodeSetupDialog(valid_profile(), fields(), symbology="i25")
    try:
        dialog.resize(460, 360)
        dialog.show()
        qt_application.processEvents()
        b = dialog.generic.builder
        b.edit_selected.click()
        qt_application.processEvents()
        rect = dialog.scroll.viewport().rect()
        point = b.segment_name.mapTo(dialog.scroll.viewport(), b.segment_name.rect().center())
        assert rect.contains(point)
        assert b.segment_name.hasFocus()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_local_sequence_start_invalid_draft_and_cycle(qt_application):
    dialog = BarcodeSetupDialog(BarcodeProfile.fixed_layout(2, [BarcodeSegment(name="Seq", length=2, source="sequence", format="numeric")]),
                                {**fields(), "EnvelopeIndex": "101"}, symbology="i25")
    try:
        b = dialog.generic.builder
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert not ok.isEnabled() and "needs 3 digits" in dialog.status.text()
        b.overflow.setCurrentIndex(1)
        assert ok.isEnabled() and "00" in b.preview.text()
        b.start.setText("abc")
        assert not ok.isEnabled()
        b.add.click()
        b.table.setCurrentCell(0, 0)
        assert b.start.text() == "abc"
        b.start.setText("0")
        b.table.setCurrentCell(1, 0)
        b.remove.click()
        assert ok.isEnabled(), dialog.status.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_legacy_conversion_requires_explicit_length(qt_application):
    legacy = BarcodeProfile(tokens=[BarcodeToken(value="EnvelopeSeq", width=2), BarcodeToken(kind="literal", value="00")])
    dialog = BarcodeSetupDialog(legacy, fields(), symbology="i25")
    try:
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert not ok.isEnabled() and "cannot fit" in dialog.status.text()
        assert dialog.generic.legacy.sample.isHidden()
        dialog.generic.convert.click()
        b = dialog.generic.builder
        assert not ok.isEnabled() and b.total.value() == 0
        b.total.setValue(4)
        assert ok.isEnabled(), dialog.status.text()
        assert dialog.candidate().version == 3 and dialog.candidate().payload(fields()) == "0100"
        assert legacy.tokens[0].width == 2 and legacy.layout_mode == "legacy"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_pending_data_can_save_but_empty_loaded_value_blocks(qt_application):
    p = BarcodeProfile.fixed_layout(4, [BarcodeSegment(name="Customer", length=4, source="data", value="Customer")])
    context = BarcodeContext(data={"Customer": ""}, system=fields(), data_loaded=False)
    dialog = BarcodeSetupDialog(p, {**fields(), CONTEXT_KEY: context}, symbology="i25")
    try:
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        assert ok.isEnabled() and "Data pending" in dialog.status.text()
        context.data_loaded = True
        dialog.refresh()
        assert not ok.isEnabled() and "Empty value" in dialog.status.text()
        context.data["Customer"] = "0001"
        dialog.refresh()
        assert ok.isEnabled() and "0001" in dialog.generic.builder.preview.text()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_template_existing_sequence_configure_undo_and_cancel(qt_application, monkeypatch):
    from composition.designer.barcode_operations import edit_template_barcode
    from composition.designer.workspace import CompositionWindow
    from composition.template.model import Element, SequenceSpec, Template
    from tests.composition.test_workspace import close_window
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    window = CompositionWindow()
    model = Template(record_mode="generated", generated_count=200, sequences=[SequenceSpec(name="MySeq", start=1)])
    model.elements.append(Element(type="i25", width_mm=100, height_mm=14, barcode_profile=BarcodeProfile.fixed_layout(
        4, [BarcodeSegment(name="Existing seq", length=4, source="sequence", value="MySeq", format="numeric")]).to_dict()))
    try:
        window._apply_template(model.to_dict(), model.elements[0].id)
        def apply(dialog):
            assert dialog.generic.builder.context.sequences["MySeq"] == "000001"
            assert "MySeq" not in dialog.generic.builder.context.data
            dialog.generic.builder.length.setValue(6)
            dialog.generic.builder.total.setValue(6)
            dialog.accept()
            assert dialog.result() == dialog.DialogCode.Accepted, dialog.status.text()
            return dialog.result()
        monkeypatch.setattr(BarcodeSetupDialog, "exec", apply)
        before = window.template.to_dict()
        edit_template_barcode(window)
        assert window.template.elements[0].barcode_profile["total_length"] == 6
        window.undo.undo()
        assert window.template.to_dict() == before
        monkeypatch.setattr(BarcodeSetupDialog, "exec", lambda dialog: 0)
        edit_template_barcode(window)
        assert window.template.to_dict() == before
    finally:
        close_window(window)


def test_legacy_conversion_preserves_literal_and_non_numeric_system(qt_application):
    original = BarcodeProfile(tokens=[BarcodeToken(kind="literal", value="AB", width=2), BarcodeToken(value="Side")])
    dialog = BarcodeSetupDialog(original, {**fields(), "Side": "Front"}, symbology="code128")
    try:
        dialog.generic.convert.click()
        b = dialog.generic.builder
        assert b.draft.segments[0].format == b.draft.segments[1].format == "text"
        assert b.draft.segments[1].length == 0
        b.total.setValue(7)
        b.table.setCurrentCell(1, 0)
        b.length.setValue(5)
        assert dialog.candidate().payload({**fields(), "Side": "Front"}) == "ABFront"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_overlay_shared_fixed_profile_apply_and_undo(qt_application, monkeypatch, tmp_path):
    from composition.designer.overlay_workspace import OverlayWindow
    from tests.composition.test_pdf_overlay_models import sample_spec
    from tests.composition.test_pdf_overlay_ui import finish
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    window = OverlayWindow()
    try:
        spec = sample_spec(tmp_path)
        spec.objects[1].profile = valid_profile()
        window.apply_spec(spec.to_dict())
        window.canvas.select_ids([spec.objects[1].element.id])
        before = window.spec.to_dict()
        def apply(dialog):
            assert dialog.generic.builder.context.system["OutputPage"] == "1"
            assert not dialog.generic.builder.context.data
            dialog.generic.builder.table.setCurrentCell(1, 0)
            dialog.generic.builder.value.setCurrentText("99")
            dialog.accept()
            assert dialog.result() == dialog.DialogCode.Accepted, dialog.status.text()
            return dialog.result()
        monkeypatch.setattr(BarcodeSetupDialog, "exec", apply)
        window.edit_profile()
        assert window.spec.objects[1].profile.segments[1].value == "99"
        window.undo.undo()
        assert window.spec.to_dict() == before
        monkeypatch.setattr(BarcodeSetupDialog, "exec", lambda dialog: 0)
        window.edit_profile()
        assert window.spec.to_dict() == before
    finally:
        finish(window)


def test_full_desktop_layout_and_long_field_popup(qt_application, tmp_path):
    context = BarcodeContext(data={"Customer_" + "A" * 55: "0001"}, system=fields())
    dialog = BarcodeSetupDialog(valid_profile(), {**fields(), CONTEXT_KEY: context}, symbology="i25")
    try:
        dialog.resize(960, 640)
        dialog.show()
        qt_application.processEvents()
        b = dialog.generic.builder
        b.source.setCurrentIndex(b.source.findData("data"))
        b.value.setCurrentIndex(0)
        b.length.setValue(4)
        b.total.setValue(6)
        dialog.scroll.ensureWidgetVisible(b.value)
        b.value.showPopup()
        qt_application.processEvents()
        available = dialog.screen().availableGeometry().width() - 24
        assert b.value.view().minimumWidth() >= min(available, b.value.fontMetrics().horizontalAdvance(next(iter(context.data))))
        assert b.value.toolTip() == next(iter(context.data))
        assert b.value.view().maximumWidth() <= dialog.screen().availableGeometry().width()
        b.value.hidePopup()
        assert dialog.footer.button(QDialogButtonBox.StandardButton.Ok).isEnabled(), dialog.status.text()
        assert dialog.body.width() <= dialog.scroll.viewport().width()
        assert dialog.grab().save(str(tmp_path / "generic-960.png"))
        dialog.scroll.verticalScrollBar().setValue(dialog.scroll.verticalScrollBar().maximum())
        qt_application.processEvents()
        assert dialog.grab().save(str(tmp_path / "generic-preview.png"))
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_compact_layout_footer_and_popup(qt_application, theme, tmp_path):
    from styles.theme import apply_theme
    apply_theme(qt_application, theme)
    dialog = BarcodeSetupDialog(valid_profile(), fields(), symbology="i25")
    try:
        dialog.resize(460, 360)
        dialog.show()
        qt_application.processEvents()
        ok = dialog.footer.button(QDialogButtonBox.StandardButton.Ok)
        corner = ok.mapTo(dialog, QPoint(ok.width(), ok.height()))
        assert corner.x() <= dialog.width() and corner.y() <= dialog.height()
        assert dialog.body.width() <= dialog.scroll.viewport().width()
        box = dialog.generic.builder.source
        box.showPopup()
        assert box.view().maximumWidth() <= dialog.screen().availableGeometry().width()
        box.hidePopup()
        assert dialog.grab().save(str(tmp_path/f"generic-{theme}.png"))
    finally:
        dialog.close()
        dialog.deleteLater()
        apply_theme(qt_application, "system")
