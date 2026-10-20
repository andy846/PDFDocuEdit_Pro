"""Watermark controls, worker preview and persisted edit routing."""
from dataclasses import replace

import pytest
from PyQt6.QtWidgets import QDialog

from core.watermarks import WatermarkSpec, add_watermark, list_watermarks, watermark_spec
from dialogs.annotation_dialogs import WatermarkDialog
from tests.test_document_windows import documents
from tests.test_document_windows import editor as editor
from tests.test_open_performance import wait_until


def test_watermark_free_angle_offsets_and_preview_do_not_mutate_source(editor, tmp_path):
    session = documents(editor, tmp_path, count=1)[0]
    doc = session.engine.document
    original = len(list_watermarks(doc[0]))
    dialog = WatermarkDialog(3, 0, editor)
    dialog.enable_preview(doc, session.canvas)
    dialog.show()
    try:
        dialog.rotation.setValue(27.5)
        dialog.x_offset.setValue(3)
        dialog.y_offset.setValue(-4)
        dialog.scale.setValue(80)
        wait_until(lambda: dialog.preview.pixmap() is not None and not dialog.preview.pixmap().isNull())
        assert dialog.preview.pixmap().height() <= dialog.preview.height()
        assert dialog.preview.pixmap().width() <= dialog.preview.width()
        assert len(list_watermarks(doc[0])) == original
        dialog._validate()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.details["rotation"] == 27.5
        assert dialog.details["x_mm"] == 3 and dialog.details["y_mm"] == -4
        assert dialog.details["scale"] == .8
    finally:
        dialog.reject()
        wait_until(lambda: all(task.done.is_set() for task in dialog._preview_jobs))
        dialog.deleteLater()


def test_watermark_edit_is_selected_instance_only_and_undoable(editor, tmp_path, monkeypatch):
    from core import viewer as viewer_module
    session = documents(editor, tmp_path, count=1)[0]
    with editor._mutation_transaction("Watermark") as allowed:
        assert allowed
        add_watermark(session.engine.document[0], WatermarkSpec(text="FIRST"))
        add_watermark(session.engine.document[1], WatermarkSpec(text="SECOND"))
        session.engine.mark_modified()
    editor._refresh_session_canvases(session)
    entry = list_watermarks(session.engine.document[0])[0]
    class Accepted(WatermarkDialog):
        def exec(self):
            self.text.setText("EDITED")
            self.rotation.setValue(12)
            self._validate()
            return self.result()
    monkeypatch.setattr(viewer_module, "WatermarkDialog", Accepted)
    editor._focus_annotation_properties(0, entry["xref"])
    first = list_watermarks(session.engine.document[0])[0]
    assert watermark_spec(session.engine.document[0], first["xref"]).text == "EDITED"
    second = list_watermarks(session.engine.document[1])[0]
    assert watermark_spec(session.engine.document[1], second["xref"]).text == "SECOND"
    assert editor._undo()
    first = list_watermarks(session.engine.document[0])[0]
    assert watermark_spec(session.engine.document[0], first["xref"]).text == "FIRST"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_watermark_dialog_controls_reachable_at_narrow_size(qt_application, theme):
    from styles.theme import apply_theme
    apply_theme(qt_application, theme)
    dialog = WatermarkDialog(5, 0)
    dialog.configure_existing(replace(WatermarkSpec(), text="Editable"), None)
    dialog.resize(700, 580)
    dialog.show()
    qt_application.processEvents()
    try:
        assert dialog.pages.isEnabled() is False
        assert dialog.rotation.isEnabled() and dialog.x_offset.isEnabled()
        assert dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
        # Existing responsive scrolling must reveal controls below the fold,
        # including on the small logical screen used by the 200% DPI probe.
        qt_application.setActiveWindow(dialog)
        dialog.y_offset.setFocus()
        qt_application.processEvents()
        viewport = dialog._responsive_scroll.viewport()
        centre = dialog.y_offset.mapTo(viewport, dialog.y_offset.rect().center())
        assert viewport.rect().contains(centre)
        button = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert dialog.rect().contains(button.mapTo(dialog, button.rect().center()))
    finally:
        dialog.reject()
        dialog.deleteLater()
        apply_theme(qt_application, "system")
