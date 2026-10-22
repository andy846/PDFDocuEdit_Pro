from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import core.viewer as viewer_module
from core.forms import enumerate_fields
from core.settings import SettingsManager

_APP = None


def make_form(path: Path) -> Path:
    with fitz.open() as document:
        page = document.new_page()
        for index, name in enumerate(("First", "Second")):
            widget = fitz.Widget()
            widget.field_name = name
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = name
            widget.rect = fitz.Rect(40, 40 + index * 50, 240, 70 + index * 50)
            page.add_widget(widget)
        document.save(path)
    return path


def window_for(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication(["inline-form-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    window = viewer_module.PDFViewer()
    window._set_motion_enabled(False)
    return window


def test_fill_form_uses_main_canvas_and_stages_until_apply(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_form(tmp_path / "form.pdf")))
    window._fill_form()
    session = window._session
    assert session.form_mode_active
    assert str(session.canvas.tool_mode) == "form"
    assert window.context_panel._stack.currentWidget() is window.context_panel.form_panel
    overlay = session.canvas._page_views[0].overlay
    point = overlay.pdf_rect_to_widget(fitz.Rect(40, 40, 240, 70)).center().toPoint()
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=point)
    editor = overlay.findChild(viewer_module.InlineTextEditor, "inlineFormEditor")
    assert editor is not None
    editor.setText("Updated")
    editor.finishRequested.emit(True)
    assert session.form_draft.staged == {"First": "Updated"}
    assert enumerate_fields(session.engine.document)[0].value == "First"
    assert session.form_draft.preview is not None
    assert enumerate_fields(session.form_draft.preview)[0].value == "Updated"
    assert window._apply_form_draft()
    assert enumerate_fields(session.engine.document)[0].value == "Updated"
    assert session.undo_stack.can_undo
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: True)
    window.close()


def test_form_draft_survives_tool_change_and_tab_switch(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    first = make_form(tmp_path / "one.pdf")
    second = make_form(tmp_path / "two.pdf")
    window._load_file_sync(str(first))
    session = window._session
    window._fill_form()
    field = session.form_draft.fields[0]
    window._form_stage(session, field, "Draft")
    window._tool_requested("search")
    assert session.form_draft.staged == {"First": "Draft"}
    assert not session.form_mode_active
    other = window._open_in_new_tab_sync(str(second))
    assert other is not session
    window.workspace.set_current_session(session)
    window._fill_form()
    assert session.form_draft.staged == {"First": "Draft"}
    assert session.form_draft.preview is not None
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: True)
    window._discard_form_draft()
    window.close()


def test_save_without_draft_keeps_unapplied_values(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    path = make_form(tmp_path / "save.pdf")
    window._load_file_sync(str(path))
    session = window._session
    window._fill_form()
    window._form_stage(session, session.form_draft.fields[0], "Draft")

    def choose_save_without_draft(box):
        next(button for button in box.buttons() if button.text() == "Save without draft").click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", choose_save_without_draft)
    window.save_file()
    assert session.form_draft.staged == {"First": "Draft"}
    with fitz.open(path) as saved:
        assert enumerate_fields(saved)[0].value == "First"
    window._discard_form_draft()
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: True)
    window.close()
