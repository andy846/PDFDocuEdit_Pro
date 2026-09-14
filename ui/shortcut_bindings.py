"""Scoped command bindings shared by the viewer and modal tools."""
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from core.commands import Command


def editing_focused():
    widget = QApplication.focusWidget()
    while widget is not None:
        if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox)):
            return True
        widget = widget.parentWidget()
    return False


class CommandAction(QAction):
    def event(self, event):
        if event.type() == QEvent.Type.Shortcut and editing_focused():
            return True
        return super().event(event)


ORGANIZER_COMMANDS = (
    ("reverse", "Reverse", ""), ("duplicate", "Duplicate", ""), ("delete", "Delete", "Delete"),
    ("rotate_left", "Rotate left", ""), ("rotate_right", "Rotate right", ""), ("crop", "Crop", ""),
    ("insert", "Insert", ""), ("blank", "Blank pages", ""), ("replace", "Replace", ""),
    ("interleave", "Interleave", ""), ("extract", "Extract", ""), ("split", "Split", ""),
    ("apply", "Apply Page Plan", ""),
    ("undo", "Undo plan", "Ctrl+Z"), ("redo", "Redo plan", "Ctrl+Y"), ("restore", "Restore", ""),
    ("all", "All", "Ctrl+A"), ("odd", "Odd", ""), ("even", "Even", ""),
    ("every", "Every N", ""), ("last", "Last N", ""), ("invert", "Invert", ""), ("clear", "Clear", ""),
)


def organizer_commands(overrides):
    return [Command("organizer." + key, label, overrides.get("organizer." + key, default),
                    "Organizer", lambda: None, enabled=lambda: False, default_shortcut=default, scope="organizer")
            for key, label, default in ORGANIZER_COMMANDS]


def bind_organizer(dialog, buttons, overrides):
    dialog._scoped_shortcuts = []
    dialog.pages._command_selection_bound = True
    for command in organizer_commands(overrides):
        button = buttons.get(command.label)
        if button is None:
            continue
        button.setProperty("commandId", command.id)
        sequence = QKeySequence(command.shortcut)
        if sequence.isEmpty():
            continue
        button.setToolTip(f"{command.label} ({sequence.toString()})")
        shortcut = QShortcut(sequence, dialog)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda b=button: b.click() if b.isEnabled() and not editing_focused() else None)
        dialog._scoped_shortcuts.append(shortcut)


DIALOG_COMMANDS = (
    ("form.preview", "Update form preview", "form"),
    ("form.reset", "Discard staged form values", "form"),
    ("form.apply", "Apply form values", "form"),
    ("compare.refresh", "Compare / Refresh", "compare"),
    ("compare.previous", "Previous difference", "compare"),
    ("compare.next", "Next difference", "compare"),
    ("compare.pair", "Pair pages", "compare"),
    ("compare.unpair", "Unpair pages", "compare"),
)


def dialog_commands(overrides):
    return [Command(key, label, overrides.get(key, ""), scope.title(), lambda: None,
                    enabled=lambda: False, scope=scope) for key, label, scope in DIALOG_COMMANDS]


def bind_dialog_commands(dialog, buttons):
    owner = dialog.parent()
    settings = getattr(owner, "settings", None)
    overrides = settings.get_shortcut_overrides() if settings is not None else {}
    for shortcut in getattr(dialog, "_command_shortcuts", []):
        shortcut.setEnabled(False)
        shortcut.deleteLater()
    dialog._command_shortcuts = []
    for command in dialog_commands(overrides):
        button = buttons.get(command.id)
        if button is None:
            continue
        button.setProperty("commandId", command.id)
        button.setToolTip(command.label)
        if command.shortcut:
            button.setToolTip(f"{command.label} ({command.shortcut})")
            shortcut = QShortcut(QKeySequence(command.shortcut), dialog)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda b=button: b.click() if b.isEnabled() and not editing_focused() else None)
            dialog._command_shortcuts.append(shortcut)
