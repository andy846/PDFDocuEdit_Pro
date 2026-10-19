"""Analysis, teach-once and profile controls shared by overlay/workflow review."""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from composition.pdf_source.detection import DetectionConfig

SIGNAL_LABELS = {"first_text": "First-page feature", "document_id": "Identity change", "page_number": "Page restart"}


class SmartDetectionControls:
    def setup_smart_controls(self):
        self.customer_profile = None
        self.single_library_profile = None
        self.smart_config = None
        self.pending_smart_scan = False
        self.teaching = False
        self.taught_marker = None
        self.taught_ids = []
        self.lesson_dirty = False
        self.pending_profile_save = False
        self.cache_path = self.window.directory / ("mailpiece-" + self.context_sha256 + ".sqlite")
        self.analyze_button = QPushButton("Analyze PDF")
        self.analyze_button.clicked.connect(self.analyze)
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
        self.teach_button = QPushButton("Teach a feature…")
        self.teach_button.clicked.connect(self.begin_teaching)
        self.open_profile_button = QPushButton("Open profile…")
        self.open_profile_button.clicked.connect(self.open_profile)
        self.save_profile_button = QPushButton("Save profile…")
        self.save_profile_button.clicked.connect(self.save_profile)
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
        self.lesson_status = QLabel("Draw a short static PDF text heading on the first sample. QR/image matching is not supported. Identity regions must include their labels.")
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
        self.library_button = QPushButton("Detection Profile Library…")
        self.library_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.library_button.clicked.connect(self.open_library)
        self.profile_label = QLabel("Single rule · no profile selected")
        self.profile_label.setWordWrap(True)
        self.profile_label.setMinimumWidth(0)
        self.profile_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.profile_label.setTextFormat(Qt.TextFormat.PlainText)
        self.profile_bar = QWidget(self)
        actions = QHBoxLayout(self.profile_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        for button in (self.analyze_button, self.teach_button, self.library_button,
                       self.open_profile_button, self.save_profile_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.layout().insertWidget(0, self.profile_bar)
        self.form.insertRow(1, self.profile_label)
        self.update_smart_controls()

    def set_collection_profile(self, profile):
        from composition.pdf_source.profile_library import validate_profile
        value = validate_profile(profile, for_scan=True)
        self.method.setCurrentIndex(self.method.findData("smart"))
        self.teaching = False
        self.invalidate()
        self.customer_profile = value
        self.single_library_profile = None
        self.lesson_dirty = False
        self.pending_profile_save = False
        self.profile_label.setText(f"{value['name']} · revision {value['revision']} · {len(value['rule_sets'])} rule sets")
        self.update_method()

    def library_root(self):
        from core.resources import data_dir
        return str(data_dir() / "composition" / "mailpiece-profiles")

    def use_single_profile(self, config, *, library_profile=None):
        self.clear_collection_profile()
        self.teaching = False
        self.lesson_dirty = False
        self.pending_profile_save = False
        self.smart_config = None
        self.invalidate()
        self.restore_config(config)
        self.update_method()
        self.single_library_profile = copy.deepcopy(library_profile)
        self.profile_label.setText(config.get("profile_name") or "Loaded profile")
        self.summary.setText("Profile loaded. Scan this PDF and review its new boundaries before applying.")

    def open_library(self):
        if self.scan_worker or self.window.active_worker:
            self.summary.setText("Wait for the current operation before opening the Library.")
            return
        from .mailpiece_profile_library import ProfileLibraryDialog
        try:
            config = asdict(self.config())
        except ValueError:
            config = None
        dialog = ProfileLibraryDialog(self.window, config, root=self.library_root(), parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted and dialog.selected_profile:
            from composition.pdf_source.profile_library import is_single_profile
            if is_single_profile(dialog.selected_profile):
                self.use_single_profile(dialog.selected_profile["config"], library_profile=dialog.selected_profile)
            else:
                self.set_collection_profile(dialog.selected_profile)

    def clear_collection_profile(self):
        self.customer_profile = None
        self.single_library_profile = None
        self.profile_label.setText("Single rule · no profile selected")

    def update_smart_controls(self):
        smart = self.method.currentData() == "smart"
        for control in (self.suggestions, self.suggestion_reason, self.suggestion_examples):
            self.form.setRowVisible(control, smart)
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
        self.profile_bar.setEnabled(False)
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
        self.clear_collection_profile()
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
        if hasattr(self, "profile_label"):
            self.clear_collection_profile()
        suggestion = self.suggestions.currentData()
        self.smart_config = copy.deepcopy(suggestion["config"]) if suggestion else None
        self.lesson_dirty = False
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
        self.clear_collection_profile()
        self.method.setCurrentIndex(self.method.findData("smart"))
        self.teaching = True
        self.taught_marker = None
        self.taught_ids = []
        self.invalidate_lesson()
        self.whole.setChecked(False)
        self.pair_mode.setCurrentIndex(self.pair_mode.findData("teaching"))
        self.update_method()
        self.refresh_pair()
        self.summary.setText("Teaching: select a static PDF text heading. Save profile checks the rule before saving; Try taught rule lets you review its matches.")
        QTimer.singleShot(0, self.scroll_to_lesson)

    def scroll_to_lesson(self):
        if not sip.isdeleted(self) and self.teaching and self.isVisible():
            self.controls_scroll.verticalScrollBar().setValue(max(0, self.first_sample.y()-24))

    def lesson_changed(self, *_):
        if self.teaching:
            self.invalidate_lesson()
            self.refresh_pair()

    def invalidate_lesson(self):
        self.lesson_dirty = True
        self.smart_config = None
        self.pending_profile_save = False
        self.invalidate()

    def region_selected(self):
        # The first deliberate drag is the marker; later drags can capture IDs.
        if self.teaching and self.taught_marker is None:
            self.remember_marker()

    def end_teaching(self):
        self.teaching = False
        self.pair_mode.setCurrentIndex(self.pair_mode.findData("ends"))
        self.update_method()
        self.controls_scroll.verticalScrollBar().setValue(0)

    def remember_marker(self):
        self.taught_marker = [c.value() for c in self.region]
        self.invalidate_lesson()
        self.lesson_status.setText(f"First-page region selected. Enter its fixed heading if needed, then Save profile or Try taught rule. {len(self.taught_ids)} identity region(s).")

    def remember_identity(self):
        region = [c.value() for c in self.region]
        if region not in self.taught_ids and len(self.taught_ids) < 8:
            self.taught_ids.append(region)
        self.invalidate_lesson()
        self.lesson_status.setText(f"{len(self.taught_ids)} identity region(s). Each must include a static label and its value.")

    def clear_taught_ids(self):
        self.taught_ids.clear()
        self.invalidate_lesson()
        self.lesson_status.setText("Identity regions cleared. The first-page feature is retained.")

    def teach_scan(self, *, save_after=False):
        if self.scan_worker or self.window.active_worker or self.window.draft_error:
            return
        if self.taught_marker is None:
            self.summary.setText("Draw a static text heading on the first-page preview, or enter its region and choose Use marker region. Then Save profile will test the rule before saving.")
            return
        self.pending_profile_save = save_after
        terms = [t.strip() for t in self.static_marker.text().split("|") if t.strip()]
        def ready(value):
            self.set_suggestions([{"title": "Taught first-page rule", "config": value["config"],
                                   "examples": [self.first_sample.value()],
                                   "reason": "Taught rule tested against all cached pages. Compare the first / continuation examples before saving a profile."}])
            self.scanned(value)
            self.lesson_dirty = False
        self.run_smart_task({"task": "mailpiece_teach", "first_page": self.first_sample.value(),
                             "continuation_page": self.continuation_sample.value(), "marker_region": self.taught_marker,
                             "id_regions": self.taught_ids, "marker_terms": terms or None}, ready)

    def queue_profile_save(self):
        if not self.pending_profile_save:
            return
        self.pending_profile_save = False
        if not self.smart_config or self.lesson_dirty or not self.report:
            return
        checked_config = copy.deepcopy(self.smart_config)
        def save_checked():
            if (not sip.isdeleted(self) and self.isVisible() and not self.lesson_dirty
                    and self.smart_config == checked_config and not self.scan_worker):
                self.save_profile()
        QTimer.singleShot(0, save_checked)

    def open_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open mailpiece profile", "", "Mailpiece profiles (*.pdmp *.pdmpx)")
        if not path:
            return
        if Path(path).suffix.lower() == ".pdmpx":
            self.run_smart_task({"task": "mailpiece_library", "operation": "open", "path": path,
                                 "root": self.library_root()},
                                lambda value: self.set_collection_profile(value["profile"]))
            return
        def ready(value):
            self.use_single_profile(value["config"])
        self.run_smart_task({"task": "mailpiece_profile_load", "path": path}, ready)

    def save_profile(self):
        smart = self.method.currentData() == "smart"
        if self.scan_worker or self.window.active_worker:
            self.summary.setText("Wait for the current check, or cancel it before saving a profile.")
            return
        if smart and self.lesson_dirty and (self.teaching or self.taught_marker is not None):
            self.teach_scan(save_after=True)
            return
        if smart and self.customer_profile:
            path, _ = QFileDialog.getSaveFileName(self, "Export detection profile", "", "Customer detection profile (*.pdmpx)")
            if path:
                self.window.worker({"task": "mailpiece_library", "operation": "export", "path": path,
                                    "profile": copy.deepcopy(self.customer_profile),
                                    "root": self.library_root(), "register": True},
                                   self.profile_saved,
                                   self.scan_failed, active=True)
            return
        if smart and not self.smart_config:
            self.summary.setText("Choose Analyze PDF or Teach a feature first. For teaching, draw a static text heading; Save profile tests it before saving. QR/image matching is not supported.")
            return
        try:
            # Resolve the current method, never a previous smart rule or scan result.
            config = asdict(self.config())
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save mailpiece profile", "", "Mailpiece profiles (*.pdmp)")
        if path:
            # Saving configuration must not discard the current boundary review.
            config["profile_name"] = Path(path).stem[:120]
            identity = ({"profile_id": self.single_library_profile["profile_id"], "revision": self.single_library_profile["revision"]}
                        if self.single_library_profile else {})
            self.window.worker({"task": "mailpiece_profile_save", "path": path, "config": config,
                                "root": self.library_root(), "library_identity": identity},
                               self.profile_saved,
                               lambda message: self.summary.setText(message), active=True)

    def profile_saved(self, value):
        if value.get("library_error"):
            self.summary.setText("File saved: " + value["path"] + ". Library not updated: " + value["library_error"])
        else:
            from composition.pdf_source.profile_library import is_single_profile
            saved = value.get("library_profile")
            self.single_library_profile = copy.deepcopy(saved) if is_single_profile(saved) else None
            if self.single_library_profile:
                self.profile_label.setText(f"{self.single_library_profile['name']} · revision {self.single_library_profile['revision']}")
            self.summary.setText("Profile saved and added to Library: " + value["path"])

    def smart_scan(self):
        if self.teaching and self.lesson_dirty:
            self.teach_scan()
            return
        if self.customer_profile:
            self.run_smart_task({"task": "mailpiece_collection_scan", "profile": copy.deepcopy(self.customer_profile)}, self.scanned)
            return
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
