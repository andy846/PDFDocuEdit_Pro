"""Analysis, teach-once and profile controls shared by overlay/workflow review."""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
)

from composition.pdf_source.detection import DetectionConfig

SIGNAL_LABELS = {"first_text": "First-page feature", "document_id": "Identity change", "page_number": "Page restart"}


class SmartDetectionControls:
    def setup_smart_controls(self):
        self.smart_config = None
        self.pending_smart_scan = False
        self.teaching = False
        self.taught_marker = None
        self.taught_ids = []
        self.cache_path = self.window.directory / ("mailpiece-" + self.context_sha256 + ".sqlite")
        self.analyze_button = QPushButton("Analyze PDF")
        self.analyze_button.clicked.connect(self.analyze)
        self.form.insertRow(0, self.analyze_button)
        self.suggestions = QComboBox()
        self.suggestions.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.suggestions.setMinimumContentsLength(10)
        self.suggestions.currentIndexChanged.connect(self.choose_suggestion)
        self.form.insertRow(1, "Suggested rule", self.suggestions)
        self.suggestion_reason = QLabel("Analyze the PDF to find first-page features, counters and identity labels.")
        self.suggestion_reason.setWordWrap(True)
        self.suggestion_reason.setTextFormat(Qt.TextFormat.PlainText)
        self.form.insertRow(2, self.suggestion_reason)
        self.suggestion_examples = QComboBox()
        self.suggestion_examples.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.suggestion_examples.currentIndexChanged.connect(self.show_example)
        self.form.insertRow(3, "Example pages", self.suggestion_examples)
        for row, (name, callback) in enumerate((("Teach a feature…", self.begin_teaching),
                               ("Open profile…", self.open_profile),
                               ("Save profile…", self.save_profile)), 4):
            button = QPushButton(name)
            button.clicked.connect(callback)
            self.form.insertRow(row, button)
        self.first_sample, self.continuation_sample = QSpinBox(), QSpinBox()
        for control, default in ((self.first_sample, 1), (self.continuation_sample, 2)):
            control.setRange(1, self.window.spec.source.pages)
            control.setValue(min(default, self.window.spec.source.pages))
            control.valueChanged.connect(self.lesson_changed)
        self.static_marker = QLineEdit()
        self.static_marker.setPlaceholderText("Static text only, e.g. Dear / Statement")
        self.static_marker.setToolTip("Optional: enter a fixed heading. Do not enter a customer name, address or account value.")
        self.static_marker.textChanged.connect(self.lesson_changed)
        self.capture_marker = QPushButton("Use marker region")
        self.capture_marker.setToolTip("Use the drawn region as the static first-page feature.")
        self.capture_marker.clicked.connect(self.remember_marker)
        self.capture_identity = QPushButton("Add ID region")
        self.capture_identity.clicked.connect(self.remember_identity)
        self.clear_identity = QPushButton("Clear ID regions")
        self.clear_identity.clicked.connect(self.clear_taught_ids)
        self.try_teaching = QPushButton("Try taught rule")
        self.try_teaching.clicked.connect(self.teach_scan)
        self.finish_teaching = QPushButton("Review boundaries")
        self.finish_teaching.clicked.connect(self.end_teaching)
        self.lesson_status = QLabel("Draw a small static feature on the first sample. Identity regions must include their labels.")
        self.lesson_status.setWordWrap(True)
        self.lesson_status.setTextFormat(Qt.TextFormat.PlainText)
        self.lesson_controls = [self.first_sample, self.continuation_sample, self.static_marker,
                                self.capture_marker, self.capture_identity, self.clear_identity, self.try_teaching, self.finish_teaching, self.lesson_status]
        for label, control in (("Example first page", self.first_sample), ("Example continuation", self.continuation_sample),
                               ("Static marker", self.static_marker)):
            self.form.addRow(label, control)
        for control in self.lesson_controls[3:]:
            self.form.addRow(control)
        self.exceptions_only = QCheckBox("Exceptions only")
        self.exceptions_only.setToolTip("When no exceptions exist, all mailpieces remain visible.")
        self.exceptions_only.toggled.connect(lambda *_: self.show_report() if self.report else None)
        self.form.insertRow(3, self.exceptions_only)
        self.pair_mode = QComboBox()
        self.pair_mode.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.pair_mode.setMinimumContentsLength(8)
        self.pair_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.pair_mode.addItem("First / last page", "ends")
        self.pair_mode.addItem("Before / after boundary", "boundary")
        self.pair_mode.addItem("Teaching examples", "teaching")
        self.pair_mode.currentIndexChanged.connect(lambda *_: self.refresh_pair())
        self.form.insertRow(3, "Compare pages", self.pair_mode)
        self.update_smart_controls()

    def update_smart_controls(self):
        smart = self.method.currentData() == "smart"
        for control in self.lesson_controls:
            self.form.setRowVisible(control, smart and self.teaching)
        self.whole.setEnabled(not smart or self.teaching)
        self.preview.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if smart and not self.teaching else QGraphicsView.DragMode.NoDrag)
        self.analyze_button.setEnabled(not bool(self.scan_worker))

    def source_request(self):
        return {"source": self.window.spec.source.path, "expected_sha256": self.context_sha256, "cache": str(self.cache_path)}

    def run_smart_task(self, request, ready):
        if self.window.active_worker or self.window.draft_error:
            return
        self.invalidate()
        self.scan_generation += 1
        token = self.scan_generation
        self.scan_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.scan_progress.setRange(0, 0)
        self.scan_progress.show()
        self.scan_status.setText("Analyzing PDF / checking signals…")
        self.scan_status.show()
        self.cancel_button.setEnabled(True)
        self.form.parentWidget().setEnabled(False)
        self.acknowledge.setEnabled(False)
        def delivered(value):
            if token == self.scan_generation and self.isVisible():
                ready(value)
        self.scan_worker = self.window.worker({**self.source_request(), **request}, delivered,
                                              lambda message: self.scan_failed(message) if token == self.scan_generation else None, active=True)
        if self.scan_worker:
            self.scan_worker.ended.connect(self.scan_ended)
            self.scan_worker.progress.connect(self.show_scan_progress)
        else:
            self.scan_ended()

    def analyze(self, *, scan_after=False):
        self.method.setCurrentIndex(self.method.findData("smart"))
        self.end_teaching()
        def ready(value):
            self.source = value["source"]
            self.set_suggestions(value["suggestions"])
            self.summary.setText(value["message"])
            if scan_after and self.smart_config:
                self.pending_smart_scan = True
        self.run_smart_task({"task": "mailpiece_analyze"}, ready)

    def set_suggestions(self, suggestions):
        self.suggestions.blockSignals(True)
        self.suggestions.clear()
        for suggestion in suggestions:
            self.suggestions.addItem(suggestion["title"], suggestion)
        self.suggestions.blockSignals(False)
        self.choose_suggestion()

    def choose_suggestion(self, *_):
        suggestion = self.suggestions.currentData()
        self.smart_config = copy.deepcopy(suggestion["config"]) if suggestion else None
        self.invalidate()
        self.suggestion_examples.blockSignals(True)
        self.suggestion_examples.clear()
        for page in suggestion["examples"] if suggestion else []:
            self.suggestion_examples.addItem(f"Source page {page:,}", page)
        self.suggestion_examples.blockSignals(False)
        self.suggestion_reason.setText(suggestion["reason"] if suggestion else "Unable to establish a rule. Teach a first-page feature or open a profile.")
        if suggestion:
            regions = []
            for rule in self.smart_config["rules"]:
                regions.append(SIGNAL_LABELS[rule["kind"]] + ": " + (", ".join(f"{v:.2f}" for v in rule["region_mm"]) + " mm (X/Y/W/H)" if rule.get("region_mm") else "whole page"))
                for field in rule.get("fields", []):
                    regions.append(field["label"] + ": " + (", ".join(f"{v:.2f}" for v in field["region_mm"]) + " mm" if field.get("region_mm") else "whole page"))
            description = suggestion["reason"] + "\n" + "\n".join(regions)
            self.suggestion_reason.setText(description)
            self.suggestion_reason.setToolTip(description)
            self.show_source_page(suggestion["examples"][0])

    def show_example(self, *_):
        page = self.suggestion_examples.currentData()
        if page is None:
            return
        self.preview_page.setRange(1, self.window.spec.source.pages)
        self.preview_page.setValue(page)
        self.show_source_page(page)
        self.secondary_preview.request(self.source or self.window.spec.to_dict()["source"], min(page+1, self.window.spec.source.pages))

    def begin_teaching(self):
        self.method.setCurrentIndex(self.method.findData("smart"))
        self.teaching = True
        self.whole.setChecked(False)
        self.pair_mode.setCurrentIndex(self.pair_mode.findData("teaching"))
        self.update_method()
        self.refresh_pair()
        QTimer.singleShot(0, lambda: self.controls_scroll.ensureWidgetVisible(self.first_sample))

    def lesson_changed(self, *_):
        if self.teaching:
            self.invalidate()
            self.refresh_pair()

    def end_teaching(self):
        self.teaching = False
        self.pair_mode.setCurrentIndex(self.pair_mode.findData("ends"))
        self.update_method()
        self.controls_scroll.verticalScrollBar().setValue(0)

    def remember_marker(self):
        self.taught_marker = [c.value() for c in self.region]
        self.invalidate()
        self.lesson_status.setText(f"First-page region saved. {len(self.taught_ids)} identity region(s).")

    def remember_identity(self):
        region = [c.value() for c in self.region]
        if region not in self.taught_ids and len(self.taught_ids) < 8:
            self.taught_ids.append(region)
        self.invalidate()
        self.lesson_status.setText(f"{len(self.taught_ids)} identity region(s). Each must include a static label and its value.")

    def clear_taught_ids(self):
        self.taught_ids.clear()
        self.invalidate()
        self.lesson_status.setText("Identity regions cleared. The first-page feature is retained.")

    def teach_scan(self):
        if self.taught_marker is None:
            self.summary.setText("Draw the first-page feature and choose Use marker region first.")
            return
        terms = [t.strip() for t in self.static_marker.text().split("|") if t.strip()]
        def ready(value):
            self.set_suggestions([{"title": "Taught first-page rule", "config": value["config"],
                                   "examples": [self.first_sample.value()],
                                   "reason": "Taught rule tested against all cached pages. Compare the first / continuation examples before saving a profile."}])
            self.scanned(value)
        self.run_smart_task({"task": "mailpiece_teach", "first_page": self.first_sample.value(),
                             "continuation_page": self.continuation_sample.value(), "marker_region": self.taught_marker,
                             "id_regions": self.taught_ids, "marker_terms": terms or None}, ready)

    def open_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open mailpiece profile", "", "Mailpiece profiles (*.pdmp)")
        if not path:
            return
        def ready(value):
            self.method.setCurrentIndex(self.method.findData("smart"))
            self.teaching = False
            self.update_method()
            self.set_suggestions([{"title": value["config"].get("profile_name") or "Loaded profile", "config": value["config"],
                                   "examples": [1], "reason": "Profile loaded. Scan this PDF and review its new boundaries before applying."}])
        self.run_smart_task({"task": "mailpiece_profile_load", "path": path}, ready)

    def save_profile(self):
        if not self.smart_config:
            self.summary.setText("Analyze or teach a rule before saving its profile.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save mailpiece profile", "", "Mailpiece profiles (*.pdmp)")
        if path:
            # Saving configuration must not discard the current boundary review.
            config = copy.deepcopy(self.smart_config)
            config["profile_name"] = Path(path).stem[:120]
            self.window.worker({"task": "mailpiece_profile_save", "path": path, "config": config},
                               lambda value: self.summary.setText("Profile saved: " + value["path"]),
                               lambda message: self.summary.setText(message))

    def smart_scan(self):
        if not self.smart_config:
            self.analyze(scan_after=True)
            return
        config = asdict(DetectionConfig(**self.smart_config))
        self.run_smart_task({"task": "mailpiece_smart_scan", "config": config}, self.scanned)

    def refresh_pair(self):
        if not hasattr(self, "secondary_preview"):
            return
        mode = self.pair_mode.currentData()
        if mode == "teaching":
            first, last = self.first_sample.value(), self.continuation_sample.value()
        elif self.report and 0 <= self.selected_row() < len(self.report["groups"]):
            first, last = self.report["groups"][self.selected_row()]
            if mode == "boundary":
                first, last = max(1, first-1), first
        else:
            first, last = self.preview_page.value(), min(self.preview_page.value()+1, self.window.spec.source.pages)
        self.preview_page.blockSignals(True)
        self.preview_page.setRange(1, self.window.spec.source.pages)
        self.preview_page.setValue(first)
        self.preview_page.blockSignals(False)
        self.show_source_page(first)
        self.secondary_preview.request(self.source or self.window.spec.to_dict()["source"], last)
