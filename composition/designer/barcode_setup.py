"""Shared, scrollable barcode setup with an explicit 18-digit inserter preset."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from composition.engine.barcode_profiles import INSERTER_I25, BarcodeProfile
from composition.engine.barcodes import validate_payload
from composition.engine.rules import validate_group
from ui.combo_popup import WideComboBox

from .overlay_dialogs import BarcodeProfileDialog
from .rules_dialog import ConditionEditor


class BarcodeSetupDialog(QDialog):
    def __init__(self, profile, fields, parent=None, *, symbology=None, samples=None,
                 duplex=False, printing_locked=False, template=False, selected_preset=None):
        super().__init__(parent)
        self.setWindowTitle("Barcode configuration")
        available = self.screen().availableGeometry()
        self.resize(min(760, available.width()-24), min(580, available.height()-24))
        self.setMinimumSize(400, 280)
        self.fields = dict(fields)
        self.samples = samples or []
        self.symbology = symbology
        self.placement_check = None
        self.preview_context = None
        self.template_mode = template
        self.profile = copy.deepcopy(profile)
        self.inserter = copy.deepcopy(profile) if profile.preset == INSERTER_I25 else BarcodeProfile.inserter()
        root = QVBoxLayout(self)
        self.preset = WideComboBox()
        self.preset.setAccessibleName("Barcode preset")
        self.preset.addItem("Generic — fields and fixed text", "generic")
        self.preset.addItem("Inserter I25 — 18 digits", INSERTER_I25)
        root.addWidget(self.preset)
        self.preset_description = QLabel()
        self.preset_description.setWordWrap(True)
        self.preset_description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.preset_description)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        generic = profile if profile.preset == "generic" else BarcodeProfile(machine=profile.machine)
        self.generic = BarcodeProfileDialog(generic, fields, self, symbology=symbology, samples=samples)
        self.generic.setWindowFlags(Qt.WindowType.Widget)
        self.generic.footer.hide()
        self.stack.addWidget(self.generic)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.stack.addWidget(self.tabs)
        body_layout.addWidget(self.stack)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.footer.button(QDialogButtonBox.StandardButton.Ok).setText("Apply barcode settings")
        self.footer.accepted.connect(self.accept)
        self.footer.rejected.connect(self.reject)
        root.addWidget(self.footer)
        sequence, form = self.section("Sequence")
        self.start = QSpinBox()
        self.start.setRange(0, 99)
        self.start.setValue(self.inserter.group_start)
        self.start.setDisplayIntegerBase(10)
        self.start.setAccessibleName("Group sequence start")
        form.addRow("Group start (00–99)", self.start)
        form.addRow(self.label("Every envelope adds one; 98 → 99 → 00 → 01.\n"
                               "Sheet sequence restarts at 01. EOG = 1 on the last physical sheet.\n"
                               "Output bin diversion: Off (VS1 / VS2 = 0).\n"
                               "ColourMark / Location = 0. Check digit is automatic."))
        form.addRow(self.label("Machine validation: " +
            ("user verified — " + self.inserter.machine if self.inserter.validation == "user_verified" else
             "pending; confirm barcode dimensions, direction and read position on the actual inserter.")))
        inserts, insert_form = self.section("Inserts")
        self.insert_modes, self.insert_buttons, self.insert_summaries = [], [], []
        from PyQt6.QtWidgets import QPushButton
        for index, insert in enumerate(self.inserter.inserts):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            control = WideComboBox()
            for title, mode in (("Not included", "never"), ("Always included", "always"), ("Conditional", "conditional")):
                control.addItem(title, mode)
            control.setCurrentIndex(control.findData(insert.mode))
            control.setAccessibleName(f"Insert {index+1}")
            button = QPushButton("Condition…")
            button.clicked.connect(lambda checked=False, i=index: self.edit_condition(i))
            layout.addWidget(control, 1)
            layout.addWidget(button)
            insert_form.addRow(f"Insert {index+1}", row)
            summary = self.label("")
            insert_form.addRow(summary)
            self.insert_modes.append(control)
            self.insert_buttons.append(button)
            self.insert_summaries.append(summary)
            control.currentIndexChanged.connect(self.refresh)
        customer, customer_form = self.section("Customer info")
        self.customer = WideComboBox()
        self.customer.addItem("Fixed 000000000 (9 zeros)", "")
        for name in sorted(fields):
            if not name.startswith("__Barcode"):
                self.customer.addItem(name, name)
        if self.inserter.customer_field and self.customer.findData(self.inserter.customer_field) < 0:
            self.customer.addItem(self.inserter.customer_field, self.inserter.customer_field)
        self.customer.setCurrentIndex(max(0, self.customer.findData(self.inserter.customer_field)))
        customer_form.addRow("Digits 9–17", self.customer)
        self.customer_name = self.label("")
        customer_form.addRow(self.customer_name)
        customer_form.addRow(self.label("Exactly nine ASCII digits. Leading zeros are kept; values are not truncated or padded."))
        placement, placement_form = self.section("Placement")
        self.printing = WideComboBox()
        self.printing.addItem("Simplex — one PDF page per physical sheet", False)
        self.printing.addItem("Duplex — front / back, pad odd envelopes with a blank back", True)
        self.printing.setCurrentIndex(int(duplex))
        self.printing.setEnabled(not printing_locked)
        placement_form.addRow("Printing", self.printing)
        placement_form.addRow(self.label("One control barcode on each sheet front; blank backs receive no barcode.\n"
                                        "Position, size and rotation remain in Object properties."))
        if printing_locked:
            placement_form.addRow(self.label("Printing follows the current envelope / Media settings."))
        self.repeat = QCheckBox("Apply to required template pages at the same X / Y position")
        self.repeat.setChecked(template)
        self.repeat.setVisible(template)
        placement_form.addRow(self.repeat)
        self.placement_details = self.label("Target pages will be checked before anything is committed.")
        self.placement_details.setVisible(template)
        placement_form.addRow(self.placement_details)
        preview, preview_form = self.section("Preview")
        self.payload = self.label("")
        self.payload.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_form.addRow(self.payload)
        self.barcode_image = QLabel()
        self.barcode_image.setMinimumHeight(70)
        self.barcode_image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preview_form.addRow(self.barcode_image)
        for control in (self.start,):
            control.valueChanged.connect(self.refresh)
        self.customer.currentIndexChanged.connect(self.refresh)
        self.printing.currentIndexChanged.connect(self.refresh)
        self.repeat.toggled.connect(self.refresh)
        self.generic.changed.connect(self.refresh)
        self.preset.currentIndexChanged.connect(self.refresh)
        self.preset.setCurrentIndex(self.preset.findData(selected_preset or profile.preset))
        self.refresh()

    @staticmethod
    def label(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def section(self, title):
        widget = QWidget()
        form = QFormLayout(widget)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.tabs.addTab(widget, title)
        return widget, form

    def candidate(self):
        if self.preset.currentData() == "generic":
            return self.generic.candidate()
        profile = copy.deepcopy(self.inserter)
        profile.group_start = self.start.value()
        profile.customer_field = self.customer.currentData() or ""
        for insert, control in zip(profile.inserts, self.insert_modes, strict=True):
            insert.mode = control.currentData()
            if insert.mode != "conditional":
                insert.when = None
        profile.validate(self.fields)
        return profile

    def edit_condition(self, index):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Insert {index+1} condition")
        available = dialog.screen().availableGeometry()
        dialog.resize(min(650, available.width()-24), min(380, available.height()-24))
        layout = QVBoxLayout(dialog)
        editor = ConditionEditor("Include insert when", sorted(self.fields), self.inserter.inserts[index].when)
        editor.setChecked(True)
        layout.addWidget(editor)
        error = self.label("")
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        def apply():
            try:
                group = editor.read_group()
                validate_group(group)
            except ValueError as exc:
                error.setText(str(exc))
                return
            self.inserter.inserts[index].when = group
            dialog.accept()
        buttons.accepted.connect(apply)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            self.insert_modes[index].setCurrentIndex(2)
        dialog.deleteLater()
        self.refresh()

    def refresh(self, *_):
        if not hasattr(self, "customer"):
            return
        inserter = self.preset.currentData() == INSERTER_I25
        self.stack.setCurrentIndex(int(inserter))
        self.preset_description.setText("Inserter I25 — 18 digits: physical sheets, inserts, automatic EOG and check digit."
                                       if inserter else "Generic barcode: join fields and fixed text in order.")
        self.customer_name.setText("Customer information: " + self.customer.currentText())
        for index, control in enumerate(self.insert_modes):
            conditional = control.currentData() == "conditional"
            self.insert_buttons[index].setEnabled(conditional)
            group = self.inserter.inserts[index].when
            self.insert_summaries[index].setText(
                (" / ".join(f"{c.field} {c.operator} {c.value}" for c in group.conditions) if group else "Set a condition to continue.")
                if conditional else "")
            self.insert_summaries[index].setVisible(conditional)
        try:
            profile = self.candidate()
            if self.placement_check is not None:
                self.placement_details.setText(self.placement_check())
            lines = []
            payload = ""
            preview_fields = self.preview_context(bool(self.printing.currentData())) if self.preview_context else self.fields
            for label, fields in [("Current record / sheet", preview_fields), *self.samples]:
                needed = profile.fields()-set(fields)
                if needed:
                    lines.append(f"{label}: data required for {', '.join(sorted(needed))}; checked during production.")
                    continue
                payload = profile.payload(fields)
                validate_payload("i25" if inserter else self.symbology or "code128", payload)
                if inserter:
                    parts = profile.inserter_parts(fields)
                    lines.append(f"{label}: {parts['group']} | {parts['sheet']} | {parts['inserts_1_3']} | "
                                 f"{parts['inserts_4_6']} | {parts['eog']} | 0 | {parts['customer']} | {parts['check_digit']}\n"
                                 f"{payload} — 18 digits")
                else:
                    lines.append(f"{label}: {payload} ({len(payload)} characters)")
            if inserter:
                self.payload.setText("Group | Sheet | Inserts 1–3 | Inserts 4–6 | EOG | Location | Customer | Check\n\n" + "\n\n".join(lines))
                if payload:
                    self.draw_preview(payload)
            self.status.setText("Settings checked. Exact dimensions and all records are checked before production.")
            self.footer.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc))
            self.payload.setText(str(exc))
            self.barcode_image.clear()
            self.footer.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def draw_preview(self, payload):
        from barcode import ITF
        from PIL import Image
        pattern = ITF(payload, narrow=1, wide=3).build()[0]
        image = Image.new("RGB", ((len(pattern)+20)*2, 72), "white")
        pixels = image.load()
        for index, bit in enumerate(pattern):
            if bit == "1":
                for x in range((index+10)*2, (index+11)*2):
                    for y in range(8, 64):
                        pixels[x, y] = (0, 0, 0)
        raw = image.tobytes()
        qimage = QImage(raw, image.width, image.height, image.width*3, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimage)
        self.barcode_image.setPixmap(pixmap.scaled(min(520, max(200, self.width()-80)), 72,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def accept(self):
        self.refresh()
        if not self.footer.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            return
        self.profile = self.candidate()
        self.duplex = bool(self.printing.currentData())
        super().accept()
