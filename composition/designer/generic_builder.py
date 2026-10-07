"""Fixed-length Generic barcode editor with retained per-segment drafts."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from composition.engine.barcode_profiles import BarcodeProfile
from composition.engine.generic_layout import BarcodeContext, BarcodeSegment
from composition.pdf_source.planner import SYSTEM_FIELDS
from ui.combo_popup import WideComboBox

SYSTEM_HELP = {
    "JobId": "Production job ID · provisional zeros in preview, actual ID during generation",
    "EnvelopeIndex": "Envelope / record index · starts at 1",
    "EnvelopeSeq": "Configured envelope sequence · may include existing zero padding",
    "LetterPage": "PDF page within the envelope · starts at 1",
    "LetterPageCount": "Source PDF pages in this envelope",
    "SheetNo": "Physical sheet within envelope · duplex front/back share the same number",
    "SheetCount": "Physical sheets in this envelope",
    "OutputPage": "Page in final output PDF · includes inserted blank backs",
    "SourcePage": "Original source PDF page",
}


def label(text):
    value = QLabel(text)
    value.setWordWrap(True)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return value


class GenericLayoutBuilder(QWidget):
    changed = pyqtSignal()

    def __init__(self, profile, fields, parent=None):
        super().__init__(parent)
        self.draft = copy.deepcopy(profile)
        self.context = BarcodeContext.from_values(fields)
        self.index = -1
        self.updating = True
        self.setMinimumWidth(0)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name, self.machine = QLineEdit(profile.name), QLineEdit(profile.machine)
        self.verified = QCheckBox("Verified on the identified inserter")
        self.verified.setChecked(profile.validation == "user_verified")
        self.total = QSpinBox()
        self.total.setRange(0, 4096)
        self.total.setSpecialValueText("Set total length…")
        self.total.setValue(profile.total_length)
        self.total.setAccessibleName("Barcode total length")
        self.configured = label("")
        form.addRow("Profile name", self.name)
        form.addRow("Machine / model", self.machine)
        form.addRow(self.verified)
        form.addRow("Total length", self.total)
        form.addRow(self.configured)
        root.addLayout(form)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Position", "Length", "Source", "Preview"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumWidth(0)
        self.table.setFixedHeight(180)
        self.table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(35)
        for col in (0, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 70), (2, 52), (3, 90)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        root.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add, self.remove = QPushButton("Add segment"), QPushButton("Remove")
        self.up, self.down = QPushButton("↑"), QPushButton("↓")
        self.up.setAccessibleName("Move segment up")
        self.down.setAccessibleName("Move segment down")
        for button in (self.add, self.remove, self.up, self.down):
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.details = QWidget()
        details = QFormLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.segment_name = QLineEdit()
        self.length = QSpinBox()
        self.length.setRange(0, 4096)
        self.length.setSpecialValueText("Set length…")
        self.source = WideComboBox()
        for text, value in (("Fixed value", "fixed"), ("Data field", "data"), ("System value", "system"), ("Running sequence", "sequence")):
            self.source.addItem(text, value)
        self.value = WideComboBox()
        self.value.setEditable(True)
        self.format = WideComboBox()
        self.format.addItem("Text — keep exact content", "text")
        self.format.addItem("Numeric — value with zero padding", "numeric")
        self.overflow = WideComboBox()
        self.overflow.addItem("Stop on overflow", "stop")
        self.overflow.addItem("Cycle within segment length (99 → 00)", "cycle")
        self.scope = WideComboBox()
        for text, value in (("Per record / envelope", "record"), ("Whole output PDF pages", "page"), ("Physical sheets — restart in each envelope", "sheet")):
            self.scope.addItem(text, value)
        self.start, self.step = QLineEdit("0"), QLineEdit("1")
        self.source_hint = label("")
        for title, widget in (("Segment name", self.segment_name), ("Length", self.length),
                              ("Source", self.source), ("Value / field", self.value), ("Format", self.format),
                              ("Overflow", self.overflow), ("Count by", self.scope), ("Start", self.start), ("Increment", self.step)):
            details.addRow(title, widget)
        details.addRow(self.source_hint)
        root.addWidget(self.details)
        self.preview = label("")
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.preview)
        self.image = QLabel()
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.image)
        self.table.currentCellChanged.connect(self.select)
        self.add.clicked.connect(self.add_segment)
        self.remove.clicked.connect(self.remove_segment)
        self.up.clicked.connect(lambda: self.move(-1))
        self.down.clicked.connect(lambda: self.move(1))
        self.source.currentIndexChanged.connect(self.change_source)
        for widget in (self.segment_name, self.start, self.step):
            widget.textChanged.connect(self.edit)
        self.value.currentTextChanged.connect(self.edit)
        self.length.valueChanged.connect(self.edit)
        self.format.currentIndexChanged.connect(self.edit)
        self.overflow.currentIndexChanged.connect(self.edit)
        self.scope.currentIndexChanged.connect(self.edit)
        for widget in (self.name, self.machine):
            widget.textChanged.connect(self.notify)
        self.total.valueChanged.connect(self.notify)
        self.verified.toggled.connect(self.notify)
        self.updating = False
        self.rebuild(0 if self.draft.segments else -1)

    def candidate(self):
        profile = copy.deepcopy(self.draft)
        profile.name, profile.machine = self.name.text(), self.machine.text()
        profile.validation = "user_verified" if self.verified.isChecked() else "pending"
        profile.total_length = self.total.value()
        profile.validate(profile.fields())
        return profile

    def notify(self, *_):
        if not self.updating:
            self.configured.setText(f"Configured: {sum(s.length for s in self.draft.segments)} / {self.total.value()} characters")
            self.changed.emit()

    def rebuild(self, selected):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.draft.segments))
        position = 1
        for row, segment in enumerate(self.draft.segments):
            values = (segment.name, f"{position}–{position+segment.length-1}" if segment.length else "Set length", str(segment.length), segment.source, "—")
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
            position += segment.length
        self.table.blockSignals(False)
        self.index = -1
        if 0 <= selected < len(self.draft.segments):
            self.table.setCurrentCell(selected, 0)
            self.select(selected)
        else:
            self.image.clear()
            self.details.setEnabled(False)
        self.update_buttons()
        self.notify()

    def select(self, row, *_):
        if not 0 <= row < len(self.draft.segments):
            return
        self.index = row
        segment = self.draft.segments[row]
        self.updating = True
        self.details.setEnabled(True)
        self.segment_name.setText(segment.name)
        self.length.setValue(segment.length)
        self.source.setCurrentIndex(self.source.findData(segment.source))
        self.format.setCurrentIndex(self.format.findData(segment.format))
        self.overflow.setCurrentIndex(self.overflow.findData(segment.overflow))
        self.scope.setCurrentIndex(self.scope.findData(segment.scope))
        self.start.setText(str(segment.start))
        self.step.setText(str(segment.step))
        self.populate_values(segment.value)
        self.updating = False
        self.update_buttons()

    def populate_values(self, value):
        source = self.source.currentData()
        self.value.clear()
        if source == "system":
            for name in sorted(SYSTEM_FIELDS):
                self.value.addItem(SYSTEM_HELP.get(name, name), name)
        elif source == "data":
            for name in sorted(self.context.data):
                self.value.addItem(name, name)
        elif source == "sequence":
            self.value.addItem("New barcode-only sequence", "")
            for name in sorted(self.context.sequences):
                self.value.addItem(name, name)
        found = self.value.findData(value)
        if found >= 0:
            self.value.setCurrentIndex(found)
        else:
            self.value.setCurrentText(value)
        self.update_details()

    def field_value(self):
        index = self.value.currentIndex()
        if index >= 0 and self.value.currentText() == self.value.itemText(index):
            return self.value.itemData(index)
        return self.value.currentText()

    def update_details(self):
        local = self.source.currentData() == "sequence" and not self.field_value()
        for widget in (self.start, self.step, self.scope):
            widget.setEnabled(local)
        cycling = self.source.currentData() == "sequence" and self.format.currentData() == "numeric"
        self.overflow.setEnabled(cycling)
        self.source_hint.setText({"fixed": "Enter fixed content. Text retains all leading zeros.",
            "data": "Value comes from the selected imported / mapped field. PDF extraction is prepared in Workflow.",
            "system": "System counters usually start at 1. Use Running sequence to choose a different start.",
            "sequence": "Existing sequences retain their own configuration. Barcode-only counters default to 0; preview navigation never advances them."}[self.source.currentData()])

    def change_source(self, *_):
        if self.updating or self.index < 0:
            return
        self.updating = True
        source = self.source.currentData()
        self.format.setCurrentIndex(self.format.findData("numeric" if source in {"system", "sequence"} else "text"))
        self.overflow.setCurrentIndex(0)
        self.populate_values("EnvelopeIndex" if source == "system" else "")
        self.updating = False
        self.edit()

    def edit(self, *_):
        if self.updating or self.index < 0:
            return
        segment = self.draft.segments[self.index]
        segment.name, segment.length = self.segment_name.text(), self.length.value()
        segment.source, segment.value = self.source.currentData(), self.field_value()
        segment.format, segment.overflow = self.format.currentData(), self.overflow.currentData()
        if segment.source != "sequence" or segment.format != "numeric":
            segment.overflow = "stop"
            self.overflow.blockSignals(True)
            self.overflow.setCurrentIndex(0)
            self.overflow.blockSignals(False)
        segment.scope = self.scope.currentData()
        # Preserve invalid drafts as text; validation locates them without
        # silently resetting the user's input when another segment is selected.
        for key, widget in (("start", self.start), ("step", self.step)):
            try:
                value = int(widget.text())
            except ValueError:
                value = widget.text()
            setattr(segment, key, value)
        position = 1
        for row, item in enumerate(self.draft.segments):
            for col, text in enumerate((item.name, f"{position}–{position+item.length-1}" if item.length else "Set length", str(item.length), item.source)):
                self.table.item(row, col).setText(text)
                self.table.item(row, col).setToolTip(text)
            position += item.length
        self.update_details()
        self.notify()

    def add_segment(self, *_):
        if len(self.draft.segments) < 30:
            self.draft.segments.append(BarcodeSegment(name=f"Segment {len(self.draft.segments)+1}"))
            self.rebuild(len(self.draft.segments)-1)

    def remove_segment(self, *_):
        if self.index >= 0:
            old = self.index
            self.draft.segments.pop(old)
            self.rebuild(min(old, len(self.draft.segments)-1))

    def move(self, direction):
        target = self.index+direction
        if 0 <= self.index < len(self.draft.segments) and 0 <= target < len(self.draft.segments):
            self.draft.segments[self.index], self.draft.segments[target] = self.draft.segments[target], self.draft.segments[self.index]
            self.rebuild(target)

    def update_buttons(self):
        self.add.setEnabled(len(self.draft.segments) < 30)
        self.remove.setEnabled(self.index >= 0)
        self.up.setEnabled(self.index > 0)
        self.down.setEnabled(0 <= self.index < len(self.draft.segments)-1)

    def show_result(self, context, result=None, pending=False):
        self.context = BarcodeContext.from_values(context)
        if result:
            for row, value in enumerate(result.segments):
                self.table.item(row, 4).setText(value.formatted)
                self.table.item(row, 4).setToolTip(f"Full value: {value.raw}\nEncoded: {value.formatted}" + ("\nCycled within segment length" if value.cycled else ""))
            parts = " | ".join(v.formatted for v in result.segments)
            self.preview.setText(f"{parts}\n\n{result.payload} — {len(result.payload)} characters")
        else:
            self.image.clear()
            self.preview.setText("Data not loaded — payload pending production validation." if pending else "")
            for row in range(self.table.rowCount()):
                self.table.item(row, 4).setText("Pending" if pending else "—")


class GenericBarcodeEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, profile, fields, parent=None, *, symbology=None, samples=None):
        super().__init__(parent)
        from .overlay_dialogs import BarcodeProfileDialog
        self.fields = fields
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.mode = label("")
        root.addWidget(self.mode)
        self.convert = QPushButton("Convert to fixed-length layout…")
        self.convert.clicked.connect(self.convert_legacy)
        root.addWidget(self.convert)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.stack)
        legacy = profile if profile.layout_mode == "legacy" else BarcodeProfile()
        public = {key: value for key, value in fields.items() if isinstance(value, str) and not key.startswith("__Barcode")}
        self.legacy = BarcodeProfileDialog(legacy, public, self, symbology=symbology, samples=samples)
        self.legacy.setWindowFlags(Qt.WindowType.Widget)
        self.legacy.footer.hide()
        self.legacy.sample.hide()  # Errors have one owner: the outer fixed footer.
        self.legacy.changed.connect(self.changed)
        self.stack.addWidget(self.legacy)
        fixed = profile if profile.layout_mode == "fixed" else BarcodeProfile.fixed_layout()
        self.builder = GenericLayoutBuilder(fixed, fields, self)
        self.builder.changed.connect(self.changed)
        self.stack.addWidget(self.builder)
        self.stack.setCurrentIndex(int(profile.layout_mode == "fixed"))
        self.preview = label("")
        root.addWidget(self.preview)
        self.update_mode()

    def update_mode(self):
        fixed = self.stack.currentIndex() == 1
        self.mode.setText("Fixed-length layout — each segment has an explicit source and length." if fixed else
                          "Legacy layout — original concatenation is retained. Convert explicitly to define exact lengths.")
        self.convert.setVisible(not fixed)
        self.preview.setVisible(not fixed)

    def convert_legacy(self):
        context = BarcodeContext.from_values(self.fields)
        segments = []
        for index, token in enumerate(self.legacy.tokens()):
            source = ("fixed" if token.kind == "literal" else "system" if token.value in SYSTEM_FIELDS else
                      "sequence" if token.value in context.sequences else "data")
            numeric = (source != "fixed" and (token.width > 0 or
                       source == "system" and token.value not in {"JobId", "Side", "PageRole", "MediaStock"} or
                       source == "sequence" and context.sequences[token.value].isascii() and context.sequences[token.value].isdigit()))
            segments.append(BarcodeSegment(name=token.value if token.kind == "field" else f"Fixed {index+1}",
                source=source, value=token.value, length=len(token.value) if token.kind == "literal" else token.width,
                format="numeric" if numeric else "text"))
        old = self.builder
        self.builder = GenericLayoutBuilder(BarcodeProfile.fixed_layout(segments=segments,
            name=self.legacy.name.text(), machine=self.legacy.machine.text()), self.fields, self)
        self.builder.changed.connect(self.changed)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.addWidget(self.builder)
        self.stack.setCurrentIndex(1)
        self.update_mode()
        self.changed.emit()

    def candidate(self):
        return self.builder.candidate() if self.stack.currentIndex() == 1 else self.legacy.candidate()
