"""Detailed compression, merge, and overlay workflows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
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

from core.diagnostics import log_failure

from .base import (
    ToolDialog,
    remember_save_directory,
    start_in_save_directory,
    windows_safe_filename_component,
)


def _track_path_edit(edit: QLineEdit) -> None:
    """Keep long paths usable: full value in the tooltip, tail visible when idle."""
    edit.setToolTip(edit.text())

    def update(text: str) -> None:
        edit.setToolTip(text)
        if not edit.hasFocus() and text:
            # Deferred: moving the cursor inside textChanged re-enters Qt's
            # internal text control and warns "Position out of range".
            QTimer.singleShot(0, lambda: edit.setCursorPosition(len(text)))

    edit.textChanged.connect(update)


class PdfFileTable(QTableWidget):
    filesDropped = pyqtSignal(list)

    @staticmethod
    def _pdf_paths(event) -> list[str]:
        return [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().casefold().endswith(".pdf")
        ]

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["Order", "Filename", "Pages", "Size (MB)", "Modified"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setDefaultSectionSize(32)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # DropOnly mode makes the viewport route drop events to this table
        # (with NoDragDrop the view swallows the drop before our handler).
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event) -> None:
        if self._pdf_paths(event):
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        # QAbstractItemView's default implementation asks its item model if
        # the hovered cell is droppable. A QTableWidget model rejects file
        # URLs, cancelling the eventual drop after dragEnterEvent accepted it.
        if self._pdf_paths(event):
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
        pdfs = self._pdf_paths(event)
        if pdfs:
            self.filesDropped.emit(pdfs)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class CompressionDialog(ToolDialog):
    def __init__(self, current_path: Path | None, parent=None):
        super().__init__("Compress PDF Files", "compress-pdf", parent)
        self.current_path = current_path
        self.details: dict[str, object] | None = None

        source = QGroupBox("Source")
        source_layout = QVBoxLayout(source)
        self.source_group = QButtonGroup(self)
        self.current = QRadioButton("Compress the currently open PDF")
        self.single = QRadioButton("Select one PDF")
        self.folder = QRadioButton("Compress every PDF in a folder")
        for button in (self.current, self.single, self.folder):
            self.source_group.addButton(button)
            source_layout.addWidget(button)
            button.toggled.connect(self._source_changed)
        self.current.setEnabled(bool(current_path))
        self.source_path = QLineEdit()
        self.source_path.setReadOnly(True)
        self.source_path.setPlaceholderText("Current document" if current_path else "Choose a PDF")
        self.source_browse = QPushButton("Browse…")
        self.source_browse.clicked.connect(self._browse_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_path, 1)
        source_row.addWidget(self.source_browse)
        source_layout.addLayout(source_row)
        self.recursive = QCheckBox("Include subfolders")
        source_layout.addWidget(self.recursive)
        self._root.addWidget(source)

        output = QGroupBox("Output settings")
        output_form = QFormLayout(output)
        self.output_folder = QLineEdit()
        self.output_folder.setReadOnly(True)
        output_browse = QPushButton("Browse…")
        output_browse.clicked.connect(self._browse_output)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_folder, 1)
        output_layout.addWidget(output_browse)
        self.suffix = QLineEdit("_compressed")
        self.overwrite = QCheckBox("Overwrite an existing output with the same name")
        output_form.addRow("Output folder", output_row)
        output_form.addRow("Filename suffix", self.suffix)
        output_form.addRow("", self.overwrite)
        self._root.addWidget(output)

        compression = QGroupBox("Compression")
        compression_form = QFormLayout(compression)
        self.level = QComboBox()
        self.level.addItems([
            "Low — fastest",
            "Medium — balanced",
            "High — smaller output",
            "Maximum — rewrite and clean",
        ])
        self.level.setToolTip(
            "Garbage collection level: removes unused objects.\n"
            "Low keeps most structure, Maximum removes everything unused."
        )
        self.level.setCurrentIndex(1)
        compression_form.addRow("Garbage collection level", self.level)
        self.clean = QCheckBox("Clean and rewrite PDF structure")
        self.clean.setToolTip("Reorganize the internal PDF structure for smaller output")
        self.clean.setChecked(True)
        self.deflate = QCheckBox("Compress uncompressed streams")
        self.deflate.setToolTip("Apply deflate compression to uncompressed data streams")
        self.deflate.setChecked(True)
        self.deflate_images = QCheckBox("Compress image streams")
        self.deflate_images.setToolTip("Re-compress images using more efficient encoding")
        self.deflate_images.setChecked(True)
        self.deflate_fonts = QCheckBox("Compress font streams")
        self.deflate_fonts.setToolTip("Compress embedded font data")
        self.deflate_fonts.setChecked(True)
        self.linear = QCheckBox("Optimize for Fast Web View (linearize)")
        self.linear.setToolTip("Restructure PDF for single-page-at-a-time web viewing")
        for control in (self.clean, self.deflate, self.deflate_images, self.deflate_fonts, self.linear):
            compression_form.addRow("", control)
        self._root.addWidget(compression)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start Compression")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        (self.current if current_path else self.single).setChecked(True)
        self._source_changed()

    def _source_changed(self) -> None:
        current = self.current.isChecked()
        self.source_path.setEnabled(not current)
        self.source_browse.setEnabled(not current)
        self.recursive.setEnabled(self.folder.isChecked())

    def _browse_source(self) -> None:
        if self.folder.isChecked():
            value = QFileDialog.getExistingDirectory(self, "Choose folder containing PDFs")
        else:
            value, _ = QFileDialog.getOpenFileName(self, "Choose PDF", "", "PDF (*.pdf)")
        if value:
            self.source_path.setText(value)

    def _browse_output(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if value:
            self.output_folder.setText(value)

    def _validate(self) -> None:
        if self.current.isChecked():
            paths = [self.current_path] if self.current_path else []
        elif self.single.isChecked():
            path = Path(self.source_path.text())
            paths = [path] if path.is_file() and path.suffix.lower() == ".pdf" else []
        else:
            folder = Path(self.source_path.text())
            if not folder.is_dir():
                paths = []
            else:
                iterator = folder.rglob("*") if self.recursive.isChecked() else folder.iterdir()
                paths = sorted(
                    path
                    for path in iterator
                    if path.is_file() and path.suffix.casefold() == ".pdf"
                )
        paths = [Path(path) for path in paths if path]
        if not paths:
            self.show_error("No valid PDF files were found for compression.")
            return
        output = Path(self.output_folder.text()) if self.output_folder.text() else None
        if output and not output.is_dir():
            self.show_error("Choose a valid output folder, or leave it blank to use each source folder.")
            return
        if not self.suffix.text() and not self.overwrite.isChecked():
            self.show_error("Enter a filename suffix or enable overwrite.")
            return
        if self.suffix.text() and not windows_safe_filename_component(self.suffix.text()):
            self.show_error(
                "The filename suffix contains characters Windows file names cannot use."
            )
            return
        self.details = {
            "paths": [str(path) for path in paths],
            "output_folder": str(output) if output else None,
            "suffix": self.suffix.text(),
            "overwrite": self.overwrite.isChecked(),
            "garbage": self.level.currentIndex() + 1,
            "clean": self.clean.isChecked(),
            "deflate": self.deflate.isChecked(),
            "deflate_images": self.deflate_images.isChecked(),
            "deflate_fonts": self.deflate_fonts.isChecked(),
            "linear": self.linear.isChecked(),
        }
        self.accept()


class MergePDFDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("Merge PDF Files", "merge-pdf", parent)
        self.file_paths: list[str] = []
        self._page_counts: dict[str, int] = {}
        self.output_path = ""
        hint = QLabel("Add or drop PDFs, then arrange the exact merge order.")
        hint.setObjectName("secondary")
        self._root.addWidget(hint)
        self.table = PdfFileTable()
        self.table.filesDropped.connect(self.add_paths)
        self._root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for text, callback in (
            ("Add PDFs…", self._add),
            ("Remove", self._remove),
            ("Move up", lambda: self._move(-1)),
            ("Move down", lambda: self._move(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        self.total = QLabel("0 files · 0 pages")
        actions.addWidget(self.total)
        self._root.addLayout(actions)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Merge…")
        buttons.accepted.connect(self._choose_output)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF (*.pdf)")
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        for value in paths:
            path = str(Path(value).resolve())
            if path not in self.file_paths and Path(path).is_file():
                self.file_paths.append(path)
        self._refresh()

    def _remove(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
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

    def _refresh(self) -> None:
        self.table.setRowCount(0)
        total_pages = 0
        for index, value in enumerate(self.file_paths, 1):
            path = Path(value)
            pages = self._page_count(value)
            total_pages += pages
            row = self.table.rowCount()
            self.table.insertRow(row)
            modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            values = (index, path.name, pages, f"{path.stat().st_size / 1048576:.2f}", modified)
            for column, item in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(item)))
        self.total.setText(f"{len(self.file_paths)} files · {total_pages} pages")

    def drop_extensions(self) -> set[str] | None:
        return {".pdf"}

    def add_dropped_paths(self, paths: list[str]) -> None:
        self.add_paths(paths)

    def _page_count(self, path: str) -> int:
        """Cached page count; opening every PDF on each refresh is wasteful."""
        if path not in self._page_counts:
            try:
                with fitz.open(path) as document:
                    self._page_counts[path] = document.page_count
            except Exception:
                log_failure('batch_tools._page_count: fallback after failure', 10)
                self._page_counts[path] = 0
        return self._page_counts[path]

    def _choose_output(self) -> None:
        if len(self.file_paths) < 2:
            self.show_error("Add at least two PDF files.")
            return
        output, _ = QFileDialog.getSaveFileName(
            self, "Save merged PDF", start_in_save_directory(self, "merged.pdf"), "PDF (*.pdf)"
        )
        if output:
            self.output_path = output if output.lower().endswith(".pdf") else f"{output}.pdf"
            remember_save_directory(self, self.output_path)
            self.accept()


class OverlayDialog(ToolDialog):
    def __init__(self, current_path: Path | None, parent=None):
        super().__init__("PDF Overlay", "overlay-pdf", parent)
        self.current_path = current_path
        self.details: dict[str, object] | None = None
        form = QFormLayout()
        self.template = QLineEdit()
        self.template.setReadOnly(True)
        form.addRow("Template PDF", self._picker(self.template, False, "Choose template PDF"))
        self.target_mode = QComboBox()
        self.target_mode.addItems(["Current PDF", "One PDF", "Folder (batch)"])
        if not current_path:
            self.target_mode.setCurrentIndex(1)
            self.target_mode.model().item(0).setEnabled(False)
        self.target_mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Target mode", self.target_mode)
        self.target = QLineEdit()
        self.target.setReadOnly(True)
        form.addRow("Target", self._picker(self.target, True, "Choose target"))
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        form.addRow("Output folder", self._picker(self.output, True, "Choose output folder", always_folder=True))
        self.suffix = QLineEdit("_overlay")
        form.addRow("Filename suffix", self.suffix)
        self.recursive = QCheckBox("Include PDFs in subfolders")
        form.addRow("", self.recursive)
        self.overwrite = QCheckBox("Overwrite existing output files")
        form.addRow("", self.overwrite)
        group = QGroupBox("Overlay settings")
        group.setLayout(form)
        self._root.addWidget(group)
        note = QLabel("The template is placed over every target page. Its last page repeats if needed.")
        note.setObjectName("secondary")
        note.setWordWrap(True)
        self._root.addWidget(note)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Overlay")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self._mode_changed()

    def _picker(self, edit: QLineEdit, target: bool, title: str, always_folder: bool = False) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        edit.setMinimumWidth(240)
        _track_path_edit(edit)
        button = QPushButton("Browse…")

        def browse() -> None:
            folder_mode = always_folder or (target and self.target_mode.currentIndex() == 2)
            if folder_mode:
                value = QFileDialog.getExistingDirectory(self, title, edit.text())
            else:
                value, _ = QFileDialog.getOpenFileName(self, title, edit.text(), "PDF (*.pdf)")
            if value:
                edit.setText(value)

        button.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return container

    def _mode_changed(self) -> None:
        current = self.target_mode.currentIndex() == 0
        self.target.setEnabled(not current)
        self.recursive.setEnabled(self.target_mode.currentIndex() == 2)

    def _validate(self) -> None:
        template = Path(self.template.text())
        output = Path(self.output.text())
        if not template.is_file():
            self.show_error("Choose a valid template PDF.")
            return
        if not output.is_dir():
            self.show_error("Choose a valid output folder.")
            return
        mode = self.target_mode.currentIndex()
        if mode == 0:
            targets = [self.current_path] if self.current_path else []
        elif mode == 1:
            path = Path(self.target.text())
            targets = [path] if path.is_file() else []
        else:
            folder = Path(self.target.text())
            iterator = (
                folder.rglob("*")
                if folder.is_dir() and self.recursive.isChecked()
                else folder.iterdir()
                if folder.is_dir()
                else []
            )
            targets = [
                path
                for path in iterator
                if path.is_file() and path.suffix.casefold() == ".pdf"
            ]
        targets = [Path(path) for path in targets if path and Path(path).resolve() != template.resolve()]
        if not targets:
            self.show_error("No target PDF files were selected.")
            return
        if not self.suffix.text() and not self.overwrite.isChecked():
            self.show_error("Enter a suffix or enable overwrite.")
            return
        if self.suffix.text() and not windows_safe_filename_component(self.suffix.text()):
            self.show_error(
                "The filename suffix contains characters Windows file names cannot use."
            )
            return
        self.details = {
            "template": str(template),
            "targets": [str(path) for path in targets],
            "output_folder": str(output),
            "suffix": self.suffix.text(),
            "overwrite": self.overwrite.isChecked(),
        }
        self.accept()
