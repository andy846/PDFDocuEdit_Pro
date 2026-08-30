"""Deep Search dialog: folder-wide PDF text and barcode search.

The layout mirrors the original PDFDocuEdit Pro "PDF Content Deep Search"
window, restyled with the application theme tokens: folder row, prominent
search row, options row (subfolders / barcode content / open method), status
row with progress, three tabs (Search Result / Preview / Error Message) and
one compact action row (clear / export / open selected).
"""

from __future__ import annotations

import html
import re
import time
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
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
)

from core.tasks import FunctionTask
from core.tools import deep_search, export_search_results_csv
from dialogs.base import SortableTableWidget, ToolDialog, remember_save_directory, start_in_save_directory
from styles.theme import get_color, get_colors

OPEN_NEW_TAB = "new_tab"
OPEN_CURRENT = "current"
OPEN_SYSTEM = "system"

_RESULT_INDEX_ROLE = Qt.ItemDataRole.UserRole + 1


class DeepSearchDialog(ToolDialog):
    """Non-modal folder-wide PDF search with preview and error tabs."""

    openRequested = pyqtSignal(str, str)  # file path, open method

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
        self._pool = QThreadPool.globalInstance()
        self._search_started_at = 0.0
        self._processed_files = 0
        self._total_files = 0

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
        self.preview = QTextEdit()
        self.preview.setObjectName("deepSearchPreview")
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, "Preview")
        self.error_table = SortableTableWidget(0, 2)
        self.error_table.setObjectName("deepSearchErrorTable")
        self._setup_error_table()
        self.tabs.addTab(self.error_table, "Error Message")
        self._root.addWidget(self.tabs, 1)

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
        self.open_selected_button = QPushButton("Open Selected Document")
        self.open_selected_button.setEnabled(False)
        self.open_selected_button.clicked.connect(self._open_selected)
        for button in (self.clear_button, self.export_button, self.open_selected_button):
            actions.addWidget(button)
        actions.addStretch(1)
        self._root.addLayout(actions)

        self.table.itemSelectionChanged.connect(self._update_preview)
        self.table.cellDoubleClicked.connect(self._handle_double_click)

    # --- table setup -------------------------------------------------------
    def _setup_result_table(self) -> None:
        self.table.setHorizontalHeaderLabels(
            ["File Name", "Page number", "Match Count", "Contextual Summary"]
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
        if self._task is not None:
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
        self.search_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Searching…")
        self.tabs.setCurrentIndex(0)
        self._search_started_at = time.monotonic()
        self._processed_files = 0
        self._total_files = 0
        task = FunctionTask(
            deep_search,
            folder,
            query,
            self.subfolders.isChecked(),
            self.barcodes.isChecked(),
            progress_argument="progress",
            cancel_argument="is_cancelled",
        )
        self._task = task
        task.signals.progress.connect(self._on_progress)
        task.signals.result.connect(self._show_results)
        task.signals.error.connect(
            lambda message: self.status.setText(f"Search failed: {message}")
        )
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

    def _search_finished(self) -> None:
        was_cancelled = bool(self._task and self._task.is_cancelled())
        self._task = None
        self.search_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.current_file.setText("")
        if was_cancelled:
            self.status.setText("Search cancelled.")
            return
        if not self._results and not self._errors and self._total_files == 0:
            self.progress.setValue(0)
            self.status.setText("No PDF files were found in the folder.")
            return
        self.progress.setValue(100)
        matches = len(self._results)
        errors = len(self._errors)
        elapsed = time.monotonic() - self._search_started_at
        processed = max(self._processed_files, matches + errors)
        self.status.setText(
            f"Search Completed! Use: {elapsed:.2f} sec, Processed: {processed} files, "
            f"Found: {matches} files, Error: {errors} files"
        )
        self.export_button.setEnabled(bool(self._results))
        if matches:
            self.tabs.setCurrentIndex(0)
            QTimer.singleShot(100, self._auto_resize_columns)
        elif errors:
            self.tabs.setCurrentIndex(2)
            QTimer.singleShot(100, lambda: self._auto_resize(self.error_table))

    def _show_results(self, results: list[dict[str, object]]) -> None:
        self._results = [result for result in results if not result.get("error")]
        self._errors = [result for result in results if result.get("error")]
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
        self.export_button.setEnabled(bool(self._results))

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
            return
        result = self._results[index]
        keywords = [keyword for keyword in self.query.text().split(",") if keyword.strip()]
        text_color = get_color("text_primary")
        error_color = get_color("error")
        parts = [
            f"<div style='color: {text_color};'>",
            f"<h3>File: {html.escape(str(result['filename']))}</h3>",
            f"<p><b>Path:</b> {html.escape(str(result['path']))}</p>",
            f"<p><b>Page number:</b> {', '.join(map(str, result['pages']))}</p>",
            f"<p><b>Matched:</b> {len(result['pages'])}</p>",
        ]
        if result.get("error"):
            parts.append(
                f"<p style='color: {error_color};'>Error: {html.escape(str(result['error']))}</p>"
            )
        else:
            parts.append("<h4>Matching content:</h4><hr/>")
            for snippet_index, snippet in enumerate(result["snippets"]):
                page_number = (
                    result["pages"][snippet_index]
                    if snippet_index < len(result["pages"])
                    else "?"
                )
                escaped = self._highlight(html.escape(str(snippet)), keywords)
                parts.append(f"<p><b>Page {page_number}:</b><br/>{escaped}</p>")
        parts.append("</div>")
        self.preview.setHtml("".join(parts))

    @staticmethod
    def _highlight(text: str, keywords: list[str]) -> str:
        colors = get_colors()
        background = colors.get("warning_soft", "#fff0d8")
        foreground = colors.get("text_primary", "#000000")
        for keyword in sorted(keywords, key=len, reverse=True):
            text = re.sub(
                re.escape(keyword),
                lambda match: (
                    f"<span style='background-color: {background}; color: {foreground}; "
                    f"font-weight: bold;'>{match.group(0)}</span>"
                ),
                text,
                flags=re.IGNORECASE,
            )
        return text

    # --- opening -------------------------------------------------------------
    def _handle_double_click(self, row: int, column: int) -> None:
        if column == 0:
            self._open_selected(row)

    def _open_selected(self, row: int | None = None) -> None:
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
        if not self._results:
            self.status.setText("No search results available to export")
            return
        safe_query = re.sub(r'[\\/:*?"<>|]', "_", self.query.text().strip())[:60] or "search"
        suggested = f"PDF Search Results_{safe_query}.html"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Search Results",
            start_in_save_directory(self, suggested),
            "HTML file (*.html);;Text file (*.txt);;CSV file (*.csv)",
        )
        if not path:
            return
        remember_save_directory(self, path)
        try:
            if path.endswith(".html"):
                self._export_html(path)
            elif path.endswith(".txt"):
                self._export_text(path)
            else:
                if not path.endswith(".csv"):
                    path += ".csv"
                export_search_results_csv(self._results, path)
            self.status.setText(f"Export successful: {path}")
        except Exception as exc:
            self.status.setText(f"Export failed: {exc}")

    def _export_html(self, path: str) -> None:
        query = html.escape(self.query.text().strip())
        folder = html.escape(self.folder.text().strip())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                "<title>PDF Search Results</title></head><body>"
                f"<h1>PDF Search Results</h1><p><b>Search keys:</b> {query}<br/>"
                f"<b>Search path:</b> {folder}<br/>"
                f"<b>Matching files:</b> {len(self._results)}<br/>"
                f"<b>Search time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}</p>"
            )
            for result in self._results:
                handle.write(
                    f"<hr/><p><b>File:</b> {html.escape(str(result['filename']))}<br/>"
                    f"<b>Path:</b> {html.escape(str(result['path']))}<br/>"
                    f"<b>Match page number:</b> {', '.join(map(str, result['pages']))}</p>"
                )
                for index, snippet in enumerate(result["snippets"]):
                    page = result["pages"][index] if index < len(result["pages"]) else "?"
                    handle.write(
                        f"<p>From page {page}: {html.escape(str(snippet))}</p>"
                    )
            handle.write("</body></html>")

    def _export_text(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("PDF Search Result\n")
            handle.write(f"Search Keys: {self.query.text().strip()}\n")
            handle.write(f"Search Path: {self.folder.text().strip()}\n")
            handle.write(f"Number of matching files: {len(self._results)}\n")
            handle.write(f"Search time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.write("-" * 80 + "\n\n")
            for index, result in enumerate(self._results):
                handle.write(f"File {index + 1}: {result['filename']}\n")
                handle.write(f"Path: {result['path']}\n")
                handle.write(
                    f"Match page number: {', '.join(map(str, result['pages']))}\n\n"
                )
                for snippet_index, snippet in enumerate(result["snippets"]):
                    page = (
                        result["pages"][snippet_index]
                        if snippet_index < len(result["pages"])
                        else "?"
                    )
                    handle.write(f"From page {page}: {snippet}\n\n")
                handle.write("-" * 80 + "\n\n")

    def reject(self) -> None:
        if self._task:
            self._task.cancel()
        super().reject()
