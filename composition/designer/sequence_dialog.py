"""Configure declarative running fields with immediate first/last examples."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from composition.data.sequences import check_field_collisions, sequence_value, validate_sequences
from composition.template.model import CompositionError, SequenceSpec, Template, required_fields


class SequenceDialog(QDialog):
    def __init__(self, template, imported_fields=(), imported_count=0, parent=None):
        super().__init__(parent)
        self.template = template
        self.imported_fields = list(imported_fields)
        self.imported_count = imported_count
        self.choice = None
        self.setWindowTitle("Running sequences")
        self.resize(850, 510)
        layout = QVBoxLayout(self)
        intro = QLabel("Create reusable fields such as {{Seq}} for text, Code 128 or QR code.\n"
                       "Values follow record/page order. Preview and reruns keep the same numbers.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Use imported CSV / TXT records", "Generate records without CSV / TXT"])
        self.mode.setCurrentIndex(int(template.record_mode == "generated"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.quantity.setValue(template.generated_count)
        self.quantity.setAccessibleName("Generated record quantity")
        row.addWidget(self.mode, 1)
        row.addWidget(QLabel("Quantity"))
        row.addWidget(self.quantity)
        layout.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Field name", "Start", "Increment", "Digits", "Prefix", "Suffix", "Scope"])
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setAccessibleName("Running sequence field settings")
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for index, width in enumerate((130, 85, 85, 55, 95, 85, 170)):
            self.table.setColumnWidth(index, width)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add sequence")
        remove = QPushButton("Remove selected")
        add.clicked.connect(lambda: self.add_sequence())
        remove.clicked.connect(self.remove_selected)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.example = QLabel()
        self.example.setWordWrap(True)
        layout.addWidget(self.example)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for seq in template.sequences:
            self.add_sequence(seq)
        if not template.sequences:
            self.add_sequence()
        self.table.setCurrentCell(0, 0)
        self.table.itemChanged.connect(self.refresh)
        self.table.currentCellChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.quantity.valueChanged.connect(self.refresh)
        self.refresh()

    def add_sequence(self, seq=None):
        if self.table.rowCount() >= 100:
            return
        if seq is None:
            names = {self.table.item(row, 0).text() for row in range(self.table.rowCount())} | set(self.imported_fields)
            name, index = "Seq", 2
            while name in names:
                name, index = f"Seq_{index}", index + 1
            seq = SequenceSpec(name=name)
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((seq.name, seq.start, seq.step, seq.padding, seq.prefix, seq.suffix)):
            self.table.setItem(row, col, QTableWidgetItem(str(value)))
        scope = QComboBox()
        scope.addItems(["Per record", "Per output page"])
        scope.setCurrentIndex(int(seq.scope == "page"))
        scope.currentIndexChanged.connect(self.refresh)
        self.table.setCellWidget(row, 6, scope)
        self.table.blockSignals(False)
        self.table.setCurrentCell(row, 0)
        if hasattr(self, "buttons"):
            self.refresh()

    def remove_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        self.table.blockSignals(True)
        for row in rows:
            self.table.removeRow(row)
        self.table.blockSignals(False)
        self.refresh()

    def values(self):
        sequences = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() for col in range(6)]
            for col in (1, 2, 3):
                if len(values[col]) > 22:
                    raise CompositionError("Start, increment and digits need short integer values.")
            try:
                seq = SequenceSpec(values[0], int(values[1]), int(values[2]), int(values[3]),
                                   values[4], values[5], "page" if self.table.cellWidget(row, 6).currentIndex() else "record")
            except ValueError as exc:
                raise CompositionError(f"Sequence row {row+1}: start, increment and digits must be integers.") from exc
            sequences.append(seq)
        mode = "generated" if self.mode.currentIndex() else "imported"
        candidate = Template(pages=self.template.pages, sequences=sequences, record_mode=mode,
                             generated_count=self.quantity.value())
        validate_sequences(candidate)
        if mode == "imported":
            check_field_collisions(candidate, self.imported_fields)
        removed = {seq.name for seq in self.template.sequences} - {seq.name for seq in sequences}
        fields = set(self.imported_fields) if mode == "imported" else set()
        used = removed & required_fields(candidate) - fields
        if used:
            raise CompositionError("Sequence fields are still used by text/barcodes/rules: " + ", ".join(sorted(used))
                                   + ". Update those objects before removing or renaming the fields.")
        return candidate

    def refresh(self, *_):
        self.quantity.setEnabled(bool(self.mode.currentIndex()))
        try:
            candidate = self.values()
            count = candidate.generated_count if candidate.record_mode == "generated" else self.imported_count
            row = self.table.currentRow()
            if candidate.sequences:
                seq = candidate.sequences[max(0, min(row, len(candidate.sequences)-1))]
                pages = len(candidate.pages)
                text = f"{seq.name}: record 1 = {sequence_value(seq, 1, 0, pages)} · record 2 = {sequence_value(seq, 2, 0, pages)}"
                if seq.scope == "page" and pages > 1:
                    text += f" · record 1 / page 2 = {sequence_value(seq, 1, 1, pages)}"
                if count:
                    text += f"\nLast: record {count:,} / page {pages} = {sequence_value(seq, count, pages-1, pages)}"
                text += "\nDigits is a minimum; longer numbers are retained. Negative signs precede padded digits."
                self.example.setText(text)
            else:
                self.example.setText("No sequence fields. Generated quantity can still create copies of static content.")
            self.error.setText("" if count else "Import data before previewing or generating imported records.")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except CompositionError as exc:
            self.error.setText(str(exc))
            self.example.clear()
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def accept(self):
        try:
            self.choice = self.values()
        except CompositionError:
            self.refresh()
            return
        super().accept()
