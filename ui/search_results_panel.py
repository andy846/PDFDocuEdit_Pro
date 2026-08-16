"""Live search results panel with debounced queries and page scoping.

The former "advanced search" dialog (page scope, match case, whole word) is
integrated here so Ctrl+F provides one complete search surface: scope the
search to all pages, the current page, or a custom range, type to search and
click a hit to jump to its page.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
)

from core.pdf_engine import SearchHit, parse_page_range
from styles.tokens import S

from .icons import icon

DEBOUNCE_MS = 300


class SearchResultsPanel(QFrame):
    """Non-modal search: type to search, click a hit to jump to its page."""

    jumpRequested = pyqtSignal(int, list)
    searchRequested = pyqtSignal(str, object)  # query, pages (list[int] | None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navSubPanel")
        self._hits: list[SearchHit] = []
        self._page_count = 0
        self._current_page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.SM, S.SM, S.SM, S.SM)
        layout.setSpacing(S.XS)

        self._query = QLineEdit()
        self._query.setObjectName("searchQuery")
        self._query.setPlaceholderText("Search document")
        self._query.setClearButtonEnabled(True)
        self._query.addAction(icon("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self._query.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._query)

        # --- page scope ---
        scope_row = QHBoxLayout()
        scope_row.setSpacing(S.XS)
        self._all_pages = QRadioButton("All")
        self._all_pages.setToolTip("Search every page")
        self._current_only = QRadioButton("Current page")
        self._current_only.setToolTip("Search only the current page")
        self._custom = QRadioButton("Custom")
        self._custom.setToolTip("Search a custom page range")
        self._all_pages.setChecked(True)
        for radio in (self._all_pages, self._current_only, self._custom):
            radio.toggled.connect(self._schedule)
            scope_row.addWidget(radio)
        scope_row.addStretch(1)
        layout.addLayout(scope_row)

        self._custom_pages = QLineEdit()
        self._custom_pages.setPlaceholderText("e.g. 1-5, 8")
        self._custom_pages.setEnabled(False)
        self._custom_pages.textChanged.connect(self._on_text_changed)
        self._custom.toggled.connect(self._custom_pages.setEnabled)
        layout.addWidget(self._custom_pages)

        # --- match options ---
        options = QHBoxLayout()
        options.setSpacing(S.SM)
        self._match_case = QCheckBox("Match case")
        self._whole_word = QCheckBox("Whole word")
        self._match_case.toggled.connect(self._schedule)
        self._whole_word.toggled.connect(self._schedule)
        options.addWidget(self._match_case)
        options.addWidget(self._whole_word)
        options.addStretch(1)
        layout.addLayout(options)

        self._list = QListWidget()
        self._list.setObjectName("navList")
        self._list.itemActivated.connect(self._on_activated)
        layout.addWidget(self._list, 1)

        self._status = QLabel("Type to search the document.")
        self._status.setObjectName("navEmpty")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_search)

    # --- document state ---------------------------------------------------
    def set_page_count(self, count: int) -> None:
        self._page_count = max(0, count)
        self._current_page = min(self._current_page, max(0, count - 1))
        self._refresh_current_label()

    def set_current_page(self, page: int) -> None:
        self._current_page = max(0, min(page, max(0, self._page_count - 1)))
        self._refresh_current_label()

    def _refresh_current_label(self) -> None:
        if self._page_count:
            self._current_only.setText(f"Current page ({self._current_page + 1})")
        else:
            self._current_only.setText("Current page")

    # --- query lifecycle ---------------------------------------------------
    def focus_query(self) -> None:
        self._query.setFocus()
        self._query.selectAll()

    def set_results(self, hits: list[SearchHit], total_matches: int) -> None:
        self._hits = hits
        self._list.clear()
        for hit in hits:
            count = len(hit.rects)
            item = QListWidgetItem(
                icon("search", 16),
                f"Page {hit.page + 1} · {count} match(es) · {hit.context}",
            )
            item.setToolTip(hit.context)
            item.setData(Qt.ItemDataRole.UserRole, hit.page)
            self._list.addItem(item)
        if hits:
            self._list.setCurrentRow(0)
        self._status.setText(f"Found {total_matches} match(es) on {len(hits)} page(s).")

    def show_searching(self) -> None:
        self._status.setText("Searching…")

    def show_error(self, message: str) -> None:
        self._status.setText(message)

    def clear(self) -> None:
        self._hits = []
        self._list.clear()
        self._status.setText("Type to search the document.")

    def reset_query(self) -> None:
        self._debounce.stop()
        self._query.blockSignals(True)
        self._query.clear()
        self._query.blockSignals(False)
        self.clear()

    def case_sensitive(self) -> bool:
        return self._match_case.isChecked()

    def whole_word(self) -> bool:
        return self._whole_word.isChecked()

    def _on_text_changed(self, _text: str) -> None:
        self._schedule()

    def _schedule(self) -> None:
        self._debounce.start()

    def _emit_search(self) -> None:
        query = self._query.text().strip()
        if not query:
            self.clear()
            return
        pages = None
        if self._current_only.isChecked():
            pages = [self._current_page] if self._page_count else []
        elif self._custom.isChecked():
            text = self._custom_pages.text().strip()
            if not text:
                self._status.setText("Enter the page range to search.")
                return
            try:
                pages = parse_page_range(text, self._page_count)
            except ValueError as exc:
                self._status.setText(str(exc))
                return
            if not pages:
                self._status.setText("Choose at least one valid page.")
                return
        self.searchRequested.emit(query, pages)

    def _on_activated(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is None:
            return
        page = int(page)
        rects = []
        for hit in self._hits:
            if hit.page == page:
                rects = list(hit.rects)
                break
        self.jumpRequested.emit(page, rects)
