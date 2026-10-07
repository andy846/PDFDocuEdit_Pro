import copy
import sys
import traceback
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QDialogButtonBox

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
