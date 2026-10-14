"""Paged Qt model for occurrence-level Deep Search results."""

from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from core.deep_search import SearchHit
from core.search_results_store import SearchResultsStore

_ROOT_INDEX = QModelIndex()


class SearchHitsModel(QAbstractTableModel):
    viewRestored = pyqtSignal(int)

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
        self.loader = None
        self.generation = 0
        self.cutoff = None
        self.cache = OrderedDict()
        self.pending_pages = set()
        self.selected_hit = None
        self.header_pending = False
        self.selection_revision = 0
        self.selected_row = -1
        self.view_query = None
        self.resetting = False

    def configure(self, paths: tuple[str, ...] | None = None,
                  keyword: str = "", source: str = "") -> None:
        if self.loader is not None:
            self.paths, self.keyword, self.source = paths, keyword, source
            self.refresh()
            return
        self.beginResetModel()
        self.paths, self.keyword, self.source = paths, keyword, source
        self._rows.clear()
        self.total = self.store.hit_count(paths, keyword, source)
        self.endResetModel()
        self.fetchMore()

    def rowCount(self, parent=_ROOT_INDEX) -> int:
        return 0 if parent.isValid() else (self.total if self.loader is not None else len(self._rows))

    def columnCount(self, parent=_ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self.rowCount():
            return None
        hit = self.hit(index.row())
        if hit is None:
            return "Loading…" if role == Qt.ItemDataRole.DisplayRole and index.column() == 0 else None
        if role == Qt.ItemDataRole.DisplayRole:
            return (hit.filename, hit.page, hit.keyword, hit.source.title(),
                    hit.context)[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return hit.path if index.column() == 0 else hit.context
        if role == Qt.ItemDataRole.UserRole:
            return hit
        return None

    def hit(self, row: int) -> SearchHit | None:
        if self.loader is None:
            return self._rows[row] if 0 <= row < len(self._rows) else None
        if not 0 <= row < self.total:
            return None
        offset = row // 200 * 200
        if offset in self.cache:
            rows = self.cache[offset]
            self.cache.move_to_end(offset)
            return rows[row - offset] if row - offset < len(rows) else None
        if (not self.header_pending and offset not in self.pending_pages
                and self.cutoff is not None):
            self.pending_pages.add(offset)
            self.loader(self._request("page", offset))
        return None

    def clear(self):
        self.beginResetModel()
        self.generation += 1
        self.cache.clear()
        self.pending_pages.clear()
        self.selected_hit = None
        self.selected_row = -1
        self.selection_revision += 1
        self.view_query = None
        self.total = 0
        self.cutoff = None
        self.header_pending = False
        self._rows.clear()
        self.endResetModel()

    def set_async_loader(self, loader):
        self.loader = loader

    def choose_row(self, row):
        if self.resetting:
            return
        if row != self.selected_row:
            self.selection_revision += 1
            self.selected_row = row
        self.selected_hit = self.hit(row)

    def _request(self, kind, offset=0):
        reference = None
        if self.selected_hit is None and self.selected_row >= 0 and self.view_query is not None:
            reference = {**self.view_query, "offset": self.selected_row}
        return {"kind": kind, "generation": self.generation, "paths": self.paths,
                "keyword": self.keyword, "source": self.source, "order": self.order,
                "offset": offset, "cutoff": self.cutoff, "selected": self.selected_hit,
                "selection_revision": self.selection_revision, "selected_ref": reference}

    def refresh(self):
        self.header_pending = True
        self.generation += 1
        self.pending_pages.clear()
        self.loader(self._request("header"))

    def discard_query(self, request):
        if request["generation"] != self.generation:
            return
        if request["kind"] == "page":
            self.pending_pages.discard(request["offset"])
        elif request["kind"] == "header":
            self.header_pending = False

    def apply_query(self, result):
        if result["generation"] != self.generation:
            return
        if result["kind"] == "header":
            if (result.get("selection_revision", 0) != self.selection_revision
                    or (result.get("selected_ref") is None and result.get("selected") != self.selected_hit)):
                self.refresh()
                return
            self.header_pending = False
            self.resetting = True
            self.beginResetModel()
            self.total, self.cutoff = result["total"], result["cutoff"]
            self.cache.clear()
            self.cache[0] = result["rows"]
            selected = result.get("selected_row")
            self.selected_hit = result.get("selected") if selected is not None else None
            self.selected_row = -1 if selected is None else selected
            self.view_query = {key: result[key] for key in ("paths", "keyword", "source", "order", "cutoff")}
            self.endResetModel()
            self.resetting = False
            self.viewRestored.emit(-1 if selected is None else selected)
        else:
            if result["cutoff"] != self.cutoff:
                return
            offset = result["offset"]
            self.pending_pages.discard(offset)
            self.cache[offset] = result["rows"]
            while len(self.cache) > 10:
                self.cache.popitem(last=False)
            if result["rows"]:
                self.dataChanged.emit(self.index(offset, 0),
                                      self.index(offset + len(result["rows"]) - 1, 4))


    def canFetchMore(self, parent=_ROOT_INDEX) -> bool:
        return self.loader is None and not parent.isValid() and len(self._rows) < self.total

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
