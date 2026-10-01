"""Type-aware property groups and searchable exact Windows font selection."""
from __future__ import annotations

from dataclasses import asdict

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from composition.engine.fonts import FAMILIES


class Properties(QWidget):
    edited = pyqtSignal(dict)
    fontRequested = pyqtSignal(dict)
    insertFieldRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading = False
        self.element = None
        self.displayed_numbers = {}
        self.catalogue = {}
        self.file_faces = {}
        self.font_choice = {}
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setStyleSheet("QDoubleSpinBox { padding: 4px 18px 4px 6px; } "
                          "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; }")
        self.title = QLabel("Select an object")
        self.title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.title)
        self.empty = QLabel("Select an object on the page or in Layers to edit its properties.")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.form_widget = QWidget()
        groups = QVBoxLayout(self.form_widget)
        groups.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        groups.setContentsMargins(0, 0, 0, 0)
        self.numbers = {}
        self.geometry = QGroupBox("Position & size (mm)")
        grid = QGridLayout(self.geometry)
        for index, (key, label, high) in enumerate([
            ("x_mm", "X", 2000), ("y_mm", "Y", 2000),
            ("width_mm", "W", 2000), ("height_mm", "H", 2000),
        ]):
            control = QDoubleSpinBox()
            control.setRange(0 if index < 2 else .1, high)
            control.setDecimals(2)
            control.setSingleStep(.5)
            control.setMinimumWidth(56)
            control.setMaximumWidth(96)
            control.setAccessibleName(label + " millimetres")
            self.numbers[key] = control
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(label))
            row.addWidget(control)
            grid.addWidget(cell, index // 2, index % 2)
            control.editingFinished.connect(self.apply)
        groups.addWidget(self.geometry)
        self.content_group = QGroupBox("Content")
        content_layout = QVBoxLayout(self.content_group)
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(95)
        self.content.setPlaceholderText("Text or {{Field_Name}}")
        self.content.setAccessibleName("Object content")
        content_layout.addWidget(self.content)
        insert_field = QPushButton("Insert data field…")
        insert_field.clicked.connect(self.insertFieldRequested)
        content_layout.addWidget(insert_field)
        groups.addWidget(self.content_group)
        self.font_group = QGroupBox("Typography")
        form = QFormLayout(self.font_group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.font_family = QComboBox()
        self.font_family.setEditable(True)
        self.font_family.setMaxVisibleItems(12)
        self.font_family.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.font_family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_family.setMinimumContentsLength(12)
        self.font_family.addItems(FAMILIES)
        self.font_family.setAccessibleName("Font family")
        self.font_family.setToolTip("Search installed Windows font families and bundled Noto fonts.")
        self.font_family.setMinimumWidth(0)
        self.font_family.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.font_style = QComboBox()
        self.font_style.setMinimumWidth(0)
        self.font_style.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.font_style.setAccessibleName("Exact font style")
        self.font_status = QLabel("Loading Windows fonts…")
        self.font_status.setWordWrap(True)
        form.addRow("Family", self.font_family)
        form.addRow("Style", self.font_style)
        form.addRow(self.font_status)
        self.bold, self.italic = QCheckBox("Bold"), QCheckBox("Italic")
        self.bold.hide()
        self.italic.hide()
        self.custom_font = QLineEdit()
        self.custom_font.setReadOnly(True)
        self.custom_font.setPlaceholderText("Bundled exact face")
        self.custom_font.setMinimumWidth(0)
        font_button = QPushButton("Choose font file…")
        font_button.clicked.connect(self._font_file)
        form.addRow(font_button)
        self.custom_font.setVisible(False)
        self.font_status.setToolTip("The selected font face is embedded in the PDF. No silent substitution.")
        for key, _label, low, high, step in [
            ("font_size", "Size (pt)", 1, 500, 1),
            ("line_spacing", "Line spacing", .5, 5, .1),
        ]:
            control = QDoubleSpinBox()
            control.setRange(low, high)
            control.setDecimals(2)
            control.setSingleStep(step)
            self.numbers[key] = control
            control.editingFinished.connect(self.apply)
            if key == "font_size":
                form.addRow("Size (pt)", control)
        self.alignment = QComboBox()
        self.alignment.addItems(["left", "center", "right"])
        self.vertical = QComboBox()
        self.vertical.addItems(["top", "center", "bottom"])
        groups.addWidget(self.font_group)
        groups.removeWidget(self.font_group)
        groups.insertWidget(1, self.font_group)
        self.text_layout_group = QGroupBox("Text layout")
        text_layout = QFormLayout(self.text_layout_group)
        text_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        text_layout.addRow("Spacing", self.numbers["line_spacing"])
        text_layout.addRow("Align", self.alignment)
        text_layout.addRow("Vertical", self.vertical)
        groups.addWidget(self.text_layout_group)
        self.appearance_group = QGroupBox("Appearance")
        form = QFormLayout(self.appearance_group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.colour, self.fill = QLineEdit(), QLineEdit()
        self.fill.setPlaceholderText("Transparent or #RRGGBB")
        for label, control in (("Colour", self.colour), ("Fill", self.fill)):
            row = QWidget()
            cells = QHBoxLayout(row)
            cells.setContentsMargins(0, 0, 0, 0)
            cells.addWidget(control)
            button = QPushButton("…")
            button.setMaximumWidth(32)
            button.setToolTip("Choose " + label.lower())
            button.clicked.connect(lambda checked=False, target=control: self._colour(target))
            cells.addWidget(button)
            form.addRow(label, row)
            if label == "Fill":
                self.fill_row = row
        control = QDoubleSpinBox()
        control.setRange(.1, 20)
        control.setDecimals(2)
        self.numbers["stroke_pt"] = control
        control.editingFinished.connect(self.apply)
        self.stroke_row = control
        form.addRow("Stroke (pt)", control)
        self.appearance_form = form
        groups.addWidget(self.appearance_group)
        self.image_group = QGroupBox("Image")
        form = QFormLayout(self.image_group)
        self.image_path = QLineEdit()
        self.image_path.setReadOnly(True)
        form.addRow(self.image_path)
        image_button = QPushButton("Choose image…")
        image_button.clicked.connect(self._image_file)
        form.addRow(image_button)
        groups.addWidget(self.image_group)
        self.barcode_group = QGroupBox("Barcode")
        form = QFormLayout(self.barcode_group)
        self.ecc = QComboBox()
        self.ecc.addItems(["L", "M", "Q", "H"])
        self.human = QCheckBox("Show Code 128 text")
        control = QDoubleSpinBox()
        control.setRange(.1, 5)
        control.setDecimals(2)
        control.setSingleStep(.05)
        self.numbers["barcode_module_mm"] = control
        control.editingFinished.connect(self.apply)
        form.addRow("Min module (mm)", control)
        form.addRow("QR correction", self.ecc)
        form.addRow(self.human)
        groups.addWidget(self.barcode_group)
        for group in (self.geometry, self.font_group, self.content_group,
                      self.text_layout_group, self.appearance_group, self.image_group, self.barcode_group):
            group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            group.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.addWidget(self.form_widget)
        layout.addStretch()
        self.form_widget.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        self.content.textChanged.connect(self._content_changed)
        for signal in (self.alignment.currentTextChanged, self.vertical.currentTextChanged,
                       self.ecc.currentTextChanged, self.human.toggled):
            signal.connect(self.apply)
        self.bold.toggled.connect(self._bundled_style)
        self.italic.toggled.connect(self._bundled_style)
        self.font_family.currentIndexChanged.connect(self._family_changed)
        self.font_family.lineEdit().editingFinished.connect(self._typed_family)
        self.font_style.activated.connect(self._style_chosen)
        self.colour.editingFinished.connect(self.apply)
        self.fill.editingFinished.connect(self.apply)
        self._configure_completion()

    def _configure_completion(self):
        self.font_family.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.font_family.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.font_family.completer().setFilterMode(Qt.MatchFlag.MatchContains)

    def set_catalogue(self, result):
        self.catalogue = {}
        for face in result["faces"]:
            for alias in face.get("aliases", [face["family"]]):
                self.catalogue.setdefault(alias, []).append(face)
        self.loading = True
        current = self.font_family.currentText()
        self.font_family.clear()
        self.font_family.addItems(list(FAMILIES) + sorted(
            set(self.catalogue) - set(FAMILIES), key=str.casefold))
        if self.font_family.findText(current) < 0:
            self.font_family.addItem(current)
        self.font_family.setCurrentIndex(self.font_family.findText(current))
        self._configure_completion()
        if self.element:
            self._set_styles(self.element.font.family, bool(self.element.font.file))
        if self.element and not self.element.font.file:
            spec = self.element.font
            style = ("Bold Italic" if spec.bold and spec.italic else
                     "Bold" if spec.bold else "Italic" if spec.italic else "Regular")
            self.font_style.setCurrentText(style)
        self.loading = False

    def _set_styles(self, family, saved=False):
        self.font_style.clear()
        if saved:
            self.font_style.addItem("Saved exact face", None)
        if family in FAMILIES:
            for style in (("Regular", "Bold") if family.endswith("HK") else
                          ("Regular", "Bold", "Italic", "Bold Italic")):
                self.font_style.addItem(style, {"bundled": True, "style": style})
        else:
            seen = set()
            for face in self.catalogue.get(family, []):
                if face["style"] in seen:
                    continue
                seen.add(face["style"])
                self.font_style.addItem(face["style"], face)
                index = self.font_style.count()-1
                self.font_style.setItemData(index, face.get("note", ""), Qt.ItemDataRole.ToolTipRole)
                if not face["usable"]:
                    self.font_style.model().item(index).setEnabled(False)

    def show_element(self, element):
        self.loading = True
        self.element = element
        self.empty.setVisible(element is None)
        self.form_widget.setVisible(element is not None)
        self.title.setText(element.type.title() + " properties" if element else "Properties")
        if element:
            self.font_choice = asdict(element.font)
            for key, control in self.numbers.items():
                control.setValue(element.font.size_pt if key == "font_size" else getattr(element, key))
            self.displayed_numbers = {key: control.value() for key, control in self.numbers.items()}
            if self.content.toPlainText() != element.value:
                self.content.setPlainText(element.value)
            if self.font_family.findText(element.font.family) < 0:
                self.font_family.addItem(element.font.family)
            self.font_family.setCurrentIndex(self.font_family.findText(element.font.family))
            self.font_family.lineEdit().setCursorPosition(0)
            self.font_family.setToolTip(element.font.family + "\nSearch Windows families or choose a font file.")
            self._set_styles(element.font.family, bool(element.font.file))
            if element.font.file:
                self.font_style.setCurrentIndex(0)
                known = self.file_faces.get(element.font.file)
                if known:
                    self.font_style.setItemText(0, known["style"] + " (saved exact face)")
                self.font_status.setText("Exact file embedded in PDF")
                self.font_status.setToolTip(element.font.file)
            else:
                style = ("Bold Italic" if element.font.bold and element.font.italic else
                         "Bold" if element.font.bold else "Italic" if element.font.italic else "Regular")
                self.font_style.setCurrentText(style)
                self.font_status.setText("Bundled font · embedded in PDF")
            self.custom_font.setText(element.font.file)
            self.bold.setChecked(element.font.bold)
            self.italic.setChecked(element.font.italic)
            self.bold.setEnabled(not element.font.file)
            self.italic.setEnabled(not element.font.file and not element.font.family.endswith("HK"))
            self.alignment.setCurrentText(element.align)
            self.vertical.setCurrentText(element.vertical_align)
            self.colour.setText(element.colour)
            self.fill.setText(element.fill)
            self.image_path.setText(element.image)
            self.ecc.setCurrentText(element.qr_error)
            self.human.setChecked(element.show_barcode_text)
            self.content_group.setVisible(element.type in {"text", "qr", "code128"})
            self.font_group.setVisible(element.type == "text" or element.show_barcode_text)
            self.text_layout_group.setVisible(element.type == "text" or element.show_barcode_text)
            self.appearance_group.setVisible(element.type in {"text", "line", "rectangle"})
            self.appearance_form.setRowVisible(self.stroke_row, element.type in {"line", "rectangle"})
            self.appearance_form.setRowVisible(self.fill_row, element.type == "rectangle")
            self.image_group.setVisible(element.type == "image")
            self.barcode_group.setVisible(element.type in {"qr", "code128"})
            self.ecc.setEnabled(element.type == "qr")
            self.human.setEnabled(element.type == "code128")
        self.loading = False

    def _content_changed(self):
        if not self.loading:
            self.apply()

    def apply(self, *args):
        if self.loading or self.element is None:
            return
        values = {key: control.value() for key, control in self.numbers.items() if key != "font_size"}
        for key in values:
            if values[key] == self.displayed_numbers.get(key):
                values[key] = getattr(self.element, key)
        font = dict(self.font_choice)
        font["size_pt"] = (self.element.font.size_pt if self.numbers["font_size"].value() ==
                           self.displayed_numbers.get("font_size") else self.numbers["font_size"].value())
        if not font["file"]:
            font.update(bold=self.bold.isChecked(), italic=self.italic.isChecked())
        values.update(value=self.content.toPlainText(), align=self.alignment.currentText(),
                      vertical_align=self.vertical.currentText(), colour=self.colour.text().strip(),
                      fill=self.fill.text().strip(), image=self.image_path.text(),
                      qr_error=self.ecc.currentText(), show_barcode_text=self.human.isChecked(), font=font)
        self.edited.emit(values)

    def _typed_family(self):
        if self.loading or not self.element:
            return
        text = self.font_family.currentText()
        if text not in FAMILIES and text not in self.catalogue:
            self.loading = True
            self.font_family.setCurrentIndex(self.font_family.findText(self.element.font.family))
            self.loading = False
            self.font_status.setText("Font not installed. Choose a listed family or a font file.")
            return
        self._family_changed()

    def _family_changed(self, *args):
        if self.loading or not self.element:
            return
        family = self.font_family.currentText()
        if family not in FAMILIES and family not in self.catalogue:
            return
        self.loading = True
        self._set_styles(family)
        normal = next((i for i in range(self.font_style.count())
                       if self.font_style.itemText(i).casefold() in {"regular", "normal", "roman"}), 0)
        self.font_style.setCurrentIndex(normal)
        self.loading = False
        self._style_chosen()

    def _style_chosen(self, *args):
        if self.loading or not self.element:
            return
        face = self.font_style.currentData()
        if not face:
            return
        if face.get("bundled"):
            self.fontRequested.emit({"cancel": True, "element_id": self.element.id})
            style = face["style"]
            self.loading = True
            self.font_choice.update(family=self.font_family.currentText(), file="",
                                    bold="Bold" in style, italic="Italic" in style)
            self.custom_font.clear()
            self.bold.setEnabled(True)
            self.italic.setEnabled(not self.font_family.currentText().endswith("HK"))
            self.bold.setChecked("Bold" in style)
            self.italic.setChecked("Italic" in style)
            self.loading = False
            self.apply()
        else:
            self.font_status.setText("Preparing exact font face…")
            self.fontRequested.emit({"face": {**face, "family": self.font_family.currentText()},
                                     "element_id": self.element.id})

    def _bundled_style(self, *args):
        if not self.loading and self.element and not self.font_choice.get("file"):
            self.apply()

    def _font_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose production font", "", "Fonts (*.ttf *.otf *.ttc *.otc)")
        if path and self.element:
            self.fontRequested.emit({"file": path, "element_id": self.element.id})

    def _colour(self, control):
        colour = QColorDialog.getColor(QColor(control.text() or "#ffffff"), self, "Choose colour")
        if colour.isValid():
            control.setText(colour.name())
            self.apply()

    def _image_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Static image", "",
                                             "Images (*.png *.jpg *.jpeg *.tif *.tiff)")
        if path:
            self.image_path.setText(path)
            self.apply()
