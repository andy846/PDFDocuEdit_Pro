from __future__ import annotations

import copy
from dataclasses import asdict

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from composition.designer.overlay_dialogs import BarcodeProfileDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.overlay.model import BarcodeProfile, OverlayObject
from composition.pdf_source.planner import EnvelopePlan
from composition.template.model import Element
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import close_window


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def bounded_ui_work(monkeypatch):
    real_preview = OverlayWindow.render_preview
    # These interaction tests exercise commits/selection; renderer tests cover PDF output.
    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    return real_preview


def test_format_change_keeps_content_geometry_font_and_undo(app):
    window = CompositionWindow()
    try:
        window.add_element("code128", "000123", x=25, y=35)
        window.properties.human.setChecked(True)
        original = asdict(window.template.elements[0])
        window.properties.barcode_format.setCurrentIndex(window.properties.barcode_format.findData("i25"))
        expected = {**original, "type": "i25"}
        assert asdict(window.template.elements[0]) == expected
        window.properties.barcode_format.setCurrentIndex(window.properties.barcode_format.findData("qr"))
        assert window.template.elements[0].type == "qr"
        assert not window.template.elements[0].show_barcode_text
        assert window.template.elements[0].value == "000123"
        window.undo.undo()
        assert asdict(window.template.elements[0]) == expected
        window.undo.undo()
        assert asdict(window.template.elements[0]) == original
    finally:
        close_window(window)


def test_normal_layer_filter_survives_edit_and_undo(app):
    window = CompositionWindow()
    try:
        window.add_element("text", "Name")
        window.add_element("text", "Account")
        window.layer_filter.setText("account")
        assert sum(not window.layers.item(row).isHidden() for row in range(window.layers.count())) == 1
        window.properties.content.setPlainText("Account balance")
        assert sum(not window.layers.item(row).isHidden() for row in range(window.layers.count())) == 1
        window.undo.undo()
        assert window.layer_filter.text() == "account"
        assert sum(not window.layers.item(row).isHidden() for row in range(window.layers.count())) == 1
        window.layer_filter.clear()
        assert all(not window.layers.item(row).isHidden() for row in range(window.layers.count()))
    finally:
        close_window(window)


def test_payload_order_and_literal_width_controls(app):
    fields = EnvelopePlan(6, sample_settings()).page(1, 1).fields()
    dialog = BarcodeProfileDialog(BarcodeProfile(), fields, symbology="i25")
    try:
        dialog.table.setCurrentCell(2, 0)
        dialog.token_up.click()
        assert dialog.candidate().payload(fields) == "0000010301"
        assert dialog.table.currentRow() == 1
        dialog.token_down.click()
        assert dialog.candidate().payload(fields) == "0000010103"
        dialog.table.cellWidget(2, 0).setCurrentText("literal")
        dialog.table.cellWidget(2, 1).setCurrentText("03")
        assert not dialog.table.cellWidget(2, 2).isEnabled()
        assert dialog.candidate().tokens[2].width == 0
        assert dialog.footer.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    finally:
        dialog.close()


def sample_settings():
    from composition.pdf_source.model import EnvelopeSettings
    return EnvelopeSettings()


def test_invalid_last_sample_blocks_profile_acceptance(app):
    fields = EnvelopePlan(6, sample_settings()).page(1, 1).fields()
    last = {**fields, "EnvelopeSeq": "1000000"}
    dialog = BarcodeProfileDialog(BarcodeProfile(), fields, symbology="i25", samples=[("Last mark", last)])
    try:
        assert "even number" in dialog.sample.text()
        assert not dialog.footer.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    finally:
        dialog.close()


def test_overlay_layers_find_hidden_last_page_and_keep_selection(app, tmp_path):
    spec = sample_spec(tmp_path)
    last = OverlayObject(Element(value="Last page note", y_mm=80), scope="last")
    spec.objects.append(last)
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        assert window.print_page.value() == 1
        window.object_filter.setText("last page")
        item = next(window.layers.item(row) for row in range(window.layers.count())
                    if window.layers.item(row).data(Qt.ItemDataRole.UserRole) == last.element.id)
        assert not item.isHidden()
        item.setSelected(True)
        assert window.print_page.value() == 3
        assert window.canvas.selected_ids() == [last.element.id]
        assert window.properties.element.id == last.element.id
        window.properties.numbers["font_size"].setValue(15)
        window.properties.apply_field("font_size")
        window.undo.undo()
        assert window.object_filter.text() == "last page"
        assert window.canvas.selected_ids() == [last.element.id]
        window.field_filter.setText("sheet")
        assert all("sheet" in window.fields.item(row).text().casefold()
                   for row in range(window.fields.count()) if not window.fields.item(row).isHidden())
    finally:
        finish(window)


def test_overlay_format_change_retains_profile_and_live_payload(app, tmp_path):
    spec = sample_spec(tmp_path)
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        window.canvas.select_ids([spec.objects[1].element.id])
        original = copy.deepcopy(window.spec.to_dict()["objects"][1])
        window.properties.barcode_format.setCurrentIndex(window.properties.barcode_format.findData("i25"))
        changed = window.spec.to_dict()["objects"][1]
        assert changed["profile"] == original["profile"]
        assert changed["control"] == original["control"]
        assert changed["element"]["type"] == "i25"
        assert "0000010103" in window.payload_summary.text()
        window.print_page.setValue(2)
        window.canvas.select_ids([spec.objects[1].element.id])
        assert "0000010203" in window.payload_summary.text()
        window.undo.undo()
        assert window.spec.to_dict()["objects"][1] == original
    finally:
        finish(window)


def test_duplex_profile_samples_use_applicable_source_pages(app, tmp_path, monkeypatch):
    spec = sample_spec(tmp_path, duplex=True)
    window = OverlayWindow()
    seen = []
    def check(dialog):
        seen.extend(dialog.samples)
        assert dialog.footer.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        return 0
    monkeypatch.setattr(BarcodeProfileDialog, "exec", check)
    try:
        window.apply_spec(spec.to_dict())
        window.canvas.select_ids([spec.objects[1].element.id])
        window.edit_profile()
        assert [fields["LetterPage"] for _, fields in seen] == ["1", "3"]
        assert all(fields["IsInsertedBlank"] == "0" for _, fields in seen)
    finally:
        finish(window)


def test_unfinished_overlay_edit_rejects_stale_preview_and_can_revert(app, tmp_path, monkeypatch):
    spec = sample_spec(tmp_path)
    window = OverlayWindow()
    try:
        window.apply_spec(spec.to_dict())
        window.canvas.select_ids([spec.objects[0].element.id])
        generation = window.preview_generation
        window.properties.content.setPlainText("{{Unfinished")
        assert window.draft_error and window.preview_generation > generation
        assert not window.actions["save"].isEnabled()
        assert not window.layers.isEnabled()
        assert window.preview_status.text() == "Fix unfinished edit"
        calls = []
        monkeypatch.setattr(window.canvas, "set_preview", lambda image: calls.append(image))
        raw_pdf, image = tmp_path / "old.pdf", tmp_path / "old.png"
        raw_pdf.write_bytes(b"old")
        image.write_bytes(b"old")
        window.preview_ready({"pdf": str(raw_pdf), "image": str(image)}, generation)
        assert not calls and not raw_pdf.exists() and not image.exists()
        window.revert_draft()
        assert not window.draft_error and window.actions["save"].isEnabled()
        assert window.layers.isEnabled()
        assert window.properties.content.toPlainText() == spec.objects[0].element.value
    finally:
        finish(window)


def test_live_background_preview_ready_error_and_review(app, tmp_path, bounded_ui_work):
    from composition.overlay.model import BarcodeToken
    from tests.composition.test_workspace import wait_until

    spec = sample_spec(tmp_path)
    window = OverlayWindow()
    try:
        window.show()
        window.apply_spec(spec.to_dict())
        window.timer.stop()
        bounded_ui_work(window)
        wait_until(lambda: window.preview_status.text() == "Preview ready")
        assert window.canvas.preview_item is not None
        spec.objects[1].element.type = "i25"
        spec.objects[1].profile.tokens = [BarcodeToken("literal", "1")]
        window.apply_spec(spec.to_dict())
        window.timer.stop()
        bounded_ui_work(window)
        wait_until(lambda: "Preview failed" in window.preview_status.text())
        assert "even number" in window.preview_status.toolTip()
        assert window.preview_error_object == spec.objects[1].element.id
        window.review_preview_error()
        assert window.canvas.selected_ids() == [spec.objects[1].element.id]
        assert window.profile_button.isEnabled()
    finally:
        finish(window)
