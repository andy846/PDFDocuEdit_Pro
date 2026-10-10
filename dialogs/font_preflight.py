"""Editor font inspection; explicit original-face selection and Repair Copy."""

import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from composition.designer.process import Worker
from core.font_preflight.service import export_report
from ui.combo_popup import WideComboBox

from .base import ToolDialog


class FontPreflightDialog(ToolDialog):
    outputReady = pyqtSignal(str)
    pageRequested = pyqtSignal(int)

    def __init__(self, source, *, password="", scan_only=False, source_current=None, parent=None):
        super().__init__("Font Preflight / Safe Embed Fonts", "font_preflight", parent)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.source = str(source)
        self.sources = [self.source]
        self.source_current = source_current or (lambda: True)
        self.scan_only = scan_only
        self.editor_source = True
        self.secrets = {"password": password}
        self.directory = tempfile.TemporaryDirectory(prefix="font-preflight-ui-")
        self.worker, self.report, self.inventory = None, {}, None
        self.selections, self.output, self.close_pending = {}, "", False
        self.batch_sources, self.batch_results = [], None
        self.heading = QLabel(
            "Analyze existing PDF fonts. Safe embedding preserves original text and layout; uncertain cases stay blocked."
        )
        self.source_label = QLabel("Source: " + Path(self.source).name)
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        self._root.addWidget(self.source_label)
        self.heading.setWordWrap(True)
        self._root.addWidget(self.heading)
        row = QHBoxLayout()
        self.policy = WideComboBox()
        self.policy.addItem("Print policy — Base-14 allowed", "print")
        self.policy.addItem("Strict policy — require embedding", "strict")
        row.addWidget(self.policy, 1)
        self.batch = QPushButton("Choose PDFs…")
        self.batch.clicked.connect(self.choose_batch)
        row.addWidget(self.batch)
        self._root.addLayout(row)
        self.password_edit = QLineEdit(password)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Source password for encrypted batch PDFs (scan only)")
        self.password_edit.textChanged.connect(self.invalidate)
        self._root.addWidget(self.password_edit)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Font / object", "Type", "Status", "Pages", "Original font"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self.show_selection)
        self.table.cellDoubleClicked.connect(self.jump_page)
        self._root.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.font_button = QPushButton("Choose original font…")
        self.catalogue = QPushButton("Find installed candidates…")
        self.font_button.clicked.connect(self.choose_font)
        self.catalogue.clicked.connect(self.find_candidates)
        row.addWidget(self.font_button)
        row.addWidget(self.catalogue)
        self._root.addLayout(row)
        self.authorized = QCheckBox("I am authorized to embed the selected original font files")
        self._root.addWidget(self.authorized)
        self.reference = QLineEdit()
        self.reference.setReadOnly(True)
        self.reference.setPlaceholderText("Authoritative PDF with the exact original fonts embedded")
        row = QHBoxLayout()
        row.addWidget(self.reference, 1)
        self.reference_button = QPushButton("Reference PDF…")
        self.reference_button.clicked.connect(self.choose_reference)
        self.repair_button_hint = (
            "Select original fonts, confirm authorized use, Check sources, then select a trusted reference."
        )
        row.addWidget(self.reference_button)
        self._root.addLayout(row)
        self.trusted = QCheckBox(
            "This reference is the correct original-font output, not a substituted-font render"
        )
        self._root.addWidget(self.trusted)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(90)
        self._root.addWidget(self.details)
        self.inspect_file = QPushButton("Inspect selected batch PDF")
        self.inspect_file.clicked.connect(self.inspect_selected_batch)
        self.inspect_file.hide()
        self.back_batch = QPushButton("Return to batch results")
        self.back_batch.clicked.connect(self.return_batch)
        self.back_batch.hide()
        self._root.addWidget(self.inspect_file)
        self._root.addWidget(self.back_batch)
        self.progress = QProgressBar()
        self._root.addWidget(self.progress)
        actions = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze fonts")
        self.check_button = QPushButton("Check sources")
        self.repair_button = QPushButton("Repair Copy…")
        self.export_button = QPushButton("Export report…")
        self.open_button = QPushButton("Open output")
        self.cancel_button = QPushButton("Cancel task")
        self.analyze_button.clicked.connect(self.analyze)
        self.check_button.clicked.connect(self.check_sources)
        self.repair_button.clicked.connect(self.repair)
        self.export_button.clicked.connect(self.export)
        self.open_button.clicked.connect(lambda: self.outputReady.emit(self.output))
        self.cancel_button.clicked.connect(lambda: self.worker.cancel() if self.worker else None)
        for control in (self.analyze_button, self.check_button, self.repair_button, self.cancel_button):
            actions.addWidget(control)
        row = QHBoxLayout()
        row.addWidget(self.export_button)
        row.addWidget(self.open_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self._root.addLayout(row)
        actions.addWidget(close)
        self._root.addLayout(actions)
        self.policy.currentIndexChanged.connect(self.invalidate)
        self.authorized.toggled.connect(self.invalidate_matches)
        self.trusted.toggled.connect(self.update_controls)
        self.monitor = QTimer(self)
        self.monitor.setInterval(200)
        self.monitor.timeout.connect(self.check_current)
        self.monitor.start()
        for edit in (self.password_edit, self.reference):
            palette = edit.palette()
            dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#a0a5ad" if dark else "#626970"))
            edit.setPalette(palette)
        self.update_controls()

    def check_current(self):
        if self.worker and not self.source_current():
            self.worker.cancel()
            self.details.setPlainText(
                "Editor source changed; cancelling this check. Reopen the tool for current content."
            )

    def update_controls(self, *_):
        busy, single = self.worker is not None, len(self.sources) == 1
        has_inventory = bool(self.inventory) and single
        for control in (
            self.batch,
            self.policy,
            self.authorized,
            self.reference_button,
            self.trusted,
            self.analyze_button,
            self.password_edit,
        ):
            control.setEnabled(not busy)
        for control in (self.font_button, self.catalogue, self.check_button):
            control.setEnabled(not busy and has_inventory)
        self.repair_button.setEnabled(
            not busy
            and has_inventory
            and bool(self.selections)
            and bool(self.reference.text())
            and self.authorized.isChecked()
            and self.trusted.isChecked()
            and bool(self.report.get("matches"))
            and all(m["status"] == "CANDIDATE_FOUND" for m in self.report["matches"])
            and self.inventory.get("complete", False)
            and not self.inventory.get("protected", True)
            and not self.scan_only
        )
        self.repair_button.setToolTip(self.repair_button_hint)
        self.inspect_file.setEnabled(not busy and bool(self.batch_results))
        self.back_batch.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(not busy and bool(self.report))
        self.open_button.setEnabled(not busy and bool(self.output))

    def invalidate(self, *_):
        self.inventory, self.report, self.output = None, {}, ""
        self.batch_sources, self.batch_results = [], None
        self.inspect_file.hide()
        self.back_batch.hide()
        self.table.setRowCount(0)
        self.update_controls()

    def invalidate_matches(self, *_):
        if self.inventory:
            self.report = {"inventory": self.inventory}
        self.update_controls()

    def choose_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose PDFs for font analysis", "", "PDF (*.pdf)")
        if paths:
            self.sources, self.source = paths, paths[0]
            self.source_current, self.scan_only, self.editor_source = (lambda: True), False, False
            self.selections = {}
            self.batch_sources, self.batch_results = [], None
            self.inspect_file.hide()
            self.back_batch.hide()
            self.source_label.setText(f"Batch: {len(paths)} PDF(s)")
            self.invalidate()
            self.heading.setText(
                f"{len(paths)} PDF(s) selected. Batch scan isolates failures; no files are modified."
            )

    def selected_resource(self):
        row = self.table.currentRow()
        rows = (self.inventory or {}).get("resources", [])
        return rows[row] if 0 <= row < len(rows) else None

    def show_selection(self):
        resource = self.selected_resource()
        if resource:
            match = next(
                (m for m in self.report.get("matches", []) if m["font_xref"] == resource["xref"]), None
            )
            self.details.setPlainText(
                (match or resource).get("reason", "")
                + "\n"
                + resource["usage"]
                + "\nDouble-click to open the first affected page."
            )

    def jump_page(self, *_):
        resource = self.selected_resource()
        if resource and resource["pages"] and len(self.sources) == 1 and self.editor_source:
            self.pageRequested.emit(resource["pages"][0] - 1)

    def choose_font(self):
        resource = self.selected_resource()
        if not resource:
            self.details.setPlainText("Select a font row first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose authorized original TrueType font", "", "TrueType (*.ttf)"
        )
        if path:
            self.selections[str(resource["xref"])] = {"path": path}
            self.invalidate_matches()
            self.fill_table()

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose authoritative original-font PDF", "", "PDF (*.pdf)"
        )
        if path:
            self.reference.setText(path)
            self.reference.setToolTip(path)
            self.trusted.setChecked(False)
            self.update_controls()

    def find_candidates(self):
        self.start(
            {"task": "font_catalogue", "names": [r["name"] for r in self.inventory["resources"]]},
            self.candidates_ready,
        )

    def candidates_ready(self, result):
        resource = self.selected_resource()
        candidates = [
            c for c in result.get("candidates", []) if resource and c["postscript_name"] == resource["name"]
        ]
        if not candidates:
            self.details.setPlainText(
                "No eligible installed static TrueType candidate for the selected font. Choose a customer-provided original file."
            )
            return
        labels = [c["postscript_name"] + " · " + c["version"] + " · " + c["path"] for c in candidates]
        selected, accepted = QInputDialog.getItem(
            self,
            "Original-face candidates",
            "Choose explicitly; matching name is not proof of identity",
            labels,
            0,
            False,
        )
        if accepted:
            self.selections[str(resource["xref"])] = {"path": candidates[labels.index(selected)]["path"]}
            self.invalidate_matches()
            self.fill_table()

    def start(self, request, callback):
        if self.worker:
            return
        if not self.source_current():
            self.details.setPlainText(
                "The Editor document changed. Close this tool and analyze the current document again."
            )
            return
        request.update(source=self.source, policy=self.policy.currentData(), scan_only=self.scan_only)
        self.secrets["password"] = self.password_edit.text()
        self.worker = Worker(
            Path(self.directory.name),
            request,
            self,
            worker_module="core.pdf_operations.worker",
            secrets=self.secrets,
        )
        self.worker.resultReady.connect(callback)
        self.worker.failed.connect(lambda message: self.details.setPlainText(message))
        self.worker.progress.connect(self.progress_changed)
        self.worker.ended.connect(self.ended)
        self.update_controls()

    def progress_changed(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(message + " %p%" if total else message)

    def ended(self):
        self.worker = None
        self.update_controls()
        if self.close_pending:
            self.reject()

    def analyze(self):
        self.output = ""
        task = "font_analyze_batch" if len(self.sources) > 1 else "font_analyze"
        self.start({"task": task, "sources": self.sources}, self.analysis_ready)

    def check_sources(self):
        self.start({"task": "font_match", "selections": self.approved_selections()}, self.analysis_ready)

    def approved_selections(self):
        return {
            key: {**value, "authorized": self.authorized.isChecked()}
            for key, value in self.selections.items()
        }

    def analysis_ready(self, result):
        self.report = result
        if result.get("files"):
            self.batch_sources, self.batch_results = list(self.sources), result
            self.inspect_file.show()
        self.inventory = result.get("inventory")
        if self.inventory and self.scan_only:
            self.inventory["protected"] = True
            self.inventory["issues"].append(
                "Original Editor document is encrypted/restricted; snapshot is scan-only."
            )
        self.fill_table()
        if self.inventory:
            self.details.setPlainText(
                "\n".join(
                    [
                        f"Pages: {self.inventory['page_count']}",
                        "Analysis: "
                        + ("Complete" if self.inventory["complete"] else "Incomplete — repair blocked"),
                        "Signed / encrypted / restricted: " + str(self.inventory["protected"]),
                        *self.inventory["issues"],
                    ]
                )
            )
        else:
            self.details.setPlainText(
                "\n".join(
                    f"{Path(self.sources[r['file_index'] - 1]).name}: {r['status']} · {r.get('reason', '')}"
                    for r in result.get("files", [])
                )
                or result.get("error", "Operation cancelled.")
            )

    def fill_table(self):
        rows = (self.inventory or {}).get("resources", [])
        if not self.inventory and self.report.get("files"):
            self.table.setRowCount(len(self.report["files"]))
            for row, item in enumerate(self.report["files"]):
                report = item.get("inventory", {})
                values = [
                    Path(self.batch_sources[item["file_index"] - 1]).name,
                    "PDF",
                    item["status"],
                    str(report.get("page_count", "")),
                    item.get("reason", ""),
                ]
                for column, value in enumerate(values):
                    control = QTableWidgetItem(value)
                    control.setToolTip(value)
                    self.table.setItem(row, column, control)
            return
        self.table.setRowCount(len(rows))
        matches = {m["font_xref"]: m for m in self.report.get("matches", [])}
        for row, resource in enumerate(rows):
            candidate = self.selections.get(str(resource["xref"]), {})
            values = [
                f"{resource['name']} / {resource['xref']}",
                resource["subtype"],
                matches.get(resource["xref"], resource)["status"],
                ", ".join(map(str, resource["pages"][:30])) + ("…" if len(resource["pages"]) > 30 else ""),
                Path(candidate.get("path", "")).name if candidate else "Not selected",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)

    def inspect_selected_batch(self):
        row = self.table.currentRow()
        if not self.batch_results or not 0 <= row < len(self.batch_results["files"]):
            return
        self.source = self.batch_sources[row]
        self.source_label.setText("Source: " + Path(self.source).name)
        self.sources = [self.source]
        self.selections = {}
        self.inspect_file.hide()
        self.back_batch.show()
        self.analysis_ready({"inventory": self.batch_results["files"][row].get("inventory")})
        self.update_controls()

    def return_batch(self):
        if self.batch_results:
            self.sources = list(self.batch_sources)
            self.source_label.setText(f"Batch: {len(self.sources)} PDF(s)")
            self.back_batch.hide()
            self.analysis_ready(self.batch_results)
            self.update_controls()

    def repair(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Publish verified PDF and audit in a new job folder"
        )
        if directory:
            self.start(
                {
                    "task": "font_repair",
                    "output_dir": directory,
                    "selections": self.approved_selections(),
                    "reference": self.reference.text(),
                    "authorized_reference": self.trusted.isChecked(),
                },
                self.repaired,
            )

    def repaired(self, result):
        self.report = result
        self.output = result.get("output_pdf", "")
        self.details.setPlainText(
            "Validated copy: " + self.output + "\nReport: " + result.get("report_dir", "")
            if self.output
            else result.get("error", "No output published.")
        )

    def export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export font evidence", "font-report.json", "JSON (*.json);;CSV (*.csv)"
        )
        if path:
            try:
                export_report(
                    self.inventory if path.lower().endswith(".csv") and self.inventory else self.report, path
                )
            except Exception as exc:
                self.details.setPlainText(str(exc))

    def reject(self):
        if self.worker:
            self.close_pending = True
            self.worker.cancel()
            self.details.setPlainText("Cancelling; waiting for safe cleanup before closing…")
            return
        self.directory.cleanup()
        super().reject()

    def closeEvent(self, event):
        if self.worker:
            event.ignore()
            self.reject()
        else:
            self.directory.cleanup()
            super().closeEvent(event)
