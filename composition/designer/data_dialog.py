"""Confirm encoding, delimiter, headers and preserved-to-normalized field mappings."""
from __future__ import annotations

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

from composition.template.model import DataConfig

from .process import Worker


class DataDialog(QDialog):
    def __init__(self, source, directory: Path, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Import CSV / TXT")
        self.resize(720, 600)
        self.directory, self.source = directory, source
        self.workers = []
        self.generation = 0
        self.originals = []
        self.initial_config = config
        self.setModal(True)
        layout = QVBoxLayout(self)
        title = QLabel(source)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QFormLayout()
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
        for signal in (self.encoding.currentTextChanged, self.delimiter.currentIndexChanged,
                       self.header.toggled, self.start_row.valueChanged):
            signal.connect(self._schedule)
        if config:
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
        config = result["config"]
        controls = [self.encoding, self.delimiter, self.header, self.start_row]
        for control in controls:
            control.blockSignals(True)
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
                          mapping={self.mapping.item(row, 0).text(): self.mapping.item(row, 1).text().strip()
                                   for row in range(self.mapping.rowCount())})

    def _schedule(self, *args):
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
        self.mapping.setRowCount(len(result["originals"]))
        self.originals = result["originals"]
        for row, original in enumerate(self.originals):
            item = QTableWidgetItem(original)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mapping.setItem(row, 0, item)
            alias = result["fields"][row]
            if self.initial_config:
                alias = self.initial_config.mapping.get(original, alias)
            self.mapping.setItem(row, 1, QTableWidgetItem(alias))
        self.sample.setColumnCount(len(self.originals))
        self.sample.setHorizontalHeaderLabels(self.originals)
        self.sample.setRowCount(len(result["sample"]))
        for row, values in enumerate(result["sample"]):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.sample.setItem(row, column, item)
        self.message.setText("Confirm the encoding and sample. Original field names are preserved.")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _failed(self, message):
        self.message.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def done(self, result):
        self.timer.stop()
        for worker in self.workers[:]:
            worker.stop_preview()
        super().done(result)
