"""Keyboard shortcut reference dialog generated from the command registry."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QHeaderView, QLineEdit, QTableWidgetItem

from core.commands import Command, filter_commands

from .base import SortableTableWidget, ToolDialog


class ShortcutsDialog(ToolDialog):
    def __init__(self, commands: list[Command], parent=None):
        super().__init__("Keyboard Shortcuts", "shortcuts", parent)
        self.setMinimumSize(560, 520)
        self._commands = list(commands)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter commands or shortcuts")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._refresh)
        self._root.addWidget(self._filter)

        self.table = SortableTableWidget(0, 3)
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
            self.table.setItem(row, 1, QTableWidgetItem(command.shortcut))
            self.table.setItem(row, 2, QTableWidgetItem(command.section))
