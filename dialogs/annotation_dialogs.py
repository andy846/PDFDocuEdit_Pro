"""Watermark configuration dialog for annotation workflows."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.pdf_engine import parse_page_range

from .base import ToolDialog


class WatermarkDialog(ToolDialog):
    def __init__(self, page_count: int, current_page: int, parent=None):
        super().__init__("Add Watermark", "watermark", parent)
        self.page_count = page_count
        self.details: dict[str, object] | None = None

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
        self.fontsize.setRange(24, 200)
        self.fontsize.setValue(64)
        size_layout.addWidget(self.fontsize)
        options_row.addLayout(size_layout)

        rotation_layout = QVBoxLayout()
        rotation_layout.addWidget(QLabel("Rotation"))
        self.rotation = QComboBox()
        self.rotation.addItem("0°", 0)
        self.rotation.addItem("45°", 45)
        self.rotation.addItem("90°", 90)
        self.rotation.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
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

        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel("Pages"))
        self.pages = QLineEdit("all")
        self.pages.setPlaceholderText("all, current, or e.g. 1,3,5-8")
        self.pages.setToolTip("all, current, or one-based ranges like 1,3,5-8")
        pages_row.addWidget(self.pages, 1)
        self._root.addLayout(pages_row)

        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Watermark")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

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
                "rotation": float(self.rotation.currentData()),
                "opacity": self.opacity.value() / 100.0,
                "pages": pages,
            }
        else:
            image = self.image.text().strip()
            if not image:
                self.show_error("Choose a watermark image.")
                return
            if not Path(image).is_file():
                self.show_error("Choose an existing watermark image file.")
                return
            self.details = {
                "mode": "image",
                "image": image,
                "opacity": self.opacity.value() / 100.0,
                "pages": pages,
            }
        self.accept()
