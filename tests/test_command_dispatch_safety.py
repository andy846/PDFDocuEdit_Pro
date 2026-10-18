"""Execution-time command admission; no registry or shortcut redesign."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import Qt

from core.commands import Command
from core.viewer import PDFViewer
from ui.command_palette import CommandPalette
from ui.infobar import InfoBar


def owner_for(commands):
    messages = []
    owner = SimpleNamespace(
        _commands_for_mode=lambda: commands,
        info_bar=SimpleNamespace(show_message=lambda *args: messages.append(args)),
    )
    return owner, messages


def test_enabled_command_executes_against_current_registry():
    calls = []
    current = [Command("save", "Save", "", "File", lambda: calls.append("old"))]
    owner, messages = owner_for(current)
    current[:] = [Command("save", "Save", "", "File", lambda: calls.append("current"))]
    PDFViewer._run_command(owner, "save")
    assert calls == ["current"] and not messages


@pytest.mark.parametrize("change", ["disabled", "document_closed", "mode_changed", "missing"])
def test_disabled_or_stale_selection_never_invokes_handler(change):
    calls = []
    context = {"loaded": True}
    commands = [
        Command(
            "pdf.extract",
            "Extract",
            "",
            "Pages",
            lambda: calls.append("unsafe"),
            enabled=lambda: context["loaded"],
        )
    ]
    owner, messages = owner_for(commands)
    if change in ("disabled", "document_closed"):
        context["loaded"] = False
    elif change == "mode_changed":
        commands[:] = [
            Command("designer.extract", "Extract", "", "Designer", lambda: calls.append("wrong mode"))
        ]
    else:
        commands.clear()
    PDFViewer._run_command(owner, "pdf.extract")
    assert calls == []
    assert messages


def test_availability_exception_fails_closed_and_is_diagnosed(caplog):
    calls = []

    def broken():
        raise RuntimeError("private field value must not be logged")

    owner, messages = owner_for(
        [Command("save", "Save", "", "File", lambda: calls.append("unsafe"), enabled=broken)]
    )
    PDFViewer._run_command(owner, "save")
    assert calls == [] and messages
    assert "Command availability check failed" in caplog.text
    assert "private field value must not be logged" not in caplog.text


def test_registry_failure_fails_closed(caplog):
    owner, messages = owner_for([])

    def broken():
        raise RuntimeError("registry unavailable")

    owner._commands_for_mode = broken
    PDFViewer._run_command(owner, "save")
    assert messages and "Command availability check failed" in caplog.text


def test_handler_programming_errors_are_not_suppressed():
    def broken():
        raise ValueError("handler bug")

    owner, _ = owner_for([Command("open", "Open", "", "File", broken)])
    with pytest.raises(ValueError, match="handler bug"):
        PDFViewer._run_command(owner, "open")


def test_palette_cached_enabled_row_is_rechecked_on_activation(qt_application):
    calls, state = [], {"enabled": True}
    commands = [
        Command("save", "Save", "", "File", lambda: calls.append("unsafe"), enabled=lambda: state["enabled"])
    ]
    bar = InfoBar()
    owner = SimpleNamespace(_commands_for_mode=lambda: commands, info_bar=bar)
    palette = CommandPalette(commands)
    palette.commandTriggered.connect(lambda key: PDFViewer._run_command(owner, key))
    try:
        item = next(
            palette._list.topLevelItem(i)
            for i in range(palette._list.topLevelItemCount())
            if palette._list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == "save"
        )
        state["enabled"] = False
        palette._activate_item(item, 0)
        assert calls == []
        assert bar._message.text()
    finally:
        palette.close()
        bar.close()
        bar.deleteLater()
