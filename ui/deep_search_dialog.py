"""Deep Search dialog with file summaries, paged occurrences, and reports."""

from __future__ import annotations

import html
import re
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableView,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
)

from core.deep_search import SearchBatch, SearchFile, SearchHit, SearchIssue, search_folder_detailed
from core.diagnostics import log_failure
from core.search_report import ReportMeta, export_html, export_report, export_text
from core.search_results_store import SearchResultsStore
from core.tasks import FunctionTask
from dialogs.base import SortableTableWidget, ToolDialog, remember_save_directory, start_in_save_directory
from styles.theme import get_color, get_colors
from ui.search_hits_model import SearchHitsModel

OPEN_NEW_TAB = "new_tab"
OPEN_CURRENT = "current"
OPEN_SYSTEM = "system"

_RESULT_INDEX_ROLE = Qt.ItemDataRole.UserRole + 1


class DeepSearchDialog(ToolDialog):
    """Non-modal folder-wide PDF search with preview and error tabs."""

    openRequested = pyqtSignal(str, str)  # file path, open method
    hitOpenRequested = pyqtSignal(str, str, int)  # path, method, one-based page

    def __init__(self, initial_folder: str, parent=None):
        super().__init__("Deep Search PDFs", "deep_search", parent)
        # Work alongside the main window and release itself when closed.
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Legacy sizing: ~80% of the screen, never smaller than the compact
        # layout that fits every column without clipping.
        self.resize(920, 620)
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(
                max(920, int(area.width() * 0.8)),
                max(620, int(area.height() * 0.8)),
            )
        self.setMinimumWidth(700)
        self._results: list[dict[str, object]] = []  # matches, aligned with table rows
        self._errors: list[dict[str, object]] = []  # failures, aligned with error rows
        self._task: FunctionTask | None = None
        self._export_task: FunctionTask | None = None
        self._pool = QThreadPool.globalInstance()
        self._search_started_at = 0.0
        self._processed_files = 0
        self._total_files = 0
        self._store = SearchResultsStore()
        self._hits_model = SearchHitsModel(self._store, self)
        self._run_completed = False
        self._search_error = False
        self._run_elapsed = 0.0
        self._searched_at = ""
        self._selected_file_path: str | None = None
        self._run_query = ""
        self._run_folder = initial_folder
        self._run_subfolders = True
        self._run_barcodes = False
        self._refresh_scheduled = False

        # --- folder row ---
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("PDF Folder:"))
        self.folder = QLineEdit(initial_folder)
        self.folder.setMinimumWidth(320)
        self.folder.setToolTip(initial_folder)
        self.folder.setClearButtonEnabled(True)
        self.folder.textChanged.connect(self._show_path_tail)
        browse = QPushButton("Browse…")
        browse.setToolTip("Choose a folder containing PDF files to search")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        self._root.addLayout(folder_row)

        # --- search row (the primary action) ---
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setObjectName("deepSearchQuery")
        self.query.setPlaceholderText("Search text — separate multiple keywords with commas")
        self.query.setClearButtonEnabled(True)
        self.query.setToolTip("Search keywords, separated by commas")
        self.query.returnPressed.connect(self._search)
        self.search_button = QPushButton("Search")
        self.search_button.setProperty("primary", True)
        self.search_button.clicked.connect(self._search)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.cancel_button)
        self._root.addLayout(search_row)

        # --- options row ---
        options_row = QHBoxLayout()
        self.subfolders = QCheckBox("Include Subfolder")
        self.subfolders.setChecked(True)
        self.subfolders.setToolTip("Recursively search subdirectories for PDF files")
        self.barcodes = QCheckBox("Include barcode content")
        self.barcodes.setChecked(False)
        self.barcodes.setToolTip(
            "Scan barcodes and QR codes on every page and match their content.\n"
            "This significantly slows down the search."
        )
        self.open_option = QComboBox()
        self.open_option.addItem("Open in new window", OPEN_NEW_TAB)
        self.open_option.addItem("Open in current window", OPEN_CURRENT)
        self.open_option.addItem("Open with system default application", OPEN_SYSTEM)
        self.open_option.setToolTip("How a result document is opened")
        options_row.addWidget(self.subfolders)
        options_row.addWidget(self.barcodes)
        options_row.addStretch(1)
        options_row.addWidget(QLabel("Open:"))
        options_row.addWidget(self.open_option)
        self._root.addLayout(options_row)

        # --- status row ---
        status_row = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setObjectName("secondary")
        self.current_file = QLabel("")
        self.current_file.setObjectName("deepSearchCurrentFile")
        self.progress = QProgressBar()
        self.progress.setObjectName("deepSearchProgress")
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(160)
        self.progress.setToolTip("Search progress")
        status_row.addWidget(self.status, 2)
        status_row.addWidget(self.current_file, 1)
        status_row.addWidget(self.progress)
        self._root.addLayout(status_row)

        # --- tabs: results / preview / errors ---
        self.tabs = QTabWidget()
        self.table = SortableTableWidget(0, 4)
        self.table.setObjectName("deepSearchResultsTable")
        self._setup_result_table()
        self.tabs.addTab(self.table, "Search Result")
        self.hits_table = QTableView()
        self.hits_table.setObjectName("deepSearchMatchesTable")
        self.hits_table.setModel(self._hits_model)
        self.hits_table.setSortingEnabled(True)
        self.hits_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.hits_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.hits_table.setWordWrap(False)
        self.hits_table.setColumnWidth(0, 180)
        self.hits_table.setColumnWidth(1, 65)
        self.hits_table.setColumnWidth(2, 130)
        self.hits_table.setColumnWidth(3, 90)
        self.hits_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.hits_table, "Matches")
        self.preview = QTextEdit()
        self.preview.setObjectName("deepSearchPreview")
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, "Preview")
        self.error_table = SortableTableWidget(0, 2)
        self.error_table.setObjectName("deepSearchErrorTable")
        self._setup_error_table()
        self.tabs.addTab(self.error_table, "Error Message")
        self._root.addWidget(self.tabs, 1)

        filter_row = QHBoxLayout()
        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Filter files by name or path")
        self.file_filter.textChanged.connect(self._refresh_filters)
        self.keyword_filter = QComboBox()
        self.keyword_filter.addItem("All keywords", "")
        self.keyword_filter.currentIndexChanged.connect(self._refresh_filters)
        self.source_filter = QComboBox()
        for label, value in (("All sources", ""), ("Text", "text"), ("Barcode", "barcode")):
            self.source_filter.addItem(label, value)
        self.source_filter.currentIndexChanged.connect(self._refresh_filters)
        self.show_all_button = QPushButton("All matching files")
        self.show_all_button.clicked.connect(self._show_all_hits)
        filter_row.addWidget(self.file_filter, 2)
        filter_row.addWidget(self.keyword_filter)
        filter_row.addWidget(self.source_filter)
        filter_row.addWidget(self.show_all_button)
        self._root.addLayout(filter_row)
        self.text_notice = QLabel("Image-only PDF pages need OCR before text search.")
        self.text_notice.setObjectName("secondary")
        self._root.addWidget(self.text_notice)

        tip = QLabel(
            "Tip: drag the edge of a column header to resize it, double-click it "
            "to fit the content, or right-click it for more options."
        )
        tip.setObjectName("deepSearchTip")
        tip.setWordWrap(True)
        self._root.addWidget(tip)

        # --- action rows ---
        actions = QHBoxLayout()
        self.clear_button = QPushButton("Clear all results")
        self.clear_button.clicked.connect(self._clear_results)
        self.export_button = QPushButton("Export Search Results")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        self.export_scope = QComboBox()
        self.export_scope.addItem("Export all results", "all")
        self.export_scope.addItem("Export current filters", "filtered")
        self.open_selected_button = QPushButton("Open Selected Document")
        self.open_selected_button.setEnabled(False)
        self.open_selected_button.clicked.connect(lambda _checked=False: self._open_selected())
        for button in (self.clear_button, self.export_button, self.open_selected_button):
            actions.addWidget(button)
        actions.addWidget(self.export_scope)
        actions.addStretch(1)
        self._root.addLayout(actions)

        self.table.currentCellChanged.connect(lambda *_args: self._update_preview())
        self.table.currentCellChanged.connect(lambda *_args: self._select_file_hits())
        self.table.cellDoubleClicked.connect(self._handle_double_click)
        self.hits_table.doubleClicked.connect(self._open_hit)
        self.hits_table.selectionModel().currentChanged.connect(
            lambda *_args: self._update_hit_preview()
        )

    # --- table setup -------------------------------------------------------
    def _setup_result_table(self) -> None:
        self.table.setHorizontalHeaderLabels(
            ["File Name", "Matching Pages", "Occurrences", "Summary"]
        )
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 120)
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._install_header_menu(self.table)

    def _setup_error_table(self) -> None:
        self.error_table.setHorizontalHeaderLabels(["File name", "Error message"])
        header = self.error_table.horizontalHeader()
        self.error_table.setColumnWidth(0, 500)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(50)
        self.error_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._install_header_menu(self.error_table)

    def _install_header_menu(self, table) -> None:
        header = table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(
            lambda position, target=table: self._show_header_menu(target, position)
        )

    def _show_header_menu(self, table, position) -> None:
        menu = QMenu(self)
        auto_column = menu.addAction("Auto column width")
        auto_all = menu.addAction("Auto column width (all columns)")
        action = menu.exec(table.horizontalHeader().mapToGlobal(position))
        if action is auto_column:
            column = table.horizontalHeader().logicalIndexAt(position)
            if column >= 0:
                table.resizeColumnToContents(column)
        elif action is auto_all:
            self._auto_resize(table)

    # --- browsing and searching --------------------------------------------
    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Search folder", self.folder.text())
        if value:
            self.folder.setText(value)

    def _show_path_tail(self, text: str) -> None:
        """Scroll long paths to the end so the folder name stays visible."""
        self.folder.setToolTip(text)
        if not self.folder.hasFocus() and text:
            QTimer.singleShot(0, lambda: self.folder.setCursorPosition(len(text)))

    def keyPressEvent(self, event) -> None:
        # Enter in the query field is handled by returnPressed; consume it so
        # it cannot trigger the dialog's default button.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.query.hasFocus():
            return
        super().keyPressEvent(event)

    def _search(self) -> None:
        if self._task is not None or self._export_task is not None:
            return  # a search is already running
        query = self.query.text().strip()
        if not query:
            self.status.setText("Enter text to search for.")
            return
        folder = self.folder.text().strip()
        if not Path(folder).expanduser().is_dir():
            self.status.setText("Choose a valid folder to search.")
            return
        self._clear_results()
        self._searched_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._run_query = query
        self._run_folder = folder
        self._run_subfolders = self.subfolders.isChecked()
        self._run_barcodes = self.barcodes.isChecked()
        self._run_completed = False
        self._search_error = False
        self.search_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Searching…")
        self.tabs.setCurrentIndex(0)
        self._search_started_at = time.monotonic()
        self._processed_files = 0
        self._total_files = 0
        task = FunctionTask(
            search_folder_detailed,
            folder,
            query,
            self._run_subfolders,
            self._run_barcodes,
            progress_argument="progress",
            cancel_argument="is_cancelled",
            batch_argument="on_batch",
        )
        self._task = task
        task.signals.progress.connect(self._on_progress)
        task.signals.batch.connect(self._receive_batch)
        task.signals.result.connect(self._detailed_result)
        task.signals.error.connect(self._on_search_error)
        task.signals.finished.connect(self._search_finished)
        self._pool.start(task)

    def _cancel_search(self) -> None:
        if self._task:
            self._task.cancel()
            self.status.setText("Cancelling search…")
            self.cancel_button.setEnabled(False)

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._total_files = max(self._total_files, total)
        self._processed_files = max(self._processed_files, current)
        self.progress.setValue(int(current / total * 100) if total else 0)
        if message:
            self.current_file.setText(f"Processing: {message}")

    def _receive_batch(self, batch: SearchBatch) -> None:
        self._store.add(batch)
        if batch.file and batch.file.matches:
            self._append_file_result(batch.file)
        if batch.issue:
            issue = batch.issue
            self._errors.append({"path": issue.path, "filename": issue.filename,
                                 "pages": [], "snippets": [], "error": issue.message})
            row = self.error_table.rowCount()
            self.error_table.insertRow(row)
            self.error_table.setItem(row, 0, QTableWidgetItem(issue.filename))
            self.error_table.setItem(row, 1, QTableWidgetItem(issue.message))
        if batch.hits:
            if not self._refresh_scheduled:
                self._refresh_scheduled = True
                QTimer.singleShot(100, self._flush_hit_refresh)
        self.export_button.setEnabled(self._task is None and bool(self._results or self._errors))

    def _flush_hit_refresh(self) -> None:
        self._refresh_scheduled = False
        if self._store.db is not None:
            self._refresh_hit_model()

    def _append_file_result(self, file: SearchFile) -> None:
        self._results.append({"path": file.path, "filename": file.filename,
                              "pages": [], "snippets": [],
                              "match_count": file.matches})
        index = len(self._results) - 1
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(file.filename)
        name.setToolTip(file.path)
        name.setData(_RESULT_INDEX_ROLE, index)
        name.setData(Qt.ItemDataRole.UserRole, file.path)
        self.table.setItem(row, 0, name)
        page_item = QTableWidgetItem(str(file.matching_pages))
        page_item.setToolTip("Number of pages with at least one match")
        self.table.setItem(row, 1, page_item)
        count_item = QTableWidgetItem(str(file.matches))
        count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, count_item)
        first_hit = self._store.hit_page(0, 1, (file.path,))
        context = first_hit[0].context if first_hit else "Select to view occurrences"
        self.table.setItem(row, 3, QTableWidgetItem(context))

    def _detailed_result(self, run) -> None:
        self._run_completed = True
        self._total_files = run.files_found
        self._processed_files = run.files_processed
        self.keyword_filter.blockSignals(True)
        self.keyword_filter.clear()
        self.keyword_filter.addItem("All keywords", "")
        for keyword in run.keywords:
            self.keyword_filter.addItem(keyword, keyword)
        self.keyword_filter.blockSignals(False)
        self.text_notice.setText(
            f"{run.no_text_files} file(s) had no extractable text. "
            "Image-only pages need OCR before text search."
        )

    def _on_search_error(self, message: str) -> None:
        self._search_error = True
        self.status.setText(f"Search failed: {message}")

    def _search_finished(self) -> None:
        was_cancelled = bool(self._task and self._task.is_cancelled())
        self._task = None
        self.search_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.current_file.setText("")
        self._run_elapsed = max(0.0, time.monotonic() - self._search_started_at)
        self._store.remove_incomplete_files()
        self._refresh_hit_model()
        if was_cancelled:
            occurrences = self._store.hit_count()
            self.status.setText(
                f"Search cancelled · partial results retained · {occurrences} occurrences"
            )
            self.export_button.setEnabled(bool(self._results or self._errors))
            return
        if self._search_error:
            self.export_button.setEnabled(bool(self._results or self._errors))
            return
        if not self._results and not self._errors and self._total_files == 0:
            self.progress.setValue(0)
            self.status.setText("No PDF files were found in the folder.")
            return
        self.progress.setValue(100)
        matches = len(self._results)
        errors = len(self._errors)
        occurrences, _, matching_pages = self._store.counts()
        elapsed = self._run_elapsed
        processed = max(self._processed_files, matches + errors)
        self.status.setText(
            f"Completed in {elapsed:.2f} s · {processed} files scanned · "
            f"{matches} matching files · {matching_pages} pages · "
            f"{occurrences} occurrences · {errors} errors"
        )
        self.export_button.setEnabled(bool(self._results or self._errors))
        if matches:
            self.tabs.setCurrentIndex(0)
        elif errors:
            self.tabs.setCurrentIndex(3)

    def _show_results(self, results: list[dict[str, object]]) -> None:
        # Compatibility path for callers using the older one-snippet-per-page
        # structure. The live search uses _receive_batch instead.
        self._results = [result for result in results if not result.get("error")]
        self._errors = [result for result in results if result.get("error")]
        for result in results:
            if result.get("error"):
                self._store.add(SearchBatch(issue=SearchIssue(
                    str(result["path"]), str(result["filename"]), str(result["error"])
                )))
                continue
            pages = list(result.get("pages", []))
            snippets = list(result.get("snippets", []))
            keyword = self.query.text().split(",")[0].strip() or "search"
            hits = tuple(SearchHit(str(result["path"]), str(result["filename"]),
                                   int(page), keyword, "text",
                                   str(snippets[index]) if index < len(snippets) else "", index)
                         for index, page in enumerate(pages))
            self._store.add(SearchBatch(hits=hits, file=SearchFile(
                str(result["path"]), str(result["filename"]), max(pages, default=0),
                len(set(pages)), len(hits), False,
            )))
        primary = QColor(get_color("primary"))
        for index, result in enumerate(self._results):
            row = self.table.rowCount()
            self.table.insertRow(row)
            file_item = QTableWidgetItem(str(result["filename"]))
            file_item.setToolTip(f"File path: {result['path']}\nDouble-click to open")
            file_item.setForeground(primary)
            file_item.setData(Qt.ItemDataRole.UserRole, str(result["path"]))
            # Keep the original index on the item so row order can change
            # (e.g. by sorting) without losing the mapping to the result.
            file_item.setData(_RESULT_INDEX_ROLE, index)
            self.table.setItem(row, 0, file_item)
            pages = ", ".join(map(str, result["pages"]))
            page_item = QTableWidgetItem(pages or "—")
            page_item.setToolTip(f"Match Page Number: {pages or '—'}")
            self.table.setItem(row, 1, page_item)
            count_item = QTableWidgetItem(str(len(result["pages"])))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, count_item)
            snippet = str(result["snippets"][0]) if result["snippets"] else "No content preview"
            context_item = QTableWidgetItem(snippet)
            context_item.setToolTip(snippet)
            self.table.setItem(row, 3, context_item)
        for result in self._errors:
            row = self.error_table.rowCount()
            self.error_table.insertRow(row)
            self.error_table.setItem(row, 0, QTableWidgetItem(str(result["filename"])))
            self.error_table.setItem(row, 1, QTableWidgetItem(str(result["error"])))
        self.status.setText(
            f"{len(self._results)} matching file(s)"
            + (f" · {len(self._errors)} file(s) could not be searched" if self._errors else "")
        )
        self.export_button.setEnabled(bool(self._results or self._errors))
        self._refresh_hit_model()
        if self.table.rowCount():
            self.table.setCurrentCell(0, 0)
        self._update_preview()

    def _visible_paths(self) -> tuple[str, ...]:
        paths: list[str] = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            index = self._result_index_for_row(row)
            if index is not None:
                paths.append(str(self._results[index]["path"]))
        return tuple(paths)

    def _refresh_filters(self, *_args) -> None:
        needle = self.file_filter.text().strip().casefold()
        for row in range(self.table.rowCount()):
            index = self._result_index_for_row(row)
            value = str(self._results[index]["path"]).casefold() if index is not None else ""
            self.table.setRowHidden(row, bool(needle and needle not in value))
        self._refresh_hit_model()

    def _select_file_hits(self) -> None:
        index = self._result_index_for_row(self.table.currentRow())
        self._selected_file_path = (str(self._results[index]["path"])
                                    if index is not None else None)
        self._refresh_hit_model()

    def _show_all_hits(self) -> None:
        self._selected_file_path = None
        self.table.clearSelection()
        self._refresh_hit_model()
        self.tabs.setCurrentWidget(self.hits_table)

    def _refresh_hit_model(self) -> None:
        visible = self._visible_paths()
        paths: tuple[str, ...] | None = (visible if self.file_filter.text().strip() else None)
        if self._selected_file_path:
            paths = tuple(path for path in visible if path == self._selected_file_path)
        self._hits_model.configure(
            paths, str(self.keyword_filter.currentData() or ""),
            str(self.source_filter.currentData() or ""),
        )

    def _update_hit_preview(self) -> None:
        hit = self._hits_model.hit(self.hits_table.currentIndex().row())
        if hit is None:
            return
        self.preview.setHtml(
            f"<h3>{html.escape(hit.filename)}</h3>"
            f"<p>{html.escape(hit.path)}</p>"
            f"<p><b>Page {hit.page} · {html.escape(hit.keyword)} · "
            f"{html.escape(hit.source.title())}</b></p>"
            f"<p>{self._highlight(hit.context, [hit.keyword])}</p>"
        )

    def _open_hit(self, index) -> None:
        hit = self._hits_model.hit(index.row())
        if hit is None:
            return
        self.hitOpenRequested.emit(hit.path, str(self.open_option.currentData()), hit.page)

    def _result_index_for_row(self, row: int) -> int | None:
        item = self.table.item(row, 0)
        if item is None:
            return None
        index = item.data(_RESULT_INDEX_ROLE)
        if index is None or not 0 <= int(index) < len(self._results):
            return None
        return int(index)

    # --- preview -------------------------------------------------------------
    def _update_preview(self) -> None:
        row = self.table.currentRow()
        index = self._result_index_for_row(row)
        self.open_selected_button.setEnabled(index is not None)
        if index is None:
            self.preview.clear()
            return
        result = self._results[index]
        keywords = [keyword for keyword in self._run_query.split(",") if keyword.strip()]
        if not keywords:
            keywords = [keyword for keyword in self.query.text().split(",") if keyword.strip()]
        text_color = get_color("text_primary")
        error_color = get_color("error")
        parts = [
            f"<div style='color: {text_color};'>",
            f"<h3>File: {html.escape(str(result['filename']))}</h3>",
            f"<p><b>Path:</b> {html.escape(str(result['path']))}</p>",
            (f"<p><b>Matching pages:</b> {self._store.counts((str(result['path']),))[2]}</p>"
             if "match_count" in result else
             f"<p><b>Page number:</b> {', '.join(map(str, result['pages']))}</p>"),
            f"<p><b>Occurrences:</b> {result.get('match_count', len(result['pages']))}</p>",
        ]
        if result.get("error"):
            parts.append(
                f"<p style='color: {error_color};'>Error: {html.escape(str(result['error']))}</p>"
            )
        else:
            parts.append("<h4>Matching content:</h4><hr/>")
            if "match_count" in result:
                hits = self._store.hit_page(0, 20, (str(result["path"]),))
                for hit in hits:
                    parts.append(f"<p><b>Page {hit.page} · {html.escape(hit.keyword)}:</b><br/>"
                                 f"{self._highlight(hit.context, [hit.keyword])}</p>")
                if int(result["match_count"]) > len(hits):
                    parts.append("<p>More occurrences are available in the Matches tab.</p>")
            for snippet_index, snippet in enumerate(result["snippets"]):
                page_number = (
                    result["pages"][snippet_index]
                    if snippet_index < len(result["pages"])
                    else "?"
                )
                escaped = self._highlight(str(snippet), keywords)
                parts.append(f"<p><b>Page {page_number}:</b><br/>{escaped}</p>")
        parts.append("</div>")
        self.preview.setHtml("".join(parts))

    @staticmethod
    def _highlight(text: str, keywords: list[str]) -> str:
        colors = get_colors()
        background = colors.get("warning_soft", "#fff0d8")
        foreground = colors.get("text_primary", "#000000")
        terms = sorted((term for term in keywords if term), key=len, reverse=True)
        if not terms:
            return html.escape(text)
        pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
        parts: list[str] = []
        previous = 0
        for match in pattern.finditer(text):
            parts.append(html.escape(text[previous:match.start()]))
            parts.append(
                f"<span style='background-color: {background}; color: {foreground}; "
                f"font-weight: bold;'>{html.escape(match.group())}</span>"
            )
            previous = match.end()
        parts.append(html.escape(text[previous:]))
        return "".join(parts)

    # --- opening -------------------------------------------------------------
    def _handle_double_click(self, row: int, column: int) -> None:
        if column == 0:
            self._open_selected(row)

    def _open_selected(self, row: int | None = None) -> None:
        if row is None and self.tabs.currentWidget() is self.hits_table:
            index = self.hits_table.currentIndex()
            if index.isValid():
                self._open_hit(index)
            return
        if row is None:
            row = self.table.currentRow()
        index = self._result_index_for_row(row)
        if index is None:
            return
        path = str(self._results[index]["path"])
        method = str(self.open_option.currentData())
        self.openRequested.emit(path, method)
        if method == OPEN_CURRENT:
            self.hide()
            parent_window = self.parentWidget().window() if self.parentWidget() else None
            if parent_window is not None:
                parent_window.raise_()
                parent_window.activateWindow()

    # --- clearing / exporting -------------------------------------------------
    def _clear_results(self) -> None:
        self._results = []
        self._errors = []
        self.table.setRowCount(0)
        self.error_table.setRowCount(0)
        self.preview.clear()
        self.progress.setValue(0)
        self.status.setText("Clear All Result")
        self.current_file.setText("")
        self.export_button.setEnabled(False)
        self.open_selected_button.setEnabled(False)
        self._selected_file_path = None
        self._store.close()
        self._store = SearchResultsStore()
        self._hits_model.store = self._store
        self._hits_model.configure(())
        self.keyword_filter.blockSignals(True)
        self.keyword_filter.clear()
        self.keyword_filter.addItem("All keywords", "")
        self.keyword_filter.blockSignals(False)
        self.source_filter.setCurrentIndex(0)

    def _auto_resize_columns(self) -> None:
        self._auto_resize(self.table)

    def _auto_resize(self, table) -> None:
        minimums = {0: 200, 1: 80, 2: 80, 3: 300} if table is self.table else {0: 200, 1: 200}
        for column in range(table.columnCount()):
            table.resizeColumnToContents(column)
            current = table.columnWidth(column)
            if current < minimums.get(column, 80):
                table.setColumnWidth(column, minimums.get(column, 80))

    def _export(self) -> None:
        if self._export_task is not None:
            return
        if not self._results and not self._errors:
            self.status.setText("No search results available to export")
            return
        safe_query = re.sub(r'[\\/:*?"<>|]', "_", self.query.text().strip())[:60] or "search"
        suggested = f"PDF Search Results_{safe_query}.html"
        path, selected_format = QFileDialog.getSaveFileName(
            self,
            "Export Search Results",
            start_in_save_directory(self, suggested),
            "HTML file (*.html);;Text file (*.txt);;CSV file (*.csv)",
        )
        if not path:
            return
        extension = Path(path).suffix.casefold()
        if extension not in {".html", ".txt", ".csv"}:
            extension = ".html" if "HTML" in selected_format else (
                ".txt" if "Text" in selected_format else ".csv"
            )
            path += extension
        remember_save_directory(self, path)
        paths, keyword, source, scope = self._export_selection()
        task = FunctionTask(
            export_report, str(self._store.path), path, extension,
            self._report_meta(scope), paths, keyword, source,
        )
        self._export_task = task
        self.export_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.status.setText("Exporting report…")
        store = self._store
        task.signals.result.connect(self._export_succeeded)
        task.signals.error.connect(self._export_failed)
        task.signals.finished.connect(self._export_finished)
        task.signals.finished.connect(
            lambda: store.close() if getattr(store, "close_after_export", False) else None
        )
        self._pool.start(task)

    def _export_succeeded(self, path: Path) -> None:
        self.status.setText(f"Export successful: {path}")

    def _export_failed(self, message: str) -> None:
        log_failure("deep_search_dialog._export: failed", 10)
        self.status.setText(f"Export failed: {message}")

    def _export_finished(self) -> None:
        self._export_task = None
        self.export_button.setEnabled(bool(self._results or self._errors))
        self.search_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def _export_html(self, path: str) -> None:
        paths, keyword, source, scope = self._export_selection()
        export_html(self._store, path, self._report_meta(scope), paths, keyword, source)

    def _export_text(self, path: str) -> None:
        paths, keyword, source, scope = self._export_selection()
        export_text(self._store, path, self._report_meta(scope), paths, keyword, source)

    def _export_selection(self) -> tuple[tuple[str, ...] | None, str, str, str]:
        if self.export_scope.currentData() == "filtered":
            return (self._hits_model.paths, self._hits_model.keyword,
                    self._hits_model.source, "Current filters")
        return None, "", "", "All results"

    def _report_meta(self, scope: str) -> ReportMeta:
        return ReportMeta(
            self._run_query or self.query.text().strip(), self._run_folder,
            self._searched_at or datetime.now().astimezone().isoformat(timespec="seconds"),
            self._run_elapsed, self._processed_files,
            self._total_files, self._run_subfolders, self._run_barcodes,
            self._run_completed, scope,
        )

    def reject(self) -> None:
        if self._task and hasattr(self._task, "cancel"):
            self._task.cancel()
        super().reject()

    def closeEvent(self, event) -> None:
        if self._task and hasattr(self._task, "cancel"):
            self._task.cancel()
        if self._export_task is not None:
            self._store.close_after_export = True
        else:
            self._store.close()
        super().closeEvent(event)
