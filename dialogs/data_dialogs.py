"""Detailed report generation and CSV / Excel merge dialogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from .base import (
    PathLineEdit,
    ToolDialog,
    remember_save_directory,
    start_in_save_directory,
)


def _folder_picker(edit: QLineEdit, title: str) -> QWidget:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    edit.setMinimumWidth(240)
    button = QPushButton("Browse…")

    def browse() -> None:
        value = QFileDialog.getExistingDirectory(container, title, edit.path())
        if value:
            edit.setText(value)

    button.clicked.connect(browse)
    row.addWidget(edit, 1)
    row.addWidget(button)
    return container


def _save_picker(edit: QLineEdit, title: str, filter_: str) -> QWidget:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    edit.setMinimumWidth(240)
    button = QPushButton("Browse…")

    def browse() -> None:
        current = edit.path()
        start = (
            current
            if current and Path(current).is_absolute()
            else start_in_save_directory(container, Path(current).name or "output")
        )
        value, _ = QFileDialog.getSaveFileName(container, title, start, filter_)
        if value:
            remember_save_directory(container, value)
            edit.setText(value)

    button.clicked.connect(browse)
    row.addWidget(edit, 1)
    row.addWidget(button)
    return container


class PageCountReportDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("PDF Page Count Report", "page-count-report", parent)
        self.details: dict[str, object] | None = None
        group = QGroupBox("Report source and output")
        form = QFormLayout(group)
        self.folder = PathLineEdit()
        # Prefill with a full path (last Save-As folder) so the validation
        # passes without forcing the user to browse first.
        self.output = PathLineEdit()
        self.output.setText(start_in_save_directory(self, "PDF-page-report.xlsx"))
        form.addRow("PDF folder", _folder_picker(self.folder, "Choose PDF folder"))
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        form.addRow("", self.recursive)
        form.addRow("Excel report", _save_picker(self.output, "Save report", "Excel (*.xlsx)"))
        self._root.addWidget(group)
        fields = QLabel("The report includes filename, page count, byte size, first-page dimensions, and full path.")
        fields.setWordWrap(True)
        fields.setObjectName("secondary")
        self._root.addWidget(fields)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create Report")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        folder = Path(self.folder.path())
        output = Path(self.output.path())
        if not self.folder.path().strip() or not folder.is_dir():
            self.show_error("Choose a valid folder containing PDF files.")
            return
        iterator = folder.rglob("*") if self.recursive.isChecked() else folder.iterdir()
        if not any(
            path.is_file() and path.suffix.casefold() == ".pdf" for path in iterator
        ):
            self.show_error("No PDF files were found with the selected settings.")
            return
        if not self.output.path().strip() or not output.is_absolute() or not output.parent.is_dir():
            self.show_error("Choose a valid Excel report location.")
            return
        if output.suffix.lower() != ".xlsx":
            output = output.with_suffix(".xlsx")
        self.details = {
            "folder": str(folder),
            "output": str(output),
            "recursive": self.recursive.isChecked(),
        }
        self.accept()


class SpreadsheetMergeDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("Merge CSV and Excel Files", "merge-spreadsheets", parent)
        self.details: dict[str, object] | None = None
        io = QGroupBox("Input and output")
        form = QFormLayout(io)
        self.input_folder = PathLineEdit()
        self.output = PathLineEdit()
        self.output.setText(start_in_save_directory(self, "merged.xlsx"))
        form.addRow("Input folder", _folder_picker(self.input_folder, "Choose input folder"))
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        form.addRow("", self.recursive)
        form.addRow("Output file", _save_picker(self.output, "Save merged data", "Excel (*.xlsx);;CSV (*.csv)"))
        self._root.addWidget(io)

        formats = QGroupBox("File formats")
        format_row = QHBoxLayout(formats)
        self.csv = QCheckBox("CSV (.csv)")
        self.xlsx = QCheckBox("Excel (.xlsx)")
        self.xls = QCheckBox("Legacy Excel (.xls)")
        self.xls.setToolTip("Read legacy Excel 97-2003 workbooks.")
        self.csv.setChecked(True)
        format_row.addWidget(self.csv)
        format_row.addWidget(self.xlsx)
        format_row.addWidget(self.xls)
        self._root.addWidget(formats)

        options = QGroupBox("Merge rules")
        options_form = QFormLayout(options)
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 100000)
        self.skip_rows.setValue(2)  # legacy PDFDocuEdit Pro default
        self.keywords = QLineEdit()
        self.keywords.setPlaceholderText("e.g. Total, Subtotal, Summary")
        self.first_cell = QRadioButton("Check only the first cell")
        self.entire_row = QRadioButton("Check every cell in the row")
        self.first_cell.setChecked(True)
        check_row = QWidget()
        check_layout = QHBoxLayout(check_row)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.addWidget(self.first_cell)
        check_layout.addWidget(self.entire_row)
        self.encoding = QComboBox()
        self.encoding.addItem("Auto detect", "auto")
        self.encoding.addItem("UTF-8", "utf-8")
        self.encoding.addItem("Traditional Chinese (Big5)", "big5")
        self.encoding.addItem("Simplified Chinese (GB18030)", "gb18030")
        self.encoding.addItem("Western (ISO-8859-1)", "iso-8859-1")
        self.encoding.addItem("Western (Windows-1252)", "windows-1252")
        self.encoding.addItem("ASCII", "ascii")
        options_form.addRow("Skip leading rows", self.skip_rows)
        options_form.addRow("Exclude rows starting with", self.keywords)
        options_form.addRow("Exclusion scope", check_row)
        options_form.addRow("CSV encoding", self.encoding)
        self._root.addWidget(options)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Merge Files")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        folder = Path(self.input_folder.path())
        output = Path(self.output.path())
        if not self.input_folder.path().strip() or not folder.is_dir():
            self.show_error("Choose a valid input folder.")
            return
        extensions: set[str] = set()
        if self.csv.isChecked():
            extensions.add(".csv")
        if self.xlsx.isChecked():
            extensions.add(".xlsx")
        if self.xls.isChecked():
            extensions.add(".xls")
        if not extensions:
            self.show_error("Select at least one file format.")
            return
        iterator = folder.rglob("*") if self.recursive.isChecked() else folder.glob("*")
        paths = sorted(path for path in iterator if path.is_file() and path.suffix.lower() in extensions)
        if not paths:
            self.show_error("No matching CSV or Excel files were found.")
            return
        if not self.output.path().strip() or not output.is_absolute() or not output.parent.is_dir():
            self.show_error("Choose a valid output location.")
            return
        if output.suffix.lower() not in {".csv", ".xlsx"}:
            output = output.with_suffix(".xlsx")
        paths = [path for path in paths if path.resolve() != output.resolve()]
        if not paths:
            self.show_error("The output file cannot also be the only input file.")
            return
        self.details = {
            "paths": [str(path) for path in paths],
            "output": str(output),
            "skip_rows": self.skip_rows.value(),
            "exclude_keywords": [value.strip() for value in self.keywords.text().split(",") if value.strip()],
            "first_cell_only": self.first_cell.isChecked(),
            "encoding": str(self.encoding.currentData()),
        }
        self.accept()
