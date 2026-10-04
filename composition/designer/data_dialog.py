"""Confirm encoding, delimiter, headers and preserved-to-normalized field mappings."""
from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from composition.data.excel_source import is_excel
from composition.template.model import DataConfig

from .process import Worker


class DataDialog(QDialog):
    def __init__(self, source, directory: Path, parent=None, config=None):
        super().__init__(parent)
        self.excel = is_excel(source)
        self.setWindowTitle("Import Excel" if self.excel else "Import CSV / TXT")
        self.resize(760, 640)
        self.directory, self.source = directory, source
        self.workers = []
        self.generation = 0
        self.originals = []
        self.sample_valid = False
        self.saved_mapping = {}
        self.sample_notes = ""
        self.initial_config = config
        self.setModal(True)
        layout = QVBoxLayout(self)
        title = QLabel(source)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QFormLayout()
        self.sheet = QComboBox()
        self.sheet.setAccessibleName("Excel worksheet")
        self.formulas = QCheckBox("Use saved formula results (no recalculation)")
        self.zeros = QCheckBox("Preserve simple leading-zero number formats")
        self.zeros.setChecked(True)
        self.encoding = QComboBox()
        self.encoding.setEditable(True)
        self.encoding.addItems(["utf-8-sig", "utf-8", "utf-16", "big5", "gb18030", "cp1252"])
        self.delimiter = QComboBox()
        for text, value in [("Comma", ","), ("Tab", "\t"), ("Semicolon", ";"), ("Pipe", "|")]:
            self.delimiter.addItem(text, value)
        self.header = QCheckBox("First selected row contains field names")
        self.header.setChecked(True)
        self.start_row = QSpinBox()
        self.start_row.setRange(1, 100000)
        form.addRow("Encoding", self.encoding)
        form.addRow("Delimiter", self.delimiter)
        form.addRow("Header", self.header)
        form.addRow("Header / start row", self.start_row)
        form.addRow("Worksheet", self.sheet)
        form.addRow("Formulas", self.formulas)
        form.addRow("Numbers", self.zeros)
        for control in (self.encoding, self.delimiter):
            control.setVisible(not self.excel)
            form.labelForField(control).setVisible(not self.excel)
        for control in (self.sheet, self.formulas, self.zeros):
            control.setVisible(self.excel)
            form.labelForField(control).setVisible(self.excel)
        layout.addLayout(form)
        layout.addWidget(QLabel("Field mapping: original source name → variable name"))
        self.mapping = QTableWidget(0, 2)
        self.mapping.setHorizontalHeaderLabels(["Original field", "Variable name"])
        self.mapping.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.mapping, 1)
        layout.addWidget(QLabel("Sample records"))
        self.sample = QTableWidget()
        layout.addWidget(self.sample, 1)
        self.message = QLabel("Checking source…")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import data")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._sample)
        self.mapping.itemChanged.connect(self._validate_mapping)
        for signal in (self.sheet.currentIndexChanged, self.formulas.toggled, self.zeros.toggled, self.encoding.currentTextChanged, self.delimiter.currentIndexChanged,
                       self.header.toggled, self.start_row.valueChanged):
            signal.connect(self._schedule)
        if config and not self.excel:
            self._suggested({"config": asdict(config)})
        else:
            self._worker({"task": "suggest", "source": source}, self._suggested, self._failed)

    def _worker(self, request, result, failure):
        worker = Worker(self.directory, request, self)
        self.workers.append(worker)
        worker.resultReady.connect(result)
        worker.failed.connect(failure)
        worker.ended.connect(lambda: self.workers.remove(worker))
        return worker

    def _suggested(self, result):
        config = asdict(self.initial_config) if self.initial_config else result["config"]
        controls = [self.encoding, self.delimiter, self.header, self.start_row, self.sheet, self.formulas, self.zeros]
        for control in controls:
            control.blockSignals(True)
        if self.excel:
            self.sheet.clear()
            for sheet in result.get("sheets", []):
                self.sheet.addItem(sheet["name"] + (" (hidden)" if sheet.get("hidden") else ""), sheet["name"])
            name = config.get("sheet") or result.get("default_sheet", "")
            selected = self.sheet.findData(name)
            if selected < 0:
                self.sheet.addItem(name + " (not found)", name)
                selected = self.sheet.count()-1
            self.sheet.setCurrentIndex(selected)
        self.formulas.setChecked(config.get("excel_formulas", "reject") == "cached")
        self.zeros.setChecked(config.get("preserve_zeros", True))
        self.encoding.setCurrentText(config["encoding"])
        index = self.delimiter.findData(config["delimiter"])
        if index == -1:
            self.delimiter.addItem(repr(config["delimiter"]), config["delimiter"])
            index = self.delimiter.count()-1
        self.delimiter.setCurrentIndex(index)
        self.header.setChecked(config["header"])
        self.start_row.setValue(config.get("header_row", 1))
        for control in controls:
            control.blockSignals(False)
        self._schedule()

    def config(self):
        return DataConfig(path=self.source, encoding=self.encoding.currentText(),
                          delimiter=self.delimiter.currentData(), header=self.header.isChecked(),
                          header_row=self.start_row.value(),
                          sheet=(self.sheet.currentData() or "") if self.excel else "",
                          excel_formulas="cached" if self.formulas.isChecked() else "reject",
                          preserve_zeros=self.zeros.isChecked(),
                          mapping={self.mapping.item(row, 0).text(): self.mapping.item(row, 1).text().strip()
                                   for row in range(self.mapping.rowCount())})

    def _schedule(self, *args):
        if self.sample_valid:
            self.saved_mapping.update(self.config().mapping)
        self.sample_valid = False
        self.generation += 1
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.timer.start()

    def _sample(self):
        generation = self.generation
        for worker in self.workers[:]:
            worker.stop_preview()
        config = self.config()
        # A changed delimiter/header must infer its own field structure.
        config.mapping = {}
        self.message.setText("Reading sample…")
        self._worker({"task": "sample", "config": asdict(config)},
                     lambda result: self._sample_ready(result, generation),
                     lambda error: self._failed(error) if generation == self.generation else None)

    def _sample_ready(self, result, generation):
        if generation != self.generation:
            return
        self.mapping.blockSignals(True)
        self.mapping.setRowCount(len(result["originals"]))
        self.originals = result["originals"]
        for row, original in enumerate(self.originals):
            item = QTableWidgetItem(original)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mapping.setItem(row, 0, item)
            alias = self.saved_mapping.get(original, result["fields"][row])
            if self.initial_config and original not in self.saved_mapping:
                alias = self.initial_config.mapping.get(original, alias)
            self.mapping.setItem(row, 1, QTableWidgetItem(alias))
        self.mapping.blockSignals(False)
        self.sample.setColumnCount(len(self.originals))
        self.sample.setHorizontalHeaderLabels(self.originals)
        self.sample.setRowCount(len(result["sample"]))
        for row, values in enumerate(result["sample"]):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.sample.setItem(row, column, item)
        self.sample_notes = ("Dates use ISO format; numbers use plain decimal values. Original field names are preserved."
                             if self.excel else "Confirm the encoding and sample. Original field names are preserved.")
        if result.get("warnings"):
            self.sample_notes += "\n" + "\n".join(result["warnings"])
        self.sample_valid = True
        self._validate_mapping()

    def _validate_mapping(self, *_):
        valid = self.sample_valid and self.mapping.rowCount() > 0
        if valid:
            names = [self.mapping.item(row, 1).text().strip() for row in range(self.mapping.rowCount())]
            valid = len(set(names)) == len(names) and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names)
            self.message.setText(self.sample_notes if valid else "Variable names must be unique and use letters, digits or underscores.")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def accept(self):
        self._validate_mapping()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            super().accept()

    def _failed(self, message):
        self.sample_valid = False
        self.message.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def done(self, result):
        self.timer.stop()
        for worker in self.workers[:]:
            worker.stop_preview()
        super().done(result)
