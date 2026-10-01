"""Explicit missing-character settings; no automatic font substitution."""
from __future__ import annotations

from dataclasses import asdict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from composition.engine.fonts import FAMILIES


class GlyphRepairDialog(QDialog):
    def __init__(self, element, catalogue, codepoint="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Repair a missing glyph")
        self.resize(590, 500)
        self.element, self.catalogue = element, catalogue
        self.choice = None
        layout = QVBoxLayout(self)
        heading = QLabel(f"Primary font: {element.font.family} — retained")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        note = QLabel(
            "Only this code point, in this object, can use the selected repair face. "
            "Characters supported by the primary font keep their original face. "
            "Size, colour and baseline follow the original text.\n"
            "For private-use characters, compare the glyph with the source document.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.code = QLineEdit(codepoint)
        self.code.setPlaceholderText("U+E473 or one character")
        form.addRow("Missing code point", self.code)
        self.family = QComboBox()
        self.family.setEditable(True)
        self.family.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.family.addItems(list(FAMILIES) + sorted(set(catalogue)-set(FAMILIES), key=str.casefold))
        completion = QCompleter([self.family.itemText(i) for i in range(self.family.count())], self.family)
        completion.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completion.setFilterMode(Qt.MatchFlag.MatchContains)
        self.family.setCompleter(completion)
        form.addRow("Repair family", self.family)
        self.style = QComboBox()
        form.addRow("Exact style", self.style)
        self.family.currentTextChanged.connect(self._styles)
        layout.addLayout(form)
        self._styles()
        self.table = QTableWidget(len(element.glyph_repairs), 2)
        self.table.setHorizontalHeaderLabels(["Configured code point", "Repair font"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for index, (key, spec) in enumerate(element.glyph_repairs.items()):
            self.table.setItem(index, 0, QTableWidgetItem(key))
            self.table.setItem(index, 1, QTableWidgetItem(spec.family))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._existing)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        file_button = QPushButton("Choose repair font file…")
        file_button.clicked.connect(self._file)
        row.addWidget(file_button)
        remove = QPushButton("Remove selected repair")
        remove.clicked.connect(self._remove)
        row.addWidget(remove)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def key(self):
        from composition.template.model import canonical_codepoint
        return canonical_codepoint(self.code.text().strip())

    def _styles(self, *args):
        self.style.clear()
        family = self.family.currentText()
        if family in FAMILIES:
            for style in (("Regular", "Bold") if family.endswith("HK") else
                          ("Regular", "Bold", "Italic", "Bold Italic")):
                self.style.addItem(style, {"spec": {
                    "family": family, "bold": "Bold" in style, "italic": "Italic" in style}})
        else:
            seen = set()
            for face in self.catalogue.get(family, []):
                if not face["usable"] or face["style"] in seen:
                    continue
                seen.add(face["style"])
                self.style.addItem(face["style"], {"face": face})

    def _existing(self):
        row = self.table.currentRow()
        if row < 0:
            return
        key = self.table.item(row, 0).text()
        spec = self.element.glyph_repairs[key]
        self.code.setText(key)
        if self.family.findText(spec.family) < 0:
            self.family.addItem(spec.family)
        self.family.setCurrentText(spec.family)
        self._styles()
        self.style.insertItem(0, "Saved exact face", {"spec": asdict(spec)})
        self.style.setCurrentIndex(0)

    def _finish(self, choice):
        try:
            self.choice = {**choice, "codepoint": self.key(), "element_id": self.element.id}
        except ValueError as exc:
            QMessageBox.warning(self, "Missing-glyph repair", str(exc))
            return
        self.accept()

    def _apply(self):
        selected = self.style.currentData()
        if not selected:
            QMessageBox.warning(self, "Repair font", "Choose an installed exact face or a font file.")
            return
        self._finish(selected)

    def _file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose repair font", "",
                                            "Fonts (*.ttf *.otf *.ttc *.otc)")
        if path:
            self._finish({"file": path})

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.code.setText(self.table.item(row, 0).text())
            self._finish({"remove": True})
