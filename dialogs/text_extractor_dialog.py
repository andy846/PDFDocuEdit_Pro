"""Visual page-region text extraction workflow."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
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
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.pdf_engine import parse_page_range

from .base import ToolDialog, remember_save_directory, start_in_save_directory


class RegionLabel(QLabel):
    selectionChanged = pyqtSignal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._start: QPoint | None = None
        self._selection = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_selection(self, selection: QRect) -> None:
        self._selection = selection.normalized()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect(self._start, self._start)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._selection = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._selection = QRect(self._start, event.position().toPoint()).normalized()
            self._start = None
            if self._selection.width() > 3 and self._selection.height() > 3:
                self.selectionChanged.emit(self._selection)
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._selection.isNull():
            painter = QPainter(self)
            painter.fillRect(self._selection, QColor(0, 122, 255, 48))
            painter.setPen(QPen(QColor(0, 122, 255), 2))
            painter.drawRect(self._selection)


class TextExtractorDialog(ToolDialog):
    def __init__(self, document: fitz.Document, current_page: int, suggested: str, parent=None):
        super().__init__("Extract Text from a Selected Region", "extract-region-text", parent)
        self.document = document
        self.current_page = current_page
        self.zoom = 1.25
        self.pdf_rect: fitz.Rect | None = None
        self.details: dict[str, object] | None = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        controls = QWidget()
        controls.setMinimumWidth(430)
        control_layout = QVBoxLayout(controls)
        preview_group = QGroupBox("Preview and region")
        preview_form = QFormLayout(preview_group)
        page_row = QWidget()
        page_layout = QHBoxLayout(page_row)
        page_layout.setContentsMargins(0, 0, 0, 0)
        previous = QPushButton("Previous")
        previous.clicked.connect(lambda: self._change_page(-1))
        self.page = QSpinBox()
        self.page.setRange(1, document.page_count)
        self.page.setValue(current_page + 1)
        self.page.valueChanged.connect(self._page_changed)
        next_ = QPushButton("Next")
        next_.clicked.connect(lambda: self._change_page(1))
        page_layout.addWidget(previous)
        page_layout.addWidget(self.page)
        page_layout.addWidget(next_)
        zoom_row = QWidget()
        zoom_layout = QHBoxLayout(zoom_row)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_out = QPushButton("−")
        zoom_out.clicked.connect(lambda: self._change_zoom(-0.25))
        self.zoom_label = QLabel()
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self._change_zoom(0.25))
        full_page = QPushButton("Use full page")
        full_page.clicked.connect(self._full_page)
        zoom_layout.addWidget(zoom_out)
        zoom_layout.addWidget(self.zoom_label, 1)
        zoom_layout.addWidget(zoom_in)
        preview_form.addRow("Preview page", page_row)
        preview_form.addRow("Zoom", zoom_row)
        preview_form.addRow("", full_page)
        control_layout.addWidget(preview_group)

        pages_group = QGroupBox("Pages to extract")
        pages_form = QVBoxLayout(pages_group)
        self.all_pages = QRadioButton("All pages")
        self.current_only = QRadioButton("Only the preview page")
        self.custom = QRadioButton("Custom pages")
        self.custom_pages = QLineEdit()
        self.custom_pages.setPlaceholderText("e.g. 1, 3, 5-8")
        self.custom_pages.setEnabled(False)
        self.custom.toggled.connect(self.custom_pages.setEnabled)
        self.all_pages.setChecked(True)
        for control in (self.all_pages, self.current_only, self.custom, self.custom_pages):
            pages_form.addWidget(control)
        control_layout.addWidget(pages_group)

        output_group = QGroupBox("Output")
        output_form = QFormLayout(output_group)
        self.output_format = QComboBox()
        self.output_format.addItems(["Excel workbook (.xlsx)", "Plain text (.txt)"])
        self.output = QLineEdit(suggested)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        output_row = QWidget()
        row = QHBoxLayout(output_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.output, 1)
        row.addWidget(browse)
        output_form.addRow("Format", self.output_format)
        output_form.addRow("Save as", output_row)
        control_layout.addWidget(output_group)
        instruction = QLabel("Drag a rectangle over the same target area used on every selected page.")
        instruction.setWordWrap(True)
        instruction.setObjectName("secondary")
        control_layout.addWidget(instruction)
        control_layout.addStretch(1)
        splitter.addWidget(controls)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        self.preview = RegionLabel()
        self.preview.selectionChanged.connect(self._selection_changed)
        scroll = QScrollArea()
        scroll.setWidget(self.preview)
        scroll.setWidgetResizable(False)
        preview_layout.addWidget(scroll)
        splitter.addWidget(preview)
        splitter.setSizes([430, 640])
        splitter.setStretchFactor(1, 1)
        self._root.addWidget(splitter, 1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Extract Text")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        self._render()

    def _render(self) -> None:
        page = self.document.load_page(self.current_page)
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))
        self.preview.resize(image.size())
        self.zoom_label.setText(f"{int(self.zoom * 100)}%")
        if self.pdf_rect:
            self.preview.set_selection(
                QRect(
                    int(self.pdf_rect.x0 * self.zoom),
                    int(self.pdf_rect.y0 * self.zoom),
                    int(self.pdf_rect.width * self.zoom),
                    int(self.pdf_rect.height * self.zoom),
                )
            )

    def _selection_changed(self, selection: QRect) -> None:
        self.pdf_rect = fitz.Rect(
            selection.x() / self.zoom,
            selection.y() / self.zoom,
            (selection.x() + selection.width()) / self.zoom,
            (selection.y() + selection.height()) / self.zoom,
        )

    def _full_page(self) -> None:
        self.pdf_rect = fitz.Rect(self.document.load_page(self.current_page).rect)
        self._render()

    def _change_page(self, amount: int) -> None:
        self.page.setValue(self.page.value() + amount)

    def _page_changed(self, value: int) -> None:
        self.current_page = value - 1
        self._render()

    def _change_zoom(self, amount: float) -> None:
        self.zoom = min(3.0, max(0.5, self.zoom + amount))
        self._render()

    def _browse_output(self) -> None:
        if self.output_format.currentIndex() == 0:
            filter_, extension = "Excel (*.xlsx)", ".xlsx"
        else:
            filter_, extension = "Text (*.txt)", ".txt"
        start = (
            self.output.text()
            if self.output.text() and Path(self.output.text()).is_absolute()
            else start_in_save_directory(self, f"extracted{extension}")
        )
        value, _ = QFileDialog.getSaveFileName(self, "Save extracted text", start, filter_)
        if value:
            remember_save_directory(self, value)
            self.output.setText(value if value.lower().endswith(extension) else f"{value}{extension}")

    def _validate(self) -> None:
        if not self.pdf_rect or self.pdf_rect.is_empty:
            self.show_error("Draw a region on the page preview or choose Use full page.")
            return
        try:
            if self.all_pages.isChecked():
                pages = list(range(self.document.page_count))
            elif self.current_only.isChecked():
                pages = [self.current_page]
            else:
                pages = parse_page_range(self.custom_pages.text(), self.document.page_count)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if not pages:
            self.show_error("Choose at least one valid page.")
            return
        output = Path(self.output.text())
        extension = ".xlsx" if self.output_format.currentIndex() == 0 else ".txt"
        if not self.output.text().strip() or not output.parent.is_dir():
            self.show_error("Choose a valid output location.")
            return
        if output.suffix.lower() != extension:
            output = output.with_suffix(extension)
        self.details = {
            "pages": pages,
            "rect": tuple(self.pdf_rect),
            "output": str(output),
            "excel": self.output_format.currentIndex() == 0,
        }
        self.accept()
