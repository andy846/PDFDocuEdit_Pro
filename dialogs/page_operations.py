"""Detailed legacy-compatible page-operation option dialogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QButtonGroup,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.pdf_engine import parse_page_range

from .base import ToolDialog, windows_safe_filename_component


class PagePatternWidget(QWidget):
    """Odd/even/multiple/custom/periodic page rule used by extract/delete."""

    def __init__(self, verb: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)

        predefined = QGroupBox("Predefined options")
        predefined_layout = QHBoxLayout(predefined)
        self.odd = QRadioButton(f"{verb} odd-numbered pages")
        self.even = QRadioButton(f"{verb} even-numbered pages")
        predefined_layout.addWidget(self.odd)
        predefined_layout.addWidget(self.even)
        layout.addWidget(predefined)

        multiple = QGroupBox("Page multiples")
        multiple_form = QFormLayout(multiple)
        self.multiple = QRadioButton(f"{verb} every Nth page")
        self.multiple_value = QSpinBox()
        self.multiple_value.setRange(2, 99999)
        self.multiple_value.setEnabled(False)
        self.multiple.toggled.connect(self.multiple_value.setEnabled)
        multiple_form.addRow(self.multiple, self.multiple_value)
        layout.addWidget(multiple)

        custom = QGroupBox("Custom page selection")
        custom_form = QFormLayout(custom)
        self.custom = QRadioButton("Use page numbers and ranges")
        self.custom_value = QLineEdit()
        self.custom_value.setPlaceholderText("e.g. 1, 3, 5-8")
        self.custom_value.setToolTip(
            "Page syntax: comma-separated numbers and ranges.\n"
            "Examples: '1,3,5-8' or the keywords 'all', 'odd' or 'even'."
        )
        self.custom_value.setEnabled(False)
        self.custom.toggled.connect(self.custom_value.setEnabled)
        custom_form.addRow(self.custom)
        custom_form.addRow("Pages", self.custom_value)
        layout.addWidget(custom)

        periodic = QGroupBox("Periodic pattern")
        periodic_layout = QVBoxLayout(periodic)
        self.periodic = QRadioButton(f"From page N, {verb.lower()} Z pages, then skip X pages")
        periodic_layout.addWidget(self.periodic)
        periodic_form = QFormLayout()
        self.start = QSpinBox()
        self.start.setRange(1, 999999)
        self.skip = QSpinBox()
        self.skip.setRange(0, 999999)
        self.skip.setValue(1)
        self.take = QSpinBox()
        self.take.setRange(1, 999999)
        for control in (self.start, self.skip, self.take):
            control.setEnabled(False)
        self.periodic.toggled.connect(self.start.setEnabled)
        self.periodic.toggled.connect(self.skip.setEnabled)
        self.periodic.toggled.connect(self.take.setEnabled)
        periodic_form.addRow("Start page N", self.start)
        periodic_form.addRow("Skip X pages", self.skip)
        periodic_form.addRow(f"{verb} Z pages", self.take)
        periodic_layout.addLayout(periodic_form)
        layout.addWidget(periodic)

        for button in (self.odd, self.even, self.multiple, self.custom, self.periodic):
            self.group.addButton(button)
        self.custom.setChecked(True)
        self.custom_value.setText("all")  # a usable default: no blank range
        layout.addStretch(1)

    def pages(self, page_count: int) -> list[int]:
        if self.odd.isChecked():
            return list(range(0, page_count, 2))
        if self.even.isChecked():
            return list(range(1, page_count, 2))
        if self.multiple.isChecked():
            value = self.multiple_value.value()
            return [index for index in range(page_count) if (index + 1) % value == 0]
        if self.custom.isChecked():
            return parse_page_range(self.custom_value.text(), page_count)
        if self.periodic.isChecked():
            pages: list[int] = []
            current = self.start.value() - 1
            while current < page_count:
                pages.extend(range(current, min(current + self.take.value(), page_count)))
                current += self.take.value() + self.skip.value()
            return sorted(set(pages))
        return []


class PageSelectionDialog(ToolDialog):
    def __init__(self, verb: str, page_count: int, parent=None):
        super().__init__(f"{verb} Pages", f"{verb.lower()}-pages", parent)
        self.page_count = page_count
        self.selected_pages: list[int] = []
        description = QLabel(
            f"Choose a detailed rule for {verb.lower()}ing pages. This document contains {page_count} pages."
        )
        description.setObjectName("secondary")
        description.setWordWrap(True)
        self._root.addWidget(description)
        self.pattern = PagePatternWidget(verb)
        self._root.addWidget(self.pattern, 1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(verb)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        try:
            pages = self.pattern.pages(self.page_count)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if not pages:
            self.show_error("The selected rule does not match any pages.")
            return
        self.selected_pages = pages
        self.accept()


class InsertPagesDialog(ToolDialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__("Insert Pages", "insert-pages", parent)
        self.page_count = page_count
        self.details: dict[str, object] | None = None
        intro = QLabel("Insert selected pages once, repeat a page throughout the document, or create blank pages.")
        intro.setObjectName("secondary")
        intro.setWordWrap(True)
        self._root.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._single_tab(), "Insert from file")
        self.tabs.addTab(self._repeat_tab(), "Repeat from file")
        self.tabs.addTab(self._blank_tab(), "Blank pages")
        self._root.addWidget(self.tabs, 1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Insert")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _file_picker(self, edit: QLineEdit) -> QWidget:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        edit.setReadOnly(True)
        edit.setPlaceholderText("Choose a source PDF")
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_pdf(edit))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return container

    def _position_fields(self, combo: QComboBox, spin: QSpinBox, form: QFormLayout) -> None:
        combo.addItems(["Beginning", "End", "Before page"])
        # "Before page" must not exceed the last page: page_count + 1 would
        # silently duplicate the "End" option.
        spin.setRange(1, max(1, self.page_count))
        spin.setEnabled(False)
        combo.currentIndexChanged.connect(lambda index: spin.setEnabled(index == 2))
        form.addRow("Insert position", combo)
        form.addRow("Target page", spin)

    def _single_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.single_path = QLineEdit()
        self.single_path.setToolTip("Path to the source PDF whose pages will be inserted")
        form.addRow("Source PDF", self._file_picker(self.single_path))
        self.single_pages = QLineEdit()
        self.single_pages.setPlaceholderText("Leave blank for all pages; e.g. 1,3,5-7")
        self.single_pages.setToolTip("Pages from the source PDF. Leave blank to insert all pages.")
        form.addRow("Source pages", self.single_pages)
        self.single_position = QComboBox()
        self.single_target = QSpinBox()
        self._position_fields(self.single_position, self.single_target, form)
        return tab

    def _repeat_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.repeat_path = QLineEdit()
        form.addRow("Source PDF", self._file_picker(self.repeat_path))
        self.repeat_pages = QLineEdit()
        self.repeat_pages.setPlaceholderText("Usually one page; e.g. 1")
        form.addRow("Pages to repeat", self.repeat_pages)
        self.repeat_interval = QSpinBox()
        self.repeat_interval.setRange(1, 99999)
        form.addRow("Insert after every N pages", self.repeat_interval)
        return tab

    def _blank_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.blank_count = QSpinBox()
        self.blank_count.setRange(1, 1000)
        form.addRow("Number of blank pages", self.blank_count)
        self.blank_size = QComboBox()
        self.blank_size.addItems(["Same as current page", "A4", "A3", "Letter"])
        form.addRow("Page size", self.blank_size)
        self.blank_orientation = QComboBox()
        self.blank_orientation.addItems(["Portrait", "Landscape"])
        form.addRow("Orientation", self.blank_orientation)
        self.blank_position = QComboBox()
        self.blank_target = QSpinBox()
        self._position_fields(self.blank_position, self.blank_target, form)
        return tab

    def _browse_pdf(self, edit: QLineEdit) -> None:
        value, _ = QFileDialog.getOpenFileName(self, "Choose source PDF", "", "PDF (*.pdf)")
        if value:
            edit.setText(value)

    def _target_position(self, combo: QComboBox, spin: QSpinBox) -> int:
        if combo.currentIndex() == 0:
            return 0
        if combo.currentIndex() == 1:
            return self.page_count
        return spin.value() - 1

    def _validate(self) -> None:
        tab = self.tabs.currentIndex()
        try:
            if tab == 0:
                source = Path(self.single_path.text())
                if not source.is_file():
                    raise ValueError("Choose a valid source PDF.")
                import fitz

                with fitz.open(source) as document:
                    pages = (
                        parse_page_range(self.single_pages.text(), document.page_count)
                        if self.single_pages.text().strip()
                        else list(range(document.page_count))
                    )
                if not pages:
                    raise ValueError("No source pages match the page range.")
                self.details = {
                    "mode": "single",
                    "source": str(source),
                    "pages": pages,
                    "position": self._target_position(self.single_position, self.single_target),
                }
            elif tab == 1:
                source = Path(self.repeat_path.text())
                if not source.is_file():
                    raise ValueError("Choose a valid source PDF.")
                import fitz

                with fitz.open(source) as document:
                    pages = parse_page_range(self.repeat_pages.text(), document.page_count)
                if not pages:
                    raise ValueError("Enter at least one valid source page to repeat.")
                self.details = {
                    "mode": "repeat",
                    "source": str(source),
                    "pages": pages,
                    "interval": self.repeat_interval.value(),
                }
            else:
                self.details = {
                    "mode": "blank",
                    "count": self.blank_count.value(),
                    "size": self.blank_size.currentText(),
                    "orientation": self.blank_orientation.currentText(),
                    "position": self._target_position(self.blank_position, self.blank_target),
                }
        except (ValueError, OSError, RuntimeError) as exc:
            self.show_error(str(exc))
            return
        self.accept()


class SplitDialog(ToolDialog):
    def __init__(self, page_count: int, suggested_prefix: str, parent=None):
        super().__init__("Split PDF", "split-pdf", parent)
        self.page_count = page_count
        self.details: dict[str, object] | None = None
        self.group = QButtonGroup(self)

        predefined = QGroupBox("Predefined output")
        predefined_layout = QVBoxLayout(predefined)
        self.every_page = QRadioButton("Export every page as a separate PDF")
        self.odd_pages = QRadioButton("Export odd-numbered pages as separate PDFs")
        self.even_pages = QRadioButton("Export even-numbered pages as separate PDFs")
        for button in (self.every_page, self.odd_pages, self.even_pages):
            self.group.addButton(button)
            predefined_layout.addWidget(button)
        self._root.addWidget(predefined)

        ranges = QGroupBox("Split points and intervals")
        ranges_form = QFormLayout(ranges)
        self.custom = QRadioButton("Split after specified pages")
        self.custom_value = QLineEdit()
        self.custom_value.setPlaceholderText("e.g. 3, 5, 10")
        self.custom_value.setEnabled(False)
        self.custom.toggled.connect(self.custom_value.setEnabled)
        self.every_n = QRadioButton("Create one file for every N pages")
        self.every_n_value = QSpinBox()
        self.every_n_value.setRange(1, max(1, page_count))
        self.every_n_value.setEnabled(False)
        self.every_n.toggled.connect(self.every_n_value.setEnabled)
        self.group.addButton(self.custom)
        self.group.addButton(self.every_n)
        ranges_form.addRow(self.custom)
        ranges_form.addRow("Split after pages", self.custom_value)
        ranges_form.addRow(self.every_n, self.every_n_value)
        self._root.addWidget(ranges)

        output = QGroupBox("Output settings")
        output_form = QFormLayout(output)
        self.output_folder = QLineEdit()
        self.output_folder.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_folder)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.output_folder, 1)
        folder_layout.addWidget(browse)
        self.prefix = QLineEdit(suggested_prefix)
        self.overwrite = QCheckBox("Replace existing split files with the same names")
        output_form.addRow("Destination", folder_row)
        output_form.addRow("Filename prefix", self.prefix)
        output_form.addRow("", self.overwrite)
        self._root.addWidget(output)
        self.every_page.setChecked(True)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Split")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _browse_folder(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_folder.text())
        if value:
            self.output_folder.setText(value)

    def _validate(self) -> None:
        if not self.output_folder.text().strip():
            self.show_error("Choose an output folder.")
            return
        folder = Path(self.output_folder.text())
        if not folder.is_dir():
            self.show_error("Choose a valid output folder.")
            return
        prefix = self.prefix.text().strip()
        if not prefix:
            self.show_error("Enter a filename prefix.")
            return
        if not windows_safe_filename_component(prefix):
            self.show_error(
                "The filename prefix contains characters Windows file names cannot use."
            )
            return
        try:
            if self.every_page.isChecked():
                ranges = [(page, page) for page in range(self.page_count)]
            elif self.odd_pages.isChecked():
                ranges = [(page, page) for page in range(0, self.page_count, 2)]
            elif self.even_pages.isChecked():
                ranges = [(page, page) for page in range(1, self.page_count, 2)]
            elif self.every_n.isChecked():
                every = self.every_n_value.value()
                ranges = [
                    (start, min(start + every - 1, self.page_count - 1))
                    for start in range(0, self.page_count, every)
                ]
            else:
                points = parse_page_range(self.custom_value.text(), self.page_count)
                if not points:
                    self.show_error("Enter the pages to split after, e.g. 3 or 2,4.")
                    return
                starts = [0]
                ranges = []
                for point in points:
                    boundary = point + 1
                    if boundary > starts[-1]:
                        ranges.append((starts[-1], boundary - 1))
                        starts.append(boundary)
                if starts[-1] < self.page_count:
                    ranges.append((starts[-1], self.page_count - 1))
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if not ranges:
            self.show_error("The selected split rule creates no files.")
            return
        self.details = {
            "folder": str(folder),
            "prefix": prefix,
            "ranges": ranges,
            "overwrite": self.overwrite.isChecked(),
        }
        self.accept()
