"""Grouping and declarative barcode profile editors for existing PDF overlays."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)

from composition.engine.barcodes import validate_payload
from composition.overlay.model import BarcodeProfile, BarcodeToken
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import SYSTEM_FIELDS, EnvelopePlan

SCOPE_LABELS = [("Every source page", "all_source"), ("Every output page (including blank backs)", "all_output"),
                ("First source page of each envelope", "first"), ("Last source page of each envelope", "last"),
                ("Sheet fronts", "front"), ("Specific letter page", "letter_page")]


class GroupingDialog(QDialog):
    def __init__(self, settings=None, source_pages=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF envelope grouping & running sequence")
        self.settings = settings or EnvelopeSettings()
        self.source_pages = source_pages
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.pages = QSpinBox()
        self.pages.setRange(1, 100)
        self.pages.setValue(self.settings.pages_per_envelope)
        form.addRow("Source pages per envelope", self.pages)
        self.pages.setEnabled(not bool(self.settings.groups))
        self.detect = QCheckBox("Auto-detect variable page counts after opening PDF")
        self.detect.setVisible(not source_pages and not self.settings.groups)
        form.addRow(self.detect)
        self.detect.toggled.connect(lambda on: self.pages.setEnabled(not on))
        self.printing = QComboBox()
        self.printing.addItems(["Simplex: one page per sheet", "Duplex: pad odd groups with a blank back"])
        self.printing.setCurrentIndex(int(self.settings.duplex))
        form.addRow("Printing", self.printing)
        self.values = {}
        for key, title in [("start", "Sequence start"), ("increment", "Increment"), ("digits", "Minimum digits"),
                           ("prefix", "Prefix"), ("suffix", "Suffix")]:
            control = QLineEdit(str(getattr(self.settings, key)))
            form.addRow(title, control)
            self.values[key] = control
            control.textChanged.connect(self.refresh)
        layout.addLayout(form)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.pages.valueChanged.connect(self.refresh)
        self.printing.currentIndexChanged.connect(self.refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def candidate(self):
        values = {key: control.text() for key, control in self.values.items()}
        for key in ("start", "increment", "digits"):
            values[key] = int(values[key])
        result = EnvelopeSettings(pages_per_envelope=1 if self.detect.isChecked() else self.pages.value(),
                                  duplex=bool(self.printing.currentIndex()), groups=self.settings.groups,
                                  excluded_pages=self.settings.excluded_pages, **values)
        result.validate()
        if self.source_pages:
            EnvelopePlan(self.source_pages, result)
        return result

    def refresh(self):
        try:
            settings = self.candidate()
            if self.source_pages:
                plan = EnvelopePlan(self.source_pages, settings)
                text = (f"{plan.source_pages:,} source pages → {plan.envelopes:,} envelopes\n"
                        f"{plan.output_pages:,} output pages · {plan.sheets:,} sheets · {plan.inserted_blanks:,} blank backs\n"
                        f"Sequence {settings.sequence(1)} → {settings.sequence(plan.envelopes)}")
            else:
                text = "Grouping and sequence are checked against the selected PDF before design begins."
            self.summary.setText(text)
        except ValueError as exc:
            self.summary.setText(str(exc))

    def accept(self):
        try:
            self.settings = self.candidate()
        except ValueError as exc:
            QMessageBox.warning(self, "Check grouping", str(exc))
            return
        super().accept()


class BarcodeProfileDialog(QDialog):
    def __init__(self, profile, fields, parent=None, *, symbology=None, samples=None):
        super().__init__(parent)
        self.setWindowTitle("Barcode payload profile")
        self.resize(600, 500)
        self.fields = fields
        self.symbology = symbology
        self.samples = samples or []
        self.rebuilding = False
        self.profile = profile
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(profile.name)
        self.machine = QLineEdit(profile.machine)
        self.verified = QCheckBox("I have verified this profile with the identified inserter")
        self.verified.setChecked(profile.validation == "user_verified")
        form.addRow("Profile name", self.name)
        form.addRow("Machine / model (optional)", self.machine)
        form.addRow(self.verified)
        layout.addLayout(form)
        hint = QLabel("Tokens are joined in order. Digits = 0 preserves the field; a positive width pads numeric fields.\n"
                      "Default: EnvelopeSeq + LetterPage (2 digits) + LetterPageCount (2 digits).")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Kind", "Field / literal", "Digits"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add token")
        add.clicked.connect(lambda: self.add_token(BarcodeToken()))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_token)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        self.token_up = QPushButton("Move up")
        self.token_down = QPushButton("Move down")
        self.token_up.clicked.connect(lambda: self.move_token(-1))
        self.token_down.clicked.connect(lambda: self.move_token(1))
        buttons.addWidget(self.token_up)
        buttons.addWidget(self.token_down)
        self.table.currentCellChanged.connect(self.update_token_buttons)
        layout.addLayout(buttons)
        self.sample = QLabel()
        self.sample.setTextFormat(Qt.TextFormat.PlainText)
        self.sample.setWordWrap(True)
        layout.addWidget(self.sample)
        for token in profile.tokens:
            self.add_token(token)
        for control in (self.name, self.machine):
            control.textChanged.connect(self.refresh)
        self.verified.toggled.connect(self.refresh)
        self.footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.footer.accepted.connect(self.accept)
        self.footer.rejected.connect(self.reject)
        layout.addWidget(self.footer)
        self.refresh()

    def add_token(self, token):
        if self.table.rowCount() >= 30:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        kind = QComboBox()
        kind.addItems(["field", "literal"])
        kind.setCurrentText(token.kind)
        value = QComboBox()
        value.setEditable(True)
        value.addItems(sorted(SYSTEM_FIELDS | set(self.fields)))
        value.setCurrentText(token.value)
        width = QSpinBox()
        width.setRange(0, 18)
        width.setValue(token.width)
        for col, control in enumerate((kind, value, width)):
            self.table.setCellWidget(row, col, control)
        width.setEnabled(token.kind == "field")
        kind.currentTextChanged.connect(lambda text: width.setEnabled(text == "field"))
        for col, control in enumerate((kind, value, width)):
            signal = control.valueChanged if col == 2 else control.currentTextChanged
            signal.connect(lambda *args, r=row, c=col: self.token_changed(r, c))
        self.table.setCurrentCell(row, 0)
        self.refresh()

    def token_changed(self, row, column):
        self.table.setCurrentCell(row, column)
        self.refresh()

    def update_token_buttons(self, *args):
        row = self.table.currentRow()
        self.token_up.setEnabled(row > 0)
        self.token_down.setEnabled(0 <= row < self.table.rowCount() - 1)

    def tokens(self):
        return [BarcodeToken(self.table.cellWidget(row, 0).currentText(),
                             self.table.cellWidget(row, 1).currentText(),
                             self.table.cellWidget(row, 2).value() if self.table.cellWidget(row, 0).currentText() == "field" else 0)
                for row in range(self.table.rowCount())]

    def move_token(self, direction):
        row = self.table.currentRow()
        target = row + direction
        if not 0 <= row < self.table.rowCount() or not 0 <= target < self.table.rowCount():
            return
        tokens = self.tokens()
        tokens[row], tokens[target] = tokens[target], tokens[row]
        self.rebuilding = True
        self.table.setRowCount(0)
        for token in tokens:
            self.add_token(token)
        self.table.setCurrentCell(target, 0)
        self.rebuilding = False
        self.refresh()

    def remove_token(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
        self.refresh()

    def candidate(self):
        profile = BarcodeProfile(name=self.name.text(), machine=self.machine.text(),
                  validation="user_verified" if self.verified.isChecked() else "pending", tokens=self.tokens())
        profile.validate(self.fields)
        return profile

    def refresh(self):
        if not hasattr(self, "sample") or self.rebuilding:
            return
        self.update_token_buttons()
        error = ""
        try:
            profile = self.candidate()
            lines = []
            for label, fields in [("Current page", self.fields), *self.samples]:
                pending=any(t.kind=="field" and t.value not in SYSTEM_FIELDS and not fields.get(t.value) for t in profile.tokens)
                if pending:
                    lines.append(label+": workflow data required; payload validated during workflow production")
                    continue
                payload = profile.payload(fields)
                if self.symbology:
                    validate_payload(self.symbology, payload)
                lines.append(f"{label}: {payload} ({len(payload)} characters)")
            self.sample.setText("\n".join(lines))
        except ValueError as exc:
            error = str(exc)
            self.sample.setText(error)
        if hasattr(self, "footer"):
            self.footer.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)

    def accept(self):
        try:
            self.profile = self.candidate()
            for _, fields in [("Current", self.fields), *self.samples]:
                if any(t.kind=="field" and t.value not in SYSTEM_FIELDS and not fields.get(t.value) for t in self.profile.tokens):
                    continue
                payload = self.profile.payload(fields)
                if self.symbology:
                    validate_payload(self.symbology, payload)
        except ValueError as exc:
            QMessageBox.warning(self, "Check barcode profile", str(exc))
            return
        super().accept()
