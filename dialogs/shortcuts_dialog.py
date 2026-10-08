"""Keyboard shortcut reference dialog generated from the command registry."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
)

from core.commands import Command, command_shortcuts, filter_commands

from .base import SortableTableWidget, ToolDialog


class ShortcutsDialog(ToolDialog):
    def __init__(self, commands: list[Command], parent=None):
        super().__init__("Keyboard Shortcuts", "shortcuts", parent)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            target_width = min(
                area.width() - 24,
                max(self.width(), min(1180, round(area.width() * 0.9))),
            )
            target_height = min(
                area.height() - 24,
                max(self.height(), min(840, round(area.height() * 0.9))),
            )
            self.setMinimumSize(
                min(840, target_width),
                min(600, target_height),
            )
            self.resize(target_width, target_height)
        else:
            self.setMinimumSize(840, 600)
            self.resize(1100, 780)
        self._commands = list(commands)
        note = QLabel("Shortcuts for the current workspace. Text fields keep their own editing keys. "
                      "Save and application commands remain available while typing. "
                      "Commands without a shortcut can be opened from menus or the command palette.")
        note.setWordWrap(True)
        self._root.addWidget(note)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter commands or shortcuts")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._refresh)
        self._root.addWidget(self._filter)

        self.table = SortableTableWidget(0, 3)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setHorizontalHeaderLabels(["Command", "Shortcut", "Section"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self._refresh("")

    def _refresh(self, query: str) -> None:
        self.table.setRowCount(0)
        commands = sorted(
            filter_commands(self._commands, query),
            key=lambda command: (command.section, command.label),
        )
        for row, command in enumerate(commands):
            self.table.insertRow(row)
            label = QTableWidgetItem(command.label)
            label.setData(Qt.ItemDataRole.UserRole, command.id)
            self.table.setItem(row, 0, label)
            bindings = command_shortcuts(command)
            self.table.setItem(row, 1, QTableWidgetItem(" / ".join(bindings) if bindings else "Not assigned"))
            self.table.setItem(row, 2, QTableWidgetItem(command.section))
