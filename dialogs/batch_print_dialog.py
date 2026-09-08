"""Batch PDF print setup: file list, print profile, and a live progress log.

Layout follows the original PDFDocuEdit Pro batch print window (file table on
the left, stacked option groups on the right, live progress log at the bottom
left), restyled with the application theme. The dialog stays open while the
batch prints and reports each file into the log, like the legacy version.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .base import ToolDialog
from .batch_tools import PdfFileTable
from .print_profile import collect_print_profile, quality_changed, restore_print_profile


class BatchPrintDialog(ToolDialog):
    cancelRequested = pyqtSignal()
    printRequested = pyqtSignal(object)  # details dict

    def __init__(self, parent=None):
        super().__init__("Batch Print PDF Files", "batch-print", parent)
        self.setModal(False)
        self.resize(1080, 680)
        self.setMinimumWidth(920)
        self.file_paths: list[str] = []
        self._page_counts: dict[str, int] = {}
        self._status: dict[str, str] = {}
        self._print_dates: dict[str, str] = {}
        self._print_times: dict[str, str] = {}
        self._sort_column_index = -1
        self._sort_descending = False
        self._cancel_requested = False
        self.details: dict[str, object] | None = None
        self._printing = False

        columns = QHBoxLayout()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "Add or drop PDFs, arrange the print order, then configure one "
            "print profile for the batch."
        )
        intro.setObjectName("secondary")
        intro.setWordWrap(True)
        left_layout.addWidget(intro)
        self.table = PdfFileTable()
        # Legacy parity: per-file progress, print date, and print time columns.
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Order", "Filename", "Pages", "Size (MB)", "Modified", "Status", "Print date", "Print time"]
        )
        for column in (5, 6, 7):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.horizontalHeader().sectionClicked.connect(self._sort_column)
        self.table.filesDropped.connect(self.add_paths)
        # Give the filename column room so long names stay readable.
        self.table.setColumnWidth(1, 220)
        left_layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        for label, tooltip, callback in (
            ("Add PDFs…", "Add PDF files to the batch", self._add),
            ("Remove", "Remove the selected PDF", self._remove),
            ("Up", "Move the selected PDF up in the print order", lambda: self._move(-1)),
            ("Down", "Move the selected PDF down in the print order", lambda: self._move(1)),
            ("Clear", "Remove every PDF from the batch", self._clear),
        ):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        self.total = QLabel("0 PDFs")
        actions.addWidget(self.total)
        left_layout.addLayout(actions)

        self.log = QTextEdit()
        self.log.setObjectName("batchPrintLog")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Print progress appears here.")
        self.log.setMinimumHeight(110)
        left_layout.addWidget(self.log)

        columns.addWidget(left, 3)

        right = QWidget()
        right.setFixedWidth(340)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # --- printer group ---
        printer_group = QGroupBox("Printer")
        printer_form = QFormLayout(printer_group)
        self.printer = QComboBox()
        default_name = QPrinterInfo.defaultPrinterName()
        for printer in QPrinterInfo.availablePrinters():
            self.printer.addItem(printer.printerName())
        index = self.printer.findText(default_name)
        if index >= 0:
            self.printer.setCurrentIndex(index)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.collate = QCheckBox("Collate multiple copies")
        self.collate.setChecked(True)
        self.colour = QComboBox()
        self.colour.addItems(["Colour", "Grayscale"])
        self.duplex = QComboBox()
        self.duplex.addItems(
            ["Printer default", "Single-sided", "Duplex — long edge", "Duplex — short edge"]
        )
        self.quality = QComboBox()
        self.quality.addItem("Draft — 150 DPI", 150)
        self.quality.addItem("Standard — 300 DPI", 300)
        self.quality.addItem("High — 600 DPI", 600)
        self.quality.addItem("Custom DPI", None)
        self.quality.setCurrentIndex(1)
        self.quality_dpi = QSpinBox()
        self.quality_dpi.setRange(72, 600)
        self.quality_dpi.setValue(300)
        self.quality_dpi.setSuffix(" DPI")
        self.quality.currentIndexChanged.connect(
            lambda _index: quality_changed(self)
        )
        quality_changed(self)
        preferences = QPushButton("Printer Preferences…")
        preferences.clicked.connect(self._printer_preferences)
        self.confirm_system = QCheckBox("Confirm with the system dialog")
        self.confirm_system.setToolTip(
            "When unchecked, the batch prints directly with the options above."
        )
        self.confirm_system.setChecked(False)
        printer_form.addRow("Printer", self.printer)
        printer_form.addRow("", preferences)
        printer_form.addRow("Copies", self.copies)
        printer_form.addRow("", self.collate)
        printer_form.addRow("Output", self.colour)
        printer_form.addRow("Two-sided", self.duplex)
        printer_form.addRow("Print quality", self.quality)
        printer_form.addRow("Custom quality", self.quality_dpi)
        printer_form.addRow("", self.confirm_system)
        right_layout.addWidget(printer_group)

        # --- paper group ---
        paper_group = QGroupBox("Paper and placement")
        paper_form = QFormLayout(paper_group)
        self.paper = QComboBox()
        self.paper.addItems(["PDF page size", "A4", "A3", "A5", "Letter"])
        self.orientation = QComboBox()
        self.orientation.addItems(["Automatic", "Portrait", "Landscape"])
        self.scale_mode = QComboBox()
        self.scale_mode.addItems(["Fit to printable area", "Actual size", "Custom scale"])
        self.scale = QSpinBox()
        self.scale.setRange(10, 400)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        self.scale.setEnabled(False)
        self.scale_mode.currentIndexChanged.connect(
            lambda index: self.scale.setEnabled(index == 2)
        )
        self.center = QCheckBox("Centre on page")
        self.center.setChecked(True)
        # Pre-filled from the saved preferences so printer-specific offsets
        # need not be re-entered for every batch.
        left_mm, right_mm, top_mm, bottom_mm = self._default_offsets()
        self.left = self._offset()
        self.left.setValue(left_mm)
        self.right = self._offset()
        self.right.setValue(right_mm)
        self.top = self._offset()
        self.top.setValue(top_mm)
        self.bottom = self._offset()
        self.bottom.setValue(bottom_mm)
        paper_form.addRow("Paper", self.paper)
        paper_form.addRow("Orientation", self.orientation)
        paper_form.addRow("Scaling", self.scale_mode)
        paper_form.addRow("Custom scale", self.scale)
        paper_form.addRow(self.center)
        paper_form.addRow("Shift from left", self.left)
        paper_form.addRow("Shift from right", self.right)
        restore_print_profile(self, self._default_profile())
        paper_form.addRow("Shift from top", self.top)
        paper_form.addRow("Shift from bottom", self.bottom)
        paper_note = QLabel(
            "Each PDF prints as its own job. “PDF page size” follows each file’s first page."
        )
        paper_note.setObjectName("secondary")
        paper_note.setWordWrap(True)
        paper_form.addRow(paper_note)
        right_layout.addWidget(paper_group)

        right_layout.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Close
        )
        self.start_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start_button.setText("Start Batch Print")
        # Ok is an AcceptRole button, but the dialog stays open while the
        # batch prints, so route it through printRequested instead of accept().
        self.start_button.clicked.connect(self._validate)
        self.cancel_button = buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.cancel_button.setToolTip("Stop the batch after the current page")
        self.cancel_button.clicked.connect(self._cancel_request)
        self.cancel_button.setEnabled(False)
        buttons.rejected.connect(self.reject)
        right_layout.addWidget(buttons)
        columns.addWidget(right)
        self._root.addLayout(columns)


    def _default_profile(self) -> dict[str, object]:
        settings = getattr(self.parent(), "settings", None)
        if settings is not None:
            return settings.get_print_profile()
        return {}
    @staticmethod
    def _offset() -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(-999, 999)
        control.setDecimals(1)
        control.setSuffix(" mm")
        return control

    def _default_offsets(self) -> tuple[float, float, float, float]:
        settings = getattr(self.parent(), "settings", None)
        if settings is not None:
            return settings.get_print_offsets()
        return (0.0, 0.0, 0.0, 0.0)

    def drop_extensions(self) -> set[str] | None:
        return {".pdf"}

    def add_dropped_paths(self, paths: list[str]) -> None:
        self.add_paths(paths)

    # --- printer preferences (legacy feature) ------------------------------
    def _printer_preferences(self) -> None:
        name = self.printer.currentText()
        if not name:
            self.show_error("No printer is available.")
            return
        try:
            printer = QPrinter()
            printer.setPrinterName(name)
            QPrintDialog(printer, self).exec()
        except Exception as exc:
            self.show_error(f"Could not open printer preferences: {exc}")

    # --- file list ---------------------------------------------------------
    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        for value in paths:
            path = Path(value).expanduser().resolve()
            if path.is_file() and path.suffix.lower() == ".pdf" and str(path) not in self.file_paths:
                self.file_paths.append(str(path))
        self._refresh()

    def _remove(self) -> None:
        rows = sorted({row.row() for row in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            removed = self.file_paths.pop(row)
            self._page_counts.pop(removed, None)
        self._refresh()

    def _move(self, offset: int) -> None:
        row = self.table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self.file_paths):
            return
        self.file_paths[row], self.file_paths[target] = self.file_paths[target], self.file_paths[row]
        self._refresh()
        self.table.selectRow(target)

    def _clear(self) -> None:
        self.file_paths.clear()
        self._page_counts.clear()
        self._status.clear()
        self._print_dates.clear()
        self._print_times.clear()
        self._refresh()

    def _page_count(self, path: str) -> int:
        """Cached page count; opening every PDF on each refresh is wasteful."""
        if path not in self._page_counts:
            try:
                with fitz.open(path) as document:
                    self._page_counts[path] = document.page_count
            except Exception:
                self._page_counts[path] = 0
        return self._page_counts[path]

    def _refresh(self) -> None:
        self.table.setRowCount(0)
        total_pages = 0
        for index, value in enumerate(self.file_paths, 1):
            path = Path(value)
            pages = self._page_count(value)
            total_pages += pages
            row = self.table.rowCount()
            self.table.insertRow(row)
            try:
                size = path.stat().st_size / 1048576
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size = 0
                modified = "—"
            values = (
                index,
                path.name,
                pages,
                f"{size:.2f}",
                modified,
                self._status.get(value, "Pending"),
                self._print_dates.get(value, "—"),
                self._print_times.get(value, "—"),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(item)))
        self.total.setText(f"{len(self.file_paths)} PDFs · {total_pages} pages")

    # --- print flow ----------------------------------------------------------
    def _validate(self) -> None:
        if self._printing:
            return
        if not self.file_paths:
            self.show_error("Add at least one PDF file.")
            return
        if not self.printer.currentText():
            self.show_error("No printer is available on this system.")
            return
        self.details = collect_print_profile(self)
        self.details.update(
            {
                "paths": list(self.file_paths),
                "page_mode": "all",
                "page_range": "",
            }
        )
        self.printRequested.emit(self.details)

    def log_message(self, message: str) -> None:
        """Append a timestamped line to the print progress log."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")

    # --- per-file status (legacy parity) -----------------------------------
    def _row_of(self, path: str) -> int:
        try:
            return self.file_paths.index(path)
        except ValueError:
            return -1

    def set_file_status(self, path: str, text: str) -> None:
        self._status[path] = text
        row = self._row_of(path)
        if row >= 0:
            self.table.setItem(row, 5, QTableWidgetItem(text))

    def mark_file_printed(self, path: str) -> None:
        stamp = datetime.now()
        self._status[path] = "Done"
        self._print_dates[path] = stamp.strftime("%Y-%m-%d")
        self._print_times[path] = stamp.strftime("%H:%M:%S")
        row = self._row_of(path)
        if row >= 0:
            self.table.setItem(row, 5, QTableWidgetItem("Done"))
            self.table.setItem(row, 6, QTableWidgetItem(self._print_dates[path]))
            self.table.setItem(row, 7, QTableWidgetItem(self._print_times[path]))

    def mark_file_error(self, path: str) -> None:
        self._status[path] = "Error"
        row = self._row_of(path)
        if row >= 0:
            self.table.setItem(row, 5, QTableWidgetItem("Error"))

    def mark_printing_as_error(self) -> None:
        """After a failed job, mark every in-flight file as failed."""
        for path, status in list(self._status.items()):
            if status.startswith("Printing"):
                self.mark_file_error(path)

    # --- header sorting (legacy parity) -------------------------------------
    def _sort_column(self, column: int) -> None:
        if self._printing or column == 0 or not self.file_paths:
            return
        if column == self._sort_column_index:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_column_index = column
            self._sort_descending = False

        def key(value: str):
            path = Path(value)
            if column == 1:
                return path.name.casefold()
            if column == 2:
                return self._page_count(value)
            if column == 3:
                try:
                    return path.stat().st_size
                except OSError:
                    return 0
            if column == 4:
                try:
                    return path.stat().st_mtime
                except OSError:
                    return 0.0
            if column == 5:
                return self._status.get(value, "Pending")
            if column == 6:
                return self._print_dates.get(value, "")
            return self._print_times.get(value, "")

        self.file_paths.sort(key=key, reverse=self._sort_descending)
        self._refresh()

    # --- cancel (legacy parity, finer-grained) ------------------------------
    def _cancel_request(self) -> None:
        self._cancel_requested = True
        self.cancel_button.setEnabled(False)
        self.log_message("Cancelling after the current page…")
        self.cancelRequested.emit()

    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def set_printing(self, printing: bool) -> None:
        self._printing = printing
        self._cancel_requested = False
        self.start_button.setEnabled(not printing)
        self.start_button.setText("Printing…" if printing else "Start Batch Print")
        self.cancel_button.setEnabled(printing)

    def closeEvent(self, event) -> None:
        if self._printing:
            self._cancel_request()
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._printing:
            self._cancel_request()
            self.hide()
            return
        super().reject()
