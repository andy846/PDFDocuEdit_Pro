"""Undo/redo history browser that can jump to any snapshot."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
)

from styles.theme import get_colors

from .base import ToolDialog


class UndoHistoryDialog(ToolDialog):
    undoToRequested = pyqtSignal(int)
    redoToRequested = pyqtSignal(int)

    def __init__(
        self,
        undo_descriptions: list[str],
        redo_descriptions: list[str],
        parent=None,
    ):
        super().__init__("Undo History", "undo-history", parent)
        self.setMinimumSize(480, 460)
        self._undo_descriptions = list(undo_descriptions)
        self._redo_descriptions = list(redo_descriptions)

        description = QLabel(
            "Choose a state, then press Jump to State (or double-click an entry)."
        )
        description.setObjectName("secondary")
        self._root.addWidget(description)

        self._list = QListWidget()
        self._list.itemActivated.connect(self._on_activated)
        self._root.addWidget(self._list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._jump = buttons.addButton(
            "Jump to State", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._jump.clicked.connect(self._jump_to_current)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self._build()

    def _build(self) -> None:
        colors = get_colors()
        self._list.clear()
        if not self._undo_descriptions and not self._redo_descriptions:
            empty = QListWidgetItem("No undo history")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            return

        # Timeline: undo states (newest first) above the current marker,
        # redo states below it.
        for index, description in enumerate(reversed(self._undo_descriptions)):
            item = QListWidgetItem(f"Undo: {description}")
            item.setData(Qt.ItemDataRole.UserRole, index + 1)
            self._list.addItem(item)

        marker = QListWidgetItem("— Current state —")
        marker.setFlags(Qt.ItemFlag.NoItemFlags)
        marker.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        marker.setForeground(QColor(colors["primary"]))
        self._list.addItem(marker)

        for index, description in enumerate(self._redo_descriptions):
            item = QListWidgetItem(f"Redo: {description}")
            item.setData(Qt.ItemDataRole.UserRole, index + 1)
            item.setForeground(QColor(colors["text_secondary"]))
            self._list.addItem(item)

        self._list.setCurrentRow(0)

    def _jump_to_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._on_activated(item)

    def _on_activated(self, item: QListWidgetItem) -> None:
        steps = item.data(Qt.ItemDataRole.UserRole)
        if steps is None:
            return
        if item.text().startswith("Undo:"):
            self.undoToRequested.emit(int(steps))
        elif item.text().startswith("Redo:"):
            self.redoToRequested.emit(int(steps))
        self.accept()
