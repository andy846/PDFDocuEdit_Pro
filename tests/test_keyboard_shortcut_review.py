from dataclasses import replace

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractItemView, QLineEdit, QVBoxLayout, QWidget

from core.commands import Command, find_shortcut_conflict
from core.settings import SettingsManager
from dialogs.shortcuts_dialog import ShortcutsDialog
from ui.diagnostics_dialog import PreferencesDialog
from ui.shortcut_bindings import CommandAction


def test_save_and_palette_work_while_text_delete_stays_local(qt_application):
    window = QWidget()
    layout = QVBoxLayout(window)
    text = QLineEdit()
    layout.addWidget(text)
    calls = []
    for key, sequence in (("save", "Ctrl+S"), ("command_palette", "Ctrl+K"), ("quick_delete", "Delete")):
        action = CommandAction(key, window)
        action.setProperty("commandId", key)
        action.setShortcut(sequence)
        action.triggered.connect(lambda checked=False, name=key: calls.append(name))
        window.addAction(action)
    window.show()
    window.activateWindow()
    text.setFocus()
    qt_application.processEvents()
    try:
        QTest.keyClick(text, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(text, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        assert calls == ["save", "command_palette"]
        text.setText("abc")
        text.setCursorPosition(0)
        QTest.keyClick(text, Qt.Key.Key_Delete)
        assert text.text() == "bc" and calls == ["save", "command_palette"]
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("overrides", [
    {"organizer.reverse": "Ctrl+S"},
    {"command_palette": "Ctrl+O, Ctrl+K"},
    {"rotate_left": "Ctrl+Shift+Z"},
])
def test_scoped_overrides_prefixes_and_redo_alias(qt_application, tmp_path, monkeypatch, overrides):
    import core.viewer as viewer
    settings = SettingsManager(tmp_path / "settings.json")
    settings.set_shortcut_overrides(overrides)
    monkeypatch.setattr(viewer, "SettingsManager", lambda: settings)
    window = viewer.PDFViewer()
    try:
        commands = {c.id: c for c in window._commands}
        assert find_shortcut_conflict(window._commands, {}) is None
        if "organizer.reverse" in overrides:
            assert commands["save"].shortcut == "Ctrl+S"
            assert {s.toString() for s in window.redo_action.shortcuts()} == {"Ctrl+Y", "Ctrl+Shift+Z"}
        if "command_palette" in overrides:
            assert not commands["open"].shortcut
            assert "Ctrl+O" not in window.command_bar._open.toolTip()
        if "rotate_left" in overrides:
            assert not commands["redo"].alternate_shortcuts
            assert window.redo_action.shortcuts() == [QKeySequence("Ctrl+Y")]
    finally:
        window.close()
        window.deleteLater()


def test_reference_readonly_searches_alternative_and_section(qt_application):
    command = Command("redo", "Redo", "Ctrl+Y", "Edit", lambda: None,
                      alternate_shortcuts=("Ctrl+Shift+Z",))
    dialog = ShortcutsDialog([command])
    try:
        assert dialog.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert dialog.table.item(0, 1).text() == "Ctrl+Y / Ctrl+Shift+Z"
        dialog._filter.setText("Ctrl+Shift+Z")
        assert dialog.table.rowCount() == 1
        dialog._filter.setText("Edit")
        assert dialog.table.rowCount() == 1
        assert find_shortcut_conflict([command, replace(command, id="other", shortcut="Ctrl+Shift+Z", alternate_shortcuts=())], {})
    finally:
        dialog.close()
        dialog.deleteLater()


def test_preferences_blocks_occupied_redo_alias(qt_application, tmp_path):
    commands = [Command("open", "Open", "Ctrl+O", "File", lambda: None),
                Command("redo", "Redo", "Ctrl+Y", "Edit", lambda: None, alternate_shortcuts=("Ctrl+Shift+Z",))]
    dialog = PreferencesDialog(SettingsManager(tmp_path / "settings.json"), commands=commands)
    try:
        for row in range(dialog.shortcut_table.rowCount()):
            if dialog.shortcut_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == "open":
                dialog.shortcut_table.selectRow(row)
        dialog.shortcut_editor.setKeySequence(QKeySequence("Ctrl+Shift+Z"))
        assert not dialog._assign_shortcut()
        assert "Redo" in dialog.shortcut_status.text()
    finally:
        dialog.close()
        dialog.deleteLater()
