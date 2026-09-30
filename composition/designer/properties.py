"""Independent element properties with explicit font faces and millimetre geometry."""
from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from composition.engine.fonts import FAMILIES


class Properties(QWidget):
    edited = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading = False
        self.element = None
        self.displayed_numbers = {}
        layout = QVBoxLayout(self)
        self.title = QLabel("Select an object")
        layout.addWidget(self.title)
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.numbers = {}
        for key, label, low, high, step in [
            ("x_mm", "X (mm)", 0, 2000, .5), ("y_mm", "Y (mm)", 0, 2000, .5),
            ("width_mm", "Width (mm)", .1, 2000, .5), ("height_mm", "Height (mm)", .1, 2000, .5),
            ("font_size", "Font size (pt)", 1, 500, 1), ("line_spacing", "Line spacing", .5, 5, .1),
            ("stroke_pt", "Stroke (pt)", .1, 20, .1), ("barcode_module_mm", "Min module (mm)", .1, 5, .05),
        ]:
            control = QDoubleSpinBox()
            control.setRange(low, high)
            control.setDecimals(2)
            control.setSingleStep(step)
            self.numbers[key] = control
            form.addRow(label, control)
            control.editingFinished.connect(self.apply)
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(120)
        self.content.setPlaceholderText("Text or {{Field_Name}}")
        form.addRow("Content", self.content)
        self.font_family = QComboBox()
        self.font_family.addItems(FAMILIES)
        form.addRow("Bundled font family", self.font_family)
        self.custom_font = QLineEdit()
        self.custom_font.setReadOnly(True)
        form.addRow("Exact font file", self.custom_font)
        font_button = QPushButton("Choose TTF / OTF…")
        font_button.clicked.connect(self._font_file)
        form.addRow(font_button)
        bundled = QPushButton("Use bundled font")
        bundled.clicked.connect(self._bundled)
        form.addRow(bundled)
        self.bold = QCheckBox("Bold")
        self.italic = QCheckBox("Italic")
        form.addRow(self.bold, self.italic)
        self.alignment = QComboBox()
        self.alignment.addItems(["left", "center", "right"])
        self.vertical = QComboBox()
        self.vertical.addItems(["top", "center", "bottom"])
        form.addRow("Alignment", self.alignment)
        form.addRow("Vertical", self.vertical)
        self.colour = QLineEdit()
        self.fill = QLineEdit()
        self.fill.setPlaceholderText("Transparent or #RRGGBB")
        form.addRow("Colour", self.colour)
        form.addRow("Fill", self.fill)
        self.image_path = QLineEdit()
        self.image_path.setReadOnly(True)
        form.addRow("Image", self.image_path)
        image_button = QPushButton("Choose image…")
        image_button.clicked.connect(self._image_file)
        form.addRow(image_button)
        self.ecc = QComboBox()
        self.ecc.addItems(["L", "M", "Q", "H"])
        self.human = QCheckBox("Show Code 128 text")
        form.addRow("QR correction", self.ecc)
        form.addRow(self.human)
        layout.addWidget(self.form_widget)
        layout.addStretch()
        self.form_widget.setEnabled(False)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self.apply)
        self.content.textChanged.connect(self._content_changed)
        for signal in (self.alignment.currentTextChanged,
                       self.vertical.currentTextChanged, self.ecc.currentTextChanged,
                       self.bold.toggled, self.italic.toggled, self.human.toggled):
            signal.connect(self.apply)
        self.font_family.currentTextChanged.connect(self._family_changed)
        self.colour.editingFinished.connect(self.apply)
        self.fill.editingFinished.connect(self.apply)

    def _content_changed(self):
        if not self.loading:
            self.apply()

    def show_element(self, element):
        self.timer.stop()
        self.loading = True
        self.element = element
        self.form_widget.setEnabled(element is not None)
        self.form_widget.setVisible(element is not None)
        self.title.setText(element.type.title() if element else "Select one object")
        if element:
            for key, widget in self.numbers.items():
                widget.setValue(element.font.size_pt if key == "font_size" else getattr(element, key))
            self.displayed_numbers = {key: widget.value() for key, widget in self.numbers.items()}
            if self.content.toPlainText() != element.value:
                self.content.setPlainText(element.value)
            self.font_family.setCurrentText(element.font.family)
            self.custom_font.setText(element.font.file)
            self.bold.setChecked(element.font.bold)
            self.italic.setChecked(element.font.italic)
            self.bold.setEnabled(not element.font.file)
            self.italic.setEnabled(not element.font.file)
            self.alignment.setCurrentText(element.align)
            self.vertical.setCurrentText(element.vertical_align)
            self.colour.setText(element.colour)
            self.fill.setText(element.fill)
            self.image_path.setText(element.image)
            self.ecc.setCurrentText(element.qr_error)
            self.human.setChecked(element.show_barcode_text)
        self.loading = False

    def apply(self, *args):
        if self.loading or self.element is None:
            return
        self.timer.stop()
        values = {key: widget.value() for key, widget in self.numbers.items() if key != "font_size"}
        # Preserve precision from PDF geometry unless the user actually edits that number.
        for key in values:
            if values[key] == self.displayed_numbers.get(key):
                values[key] = getattr(self.element, key)
        values.update(value=self.content.toPlainText(), align=self.alignment.currentText(),
                      vertical_align=self.vertical.currentText(), colour=self.colour.text().strip(),
                      fill=self.fill.text().strip(), image=self.image_path.text(),
                      qr_error=self.ecc.currentText(), show_barcode_text=self.human.isChecked(),
                      font={"family": self.font_family.currentText(),
                            "size_pt": (self.element.font.size_pt if self.numbers["font_size"].value() ==
                                        self.displayed_numbers.get("font_size") else self.numbers["font_size"].value()),
                            "bold": self.bold.isChecked(), "italic": self.italic.isChecked(),
                            "file": self.custom_font.text()})
        self.edited.emit(values)

    def _family_changed(self, *args):
        if not self.loading:
            self.custom_font.clear()
            self.bold.setEnabled(True)
            self.italic.setEnabled(True)
            self.apply()

    def _font_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Exact production font", "", "Fonts (*.ttf *.otf)")
        if path:
            self.loading = True
            self.custom_font.setText(path)
            self.bold.setChecked(False)
            self.italic.setChecked(False)
            self.bold.setEnabled(False)
            self.italic.setEnabled(False)
            self.loading = False
            self.apply()

    def _bundled(self):
        self.custom_font.clear()
        self.bold.setEnabled(True)
        self.italic.setEnabled(True)
        self.apply()

    def _image_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Static image", "", "Images (*.png *.jpg *.jpeg *.tif *.tiff)")
        if path:
            self.image_path.setText(path)
            self.apply()
