"""Watermark configuration dialog for annotation workflows."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.pdf_engine import parse_page_range
from core.watermarks import ANCHORS, WatermarkSpec
from ui.responsive import reveal_widget

from .base import ToolDialog


class _WatermarkPreviewLabel(QLabel):
    def __init__(self, *args):
        super().__init__(*args)
        self._original = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

    def set_preview_image(self, image):
        self._original = QPixmap.fromImage(image)
        self._fit_image()

    def _fit_image(self):
        if self._original is not None:
            self.setPixmap(self._original.scaled(self.contentsRect().size(),
                           Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()


class WatermarkDialog(ToolDialog):
    def _reveal_focus(self, old, current):
        if current is not None and self.isAncestorOf(current):
            parent = current.parentWidget()
            control = parent if isinstance(parent, (QSpinBox, QDoubleSpinBox)) else current
            reveal_widget(control, whole_control=True)

    def __init__(self, page_count: int, current_page: int, parent=None):
        super().__init__("Add Watermark", "watermark", parent)
        self.page_count = page_count
        self.details: dict[str, object] | None = None
        self.current_page = current_page
        self._embedded_image = None
        self._image_width_pt = None
        self._watermark_color = (.5, .5, .5)
        self._existing_id = None
        self._source_doc = self._preview_owner = self._preview_snapshot = None
        self._preview_jobs = []
        self._preview_generation = 0
        self._preview_closed = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(160)
        self._preview_timer.timeout.connect(self._start_preview)

        mode_row = QHBoxLayout()
        self.text_mode = QRadioButton("Text watermark")
        self.image_mode = QRadioButton("Image watermark")
        self.text_mode.setChecked(True)
        mode_row.addWidget(self.text_mode)
        mode_row.addWidget(self.image_mode)
        mode_row.addStretch(1)
        self._root.addLayout(mode_row)

        text_group = QWidget()
        text_layout = QVBoxLayout(text_group)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.text = QLineEdit("CONFIDENTIAL")
        self.text.setPlaceholderText("Watermark text")
        text_layout.addWidget(QLabel("Text"))
        text_layout.addWidget(self.text)
        self._root.addWidget(text_group)

        image_row = QHBoxLayout()
        self.image = QLineEdit()
        self.image.setReadOnly(True)
        self.image.setPlaceholderText("Choose an image file")
        self.image_browse = QPushButton("Browse…")
        self.image_browse.clicked.connect(self._browse_image)
        image_row.addWidget(self.image, 1)
        image_row.addWidget(self.image_browse)
        self._root.addLayout(image_row)
        self.image_mode.toggled.connect(
            lambda checked: (
                text_group.setEnabled(not checked),
                self.image.setEnabled(checked),
                self.image_browse.setEnabled(checked),
            )
        )

        options_row = QHBoxLayout()
        size_layout = QVBoxLayout()
        size_layout.addWidget(QLabel("Font size"))
        self.fontsize = QSpinBox()
        self.fontsize.setRange(1, 1000)
        self.fontsize.setValue(64)
        size_layout.addWidget(self.fontsize)
        options_row.addLayout(size_layout)

        rotation_layout = QVBoxLayout()
        rotation_layout.addWidget(QLabel("Rotation"))
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(-360, 360)
        self.rotation.setDecimals(1)
        self.rotation.setSuffix("°")
        self.rotation.setValue(45)
        rotation_layout.addWidget(self.rotation)
        options_row.addLayout(rotation_layout)

        opacity_layout = QVBoxLayout()
        opacity_label = QHBoxLayout()
        opacity_label.addWidget(QLabel("Opacity"))
        self.opacity_value = QLabel("25%")
        opacity_label.addWidget(self.opacity_value)
        opacity_layout.addLayout(opacity_label)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        self.opacity.valueChanged.connect(
            lambda value: self.opacity_value.setText(f"{value}%")
        )
        opacity_layout.addWidget(self.opacity)
        options_row.addLayout(opacity_layout, 1)
        self._root.addLayout(options_row)

        placement = QHBoxLayout()
        self.anchor = QComboBox()
        for value in ANCHORS:
            self.anchor.addItem(value.replace("-", " ").title(), value)
        self.anchor.setCurrentIndex(4)
        placement.addWidget(QLabel("Position"))
        placement.addWidget(self.anchor)
        self.scale = QDoubleSpinBox()
        self.scale.setDecimals(6)
        self.scale.setRange(.000001, 2000)
        self.scale.setValue(100)
        self.scale.setSuffix("%")
        placement.addWidget(QLabel("Scale"))
        placement.addWidget(self.scale)
        self._root.addLayout(placement)
        offsets = QHBoxLayout()
        self.x_offset, self.y_offset = QDoubleSpinBox(), QDoubleSpinBox()
        for label, field in (("X offset", self.x_offset), ("Y offset", self.y_offset)):
            field.setRange(-2000, 2000)
            field.setDecimals(2)
            field.setSuffix(" mm")
            offsets.addWidget(QLabel(label))
            offsets.addWidget(field)
        self._root.addLayout(offsets)
        hint = QLabel("Offsets: right / down are positive. Drag the applied watermark to move or resize; right-click to edit it.")
        hint.setWordWrap(True)
        self._root.addWidget(hint)
        self.preview = _WatermarkPreviewLabel("Preview of the current page")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(340)
        self._root.addWidget(self.preview)

        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel("Pages"))
        self.pages = QLineEdit("all")
        self.pages.setPlaceholderText("all, current, or e.g. 1,3,5-8")
        self.pages.setToolTip("all, current, or one-based ranges like 1,3,5-8")
        pages_row.addWidget(self.pages, 1)
        self._root.addLayout(pages_row)

        self.add_validation()
        buttons = self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Watermark")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
        for control in (self.text, self.image, self.pages):
            control.textChanged.connect(self._queue_preview)
        for control in (self.fontsize, self.rotation, self.opacity, self.scale, self.x_offset, self.y_offset):
            control.valueChanged.connect(self._queue_preview)
        self.anchor.currentIndexChanged.connect(self._queue_preview)
        self.image_mode.toggled.connect(self._mode_changed)
        self.image.setEnabled(False)
        self.image_browse.setEnabled(False)

    def _mode_changed(self, image):
        self.rotation.setValue(0 if image else 45)
        self._queue_preview()

    def configure_existing(self, spec, image, identifier=None):
        self.setWindowTitle("Edit Watermark")
        self._embedded_image, self._existing_id = image, identifier
        self._image_width_pt, self._watermark_color = spec.image_width_pt, spec.color
        self.image_mode.setChecked(spec.mode == "image")
        self.text.setText(spec.text)
        self.fontsize.setValue(round(spec.fontsize))
        self.rotation.setValue(spec.rotation)
        self.opacity.setValue(round(spec.opacity * 100))
        self.scale.setValue(spec.scale * 100)
        self.anchor.setCurrentIndex(self.anchor.findData(spec.anchor))
        self.x_offset.setValue(spec.x_mm)
        self.y_offset.setValue(spec.y_mm)
        self.pages.setText("current")
        self.pages.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Update selected watermark")

    def enable_preview(self, document, owner):
        self._source_doc, self._preview_owner = document, owner
        self._queue_preview()

    def _spec(self):
        return WatermarkSpec(mode="image" if self.image_mode.isChecked() else "text",
                             text=self.text.text().strip(), fontsize=self.fontsize.value(),
                             rotation=self.rotation.value(), opacity=self.opacity.value() / 100,
                             scale=self.scale.value() / 100, anchor=self.anchor.currentData(),
                             x_mm=self.x_offset.value(), y_mm=self.y_offset.value(),
                             image_width_pt=self._image_width_pt, color=self._watermark_color)

    def _queue_preview(self, *_args):
        self._preview_generation += 1
        if self._source_doc is not None and not self._preview_closed:
            self._preview_timer.start()

    def _start_preview(self):
        from core.diagnostics import log_lifecycle
        from ui.watermark_preview import WatermarkPreviewTask
        if self._preview_closed or self._source_doc is None:
            return
        if any(not task.done.is_set() for task in self._preview_jobs):
            for task in self._preview_jobs:
                task.cancelled.set()
            self._preview_timer.start()
            return
        spec = self._spec()
        try:
            spec.validate()
        except ValueError:
            self.preview.clear()
            self.preview.setText("Enter valid watermark settings to preview.")
            return
        task = WatermarkPreviewTask(self._source_doc, self.current_page, spec,
                                    self._embedded_image, self.image.text(), self._preview_snapshot,
                                    self._preview_generation, self._existing_id)
        self._preview_jobs = [task]
        log_lifecycle("watermark.preview_started", generation=self._preview_generation)
        self._preview_owner._preview_readers.append(task)
        task.signals.finished.connect(self._preview_finished)
        QThreadPool.globalInstance().start(task)

    def _preview_finished(self, result):
        if self._preview_closed:
            return
        if result["snapshot"]:
            self._preview_snapshot = result["snapshot"]
        if result["generation"] != self._preview_generation:
            return
        if result["image"] is not None:
            self.preview.set_preview_image(result["image"])
        else:
            self.preview.clear()
            self.preview.setText(result["error"] or "Preview cancelled")

    def done(self, result):
        from core.diagnostics import log_lifecycle
        self._preview_closed = True
        self._preview_timer.stop()
        for task in self._preview_jobs:
            task.cancelled.set()
        log_lifecycle("watermark.dialog_closed", accepted=result == self.DialogCode.Accepted,
                      readers=sum(not task.done.is_set() for task in self._preview_jobs))
        super().done(result)

    def _browse_image(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Choose watermark image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if value:
            self.image.setText(value)
            self.image.setToolTip(value)

    def _validate(self) -> None:
        pages = self.pages.text().strip()
        if not pages:
            self.show_error("Enter a page range such as all, current, or 1,3,5-8.")
            return
        normalized = pages.casefold()
        if normalized not in {"all", "current"}:
            try:
                parsed = parse_page_range(pages, self.page_count)
            except ValueError as exc:
                self.show_error(str(exc))
                return
            if not parsed:
                self.show_error("The page range does not match any page.")
                return
        if self.text_mode.isChecked():
            if not self.text.text().strip():
                self.show_error("Enter the watermark text.")
                return
            self.details = {
                "mode": "text",
                "text": self.text.text().strip(),
                "fontsize": self.fontsize.value(),
                "rotation": self.rotation.value(),
                "opacity": self.opacity.value() / 100.0,
                "pages": pages,
            }
        else:
            image = self.image.text().strip()
            if not image and self._embedded_image is None:
                self.show_error("Choose a watermark image.")
                return
            if image and not Path(image).is_file():
                self.show_error("Choose an existing watermark image file.")
                return
            self.details = {
                "mode": "image",
                "image": image,
                "opacity": self.opacity.value() / 100.0,
                "pages": pages,
                "image_data": self._embedded_image if not image else None,
            }
        self.details.update(rotation=self.rotation.value(), scale=self.scale.value() / 100,
                            anchor=self.anchor.currentData(), x_mm=self.x_offset.value(),
                            y_mm=self.y_offset.value(), image_width_pt=self._image_width_pt,
                            color=self._watermark_color)
        try:
            self._spec().validate()
        except ValueError as exc:
            self.show_error(str(exc))
            self.details = None
            return
        self.accept()
