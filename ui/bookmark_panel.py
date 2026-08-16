"""Per-document bookmark navigation panel."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from styles.tokens import D, S

from .icons import icon
from .motion import MotionIconButton


class BookmarkPanel(QFrame):
    """List of saved bookmarks; supports jump, add (current page) and remove."""

    jumpRequested = pyqtSignal(int)
    addRequested = pyqtSignal()
    removeRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navSubPanel")
        self._bookmarks: list[dict] = []
        self._current_page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.SM, S.SM, S.SM, S.SM)
        layout.setSpacing(S.XS)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(S.XS)
        self._add = MotionIconButton("bookmark-plus", "Add bookmark for the current page (Ctrl+D)", D.ICON_SM)
        self._add.clicked.connect(self.addRequested.emit)
        self._remove = MotionIconButton("trash", "Remove selected bookmark", D.ICON_SM)
        self._remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(self._add)
        toolbar.addWidget(self._remove)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._list = QListWidget()
        self._list.setObjectName("navList")
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemSelectionChanged.connect(self._update_remove_enabled)
        layout.addWidget(self._list, 1)

        self._empty = QLabel("No bookmarks yet. Press + to bookmark the current page.")
        self._empty.setObjectName("navEmpty")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._update_remove_enabled()

    def load_bookmarks(self, items: list[dict]) -> None:
        self._bookmarks = items
        self._list.clear()
        for index, item in enumerate(items):
            page = int(item.get("page", 0))
            title = str(item.get("title", "")).strip() or f"Page {page + 1}"
            entry = QListWidgetItem(icon("bookmark", D.ICON_SM), f"Page {page + 1} · {title}")
            entry.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(entry)
        self._empty.setVisible(not items)
        self._update_remove_enabled()

    def clear(self) -> None:
        self._bookmarks = []
        self._list.clear()
        self._empty.show()
        self._update_remove_enabled()

    def set_current_page(self, page: int) -> None:
        self._current_page = max(0, page)

    def set_animations_enabled(self, enabled: bool) -> None:
        self._add.set_animations_enabled(enabled)
        self._remove.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        self._add.refresh_icon()
        self._remove.refresh_icon()

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self.removeRequested.emit(row)

    def _on_activated(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and 0 <= index < len(self._bookmarks):
            self.jumpRequested.emit(int(self._bookmarks[index].get("page", 0)))

    def _update_remove_enabled(self) -> None:
        self._remove.setEnabled(self._list.currentRow() >= 0)
