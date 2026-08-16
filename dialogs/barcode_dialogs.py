"""Detailed single and batch barcode / QR code workflows."""

from __future__ import annotations

import csv
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
)

from .base import SortableTableWidget, ToolDialog, remember_save_directory, start_in_save_directory
from .conversion_dialogs import FileListDialog


class BarcodeScanDialog(FileListDialog):
    def __init__(self, current_path: Path | None, parent=None):
        super().__init__(
            "Read Barcode and QR Codes",
            "barcode-scan",
            {".pdf"},
            "PDF (*.pdf)",
            parent,
        )
        self.details: dict[str, object] | None = None
        if current_path:
            self.add_paths([str(current_path)])
        options = QGroupBox("Scan options")
        form = QFormLayout(options)
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("Leave blank for all pages; e.g. 1-3, 7, 10-12")
        self.dpi = QComboBox()
        self.dpi.addItems(["150 DPI — fast", "200 DPI — balanced", "300 DPI — detailed", "400 DPI — small codes"])
        self.dpi.setCurrentIndex(1)
        form.addRow("Pages", self.pages)
        form.addRow("Scan resolution", self.dpi)
        note = QLabel("Higher resolution improves small-code detection but uses more memory and time.")
        note.setWordWrap(True)
        note.setObjectName("secondary")
        form.addRow("", note)
        self._root.addWidget(options)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start Scan")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        if not self.file_paths:
            self.show_error("Add at least one PDF file.")
            return
        page_range = self.pages.text().strip()
        if page_range:
            try:
                from core.pdf_engine import parse_page_range

                parse_page_range(page_range, None)
            except ValueError as exc:
                self.show_error(str(exc))
                return
        self.details = {
            "paths": list(self.file_paths),
            "page_range": page_range,
            "dpi": [150, 200, 300, 400][self.dpi.currentIndex()],
        }
        self.accept()


class BarcodeResultsDialog(ToolDialog):
    def __init__(self, results: list[dict[str, object]], parent=None):
        super().__init__("Barcode / QR Code Results", "barcode-results", parent)
        self.results = results
        summary = QLabel(
            f"{len(results)} code(s) found in {len({str(item.get('path', '')) for item in results})} file(s)."
            if results
            else "No barcodes or QR codes were found. Try a higher scan resolution."
        )
        summary.setObjectName("secondary")
        self._root.addWidget(summary)
        self.table = SortableTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Page", "Type", "Decoded data"])
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for item in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, value in enumerate(
                (item.get("file", ""), item.get("page", ""), item.get("type", ""), item.get("data", ""))
            ):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item.get("path", ""))
                self.table.setItem(row, column, cell)
        self._root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        export_csv = QPushButton("Export CSV…")
        export_csv.clicked.connect(self._export_csv)
        export_excel = QPushButton("Export Excel…")
        export_excel.clicked.connect(self._export_excel)
        actions.addWidget(export_csv)
        actions.addWidget(export_excel)
        actions.addStretch(1)
        self._root.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _export_csv(self) -> None:
        value, _ = QFileDialog.getSaveFileName(
            self,
            "Export barcode results",
            start_in_save_directory(self, "barcode-results.csv"),
            "CSV (*.csv)",
        )
        if not value:
            return
        remember_save_directory(self, value)
        if not value.casefold().endswith(".csv"):
            value += ".csv"
        with Path(value).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["File", "Page", "Type", "Data", "Path"])
            for item in self.results:
                writer.writerow([item.get("file"), item.get("page"), item.get("type"), item.get("data"), item.get("path")])

    def _export_excel(self) -> None:
        value, _ = QFileDialog.getSaveFileName(
            self,
            "Export barcode results",
            start_in_save_directory(self, "barcode-results.xlsx"),
            "Excel (*.xlsx)",
        )
        if not value:
            return
        remember_save_directory(self, value)
        if not value.casefold().endswith(".xlsx"):
            value += ".xlsx"
        try:
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Codes"
            sheet.append(["File", "Page", "Type", "Data", "Path"])
            for item in self.results:
                sheet.append([item.get("file"), item.get("page"), item.get("type"), item.get("data"), item.get("path")])
            sheet.column_dimensions["A"].width = 34
            sheet.column_dimensions["D"].width = 54
            sheet.column_dimensions["E"].width = 72
            workbook.save(value)
        except Exception as exc:
            self.show_error(f"Excel export failed: {exc}")
