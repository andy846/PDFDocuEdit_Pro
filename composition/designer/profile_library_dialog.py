"""Browse local profiles and import them through the existing worker transport."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from composition.media.model import FAMILIES, PS_FAMILIES

from .process import Worker


class ProfileLibraryDialog(QDialog):
    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Print Media · Profile library")
        self.resize(820, 560)
        self.library = str(directory)
        self.directory = Path(tempfile.mkdtemp(prefix="media-library-"))
        self.worker = None
        self.closing = False
        self.selected_profile = None
        self.entries = []
        root = QVBoxLayout(self)
        note = QLabel("Choose a saved setup for this environment. Import profile JSON files or a folder; document data is not imported.")
        note.setWordWrap(True)
        root.addWidget(note)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Device"))
        self.device = QComboBox()
        self.device.addItem("All devices", "")
        for key, label in (FAMILIES | PS_FAMILIES).items():
            self.device.addItem(label, key)
        filters.addWidget(self.device, 1)
        self.kind = QComboBox()
        self.kind.addItem("All profile types", "")
        self.kind.addItem("Complete media setup", "media")
        self.kind.addItem("Printer mappings only", "printer")
        filters.addWidget(self.kind, 1)
        for combo in (self.device, self.kind):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        root.addLayout(filters)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.profiles = QListWidget()
        self.profiles.setMinimumWidth(180)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumWidth(200)
        self.splitter.addWidget(self.profiles)
        self.splitter.addWidget(self.details)
        self.splitter.setSizes([330, 460])
        root.addWidget(self.splitter, 1)
        imports = QHBoxLayout()
        self.import_files = QPushButton("Import profiles…")
        self.import_folder = QPushButton("Import folder…")
        imports.addWidget(self.import_files)
        imports.addWidget(self.import_folder)
        imports.addStretch(1)
        root.addLayout(imports)
        self.status = QLabel("Reading local profiles…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.use_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.use_button.setText("Use selected profile")
        self.use_button.setProperty("primary", True)
        root.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.profiles.currentItemChanged.connect(self.describe)
        self.device.currentIndexChanged.connect(self.filter_entries)
        self.kind.currentIndexChanged.connect(self.filter_entries)
        self.import_files.clicked.connect(self.choose_files)
        self.import_folder.clicked.connect(self.choose_folder)
        self.start()

    def start(self, **options):
        if self.worker is not None:
            return
        self.status.setText("Importing profiles…" if options else "Reading local profiles…")
        self.worker = Worker(self.directory, {"task": "media_profile_library", "directory": self.library, **options}, self)
        self.worker.resultReady.connect(self.ready)
        self.worker.failed.connect(self.status.setText)
        self.worker.ended.connect(self.ended)
        self.controls()

    def controls(self):
        busy = self.worker is not None
        for widget in (self.import_files, self.import_folder, self.profiles, self.device, self.kind):
            widget.setEnabled(not busy)
        self.use_button.setEnabled(not busy and self.profiles.currentItem() is not None)

    def ready(self, result):
        self.entries = result["entries"]
        self.filter_entries()
        text = f"{len(self.entries)} saved profiles. Device validation: Pending."
        if "imported" in result:
            text = f"Imported {result['imported']} · Already saved {result['duplicates']}. " + text
        errors = result.get("import_errors", []) + result.get("errors", [])
        if errors:
            text += f" {len(errors)} invalid / unreadable file(s); hover for details."
        if result.get("cancelled"):
            text += " Import cancelled; completed imports are retained."
        self.status.setText(text)
        self.status.setToolTip("\n".join(errors[:20]))

    def filter_entries(self):
        current = self.profiles.currentItem()
        previous = current.data(Qt.ItemDataRole.UserRole)["id"] if current else None
        self.profiles.clear()
        for entry in self.entries:
            if self.device.currentData() and entry["family"] != self.device.currentData():
                continue
            if self.kind.currentData() and entry["profile"]["kind"] != self.kind.currentData():
                continue
            kind = "Media setup" if entry["profile"]["kind"] == "media" else "Printer mappings"
            item = QListWidgetItem(entry["name"] + "\n" + kind)
            item.setToolTip(entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.profiles.addItem(item)
            if entry["id"] == previous:
                self.profiles.setCurrentItem(item)
        if self.profiles.currentRow() < 0 and self.profiles.count():
            self.profiles.setCurrentRow(0)
        self.describe()

    def describe(self, *_):
        item = self.profiles.currentItem()
        if not item:
            self.details.setPlainText("No matching profiles.\n\nImport a profile file or folder, or choose All devices.\n\nCancel keeps your current media settings.")
            self.controls()
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        profile = entry["profile"]
        settings = profile["settings"]
        printer = settings if profile["kind"] == "printer" else settings["printer_profile"]
        output = "PDF + PostScript" if printer["backend"] == "postscript" else "PDF + JDF"
        lines = [entry["name"], "Device: " + (FAMILIES | PS_FAMILIES)[entry["family"]], "Output: " + output,
                 "Device validation: Pending", "Notes: " + printer["controller_version"], ""]
        if profile["kind"] == "media":
            lines += ["Replaces Stocks, page rules, duplex settings and printer mappings.",
                      "Enabled: " + str(settings["enabled"]), "Duplex: " + str(settings["duplex"]),
                      "Rule scope: " + {"page": "Logical page within each letter / record", "role": "Page role within each letter / record",
                                        "template": "Template page identity (requires the matching template)"}[settings["mode"]],
                      "", "Stocks:"]
            lines += [f"  {s['id']} · {s['name']} · {s['width_mm']} × {s['height_mm']} mm" for s in settings["stocks"]]
            lines += ["", "Page rules:"]
            lines += [f"  {key} -> {value}" for key, value in list(settings["assignments"].items())[:50]]
            if len(settings["assignments"]) > 50:
                lines.append("  More rules are available in Page rules after loading.")
            lines += ["Fallback: " + (settings["fallback_stock"] or "Block unassigned pages")]
        else:
            lines += ["Replaces printer mappings only. Stocks and page rules stay as they are.",
                      "Stock IDs must match your current setup."]
        lines += ["", "Printer mappings (" + printer["selection_mode"] + "):"]
        lines += [f"  {key}: " + ", ".join(f"{name}={value}" for name, value in values.items() if value is not None and value != "")
                  for key, values in printer["mappings"].items()]
        lines += ["", "After loading, review Page rules and export a paper-selection test PS before production."]
        self.details.setPlainText("\n".join(lines))
        self.controls()

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Import media / printer profiles", "", "JSON profiles (*.json)")
        if paths:
            self.start(sources=paths)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Import profile folder (including subfolders)")
        if path:
            self.start(folder=path)

    def ended(self):
        self.worker = None
        self.controls()
        if self.closing:
            self.reject()

    def accept(self):
        if self.worker is not None or self.profiles.currentItem() is None:
            return
        self.selected_profile = copy.deepcopy(self.profiles.currentItem().data(Qt.ItemDataRole.UserRole)["profile"])
        self.cleanup()
        super().accept()

    def reject(self):
        if self.worker is not None:
            self.closing = True
            self.worker.cancel()
            self.status.setText("Cancelling after the current file; completed imports are retained…")
            return
        self.cleanup()
        super().reject()

    def closeEvent(self, event):
        event.ignore()
        self.reject()

    def cleanup(self):
        if self.directory.exists():
            for path in self.directory.iterdir():
                path.unlink(missing_ok=True)
            self.directory.rmdir()
