"""Filename-based PDF search and open dialog."""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.platform_service import PlatformService

from .base import SortableTableWidget, ToolDialog

SYSTEM_NAME = platform.system()


class _SearchSignals(QObject):
    found = pyqtSignal(object)  # Path
    finished = pyqtSignal(int, int)  # found, scanned


class _SearchTask(QRunnable):
    """Background filename walk that reports matches to the GUI thread."""

    def __init__(
        self,
        folder: Path,
        recursive: bool,
        needle: str,
        case_sensitive: bool,
        exact: bool,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._folder = folder
        self._recursive = recursive
        self._needle = needle
        self._case_sensitive = case_sensitive
        self._exact = exact
        self._cancelled = False
        self.signals = _SearchSignals()

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        iterator = (
            self._folder.rglob("*")
            if self._recursive
            else self._folder.iterdir()
        )
        found = 0
        scanned = 0
        try:
            for path in iterator:
                if self._cancelled or found >= 5000:
                    break
                if not path.is_file() or path.suffix.casefold() != ".pdf":
                    continue
                scanned += 1
                name = (
                    path.name
                    if self._case_sensitive
                    else path.name.casefold()
                )
                matched = (
                    name == self._needle
                    if self._exact
                    else self._needle in name
                )
                if matched:
                    self.signals.found.emit(path)
                    found += 1
        except BaseException:
            # Never let an exception escape QRunnable.run().
            pass
        self.signals.finished.emit(found, scanned)


class SearchOpenDialog(ToolDialog):
    def __init__(self, start_folder: str, parent=None):
        super().__init__("Search and Open PDF", "search-open-pdf", parent)
        self.selected_path = ""
        self.open_in_new_tab = False

        location = QGroupBox("Search location")
        location_row = QHBoxLayout(location)
        self.folder = QLineEdit(start_folder)
        self.folder.setMinimumWidth(320)
        self.folder.setToolTip(start_folder)
        self.folder.textChanged.connect(self._show_path_tail)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        location_row.addWidget(self.folder, 1)
        location_row.addWidget(browse)
        self._root.addWidget(location)

        search = QGroupBox("Filename")
        search_layout = QVBoxLayout(search)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Enter a full or partial PDF filename")
        self.query.returnPressed.connect(self._search)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._search)
        row.addWidget(self.query, 1)
        row.addWidget(self.search_button)
        search_layout.addLayout(row)
        options = QHBoxLayout()
        self.case_sensitive = QCheckBox("Case sensitive")
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.exact = QCheckBox("Exact filename match")
        options.addWidget(self.case_sensitive)
        options.addWidget(self.recursive)
        options.addWidget(self.exact)
        options.addStretch(1)
        search_layout.addLayout(options)
        self._root.addWidget(search)

        self.table = SortableTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Filename", "Folder", "Size", "Modified"])
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(lambda _item: self._choose(False))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self._root.addWidget(self.table, 1)
        self.status = QLabel("Ready to search")
        self.status.setObjectName("secondary")
        self._root.addWidget(self.status)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Open Selected")
        self.open_button.clicked.connect(lambda: self._choose(False))
        self.new_window_button = QPushButton("Open in New Tab")
        self.new_window_button.clicked.connect(lambda: self._choose(True))
        reveal = QPushButton(
            "Reveal in Finder" if SYSTEM_NAME == "Darwin" else "Reveal in Explorer"
        )
        reveal.clicked.connect(self._reveal)
        for button in (self.open_button, self.new_window_button, reveal):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch(1)
        self._root.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Choose search folder", self.folder.text())
        if value:
            self.folder.setText(value)

    def _show_path_tail(self, text: str) -> None:
        """Scroll long paths to the end so the folder name stays visible."""
        self.folder.setToolTip(text)
        if not self.folder.hasFocus() and text:
            QTimer.singleShot(0, lambda: self.folder.setCursorPosition(len(text)))

    def _search(self) -> None:
        folder = Path(self.folder.text()).expanduser()
        query = self.query.text()
        if not self.folder.text().strip() or not folder.is_dir():
            self.show_error("Choose a valid search folder.")
            return
        if not query:
            self.show_error("Enter a filename or part of a filename.")
            return
        self._cancel_pending_search()
        needle = query if self.case_sensitive.isChecked() else query.casefold()
        task = _SearchTask(
            folder,
            self.recursive.isChecked(),
            needle,
            self.case_sensitive.isChecked(),
            self.exact.isChecked(),
        )
        self._search_task = task
        self._search_progress = QProgressDialog(
            "Searching PDF filenames…", "Cancel", 0, 0, self
        )
        self._search_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._search_progress.setMinimumDuration(300)
        self._search_progress.canceled.connect(task.cancel)
        self.search_button.setEnabled(False)
        self.table.setRowCount(0)
        task.signals.found.connect(self._append_result)
        task.signals.finished.connect(self._search_finished)
        QThreadPool.globalInstance().start(task)

    def _cancel_pending_search(self) -> None:
        task = getattr(self, "_search_task", None)
        if task is not None:
            task.cancel()
            self._search_task = None
        progress = getattr(self, "_search_progress", None)
        if progress is not None:
            progress.close()
            self._search_progress = None

    def _search_finished(self, found: int, scanned: int) -> None:
        self._search_task = None
        progress = getattr(self, "_search_progress", None)
        if progress is not None:
            progress.close()
            self._search_progress = None
        self.search_button.setEnabled(True)
        suffix = " (limited to 5,000)" if found >= 5000 else ""
        self.status.setText(
            f"Found {found} matching PDF file(s) after checking {scanned:,}{suffix}."
        )

    def closeEvent(self, event) -> None:
        self._cancel_pending_search()
        super().closeEvent(event)

    def _append_result(self, path: Path) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (
            path.name,
            str(path.parent),
            f"{path.stat().st_size / 1048576:.2f} MB",
            datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(str(path))
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.table.setItem(row, column, item)

    def _selection_changed(self) -> None:
        enabled = self.table.currentRow() >= 0
        self.open_button.setEnabled(enabled)
        self.new_window_button.setEnabled(enabled)
        for button in self.findChildren(QPushButton):
            if button.text() == "Reveal in Finder / Explorer":
                button.setEnabled(enabled)

    def _current_path(self) -> str:
        item = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _choose(self, new_window: bool) -> None:
        value = self._current_path()
        if value:
            self.selected_path = value
            self.open_in_new_tab = new_window
            self.accept()

    def _reveal(self) -> None:
        value = self._current_path()
        if value:
            PlatformService.reveal_file(value)
