"""One production dialog for the shared Flatten and Repair services."""
from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
)

from composition.designer.process import Worker
from core.pdf_operations.model import PdfOperationPlan, PdfOptions
from core.variables import VariableContext, VariableError
from ui.variable_name import VariableNameEdit

from .base import ToolDialog


class PdfOperationDialog(ToolDialog):
    outputReady = pyqtSignal(str)

    def __init__(self, source, operation, *, page_count=0, current_page=0, password="",
                 output_password="", output_permissions=None, source_current=None, parent=None,
                 settings_only=False, initial_options=None):
        title = "Flatten PDF" if operation == "flatten" else "PDF Repair / Production Normalise"
        super().__init__(title, "pdf_" + operation, parent)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.source = str(source)
        self.operation = operation
        self.settings_only = settings_only
        self.selected_options = None
        self.page_count, self.current_page = page_count, current_page
        self.secrets = {"password": password or "", "output_password": output_password or "",
                        "output_permissions": output_permissions}
        self.source_current = source_current or (lambda: True)
        self.directory = tempfile.TemporaryDirectory(prefix="pdf-operation-ui-")
        self.worker = None
        self.plan = None
        self.sources = [self.source]
        self.analyses = []
        self.last_result = {}
        self.close_pending = False
        self.signed_hint = self.recovery_hint = False
        self.source_label = QLabel("Source: " + Path(source).name)
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        self._root.addWidget(self.source_label)
        self.batch_button = QPushButton("Choose PDFs for batch processing…")
        self.batch_button.clicked.connect(self.choose_batch)
        self._root.addWidget(self.batch_button)
        form = QFormLayout()
        self._root.addLayout(form)
        self.password_edit = QLineEdit(password or "")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("For an encrypted source; passed privately to the worker")
        form.addRow("Source password", self.password_edit)
        self.mode = QComboBox()
        for label, value in (("Safe Repair — structural rewrite only", "safe"),
                             ("Production Normalise — explicit options", "normalise"),
                             ("Maximum Compatibility — rasterise all pages", "maximum")):
            self.mode.addItem(label, value)
        if operation == "repair":
            form.addRow("Mode", self.mode)
        self.pages = QComboBox()
        self.pages.addItems(["All pages", "Current page", "Page range"])
        self.range = QLineEdit()
        self.range.setPlaceholderText("1-3,5")
        form.addRow("Pages", self.pages)
        form.addRow("Range", self.range)
        self.annotations = QCheckBox("Flatten visible annotations")
        self.annotations.setChecked(operation == "flatten")
        self.forms = QCheckBox("Flatten AcroForm values")
        self.forms.setToolTip("Freeze current visible field appearances. XFA is unsupported; calculations will not run.")
        self.raster = QCheckBox("Rasterise selected pages")
        self.raster.setToolTip("Rebuild pages as images: original text, vectors and interactions are lost.")
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 1200)
        self.dpi.setValue(300)
        form.addRow(self.annotations)
        form.addRow(self.forms)
        form.addRow(self.raster)
        form.addRow("Raster DPI", self.dpi)
        self.javascript = QCheckBox("Remove JavaScript")
        self.attachments = QCheckBox("Remove embedded files and page attachments")
        self.metadata = QCheckBox("Remove Info metadata and XMP")
        self.boxes = QCheckBox("Clip invalid CropBox to MediaBox")
        self.boxes.setToolTip("Explicitly changes the visible page crop. Other page boxes are not guessed or rebuilt.")
        if operation == "repair":
            for control in (self.javascript, self.attachments, self.metadata, self.boxes):
                form.addRow(control)
        self.preflight = QCheckBox("Run Production Preflight before / after")
        self.allow_errors = QCheckBox("Save Preflight errors as Needs review")
        form.addRow(self.preflight)
        form.addRow(self.allow_errors)
        self.signature = QCheckBox("Acknowledge invalidated digital signature")
        self.signature.setToolTip("A derived PDF cannot retain the original digital signature validity.")
        self.raster_ack = QCheckBox("Accept rasterisation losses (no automatic OCR)")
        self.recovery_ack = QCheckBox("Accept recovery with limited appearance QC")
        self.recovery_ack.setToolTip("If the original cannot render, comparison uses the recovered baseline only. Output needs review.")
        form.addRow(self.signature)
        form.addRow(self.raster_ack)
        if operation == "repair":
            form.addRow(self.recovery_ack)
        self.naming = VariableNameEdit("{{input.stem}}_" + ("flattened.pdf" if operation == "flatten" else "repaired.pdf"), self)
        self.naming.set_context(VariableContext.for_job(input_path=self.source, job_id="example-job"))
        form.addRow("Output PDF", self.naming)
        self.output_folder = QLineEdit()
        self.output_folder.setPlaceholderText("Each run publishes PDF + CSV + JSON in a new job folder")
        form.addRow("Output root", self.output_folder)
        browse = QPushButton("Choose output folder…")
        browse.clicked.connect(self.browse_output)
        form.addRow(browse)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(130)
        self._root.addWidget(self.summary, 1)
        self.progress = QProgressBar()
        self._root.addWidget(self.progress)
        actions = QHBoxLayout()
        self.analyse_button = QPushButton("Analyse")
        self.generate_button = QPushButton("Generate new copy")
        self.cancel_button = QPushButton("Cancel task")
        self.open_button = QPushButton("Open output PDF")
        self.reports_button = QPushButton("Open reports")
        self.result_actions = QHBoxLayout()
        self.result_actions.addWidget(self.open_button)
        self.result_actions.addWidget(self.reports_button)
        self._root.addLayout(self.result_actions)
        close = QPushButton("Close")
        for button in (self.analyse_button, self.generate_button, self.cancel_button,
                       close):
            actions.addWidget(button)
        self._root.addLayout(actions)
        self.analyse_button.clicked.connect(self.analyze)
        self.generate_button.clicked.connect(self.generate)
        self.cancel_button.clicked.connect(lambda: self.worker.cancel() if self.worker else None)
        self.open_button.clicked.connect(lambda: self.outputReady.emit(self.last_result.get("output_pdf", "")))
        self.reports_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_result.get("report_dir", ""))))
        close.clicked.connect(self.reject)
        self.mode.currentIndexChanged.connect(self.options_changed)
        self.pages.currentIndexChanged.connect(self.options_changed)
        self.range.textChanged.connect(self.options_changed)
        self.dpi.valueChanged.connect(self.options_changed)
        for control in (self.annotations, self.forms, self.raster, self.javascript, self.attachments,
                        self.metadata, self.boxes, self.preflight, self.allow_errors, self.signature, self.raster_ack):
            control.toggled.connect(self.options_changed)
        self.recovery_ack.toggled.connect(self.options_changed)
        self.options_changed()
        if settings_only:
            self.pages.model().item(1).setEnabled(False)
            for control in (self.batch_button, self.password_edit, self.naming, self.output_folder,
                            browse, self.analyse_button, self.cancel_button, self.open_button, self.reports_button,
                            self.progress):
                control.hide()
            for control in (self.password_edit, self.naming, self.output_folder):
                label = form.labelForField(control)
                if label:
                    label.hide()
            self.generate_button.setText("Apply settings")
            self.summary.setPlainText("Settings only. Check to this step will analyze, process and validate an isolated working copy; it does not publish production output.")
            if initial_options:
                self.load_options(initial_options)
            self.generate_button.setEnabled(True)

    def load_options(self, options):
        self.mode.setCurrentIndex(self.mode.findData(options.mode))
        if options.pages is not None:
            self.pages.setCurrentIndex(2)
            self.range.setText(",".join(str(page + 1) for page in options.pages))
        for control, key in ((self.annotations, "annotations"), (self.forms, "forms"),
                             (self.raster, "rasterise"), (self.javascript, "remove_javascript"),
                             (self.attachments, "remove_attachments"), (self.metadata, "remove_metadata"),
                             (self.boxes, "normalise_boxes"), (self.preflight, "preflight"),
                             (self.allow_errors, "allow_preflight_errors"), (self.signature, "acknowledge_signatures"),
                             (self.raster_ack, "acknowledge_raster"), (self.recovery_ack, "acknowledge_recovery")):
            control.setChecked(getattr(options, key))
        self.dpi.setValue(options.dpi)

    def options(self):
        selected = None
        if self.pages.currentIndex() == 1:
            if not self.page_count and not self.settings_only:
                raise ValueError("Analyze all pages first to establish the page count.")
            selected = (self.current_page,)
        elif self.pages.currentIndex() == 2:
            from core.pdf_engine import parse_page_range
            if not self.page_count and not self.settings_only:
                raise ValueError("Analyze all pages first to establish the page count.")
            selected = tuple(parse_page_range(self.range.text(), self.page_count or 1000000))
        normalise = self.operation == "repair" and self.mode.currentData() == "normalise"
        maximum = self.operation == "repair" and self.mode.currentData() == "maximum"
        options = PdfOptions(operation=self.operation, mode=self.mode.currentData(), pages=None if maximum else selected,
                             annotations=self.annotations.isChecked() if self.operation == "flatten" or normalise else False,
                             forms=self.forms.isChecked() if self.operation == "flatten" or normalise else False,
                             rasterise=self.raster.isChecked() if self.operation == "flatten" or normalise else maximum,
                             dpi=self.dpi.value(), remove_javascript=normalise and self.javascript.isChecked(),
                             remove_attachments=normalise and self.attachments.isChecked(),
                             remove_metadata=normalise and self.metadata.isChecked(), normalise_boxes=normalise and self.boxes.isChecked(),
                             preflight=self.preflight.isChecked(), allow_preflight_errors=self.allow_errors.isChecked(),
                             acknowledge_signatures=self.signature.isChecked(), acknowledge_raster=self.raster_ack.isChecked(),
                             acknowledge_recovery=self.recovery_ack.isChecked())
        options.validate(self.page_count or None)
        return options

    def options_changed(self, *_):
        self.plan = None
        self.analyses = []
        active = self.operation == "flatten" or self.mode.currentData() == "normalise"
        for control in (self.annotations, self.forms, self.raster, self.javascript, self.attachments, self.metadata, self.boxes):
            control.setEnabled(active and self.worker is None)
        self.range.setEnabled(self.pages.currentIndex() == 2 and self.worker is None)
        self.generate_button.setEnabled(self.settings_only)
        self.cancel_button.setEnabled(self.worker is not None)
        self.cancel_button.setVisible(self.worker is not None)
        self.open_button.setEnabled(bool(self.last_result.get("output_pdf")))
        self.reports_button.setEnabled(bool(self.last_result.get("report_dir")))
        self.open_button.setVisible(bool(self.last_result.get("output_pdf")))
        self.reports_button.setVisible(bool(self.last_result.get("report_dir")))
        self.signature.setVisible(self.settings_only or self.signed_hint)
        self.recovery_ack.setVisible(self.settings_only or self.recovery_hint)
        self.raster_ack.setVisible(self.raster.isChecked() or self.mode.currentData() == "maximum")
        self.allow_errors.setVisible(self.preflight.isChecked())
        self.dpi.setEnabled((self.raster.isChecked() or self.mode.currentData() == "maximum") and self.worker is None)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Output root folder", self.output_folder.text())
        if path:
            self.output_folder.setText(path)

    def choose_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Batch PDF sources", "", "PDF (*.pdf)")
        if paths:
            self.sources = paths
            self.source = paths[0]
            self.source_label.setText(f"Sources: {len(paths)} PDF(s) · {Path(paths[0]).name}")
            self.page_count = 0
            self.naming.set_context(VariableContext.for_job(input_path=paths[0], job_id="example-job"))
            self.batch_button.setText(f"Batch: {len(paths)} PDF(s) · choose again…")
            self.source_current = lambda: True
            self.secrets["output_password"] = ""
            self.options_changed()

    def start_worker(self, request, result):
        self.analyse_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.secrets["password"] = self.password_edit.text()
        if self.plan and self.plan.encrypted:
            self.secrets["output_password"] = self.password_edit.text()
        self.worker = Worker(Path(self.directory.name), request, self, worker_module="core.pdf_operations.worker", secrets=self.secrets)
        self.worker.resultReady.connect(result)
        self.worker.failed.connect(self.summary.setPlainText)
        self.worker.progress.connect(self.update_progress)
        self.worker.ended.connect(self.worker_ended)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.analyse_button.hide()
        self.generate_button.hide()
        self.mode.setEnabled(False)
        self.pages.setEnabled(False)
        self.batch_button.setEnabled(False)
        for control in (self.annotations, self.forms, self.raster, self.javascript, self.attachments,
                        self.metadata, self.boxes, self.preflight, self.allow_errors, self.signature,
                        self.raster_ack, self.range, self.dpi, self.naming, self.output_folder):
            control.setEnabled(False)
        self.recovery_ack.setEnabled(False)
        self.password_edit.setEnabled(False)

    def update_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(message + " %p%" if total else message)

    def analyze(self):
        if self.worker:
            return
        try:
            if not self.source_current():
                raise ValueError("The PDF changed. Close this tool and reopen it for a current snapshot.")
            self.plan = None
            self.summary.setPlainText("Analyzing in an isolated background process…")
            request = {"task": "analyse_batch", "sources": self.sources, "options": asdict(self.options())} if len(self.sources) > 1 else {
                "task": "analyse", "source": self.sources[0], "options": asdict(self.options())}
            self.start_worker(request, self.analysis_ready)
        except (ValueError, OSError) as exc:
            self.summary.setPlainText(str(exc))

    def analysis_ready(self, result):
        if "analyses" in result:
            self.analyses = result["analyses"]
            self.summary.setPlainText("\n".join(
                Path(row["source"]).name + ": " + (row["error"] or "; ".join(row["plan"]["issues"]) or
                    f"Ready for review · {row['plan']['page_count']} pages") for row in self.analyses))
            return
        if "plan" not in result:
            self.summary.setPlainText(result.get("error", "Analysis cancelled."))
            return
        self.plan = PdfOperationPlan.from_dict(result["plan"])
        self.signed_hint = self.plan.signed
        self.recovery_hint = bool(self.plan.diagnostics.get("recovery", {}).get("original_unrenderable"))
        self.signature.setVisible(self.signed_hint)
        self.recovery_ack.setVisible(self.recovery_hint)
        self.page_count = self.plan.page_count
        lines = [f"Pages: {self.plan.page_count}", f"Annotations: {self.plan.annotations}", f"Form widgets: {self.plan.forms}",
                 "Source preserved; output is a new job folder."]
        if self.plan.signed:
            lines.append("Digital signature found — explicit confirmation required.")
        lines.extend(self.plan.issues)
        for key, value in self.plan.diagnostics.items():
            lines.append(key + ": " + value["status"] + " · " + value.get("message", value.get("coverage", "")))
        self.summary.setPlainText("\n".join(lines))

    def generate(self):
        if self.settings_only:
            try:
                self.selected_options = self.options()
                self.directory.cleanup()
                self.accept()
            except ValueError as exc:
                self.summary.setPlainText(str(exc))
            return
        if self.worker or not (self.plan or self.analyses):
            return
        try:
            expected = self.plan.options if self.plan else PdfOptions.from_dict(next(row["plan"]["options"] for row in self.analyses if row["plan"]))
            if not self.source_current() or self.options() != expected:
                raise ValueError("Source/settings changed. Analyze again before generation.")
            if not self.output_folder.text().strip():
                raise ValueError("Choose an output root folder.")
            self.naming.resolved()
            request = {"task": "execute_batch", "analyses": self.analyses} if self.analyses else {"task": "execute", "plan": self.plan.to_dict()}
            request.update(output_dir=self.output_folder.text().strip(), output_name=self.naming.text())
            self.start_worker(request, self.generated)
        except (ValueError, VariableError) as exc:
            self.summary.setPlainText(str(exc))

    def generated(self, result):
        self.last_result = result
        self.summary.setPlainText("\n".join(["Status: " + result.get("status", "failed"),
                                              "PDF: " + result.get("output_pdf", ""),
                                              "Reports: " + result.get("report_dir", ""),
                                              *result.get("warnings", []), result.get("error", "")]))

    def worker_ended(self):
        self.worker = None
        self.analyse_button.show()
        self.generate_button.show()
        self.cancel_button.hide()
        self.analyse_button.setEnabled(True)
        self.mode.setEnabled(True)
        self.pages.setEnabled(True)
        self.batch_button.setEnabled(True)
        self.password_edit.setEnabled(True)
        for control in (self.preflight, self.allow_errors, self.signature, self.raster_ack,
                        self.dpi, self.naming, self.output_folder):
            control.setEnabled(True)
        self.recovery_ack.setEnabled(True)
        active = self.operation == "flatten" or self.mode.currentData() == "normalise"
        for control in (self.annotations, self.forms, self.raster, self.javascript, self.attachments, self.metadata, self.boxes):
            control.setEnabled(active)
        self.range.setEnabled(self.pages.currentIndex() == 2)
        self.dpi.setEnabled(self.raster.isChecked() or self.mode.currentData() == "maximum")
        self.cancel_button.setEnabled(False)
        self.generate_button.setEnabled(bool((self.plan and not self.plan.issues) or
                                            any(row["plan"] and not row["plan"]["issues"] for row in self.analyses)))
        self.open_button.setEnabled(bool(self.last_result.get("output_pdf")))
        self.reports_button.setEnabled(bool(self.last_result.get("report_dir")))
        self.open_button.setVisible(bool(self.last_result.get("output_pdf")))
        self.reports_button.setVisible(bool(self.last_result.get("report_dir")))
        if self.close_pending:
            self.reject()

    def reject(self):
        if self.worker:
            self.close_pending = True
            self.worker.cancel()
            self.summary.setPlainText("Cancelling; waiting for safe temporary-file cleanup…")
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
