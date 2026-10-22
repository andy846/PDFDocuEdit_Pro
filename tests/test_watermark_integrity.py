"""Watermark text must survive encoding, and untouched opacity must roundtrip."""
import io

import pytest
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractSlider, QDialog, QStyle, QStyleOptionSlider

from core import viewer as viewer_module
from core.pdf_backend import fitz
from core.watermarks import (
    WatermarkError,
    WatermarkSpec,
    add_watermark,
    add_watermarks,
    list_watermarks,
    watermark_spec,
)
from dialogs.annotation_dialogs import WatermarkDialog
from tests.test_document_windows import documents
from tests.test_document_windows import editor as editor
from ui.watermark_preview import WatermarkPreviewTask


def image_data():
    output = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(output, format="PNG")
    return output.getvalue()


def pdf_bytes(document):
    return document.tobytes(no_new_id=True)


@pytest.mark.parametrize("text", ["مرحبا", "שלום", "😀", "e\u0301", "A\u200dB", "A\x00B", "\U0010ffff", "\u1100\u1161"])
@pytest.mark.parametrize("batch", [False, True])
def test_unreliable_text_is_rejected_before_any_target_change(text, batch):
    with fitz.open() as document:
        for _ in range(2):
            document.new_page().insert_text((30, 30), "Original content")
        before = pdf_bytes(document)
        with pytest.raises(WatermarkError, match="U\\+") as error:
            if batch:
                add_watermarks(document, [0, 1], WatermarkSpec(text=text))
            else:
                add_watermark(document[0], WatermarkSpec(text=text))
        assert text not in str(error.value)
        assert pdf_bytes(document) == before


@pytest.mark.parametrize("text", ["TEST ASCII", "測試中文 WATERMARK", "Fallback \u1e9e", "\uac00"])
def test_supported_text_and_bundled_fallback_survive_save(text):
    with fitz.open() as document:
        page = document.new_page()
        add_watermark(page, WatermarkSpec(text=text, fontsize=24, rotation=0, opacity=1))
        with fitz.open(stream=pdf_bytes(document), filetype="pdf") as saved:
            assert saved[0].get_text().strip() == text
            assert min(saved[0].get_pixmap().samples) < 240
            if "\u1e9e" in text:
                fonts = [row for row in saved[0].get_fonts(full=True) if "NotoSans" in row[3].replace(" ", "")]
                assert fonts and all(saved.extract_font(row[0])[3] for row in fonts)


def test_missing_bundled_fallback_refuses_without_target_changes(tmp_path, monkeypatch):
    from core import pdf_runtime
    monkeypatch.setattr(pdf_runtime, "asset_root", lambda: tmp_path)
    with fitz.open() as document:
        page = document.new_page()
        before = pdf_bytes(document)
        with pytest.raises(WatermarkError, match="U\\+1E9E"):
            add_watermark(page, WatermarkSpec(text="\u1e9e"))
        assert pdf_bytes(document) == before


def test_incorrect_encoded_output_is_rejected_before_target_change(monkeypatch):
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((30, 30), "Original")
        before = pdf_bytes(document)
        get_text = fitz.Page.get_text
        def wrong_mapping(page, *args, **kwargs):
            if page.parent is not document:
                return "WRONG MAPPING\n"
            return get_text(page, *args, **kwargs)
        monkeypatch.setattr(fitz.Page, "get_text", wrong_mapping)
        with pytest.raises(WatermarkError, match="U\\+"):
            add_watermark(page, WatermarkSpec(text="SAFE"))
        assert pdf_bytes(document) == before


def test_batch_prepares_text_only_once(monkeypatch):
    insert_text = fitz.Page.insert_text
    calls = []
    def count(page, point, text, *args, **kwargs):
        if text == "ONCE":
            calls.append(True)
        return insert_text(page, point, text, *args, **kwargs)
    monkeypatch.setattr(fitz.Page, "insert_text", count)
    with fitz.open() as document:
        for _ in range(20):
            document.new_page()
        add_watermarks(document, list(range(20)), WatermarkSpec(text="ONCE"))
        assert calls == [True]
        assert all("ONCE" in page.get_text() for page in document)


def test_preview_rejects_unreliable_text_without_mutating_source(qt_application):
    with fitz.open() as document:
        document.new_page()
        before = pdf_bytes(document)
        task = WatermarkPreviewTask(document, 0, WatermarkSpec(text="שלום"), None, None, None, 1, None)
        results = []
        task.signals.finished.connect(results.append)
        task.run()
        assert task.done.is_set() and results[0]["image"] is None
        assert "U+" in results[0]["error"] and "שלום" not in results[0]["error"]
        assert pdf_bytes(document) == before


def test_dialog_cannot_accept_unreliable_text(qt_application, monkeypatch):
    dialog = WatermarkDialog(1, 0)
    errors = []
    monkeypatch.setattr(dialog, "show_error", errors.append)
    dialog.text.setText("مرحبا")
    dialog._validate()
    try:
        assert dialog.result() == QDialog.DialogCode.Rejected and dialog.details is None
        assert errors and "U+" in errors[0]
    finally:
        dialog.reject()
        dialog.deleteLater()


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize("opacity", [0, .01, .05, 1, .004, .123456789])
def test_untouched_opacity_is_exact_in_preview_and_apply(qt_application, mode, opacity):
    dialog = WatermarkDialog(1, 0)
    dialog.configure_existing(WatermarkSpec(mode=mode, opacity=opacity), image_data() if mode == "image" else None)
    dialog.x_offset.setValue(1)
    try:
        assert dialog._spec().opacity == opacity
        dialog._validate()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.details["opacity"] == opacity
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_explicit_slider_action_can_replace_fractional_opacity_with_zero(qt_application):
    dialog = WatermarkDialog(1, 0)
    dialog.configure_existing(WatermarkSpec(opacity=.004), None)
    dialog.opacity.triggerAction(QAbstractSlider.SliderAction.SliderToMinimum)
    try:
        assert dialog._spec().opacity == 0
        assert dialog.opacity_value.text() == "0%"
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_native_slider_move_action_without_value_change_preserves_opacity(qt_application):
    dialog = WatermarkDialog(1, 0)
    dialog.configure_existing(WatermarkSpec(opacity=.123456789), None)
    try:
        # Native styles may emit SliderMove on a handle press without moving it.
        dialog.opacity.actionTriggered.emit(QAbstractSlider.SliderAction.SliderMove.value)
        assert dialog._spec().opacity == .123456789
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_press_release_opacity_handle_without_moving_preserves_exact_value(qt_application):
    dialog = WatermarkDialog(1, 0)
    dialog.configure_existing(WatermarkSpec(opacity=.123456789), None)
    dialog.show()
    qt_application.processEvents()
    option = QStyleOptionSlider()
    dialog.opacity.initStyleOption(option)
    handle = dialog.opacity.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, dialog.opacity)
    try:
        QTest.mousePress(dialog.opacity, Qt.MouseButton.LeftButton, pos=handle.center())
        QTest.mouseRelease(dialog.opacity, Qt.MouseButton.LeftButton, pos=handle.center())
        qt_application.processEvents()
        assert dialog.opacity.value() == 12
        assert dialog._spec().opacity == .123456789
    finally:
        dialog.reject()
        dialog.deleteLater()


@pytest.mark.parametrize("mode", ["text", "image"])
@pytest.mark.parametrize("opacity", [0, .004])
def test_edit_other_property_save_reopen_undo_redo_preserves_opacity(editor, tmp_path, monkeypatch, mode, opacity):
    session = documents(editor, tmp_path, count=1)[0]
    with editor._mutation_transaction("Add watermark") as allowed:
        assert allowed
        add_watermark(session.engine.document[0], WatermarkSpec(mode=mode, text="SAFE", fontsize=24,
                      opacity=opacity, rotation=0), image=image_data() if mode == "image" else None)
        session.engine.mark_modified()
    class EditOtherProperty(WatermarkDialog):
        def exec(self):
            self.rotation.setValue(12)
            self._validate()
            return self.result()
    monkeypatch.setattr(viewer_module, "WatermarkDialog", EditOtherProperty)
    entry = list_watermarks(session.engine.document[0])[0]
    editor._focus_annotation_properties(0, entry["xref"])
    def spec():
        page = session.engine.document[0]
        return watermark_spec(page, list_watermarks(page)[0]["xref"])
    assert spec().opacity == opacity and spec().rotation == 12
    assert editor._undo() and spec().opacity == opacity and spec().rotation == 0
    assert editor._redo() and spec().opacity == opacity and spec().rotation == 12
    destination = tmp_path / "saved.pdf"
    session.engine.save(destination)
    with fitz.open(destination) as saved:
        assert watermark_spec(saved[0], list_watermarks(saved[0])[0]["xref"]).opacity == opacity


def test_stale_accepted_dialog_cannot_replace_existing_watermark(editor, tmp_path, monkeypatch):
    session = documents(editor, tmp_path, count=1)[0]
    with editor._mutation_transaction("Original watermark") as allowed:
        assert allowed
        add_watermark(session.engine.document[0], WatermarkSpec(text="ORIGINAL", rotation=0))
        session.engine.mark_modified()
    before = session.undo_stack.undo_count
    entry = list_watermarks(session.engine.document[0])[0]
    class StaleAccepted(WatermarkDialog):
        def exec(self):
            self._validate()
            assert self.result() == QDialog.DialogCode.Accepted
            self.details["text"] = "שלום"
            return self.result()
    errors = []
    monkeypatch.setattr(viewer_module, "WatermarkDialog", StaleAccepted)
    monkeypatch.setattr(editor, "_error", lambda title, message: errors.append(message))
    editor._focus_annotation_properties(0, entry["xref"])
    current = list_watermarks(session.engine.document[0])
    assert len(current) == 1 and current[0]["id"] == entry["id"]
    assert watermark_spec(session.engine.document[0], current[0]["xref"]).text == "ORIGINAL"
    assert session.undo_stack.undo_count == before
    assert errors and "U+" in errors[0] and "שלום" not in errors[0]
