"""Document outline (table of contents) navigation panel."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from styles.tokens import S

from .icons import icon


def toc_to_zero_based(toc: list[tuple[int, str, int]]) -> list[tuple[int, str, int]]:
    """Convert a fitz TOC (one-based pages) into zero-based page indexes."""
    converted: list[tuple[int, str, int]] = []
    for level, title, page in toc:
        converted.append((max(1, int(level)), str(title), max(0, int(page) - 1)))
    return converted


class OutlinePanel(QFrame):
    """Tree view of the document outline; clicking a node jumps to its page."""

    jumpRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navSubPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.SM, S.SM, S.SM, S.SM)
        layout.setSpacing(S.SM)

        self._tree = QTreeWidget()
        self._tree.setObjectName("outlineTree")
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

        self._empty = QLabel("This document has no outline")
        self._empty.setObjectName("navEmpty")
        self._empty.setWordWrap(True)
        self._empty.hide()
        layout.addWidget(self._empty)

    def load_toc(self, toc: list[tuple[int, str, int]]) -> None:
        self._tree.clear()
        converted = toc_to_zero_based(toc)
        if not converted:
            self._empty.show()
            self._tree.hide()
            return
        self._empty.hide()
        self._tree.show()
        parents: dict[int, QTreeWidgetItem] = {}
        for level, title, page in converted:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page)
            item.setIcon(0, icon("file-text", 14))
            if level <= 1 or not parents:
                self._tree.addTopLevelItem(item)
            else:
                parent = parents.get(level - 1)
                if parent is None:
                    self._tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
            parents[level] = item

    def clear(self) -> None:
        self._tree.clear()
        self._empty.show()
        self._tree.hide()

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.jumpRequested.emit(int(page))
