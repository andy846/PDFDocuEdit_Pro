"""Legacy-compatible detailed batch conversion option dialogs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .base import (
    PathLineEdit,
    ToolDialog,
    last_save_directory,
    remember_save_directory,
    windows_safe_filename_component,
)


class BatchFileTable(QTableWidget):
    filesDropped = pyqtSignal(list)

    def _local_paths(self, event) -> list[Path]:
        return [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]

    def _can_drop(self, event) -> bool:
        return any(
            path.is_dir() or path.suffix.casefold() in self.extensions
            for path in self._local_paths(event)
        )

    def _dropped_paths(self, event) -> list[str]:
        paths: list[str] = []
        for path in self._local_paths(event):
            if path.is_dir():
                paths.extend(str(item) for item in path.iterdir() if item.is_file() and item.suffix.casefold() in self.extensions)
            elif path.suffix.casefold() in self.extensions:
                paths.append(str(path))
        return paths

    def __init__(self, extensions: set[str], parent=None):
        super().__init__(0, 4, parent)
        self.extensions = extensions
        self.setHorizontalHeaderLabels(["Order", "Filename", "Size (MB)", "Modified"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # DropOnly mode makes the viewport route drop events to this table.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)
        self.verticalHeader().setDefaultSectionSize(32)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

    def dragEnterEvent(self, event) -> None:
        if self._can_drop(event):
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        # QAbstractItemView otherwise asks its model about the hovered cell;
        # its model rejects external file URLs and cancels the final drop.
        if self._can_drop(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        values = self._dropped_paths(event)
        paths: list[str] = []
        for value in values:
            path = Path(value)
            if path.is_dir():
                paths.extend(
                    str(item)
                    for item in path.iterdir()
                    if item.is_file() and item.suffix.lower() in self.extensions
                )
            elif path.suffix.lower() in self.extensions:
                paths.append(str(path))
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()


class FileListDialog(ToolDialog):
    """Base for batch conversion dialogs with sorting and drag-and-drop."""

    def __init__(self, title: str, key: str, extensions: set[str], filter_: str, parent=None):
        super().__init__(title, key, parent)
        self.extensions = extensions
        self.filter = filter_
        self.file_paths: list[str] = []
        self.table = BatchFileTable(extensions)
        self.table.filesDropped.connect(self.add_paths)
        self._root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for label, callback in (
            ("Add files…", self._add_files),
            ("Add folder…", self._add_folder),
            ("Remove", self._remove),
            ("Move up", lambda: self._move(-1)),
            ("Move down", lambda: self._move(1)),
            ("Clear", self._clear),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        self.total = QLabel("0 files")
        actions.addWidget(self.total)
        self._root.addLayout(actions)

    def drop_extensions(self) -> set[str] | None:
        return self.extensions

    def add_dropped_paths(self, paths: list[str]) -> None:
        self.add_paths(paths)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", self.filter)
        self.add_paths(paths)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import folder")
        if folder:
            self.add_paths(
                [str(path) for path in Path(folder).iterdir() if path.suffix.lower() in self.extensions]
            )

    def add_paths(self, paths: list[str]) -> None:
        for value in paths:
            path = Path(value).expanduser().resolve()
            if path.is_file() and path.suffix.lower() in self.extensions and str(path) not in self.file_paths:
                self.file_paths.append(str(path))
        self._refresh()

    def _remove(self) -> None:
        rows = sorted({row.row() for row in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.file_paths.pop(row)
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
        self._refresh()

    def _refresh(self) -> None:
        self.table.setRowCount(0)
        for index, value in enumerate(self.file_paths, 1):
            path = Path(value)
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                index,
                path.name,
                f"{path.stat().st_size / 1048576:.2f}",
                datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(item)))
        self.total.setText(f"{len(self.file_paths)} files")

    @staticmethod
    def folder_picker(edit: QLineEdit, title: str) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        edit.setMinimumWidth(240)
        button = QPushButton("Browse…")

        def browse() -> None:
            start = edit.path() or last_save_directory(container)
            value = QFileDialog.getExistingDirectory(container, title, start)
            if value:
                remember_save_directory(container, value)
                edit.setText(value)

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return container


class OfficeConversionDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("Batch Convert Office Files to PDF", "office-to-pdf", parent)
        self.details: dict[str, object] | None = None
        folders = QGroupBox("Folders")
        form = QFormLayout(folders)
        self.source = PathLineEdit()
        self.output = PathLineEdit()
        form.addRow("Source folder", FileListDialog.folder_picker(self.source, "Choose source folder"))
        form.addRow("Output folder", FileListDialog.folder_picker(self.output, "Choose output folder"))
        self.recursive = QCheckBox("Include subfolders")
        form.addRow("", self.recursive)
        self._root.addWidget(folders)

        types = QGroupBox("File types")
        row = QHBoxLayout(types)
        self.word = QCheckBox("Word (.doc, .docx)")
        self.excel = QCheckBox("Excel (.xls, .xlsx)")
        self.powerpoint = QCheckBox("PowerPoint (.ppt, .pptx)")
        for box in (self.word, self.excel, self.powerpoint):
            box.setChecked(True)
            row.addWidget(box)
        self._root.addWidget(types)
        options = QGroupBox("Output options")
        options_layout = QVBoxLayout(options)
        self.overwrite = QCheckBox("Overwrite existing PDF files")
        self.keep_structure = QCheckBox("Recreate source subfolders in the output folder")
        options_layout.addWidget(self.overwrite)
        options_layout.addWidget(self.keep_structure)
        self._root.addWidget(options)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start Conversion")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        source = Path(self.source.path())
        output = Path(self.output.path())
        if (
            not self.source.path().strip()
            or not self.output.path().strip()
            or not source.is_dir()
            or not output.is_dir()
        ):
            self.show_error("Choose valid source and output folders.")
            return
        extensions: set[str] = set()
        if self.word.isChecked():
            extensions.update({".doc", ".docx"})
        if self.excel.isChecked():
            extensions.update({".xls", ".xlsx"})
        if self.powerpoint.isChecked():
            extensions.update({".ppt", ".pptx"})
        if not extensions:
            self.show_error("Select at least one Office file type.")
            return
        iterator = source.rglob("*") if self.recursive.isChecked() else source.glob("*")
        paths = sorted(path for path in iterator if path.is_file() and path.suffix.lower() in extensions)
        if not paths:
            self.show_error("No matching Office files were found.")
            return
        self.details = {
            "paths": [str(path) for path in paths],
            "source_folder": str(source),
            "output_folder": str(output),
            "overwrite": self.overwrite.isChecked(),
            "keep_structure": self.keep_structure.isChecked(),
        }
        self.accept()


class TextConversionDialog(FileListDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Batch Convert Text Files to PDF",
            "text-to-pdf",
            {".txt"},
            "Text files (*.txt)",
            parent,
        )
        self.details: dict[str, object] | None = None
        output = QGroupBox("Output")
        form = QFormLayout(output)
        self.single = QRadioButton("Combine all text files into one PDF")
        self.separate = QRadioButton("Create one PDF for each text file")
        self.single.setChecked(True)
        self.output_file = QLineEdit("text-files.pdf")
        self.output_folder = PathLineEdit()
        form.addRow(self.single)
        form.addRow(self.separate)
        form.addRow("Combined filename", self.output_file)
        form.addRow("Output folder", self.folder_picker(self.output_folder, "Choose output folder"))
        self.encoding = QComboBox()
        self.encoding.addItems(["Auto detect", "UTF-8", "Traditional Chinese (Big5)", "Simplified Chinese (GB18030)"])
        form.addRow("Text encoding", self.encoding)
        self.overwrite = QCheckBox("Overwrite existing files")
        form.addRow("", self.overwrite)
        self.separate.toggled.connect(lambda value: self.output_file.setEnabled(not value))
        self._root.addWidget(output)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create PDF")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        folder = Path(self.output_folder.path())
        if not self.file_paths:
            self.show_error("Add at least one text file.")
            return
        if not self.output_folder.path().strip() or not folder.is_dir():
            self.show_error("Choose a valid output folder.")
            return
        filename = self.output_file.text().strip()
        if self.single.isChecked() and not filename:
            self.show_error("Enter a filename for the combined PDF.")
            return
        if filename and not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        self.details = {
            "paths": list(self.file_paths),
            "output_folder": str(folder),
            "single": self.single.isChecked(),
            "filename": filename,
            "encoding": self.encoding.currentIndex(),
            "overwrite": self.overwrite.isChecked(),
        }
        self.accept()


class PostScriptConversionDialog(FileListDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Batch Convert PostScript to PDF",
            "postscript-to-pdf",
            {".ps", ".eps"},
            "PostScript (*.ps *.eps)",
            parent,
        )
        self.details: dict[str, object] | None = None
        output = QGroupBox("Output settings")
        form = QFormLayout(output)
        self.output_folder = PathLineEdit()
        form.addRow("Output folder", self.folder_picker(self.output_folder, "Choose output folder"))
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("Optional filename prefix")
        form.addRow("Filename prefix", self.prefix)
        self.overwrite = QCheckBox("Overwrite existing PDF files")
        form.addRow("", self.overwrite)
        self._root.addWidget(output)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start Conversion")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        folder = Path(self.output_folder.path())
        if not self.file_paths:
            self.show_error("Add at least one PostScript file.")
            return
        if not self.output_folder.path().strip() or not folder.is_dir():
            self.show_error("Choose a valid output folder.")
            return
        prefix = self.prefix.text().strip()
        if prefix and not windows_safe_filename_component(prefix):
            self.show_error(
                "The filename prefix contains characters Windows file names cannot use."
            )
            return
        self.details = {
            "paths": list(self.file_paths),
            "output_folder": str(folder),
            "prefix": prefix,
            "overwrite": self.overwrite.isChecked(),
        }
        self.accept()
