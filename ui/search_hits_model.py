"""Paged Qt model for occurrence-level Deep Search results."""

from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.deep_search import SearchHit
from core.search_results_store import SearchResultsStore

_ROOT_INDEX = QModelIndex()


class SearchHitsModel(QAbstractTableModel):
    HEADERS = ("File", "Page", "Keyword", "Source", "Context")
    ORDERS = ("filename COLLATE NOCASE, page, position, id", "page, position, id",
              "keyword COLLATE NOCASE, path, page, position, id",
              "source, path, page, position, id",
              "context COLLATE NOCASE, path, page, position, id")

    def __init__(self, store: SearchResultsStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.paths: tuple[str, ...] | None = None
        self.keyword = ""
        self.source = ""
        self.order = self.ORDERS[0]
        self._rows: list[SearchHit] = []
        self.total = 0

    def configure(self, paths: tuple[str, ...] | None = None,
                  keyword: str = "", source: str = "") -> None:
        self.beginResetModel()
        self.paths, self.keyword, self.source = paths, keyword, source
        self._rows.clear()
        self.total = self.store.hit_count(paths, keyword, source)
        self.endResetModel()
        self.fetchMore()

    def rowCount(self, parent=_ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=_ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        hit = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (hit.filename, hit.page, hit.keyword, hit.source.title(),
                    hit.context)[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return hit.path if index.column() == 0 else hit.context
        if role == Qt.ItemDataRole.UserRole:
            return hit
        return None

    def hit(self, row: int) -> SearchHit | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def canFetchMore(self, parent=_ROOT_INDEX) -> bool:
        return not parent.isValid() and len(self._rows) < self.total

    def fetchMore(self, parent=_ROOT_INDEX) -> None:
        if parent.isValid() or not self.canFetchMore(parent):
            return
        rows = self.store.hit_page(len(self._rows), 200, self.paths,
                                   self.keyword, self.source, self.order)
        if not rows:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self._rows.extend(rows)
        self.endInsertRows()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self.ORDERS):
            return
        self.order = self.ORDERS[column]
        if order == Qt.SortOrder.DescendingOrder:
            self.order = ", ".join(
                item.strip() + " DESC" for item in self.order.split(",")
            )
        self.configure(self.paths, self.keyword, self.source)
