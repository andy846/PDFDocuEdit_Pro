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

from .rule_controls import rules_summary


class Properties(QWidget):
    batchApplyRequested = pyqtSignal()
    batchRevertRequested = pyqtSignal()
    bulkChanged = pyqtSignal()
    edited = pyqtSignal(dict)
    geometryEdited = pyqtSignal(dict)
    fontRequested = pyqtSignal(dict)
    insertFieldRequested = pyqtSignal()
    glyphRepairRequested = pyqtSignal()
    revertRequested = pyqtSignal()
    rulesRequested = pyqtSignal()
    rulesClearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading = False
        self.element = None
        self.bulk_ids = []
        self.geometry_ids = []
        self.multi_selection = False
        self.bulk_dirty = set()
        self.bulk_font_request = None
        self.batch_resolver = lambda: True
        self.selection_elements = []
        self.displayed_numbers = {}
        self.catalogue = {}
        self.file_faces = {}
        self.font_choice = {}
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setStyleSheet("QDoubleSpinBox { min-height: 26px; padding: 2px 18px 2px 6px; } "
                          "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 16px; }")
        self.title = QLabel("Select an object")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.title)
        self.include_barcode = QCheckBox("Include barcode text")
        self.include_barcode.setToolTip("Code 128 / I25 text only; barcode payloads and profiles stay unchanged.")
        self.include_barcode.setAccessibleName("Include barcode human-readable text")
        self.include_barcode.hide()
        self.include_barcode.toggled.connect(self._include_barcode_changed)
        layout.addWidget(self.include_barcode)
        self.batch_status = QLabel()
        self.batch_status.setWordWrap(True)
        self.batch_status.hide()
        layout.addWidget(self.batch_status)
        self.batch_revert = QPushButton("Revert changes")
        self.batch_revert.setToolTip("Revert unapplied settings; committed objects are retained.")
        self.batch_revert.setAccessibleName("Revert unapplied settings")
        self.batch_revert.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.batch_revert.clicked.connect(self.batchRevertRequested)
        self.batch_revert.hide()
        layout.addWidget(self.batch_revert)
        self.empty = QLabel("Select an object on the page or in Layers to edit its properties.")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.form_widget = QWidget()
        groups = QVBoxLayout(self.form_widget)
        groups.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        groups.setContentsMargins(0, 0, 0, 0)
        self.numbers = {}
        self.geometry = QGroupBox("Geometry")
        self.geometry_cells, self.geometry_checks, self.geometry_labels = {}, {}, {}
        grid = QGridLayout(self.geometry)
        for index, (key, label, high) in enumerate([
            ("x_mm", "X (mm)", 2000), ("y_mm", "Y (mm)", 2000),
            ("width_mm", "W (mm)", 2000), ("height_mm", "H (mm)", 2000),
            ("rotation_deg", "Angle (°)", 360),
        ]):
            control = QDoubleSpinBox()
            control.setRange(-360 if key == "rotation_deg" else 0 if index < 2 else .1, high)
            control.setDecimals(2)
            control.setSingleStep(.5)
            control.setMinimumWidth(56)
            control.setMaximumWidth(96)
            control.setAccessibleName("Rotation degrees" if key == "rotation_deg" else label + " millimetres")
            control.setToolTip("Clockwise rotation around the box centre." if key == "rotation_deg" else
                               "Unrotated box dimension in millimetres." if key in {"width_mm", "height_mm"} else
                               "Position in millimetres from the page top-left.")
            self.numbers[key] = control
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 0, 0, 0)
            label_widget = QCheckBox(label) if key in {"width_mm", "height_mm", "rotation_deg"} else QLabel(label)
            if isinstance(label_widget, QCheckBox):
                self.geometry_checks[key] = label_widget
                self.geometry_labels[key] = QLabel(label)
                row.addWidget(self.geometry_labels[key])
            self.geometry_cells[key] = cell
            row.addWidget(label_widget)
            row.addWidget(control)
            grid.addWidget(cell, index, 0)
            control.editingFinished.connect(lambda name=key: self.apply_field(name))
        for check in self.geometry_checks.values():
            check.toggled.connect(lambda: self.bulkChanged.emit() if self.multi_selection and not self.loading else None)
        self.geometry_apply = QPushButton("Apply to selected")
        self.geometry_apply.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.geometry_apply.setToolTip("Only checked width, height and angle settings change. Text, fonts and other settings are retained.")
        self.geometry_apply.clicked.connect(self.apply_geometry)
        grid.addWidget(self.geometry_apply, 5, 0)
        groups.addWidget(self.geometry)
        self.content_group = QGroupBox("Content")
        content_layout = QVBoxLayout(self.content_group)
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(95)
        self.content.setPlaceholderText("Text or {{Field_Name}}")
        self.content.setAccessibleName("Object content")
        content_layout.addWidget(self.content)
        self.draft_status = QLabel()
        self.draft_status.setWordWrap(True)
        self.draft_status.hide()
        layout.insertWidget(2, self.draft_status)
        self.revert_content = QPushButton("Revert unfinished edit")
        self.revert_content.clicked.connect(self.revertRequested)
        self.revert_content.hide()
        layout.insertWidget(3, self.revert_content)
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
        self.repair_status = QLabel("No missing-glyph repairs configured")
        self.repair_status.setWordWrap(True)
        form.addRow(self.repair_status)
        self.repair_button = QPushButton("Repair missing glyph…")
        self.repair_button.clicked.connect(self.glyphRepairRequested)
        form.addRow(self.repair_button)
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
            control.editingFinished.connect(lambda name=key: self.apply_field(name))
            if key == "font_size":
                form.addRow("Size (pt)", control)
        self.alignment = QComboBox()
        self.alignment.addItems(["left", "center", "right"])
        self.vertical = QComboBox()
        self.vertical.addItems(["top", "center", "bottom"])
        groups.addWidget(self.font_group)
        groups.removeWidget(self.font_group)
        groups.insertWidget(1, self.font_group)
        self.rules_group = QGroupBox("Object rules")
        rules_layout = QVBoxLayout(self.rules_group)
        self.rules_summary = QLabel()
        self.rules_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.rules_summary.setWordWrap(True)
        rules_layout.addWidget(self.rules_summary)
        rule_buttons = QHBoxLayout()
        self.rules_button = QPushButton("Edit rules…")
        self.rules_button.clicked.connect(self.rulesRequested)
        self.rules_clear = QPushButton("Clear")
        self.rules_clear.clicked.connect(self.rulesClearRequested)
        rule_buttons.addWidget(self.rules_button)
        rule_buttons.addWidget(self.rules_clear)
        rules_layout.addLayout(rule_buttons)
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
        control.editingFinished.connect(lambda: self.apply_field("stroke_pt"))
        self.stroke_row = control
        form.addRow("Stroke (pt)", control)
        self.appearance_form = form
        groups.addWidget(self.appearance_group)
        groups.addWidget(self.rules_group)
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
        self.barcode_format = QComboBox()
        self.barcode_format.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.barcode_format.setMinimumContentsLength(10)
        self.barcode_format.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for label, kind in (("Code 128", "code128"), ("I25 (Interleaved 2 of 5)", "i25"), ("QR code", "qr")):
            self.barcode_format.addItem(label, kind)
        self.barcode_format.setAccessibleName("Barcode format")
        self.barcode_format.setToolTip("Change format while retaining the object's content, position and size.")
        self.barcode_format.currentIndexChanged.connect(self.apply)
        form.addRow("Format", self.barcode_format)
        self.ecc = QComboBox()
        self.ecc.addItems(["L", "M", "Q", "H"])
        self.human = QCheckBox("Show barcode text")
        self.barcode_hint = QLabel()
        self.barcode_hint.setWordWrap(True)
        control = QDoubleSpinBox()
        control.setRange(.1, 5)
        control.setDecimals(2)
        control.setSingleStep(.05)
        self.numbers["barcode_module_mm"] = control
        control.editingFinished.connect(lambda: self.apply_field("barcode_module_mm"))
        form.addRow("Min module (mm)", control)
        form.addRow("QR correction", self.ecc)
        form.addRow(self.human)
        form.addRow(self.barcode_hint)
        groups.addWidget(self.barcode_group)
        for group in (self.geometry, self.rules_group, self.font_group, self.content_group,
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
        for signal, key in [(self.alignment.currentTextChanged, "align"),
                            (self.vertical.currentTextChanged, "vertical_align"),
                            (self.ecc.currentTextChanged, "qr_error"),
                            (self.human.toggled, "show_barcode_text")]:
            signal.connect(lambda *args, name=key: self.apply_field(name))
        self.bold.toggled.connect(self._bundled_style)
        self.italic.toggled.connect(self._bundled_style)
        self.font_family.currentIndexChanged.connect(self._family_changed)
        self.font_family.activated.connect(lambda *args: self._family_changed(force=True) if self.bulk_ids else None)
        self.font_family.lineEdit().editingFinished.connect(self._typed_family)
        self.font_style.activated.connect(self._style_chosen)
        self.colour.editingFinished.connect(lambda: self.apply_field("colour"))
        self.fill.editingFinished.connect(lambda: self.apply_field("fill"))
        for key, control in self.numbers.items():
            control.valueChanged.connect(lambda *args, name=key: self._mark_bulk_dirty(name))
            control.lineEdit().textEdited.connect(lambda *args, name=key: self._mark_bulk_dirty(name))
        self.colour.textChanged.connect(lambda: self._mark_bulk_dirty("colour"))
        self.alignment.activated.connect(lambda: self.apply_field("align") if self.bulk_ids else None)
        self.vertical.activated.connect(lambda: self.apply_field("vertical_align") if self.bulk_ids else None)
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

    def restore_geometry(self, selected):
        if not selected:
            return
        loading = self.loading
        self.loading = True
        mixed = []
        for key in ("x_mm", "y_mm", "width_mm", "height_mm", "rotation_deg"):
            self.numbers[key].setValue(getattr(selected[0], key))
            self.displayed_numbers[key] = self.numbers[key].value()
            if key in self.geometry_checks:
                self.geometry_checks[key].setChecked(False)
                if any(getattr(element, key) != getattr(selected[0], key) for element in selected[1:]):
                    mixed.append(key)
        self.geometry.setTitle("Geometry · mixed" if mixed else "Geometry")
        self.geometry.setToolTip("Values shown are from the first selected object. Mixed: " + ", ".join(mixed)
                                 if mixed else "Position, size and clockwise angle.")
        self.loading = loading

    def show_element(self, element):
        self.geometry.setTitle("Geometry")
        self.bulk_dirty.clear()
        self.bulk_font_request = None
        self.batch_status.hide()
        self.batch_revert.hide()
        self.include_barcode.hide()
        for control in self.numbers.values():
            control.lineEdit().setPlaceholderText("")
        self.bulk_ids = []
        self.multi_selection = False
        self.geometry_ids = [element.id] if element else []
        self.geometry_apply.hide()
        for cell in self.geometry_cells.values():
            cell.show()
        for key, check in self.geometry_checks.items():
            check.setChecked(False)
            check.hide()
            self.geometry_labels[key].show()
        self.font_family.lineEdit().setPlaceholderText("")
        self.font_style.setPlaceholderText("")
        self.colour.setPlaceholderText("")
        self.empty.setText("Select an object on the page or in Layers to edit its properties.")
        self.repair_button.setEnabled(True)
        self.repair_button.show()
        self.repair_status.show()
        self.loading = True
        self.element = element
        self.empty.setVisible(element is None)
        self.form_widget.setVisible(element is not None)
        self.title.setText(element.type.title() + " properties" if element else "Properties")
        if element:
            self.font_choice = asdict(element.font)
            self.rules_summary.setText(rules_summary(element.rules))
            self.rules_clear.setEnabled(bool(element.rules.visible_when or element.rules.alternative))
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
            repairs = element.glyph_repairs
            self.repair_status.setText("\n".join(f"{key}: {spec.family}" for key, spec in repairs.items())
                                       or "No missing-glyph repairs configured")
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
            self.barcode_format.setCurrentIndex(self.barcode_format.findData(element.type))
            self.ecc.setCurrentText(element.qr_error)
            self.human.setChecked(element.show_barcode_text)
            self.content_group.setVisible(element.type in {"text", "qr", "code128", "i25"})
            self.font_group.setVisible(element.type == "text" or element.show_barcode_text)
            self.text_layout_group.setVisible(element.type == "text" or element.show_barcode_text)
            self.appearance_group.setVisible(element.type in {"text", "line", "rectangle"})
            self.appearance_form.setRowVisible(self.stroke_row, element.type in {"line", "rectangle"})
            self.appearance_form.setRowVisible(self.fill_row, element.type == "rectangle")
            self.image_group.setVisible(element.type == "image")
            self.barcode_group.setVisible(element.type in {"qr", "code128", "i25"})
            self.ecc.setEnabled(element.type == "qr")
            self.barcode_hint.setText("I25: digits 0-9 only; an even number of digits. Leading zeros are preserved; no checksum is added." if element.type == "i25" else "")
            self.barcode_hint.setVisible(element.type == "i25")
            self.human.setEnabled(element.type in {"code128", "i25"})
        self.loading = False

    def show_selection(self, selected):
        if len(selected) <= 1:
            self.show_element(selected[0] if selected else None)
            return
        self.selection_elements = list(selected)
        text = [e for e in selected if e.type == "text" or (self.include_barcode.isChecked() and e.type in {"code128", "i25"} and e.show_barcode_text)]
        self.show_element(text[0] if text else selected[0])
        self.multi_selection = True
        self.include_barcode.setVisible(any(e.type in {"code128", "i25"} and e.show_barcode_text for e in selected))
        self.geometry_ids = [e.id for e in selected]
        self.restore_geometry(selected)
        self.bulk_ids = [e.id for e in text]
        self.font_family.lineEdit().setModified(False)
        self.title.setText(f"{len(selected)} selected · {len(text)} formatting targets")
        for key in ("x_mm", "y_mm"):
            self.geometry_cells[key].hide()
        for key, check in self.geometry_checks.items():
            check.setEnabled(True)
            check.show()
            self.geometry_labels[key].hide()
        self.geometry_apply.setText("Apply changes")
        self.geometry_apply.setAccessibleName("Apply changed settings")
        self.geometry_apply.setToolTip("Commit checked geometry and changed text settings together, with one Undo.")
        self.geometry_apply.show()
        self.batch_revert.show()
        self.batch_status.setText("Change settings, then Apply. Unchanged or mixed settings are retained.")
        self.batch_status.show()
        self.loading = True
        for key in self.geometry_checks:
            if any(getattr(e, key) != getattr(selected[0], key) for e in selected[1:]):
                self.numbers[key].lineEdit().clear()
                self.numbers[key].lineEdit().setPlaceholderText("Mixed")
        self.loading = False
        if not text:
            for group in (self.rules_group, self.content_group, self.font_group, self.text_layout_group,
                          self.appearance_group, self.image_group, self.barcode_group):
                group.hide()
            self.geometry.show()
            self.empty.setText("Edit width, height or angle, then apply the checked settings to all selected objects.")
            self.empty.show()
            self._refresh_layout()
            return
        differing = []
        for name, getter in [("fonts", lambda e: (e.font.family, e.font.file, e.font.bold, e.font.italic)),
                             ("sizes", lambda e: e.font.size_pt),
                             ("layouts", lambda e: (e.align, e.vertical_align, e.line_spacing)),
                             ("colours", lambda e: e.colour)]:
            if any(getter(e) != getter(text[0]) for e in text[1:]):
                differing.append(name)
        note = ("Mixed " + ", ".join(differing) + ". " if differing else "")
        note += f"Formatting targets: {len(text)}. Mixed values stay unchanged until edited. "
        note += "Checked width, height and angle apply to all selected objects; unchecked geometry is retained."
        if len(selected) != len(text):
            note += f" {len(selected)-len(text)} other objects excluded."
        self.empty.setText(note)
        self.empty.show()
        for group in (self.rules_group, self.content_group, self.image_group, self.barcode_group):
            group.hide()
        self.geometry.show()
        self.font_group.show()
        self.text_layout_group.show()
        self.appearance_group.show()
        self.appearance_form.setRowVisible(self.stroke_row, False)
        self.appearance_form.setRowVisible(self.fill_row, False)
        self.repair_button.hide()
        self.repair_status.setText("Existing glyph repairs are retained.")
        self.repair_status.setVisible(any(e.glyph_repairs for e in text))
        self.font_status.setText("Exact face changes apply to selected text.")
        self.font_style.setToolTip("Choose an exact style to apply to the formatting targets.")
        self.loading = True
        for key, getter in (("font_size", lambda e: e.font.size_pt), ("line_spacing", lambda e: e.line_spacing)):
            if any(getter(e) != getter(text[0]) for e in text[1:]):
                self.numbers[key].lineEdit().clear()
                self.numbers[key].lineEdit().setPlaceholderText("Mixed")
        for control, getter in ((self.alignment, lambda e: e.align), (self.vertical, lambda e: e.vertical_align)):
            control.setPlaceholderText("Mixed")
            if any(getter(e) != getter(text[0]) for e in text[1:]):
                control.setCurrentIndex(-1)
        if "fonts" in differing:
            self.font_family.setCurrentIndex(-1)
            self.font_family.lineEdit().setPlaceholderText("Mixed fonts")
            self.font_style.setCurrentIndex(-1)
            self.font_style.setPlaceholderText("Mixed styles")
        if "colours" in differing:
            self.colour.clear()
            self.colour.setPlaceholderText("Mixed")
        self.loading = False
        self._refresh_layout()
        self.bulkChanged.emit()

    def _refresh_layout(self):
        # Apply hidden-group size constraints now, before the inspector computes scrollbars.
        for widget in reversed(self.findChildren(QWidget)):
            if widget.layout():
                widget.layout().invalidate()
                widget.layout().activate()
        self.form_widget.layout().activate()
        self.layout().invalidate()
        self.layout().activate()
        self.setMinimumWidth(self.minimumSizeHint().width())
        if self.parentWidget():
            self.resize(max(self.minimumWidth(), self.parentWidget().width()), self.height())
        self.updateGeometry()

    def has_batch_draft(self):
        return bool(self.multi_selection and (self.bulk_dirty or self.bulk_font_request or
                    any(check.isChecked() for check in self.geometry_checks.values())))

    def batch_values(self):
        geometry = {key: self.numbers[key].value() for key, check in self.geometry_checks.items() if check.isChecked()}
        values = {}
        font = {}
        if "font" in self.bulk_dirty and not self.bulk_font_request:
            font.update({k: self.font_choice[k] for k in ("family", "file", "bold", "italic")})
        if "font_size" in self.bulk_dirty:
            font["size_pt"] = self.numbers["font_size"].value()
        if font:
            values["font"] = font
        for key, value in (("line_spacing", self.numbers["line_spacing"].value()),
                           ("colour", self.colour.text().strip()), ("align", self.alignment.currentText()),
                           ("vertical_align", self.vertical.currentText())):
            if key in self.bulk_dirty:
                values[key] = value
        return values if self.bulk_ids else {}, geometry

    def _include_barcode_changed(self, checked):
        if self.loading or not self.multi_selection:
            return
        if self.has_batch_draft() and not self.batch_resolver():
            self.include_barcode.blockSignals(True)
            self.include_barcode.setChecked(not checked)
            self.include_barcode.blockSignals(False)
            return
        self.show_selection(self.selection_elements)

    def apply_geometry(self):
        if self.loading or not self.geometry_ids:
            return
        if self.multi_selection:
            self.batchApplyRequested.emit()
        else:
            values = {key: self.numbers[key].value() for key, check in self.geometry_checks.items() if check.isChecked()}
            if values:
                self.geometryEdited.emit(values)

    def _mark_bulk_dirty(self, name):
        if not self.multi_selection or self.loading:
            return
        if name in self.geometry_checks:
            self.geometry_checks[name].setChecked(True)
        elif self.bulk_ids:
            self.bulk_dirty.add(name)
        self.batch_status.setText("Unapplied settings · Apply or Revert before changing selection / page / saving.")
        self.bulkChanged.emit()

    def apply_field(self, name):
        if self.loading or not self.element:
            return
        if self.multi_selection:
            if name in {"align", "vertical_align"}:
                self._mark_bulk_dirty(name)
            return
        if name in self.geometry_checks:
            control = self.numbers[name]
            value = getattr(self.element, name) if control.value() == self.displayed_numbers.get(name) else control.value()
            self.geometryEdited.emit({name: value})
            return
        self.apply()

    def _emit_font_request(self, request):
        if self.multi_selection:
            if request.get("cancel"):
                self.bulk_font_request = None
            elif self.bulk_ids:
                self.bulk_font_request = dict(request)
                self._mark_bulk_dirty("font")
                self.font_status.setText("Exact font pending · Apply changed settings to prepare and commit.")
            return
        self.fontRequested.emit(request)

    def _content_changed(self):
        if not self.loading:
            self.apply()

    def apply(self, *args):
        if self.loading or self.element is None:
            return
        if self.multi_selection:
            return self.batch_resolver()
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
        if self.element.type in {"code128", "i25", "qr"}:
            kind = self.barcode_format.currentData()
            values["type"] = kind
            if kind == "qr":
                values["show_barcode_text"] = False
                if kind != self.element.type:
                    values["glyph_repairs"] = {}
        self.edited.emit(values)

    def _typed_family(self):
        if self.loading or not self.element:
            return
        if self.bulk_ids and not self.font_family.lineEdit().isModified():
            return
        text = self.font_family.currentText()
        if text not in FAMILIES and text not in self.catalogue:
            self.loading = True
            self.font_family.setCurrentIndex(self.font_family.findText(self.element.font.family))
            self.loading = False
            self.font_status.setText("Font not installed. Choose a listed family or a font file.")
            return
        self._family_changed(force=True)

    def _family_changed(self, *args, force=False):
        if self.bulk_ids and not force:
            return
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
            if self.bulk_ids and self.font_choice.get("file") and self.font_style.currentIndex() == 0:
                self._emit_font_request({"file": self.font_choice["file"], "element_id": self.element.id})
            return
        if face.get("bundled"):
            self._emit_font_request({"cancel": True, "element_id": self.element.id})
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
            if self.bulk_ids:
                self._mark_bulk_dirty("font")
            else:
                self.apply()
        else:
            self.font_status.setText("Preparing exact font face…")
            self._emit_font_request({"face": {**face, "family": self.font_family.currentText()},
                                     "element_id": self.element.id})

    def _bundled_style(self, *args):
        if not self.loading and self.element and not self.font_choice.get("file"):
            if self.multi_selection:
                self.font_choice.update(bold=self.bold.isChecked(), italic=self.italic.isChecked())
                self._mark_bulk_dirty("font")
            else:
                self.apply()

    def _font_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose production font", "", "Fonts (*.ttf *.otf *.ttc *.otc)")
        if path and self.element:
            self._emit_font_request({"file": path, "element_id": self.element.id})

    def _colour(self, control):
        colour = QColorDialog.getColor(QColor(control.text() or "#ffffff"), self, "Choose colour")
        if colour.isValid():
            control.setText(colour.name())
            self._mark_bulk_dirty("colour" if control is self.colour else "fill")
            self.apply_field("colour" if control is self.colour else "fill")

    def _image_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Static image", "",
                                             "Images (*.png *.jpg *.jpeg *.tif *.tiff)")
        if path:
            self.image_path.setText(path)
            self.apply()
