from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from core.commands import Command
from core.settings import SettingsManager
from ui.diagnostics_dialog import PreferencesDialog

_app_instance: QApplication | None = None


def _app() -> QApplication:
    global _app_instance
    if _app_instance is None:
        _app_instance = QApplication.instance() or QApplication(
            ["pdfdocuedit-shortcut-test"]
        )
    return _app_instance


def _commands() -> list[Command]:
    return [
        Command(
            "open",
            "Open",
            "Ctrl+O",
            "File",
            lambda: None,
            default_shortcut="Ctrl+O",
        ),
        Command(
            "save",
            "Save",
            "Ctrl+S",
            "File",
            lambda: None,
            default_shortcut="Ctrl+S",
        ),
    ]


def test_preferences_assigns_persists_and_restores_shortcut(tmp_path: Path) -> None:
    _app()
    settings = SettingsManager(tmp_path / "settings.json")
    dialog = PreferencesDialog(settings, commands=_commands())
    assert dialog.width() >= 960
    assert dialog.height() >= 800

    for row in range(dialog.shortcut_table.rowCount()):
        item = dialog.shortcut_table.item(row, 0)
        if item.text() == "Open":
            dialog.shortcut_table.selectRow(row)
            break
    dialog.shortcut_editor.setKeySequence(QKeySequence("Ctrl+Alt+O"))
    assert dialog._assign_shortcut()
    dialog.accept()

    assert settings.get_shortcut_overrides() == {"open": "Ctrl+Alt+O"}

    restored = PreferencesDialog(
        settings,
        commands=[
            Command(
                "open",
                "Open",
                "Ctrl+Alt+O",
                "File",
                lambda: None,
                default_shortcut="Ctrl+O",
            ),
            Command(
                "save",
                "Save",
                "Ctrl+S",
                "File",
                lambda: None,
                default_shortcut="Ctrl+S",
            ),
        ],
    )
    for row in range(restored.shortcut_table.rowCount()):
        if restored.shortcut_table.item(row, 0).text() == "Open":
            restored.shortcut_table.selectRow(row)
            break
    restored._restore_shortcut()
    assert restored.shortcut_overrides() == {}


def test_preferences_rejects_duplicate_shortcuts(tmp_path: Path) -> None:
    _app()
    dialog = PreferencesDialog(
        SettingsManager(tmp_path / "settings.json"),
        commands=_commands(),
    )
    for row in range(dialog.shortcut_table.rowCount()):
        if dialog.shortcut_table.item(row, 0).text() == "Open":
            dialog.shortcut_table.selectRow(row)
            break
    dialog.shortcut_editor.setKeySequence(QKeySequence("Ctrl+S"))

    assert not dialog._assign_shortcut()
    assert "Save" in dialog.shortcut_status.text()
    assert dialog.shortcut_overrides() == {}


def test_viewer_applies_menu_side_panel_and_legacy_shortcut_overrides(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    settings = SettingsManager(tmp_path / "settings.json")
    settings.set_shortcut_overrides(
        {
            "rotate": "Ctrl+Alt+6",
            "rotate_left": "Ctrl+Alt+L",
            "quick_delete": "",
        }
    )
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)

    window = viewer_module.PDFViewer()
    portable = QKeySequence.SequenceFormat.PortableText
    commands = {command.id: command for command in window._commands}

    assert commands["rotate"].shortcut == "Ctrl+Alt+6"
    assert commands["rotate"].default_shortcut == "F6"
    assert window.rotate_action.shortcut().toString(portable) == "Ctrl+Alt+6"
    assert "Ctrl+Alt+6" in window.side_panel._buttons["rotate"].toolTip()
    assert window._shortcut_rotate_left.key().toString(portable) == "Ctrl+Alt+L"
    assert window._shortcut_delete is None
    quit_action = next(
        action
        for action in window._registered_shortcut_actions
        if action.property("shortcutBaseLabel") == "Quit"
    )
    assert quit_action.shortcut().toString(portable) == "Ctrl+Q"
    window.close()
