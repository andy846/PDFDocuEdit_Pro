from dataclasses import replace

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.commands import Command, find_shortcut_conflict, shortcut_conflict
from core.settings import SettingsManager
from dialogs.document_dialogs import VisualOrganizerDialog
from ui.diagnostics_dialog import PreferencesDialog


def test_prefix_and_scope_conflicts():
    a = Command("one", "One", "Ctrl+K", "Test", lambda: None)
    b = Command("two", "Two", "Ctrl+K, Ctrl+S", "Test", lambda: None)
    assert shortcut_conflict(a.shortcut, b.shortcut)
    assert find_shortcut_conflict([a, b], {}) == (a, b)
    assert find_shortcut_conflict([a, replace(b, scope="organizer")], {}) is None


def test_restore_cannot_save_conflicting_shortcut(tmp_path):
    app = QApplication.instance() or QApplication([])
    commands = [Command("a", "A", "Ctrl+L", "Test", lambda: None, default_shortcut="Ctrl+K"),
                Command("b", "B", "Ctrl+K, Ctrl+S", "Test", lambda: None)]
    dialog = PreferencesDialog(SettingsManager(tmp_path / "settings.json"), commands=commands)
    dialog._shortcut_values["a"] = "Ctrl+K"
    dialog.accept()
    assert dialog.result() == 0
    assert "conflict" in dialog.shortcut_status.text().lower()
    dialog.reject()
    app.processEvents()


def test_organizer_custom_shortcut_and_input_focus(tmp_path):
    app = QApplication.instance() or QApplication([])
    from PyQt6.QtWidgets import QWidget
    parent = QWidget()
    parent.settings = SettingsManager(tmp_path / "settings.json")
    parent.settings.set_shortcut_overrides({"organizer.reverse": "Ctrl+Alt+R"})
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    dialog = VisualOrganizerDialog(doc, parent)
    try:
        dialog.show()
        app.processEvents()
        dialog.pages.select_positions([0, 1, 2])
        dialog.pages.setFocus()
        binding = next(s for s in dialog._scoped_shortcuts if s.key() == QKeySequence("Ctrl+Alt+R"))
        binding.activated.emit()
        assert dialog.pages.order() == [2, 1, 0]
        dialog.selection_input.setFocus()
        app.processEvents()
        binding.activated.emit()
        assert dialog.pages.order() == [2, 1, 0]
        QTest.keyClicks(dialog.selection_input, "1")
        QTest.keyClick(dialog.selection_input, Qt.Key.Key_Backspace)
    finally:
        dialog.reject()
        parent.close()
        doc.close()
