"""Spotlight-style command palette (Ctrl+K)."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from core.commands import Command, filter_commands
from styles.theme import get_colors
from styles.tokens import D, F, S

from .icons import icon


class CommandPalette(QDialog):
    """Frameless popup that filters and runs registered commands."""

    commandTriggered = pyqtSignal(str)

    def __init__(self, commands: list[Command], parent=None):
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.setFixedSize(min(540, area.width() - 32), min(420, area.height() - 32))
        else:
            self.setFixedSize(540, 420)
        self._commands = list(commands)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.XS, S.XS, S.XS, S.XS)
        layout.setSpacing(0)

        self._input = QLineEdit()
        self._input.setObjectName("paletteInput")
        self._input.setPlaceholderText("Type a command name or shortcut…")
        self._input.textChanged.connect(self._refresh)
        self._input.returnPressed.connect(self._activate_current)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        self._list = QTreeWidget()
        self._list.setObjectName("paletteList")
        self._list.setHeaderHidden(True)
        self._list.setColumnCount(2)
        self._list.setRootIsDecorated(False)
        self._list.setUniformRowHeights(True)
        self._list.itemActivated.connect(self._activate_item)
        layout.addWidget(self._list, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(S.MD, S.XS, S.MD, S.MD)
        hint = QLabel("↑↓ Select   Enter Run   Esc Close")
        hint.setObjectName("paletteShortcut")
        footer.addWidget(hint)
        footer.addStretch(1)
        layout.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.reject)
        self._refresh("")

    def eventFilter(self, obj, event) -> bool:
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
        return super().eventFilter(obj, event)

    def _refresh(self, query: str) -> None:
        colors = get_colors()
        self._list.clear()
        commands = filter_commands(self._commands, query)
        current_section = None
        for command in commands:
            if command.section != current_section:
                current_section = command.section
                header = QTreeWidgetItem(self._list, [command.section, ""])
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setFirstColumnSpanned(True)
                header.setForeground(0, QColor(colors["text_secondary"]))
                header.setFont(0, QFont(header.font(0).family(), F.XS, F.SEMIBOLD))
            item = QTreeWidgetItem(self._list, [command.label, command.shortcut])
            item.setData(0, Qt.ItemDataRole.UserRole, command.id)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(1, QColor(colors["text_secondary"]))
            item.setIcon(0, icon("command", D.ICON_SM))
            if not command.is_enabled():
                item.setForeground(0, QColor(colors["text_disabled"]))
                item.setForeground(1, QColor(colors["text_disabled"]))
                item.setToolTip(0, "This command is currently unavailable")
                # A disabled command must also be non-selectable and
                # non-runnable, not just greyed out.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        if self._list.topLevelItemCount():
            self._list.setCurrentItem(self._first_selectable())

    def _first_selectable(self) -> QTreeWidgetItem | None:
        for index in range(self._list.topLevelItemCount()):
            item = self._list.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                return item
        return None

    def _move_selection(self, step: int) -> None:
        if self._list.topLevelItemCount() == 0:
            return
        items = [
            item
            for index in range(self._list.topLevelItemCount())
            if (item := self._list.topLevelItem(index)).flags() & Qt.ItemFlag.ItemIsEnabled
        ]
        if not items:
            return
        current = self._list.currentItem()
        if current is None:
            self._list.setCurrentItem(items[0])
            return
        try:
            position = items.index(current)
        except ValueError:
            self._list.setCurrentItem(items[0])
            return
        target = max(0, min(len(items) - 1, position + step))
        self._list.setCurrentItem(items[target])

    def refresh(self) -> None:
        """Re-evaluate enablement after the document state changed."""
        self._refresh(self._input.text())

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._activate_item(item, 0)

    def _activate_item(self, item: QTreeWidgetItem, _column: int) -> None:
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        command_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not command_id:
            return
        self.commandTriggered.emit(str(command_id))
        self.accept()
