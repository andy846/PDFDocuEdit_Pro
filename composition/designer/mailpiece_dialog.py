"""Background scan and explicit operator review of mailpiece boundaries."""
from __future__ import annotations

import copy
from bisect import bisect_left
from dataclasses import asdict

from PyQt6.QtCore import QAbstractTableModel, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from composition.pdf_source.detection import DetectionConfig, edit_boundary
from composition.production.model import now

from .mailpiece_preview import PairedSourcePreview, SourcePreview
from .mailpiece_region import RegionView
from .mailpiece_smart_ui import SIGNAL_LABELS, SmartDetectionControls

METHODS = [("Auto analysis / detection profile", "smart"), ("Page number pattern", "page_number"), ("Document / Account ID changes", "document_id"),
           ("First-page text markers (all)", "first_text"), ("Separator page", "separator"),
           ("Text present in selected region", "region_present"), ("Combine boundary rules", "combined")]


class BoundaryTable(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups, self.warnings = [], []
        self.rows, self.report = [], {}

    def replace(self, report, exceptions_only=False):
        self.beginResetModel()
        self.groups = report["groups"]
        self.report = report
        self.warnings = sorted({f["page"] for f in report["findings"]})
        self.rows = [i for i, (start, end) in enumerate(self.groups) if not exceptions_only or not self.warnings
                     or any(start <= p <= end for p in self.warnings)]
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("Envelope", "Source pages", "Count", "Review", "Evidence / end")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        number = self.rows[index.row()]
        start, end = self.groups[number]
        warning_index = bisect_left(self.warnings, start)
        needs_review = warning_index < len(self.warnings) and self.warnings[warning_index] <= end
        evidence = next((e for e in self.report.get("evidence", []) if e["page"] == start), {})
        reason = " + ".join(SIGNAL_LABELS.get(m, m) for m in evidence.get("matched", [])) or "Operator boundary"
        if evidence.get("end_basis") in ("next_start_inferred", "pdf_end_inferred"):
            reason += "; end inferred"
        return (f"{number+1:06}", f"{start}–{end}", end-start+1,
                "Needs review" if needs_review else "Evidence consistent" if self.report.get("established") else "Check boundaries", reason)[index.column()]


class MailpieceDialog(SmartDetectionControls, QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.context_sha256 = window.spec.source.sha256
        self.context_settings = asdict(window.spec.settings)
        self.context_review = copy.deepcopy(window.spec.detection_review)
        self.setWindowTitle("Auto Detect Mailpieces · Analyze → Review → Apply")
        self.resize(880, 650)
        self.report = self.source = None
        self.scan_worker = None
        self.scan_generation = 0
        self.warning_cursor = 0
        self.review_undo, self.review_redo = [], []
        outer = QVBoxLayout(self)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        left = QWidget()
        form = QFormLayout(left)
        self.form = form
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.method = QComboBox()
        for title, key in METHODS:
            self.method.addItem(title, key)
        self.method.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        form.addRow("Method", self.method)
        self.number_pattern = QLineEdit("Page {CURRENT} of {TOTAL}")
        self.id_pattern = QLineEdit("Account No: {ID}")
        self.markers = QPlainTextEdit("Statement Date\nAccount Number")
        self.markers.setMaximumHeight(70)
        self.separator = QLineEdit("SEPARATOR")
        form.addRow("Page pattern", self.number_pattern)
        form.addRow("ID pattern", self.id_pattern)
        self.first_ids = QCheckBox("ID only on first pages (carry forward)")
        form.addRow(self.first_ids)
        form.addRow("First-page text\n(one per line, all)", self.markers)
        form.addRow("Separator text", self.separator)
        self.remove = QCheckBox("Remove separator pages")
        self.remove.setChecked(True)
        form.addRow(self.remove)
        self.combined = {}
        for kind, title in (("page_number", "Page sequence restarts at 1"), ("document_id", "ID changes"),
                            ("first_text", "First-page text matches"), ("region_present", "Text region is present")):
            check = QCheckBox(title)
            check.setChecked(kind in ("page_number", "document_id"))
            self.combined[kind] = check
            form.addRow(check)
        self.combine = QComboBox()
        self.combine.addItem("OR: any boundary condition", "any")
        self.combine.addItem("AND: all boundary conditions", "all")
        form.addRow("Combine", self.combine)
        self.whole = QCheckBox("Search whole page")
        self.whole.setChecked(True)
        form.addRow(self.whole)
        self.region = []
        for title, value in (("X (mm)", 25), ("Y (mm)", 20), ("W (mm)", 80), ("H (mm)", 20)):
            control = QDoubleSpinBox()
            control.setDecimals(2)
            control.setRange(0 if title[0] in "XY" else .1, 2000)
            control.setValue(value)
            self.region.append(control)
            form.addRow(title, control)
        self.whole.toggled.connect(lambda checked: self.update_method())
        self.whole.toggled.connect(lambda checked: [c.setEnabled(not checked) for c in self.region])
        for control in self.region:
            control.setEnabled(False)
        hint = QLabel("Use PDF text layers. Patterns are literal text with placeholders; no Python or arbitrary regex. Drag on the source preview to select a region. All source pages must share page geometry in this first version.")
        hint.setWordWrap(True)
        form.addRow(hint)
        scroll = QScrollArea()
        self.controls_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        splitter.addWidget(scroll)
        right = QWidget()
        layout = QVBoxLayout(right)
        self.model = BoundaryTable(self)
        self.table = QTableView()
        self.table.setStyleSheet("QTableView { selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self.selected)
        self.review_splitter = QSplitter(Qt.Orientation.Vertical)
        self.table.setMinimumHeight(70)
        self.review_splitter.addWidget(self.table)
        preview_area = QWidget()
        self.review_splitter.addWidget(preview_area)
        layout.addWidget(self.review_splitter)
        layout = QVBoxLayout(preview_area)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview_page = QSpinBox()
        self.preview_page.setPrefix("Source page ")
        self.preview_page.setRange(1, window.spec.source.pages)
        self.preview_page.valueChanged.connect(self.show_source_page)
        navigation = QHBoxLayout()
        navigation.addWidget(self.preview_page, 1)
        fit = QPushButton("Fit page")
        fit.clicked.connect(lambda: (self.preview.fit_page(), self.secondary_preview.preview.fit_page()))
        navigation.addWidget(fit)
        self.next_warning = QPushButton("Next warning")
        self.next_warning.clicked.connect(self.select_next_warning)
        navigation.addWidget(self.next_warning)
        layout.addLayout(navigation)
        self.preview = RegionView(self)
        self.source_preview = SourcePreview(self)
        self.whole.toggled.connect(self.preview.update_region)
        for control in self.region:
            control.valueChanged.connect(self.preview.update_region)
        self.preview_pair = QSplitter()
        self.preview_pair.setChildrenCollapsible(False)
        self.preview_pair.addWidget(self.preview)
        self.secondary_preview = PairedSourcePreview(self)
        self.preview_pair.addWidget(self.secondary_preview)
        self.preview_pair.setSizes([280, 280])
        layout.addWidget(self.preview_pair, 2)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        layout.addWidget(self.preview_status)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(72)
        layout.addWidget(self.detail)
        edits = QHBoxLayout()
        self.split_button = QPushButton("Split…")
        self.split_button.setToolTip("Choose the source page where a new mailpiece starts.")
        self.merge_button = QPushButton("Merge previous")
        self.merge_button.setToolTip("Merge this mailpiece with the preceding adjacent mailpiece.")
        self.split_button.clicked.connect(self.split)
        self.merge_button.clicked.connect(self.merge)
        edits.addWidget(self.split_button)
        edits.addWidget(self.merge_button)
        self.undo_boundary = QPushButton("Undo")
        self.redo_boundary = QPushButton("Redo")
        self.undo_boundary.clicked.connect(lambda: self.restore_boundary_edit(False))
        self.redo_boundary.clicked.connect(lambda: self.restore_boundary_edit(True))
        for button in (self.undo_boundary, self.redo_boundary):
            button.setAutoDefault(False)
            button.setToolTip("Undo/redo boundary edits in this review; the main project is unchanged until Accept & apply.")
            edits.addWidget(button)
        layout.addLayout(edits)
        self.review_splitter.setSizes([130, 365])
        splitter.addWidget(right)
        splitter.setSizes([300, 560])
        self.summary = QLabel("Configure detection, scan, then review every boundary before applying. No barcode is added by scanning.")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.scan_progress = QProgressBar()
        self.scan_progress.setFixedHeight(6)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()
        outer.addWidget(self.scan_progress)
        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        self.scan_status.hide()
        outer.addWidget(self.scan_status)
        self.acknowledge = QCheckBox("I reviewed all warnings and accept these boundaries / exclusions")
        self.acknowledge.toggled.connect(self.update_apply)
        outer.addWidget(self.acknowledge)
        buttons = QHBoxLayout()
        self.scan_button, self.cancel_button = QPushButton("Scan PDF"), QPushButton("Cancel scan")
        self.apply_button, close = QPushButton("Accept & apply boundaries"), QPushButton("Close")
        self.scan_button.clicked.connect(self.scan)
        self.cancel_button.clicked.connect(lambda: self.scan_worker.cancel() if self.scan_worker else None)
        self.apply_button.clicked.connect(self.apply)
        close.clicked.connect(self.reject)
        for button in (self.scan_button, self.cancel_button, self.apply_button, close):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.method.currentIndexChanged.connect(self.update_method)
        self.update_method()
        self.cancel_button.setEnabled(False)
        self.setup_smart_controls()
        self.update_apply()
        for control in (self.method, self.number_pattern, self.id_pattern, self.separator, self.combine):
            signal = control.textChanged if isinstance(control, QLineEdit) else control.currentIndexChanged
            signal.connect(self.invalidate)
        self.markers.textChanged.connect(self.invalidate)
        for control in (self.whole, self.remove, self.first_ids, *self.combined.values()):
            control.toggled.connect(self.invalidate)
        for control in self.region:
            control.valueChanged.connect(self.invalidate)
        saved = window.spec.detection_review if window.spec else {}
        if saved and "config" in saved and window.spec.settings.groups:
            self.restore_config(saved["config"])
            self.source = window.spec.to_dict()["source"]
            self.report = copy.deepcopy(saved)
            self.report["accepted"] = False
            self.show_report()
        else:
            self.show_source_page(1)

    def update_method(self):
        kind = self.method.currentData()
        for control, visible in ((self.number_pattern, kind in ("page_number", "combined")),
                                 (self.id_pattern, kind in ("document_id", "combined")),
                                 (self.first_ids, kind in ("document_id", "combined")),
                                 (self.markers, kind in ("first_text", "combined")),
                                 (self.separator, kind == "separator"), (self.remove, kind == "separator"),
                                 (self.combine, kind == "combined")):
            self.form.setRowVisible(control, visible)
        for control in self.region:
            self.form.setRowVisible(control, not self.whole.isChecked())
        self.number_pattern.setEnabled(kind in ("page_number", "combined"))
        self.id_pattern.setEnabled(kind in ("document_id", "combined"))
        self.first_ids.setEnabled(kind in ("document_id", "combined"))
        self.markers.setEnabled(kind in ("first_text", "combined"))
        self.separator.setEnabled(kind == "separator")
        self.remove.setEnabled(kind == "separator")
        for control in self.combined.values():
            self.form.setRowVisible(control, kind == "combined")
        self.combine.setEnabled(kind == "combined")
        if hasattr(self, "lesson_controls"):
            self.update_smart_controls()

    def config(self):
        kind = self.method.currentData()
        if kind == "smart":
            if not self.smart_config:
                raise ValueError("Analyze the PDF, teach a feature, or open a detection profile first.")
            result = DetectionConfig(**self.smart_config)
            result.validate()
            return result
        kinds = [key for key, check in self.combined.items() if check.isChecked()] if kind == "combined" else [kind]
        rules = []
        for key in kinds:
            rule = {"kind": key}
            if key in ("page_number", "document_id"):
                rule["pattern"] = (self.number_pattern if key == "page_number" else self.id_pattern).text()
                if key == "document_id" and self.first_ids.isChecked():
                    rule["allow_missing_continuation"] = True
            elif key in ("first_text", "separator"):
                rule["terms"] = ([self.separator.text()] if key == "separator" else [line.strip() for line in self.markers.toPlainText().splitlines() if line.strip()])
            rules.append(rule)
        result = DetectionConfig(rules, self.combine.currentData(), None if self.whole.isChecked() else [c.value() for c in self.region], self.remove.isChecked())
        result.validate()
        return result

    def restore_config(self, config):
        if config.get("version") == 2:
            self.method.setCurrentIndex(self.method.findData("smart"))
            self.set_suggestions([{"title": config.get("profile_name") or "Saved spatial rules", "config": config,
                                   "examples": [1], "reason": "Saved rules restored. Existing boundaries remain unchanged until you rescan and accept."}])
            return
        rules = config["rules"]
        self.method.setCurrentIndex(self.method.findData("combined" if len(rules) > 1 else rules[0]["kind"]))
        for key, control in self.combined.items():
            control.setChecked(any(rule["kind"] == key for rule in rules))
        for rule in rules:
            if rule["kind"] == "page_number":
                self.number_pattern.setText(rule["pattern"])
            elif rule["kind"] == "document_id":
                self.id_pattern.setText(rule["pattern"])
                self.first_ids.setChecked(rule.get("allow_missing_continuation", False))
            elif rule["kind"] == "first_text":
                self.markers.setPlainText("\n".join(rule["terms"]))
            elif rule["kind"] == "separator":
                self.separator.setText(rule["terms"][0])
        self.combine.setCurrentIndex(self.combine.findData(config["combine"]))
        self.remove.setChecked(config["remove_separators"])
        self.whole.setChecked(config["region_mm"] is None)
        if config["region_mm"]:
            for control, number in zip(self.region, config["region_mm"], strict=True):
                control.setValue(number)

    def invalidate(self, *args):
        if self.report:
            self.report = None
            self.clear_results()
            self.summary.setText("Detection options changed. Scan again before applying boundaries.")
        self.acknowledge.setChecked(False)
        self.update_apply()

    def clear_results(self):
        self.review_undo.clear()
        self.review_redo.clear()
        self.model.replace({"groups": [], "findings": []})
        self.detail.clear()
        self.preview_page.setRange(1, self.window.spec.source.pages)

    def scan(self):
        if self.method.currentData() == "smart":
            self.smart_scan()
            return
        if self.window.active_worker or self.window.draft_error:
            return
        try:
            config = self.config()
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        self.report = None
        self.clear_results()
        self.update_apply()
        self.scan_generation += 1
        generation = self.scan_generation
        self.acknowledge.setChecked(False)
        self.summary.setText("Scanning current detection settings. Review the new results before applying boundaries.")
        self.scan_progress.setRange(0, 0)
        self.scan_progress.show()
        self.scan_status.setText("Inspecting source and scanning text…")
        self.scan_status.show()
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.scan_worker = self.window.worker({"task": "mailpiece_scan", "source": self.window.spec.source.path,
            "expected_sha256": self.window.spec.source.sha256, "config": asdict(config)},
            lambda value: self.scanned(value) if generation == self.scan_generation else None,
            lambda message: self.scan_failed(message) if generation == self.scan_generation else None, active=True)
        if self.scan_worker:
            self.scan_worker.ended.connect(self.scan_ended)
            self.scan_worker.progress.connect(self.show_scan_progress)
        else:
            self.scan_ended()

    def show_scan_progress(self, done, total, message):
        self.scan_progress.setRange(0, max(1, total))
        self.scan_progress.setValue(done)
        self.scan_status.setText(message)

    def scan_ended(self):
        self.scan_worker = None
        self.scan_progress.hide()
        self.scan_status.hide()
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.update_apply()
        self.analyze_button.setEnabled(True)
        self.form.parentWidget().setEnabled(True)
        self.acknowledge.setEnabled(True)
        if self.pending_smart_scan:
            self.pending_smart_scan = False
            QTimer.singleShot(0, self.scan)

    def scanned(self, value):
        if not self.isVisible():
            return
        self.source, self.report = value["source"], value["detection"]
        # Edits made during scanning cannot reuse results from different rules.
        try:
            current = asdict(self.config())
        except ValueError:
            current = None
        if self.report["config"] != current:
            self.invalidate()
            self.summary.setText("Options changed during scanning. Scan again.")
            return
        if self.report.get("version", self.report["config"].get("version")) == 2:
            self.exceptions_only.blockSignals(True)
            self.exceptions_only.setChecked(bool(self.report["findings"]))
            self.exceptions_only.blockSignals(False)
        self.show_report()

    def scan_failed(self, message):
        self.summary.setText(message)
        self.report = None
        self.clear_results()
        self.update_apply()

    def show_report(self, selected_row=0):
        self.model.replace(self.report, self.exceptions_only.isChecked())
        groups = self.report["groups"]
        counts = [sum(end-start+1 == n for start,end in groups) for n in (1,2,3)]
        counts.append(len(groups)-sum(counts))
        self.summary.setText((self.report.get("message", "") + "\n" if not groups else "") + f"{self.report['pages']:,} source pages · {len(groups):,} mailpieces · {len(self.report['excluded_pages']):,} excluded separators\n"
                             f"1 page: {counts[0]:,} · 2: {counts[1]:,} · 3: {counts[2]:,} · 4+: {counts[3]:,} · {len(self.report['findings']):,} warnings")
        self.acknowledge.setChecked(False)
        self.update_apply()
        if groups:
            visible = self.model.rows.index(selected_row) if selected_row in self.model.rows else 0
            self.table.selectRow(visible)

    def selected_row(self):
        row = self.table.currentIndex().row()
        return self.model.rows[row] if 0 <= row < len(self.model.rows) else -1

    def update_apply(self):
        self.apply_button.setEnabled(bool(self.report and self.report["groups"] and not self.scan_worker
                                          and not self.window.active_worker and self.acknowledge.isChecked()))
        index = self.selected_row()
        selected = self.report and 0 <= index < len(self.report["groups"])
        self.split_button.setEnabled(bool(selected and not self.scan_worker and
                                         self.report["groups"][index][0] < self.report["groups"][index][1]))
        adjacent = selected and index > 0 and self.report["groups"][index-1][1]+1 == self.report["groups"][index][0]
        self.merge_button.setEnabled(bool(adjacent and not self.scan_worker))
        self.next_warning.setEnabled(bool(self.report and self.model.warnings and not self.scan_worker))
        self.undo_boundary.setEnabled(bool(self.report and self.review_undo and not self.scan_worker))
        self.redo_boundary.setEnabled(bool(self.report and self.review_redo and not self.scan_worker))

    def selected(self, current, previous):
        if not self.report or not current.isValid():
            return
        start, end = self.report["groups"][self.model.rows[current.row()]]
        self.update_apply()
        reasons = [f"Source page {f['page']}: {f['message']}" for f in self.report["findings"] if start <= f["page"] <= end]
        evidence = next((e for e in self.report["evidence"] if e["page"] == start), {})
        matches = [SIGNAL_LABELS.get(m, m) for m in evidence.get("matched", [])]
        end_reason = {"next_start_inferred": "End inferred from the next first page; document completeness is not independently proven.",
                      "pdf_end_inferred": "Last letter extends to the PDF end; document completeness is not independently proven.",
                      "printed_sequence": "Printed page sequence checked; review any sequence warnings."}.get(evidence.get("end_basis"), "Operator-edited boundary.")
        self.detail.setPlainText(f"Source pages {start}–{end}; boundary evidence: {', '.join(matches) or 'operator/manual start'}\n" + end_reason + "\n" + "\n".join(reasons))
        self.preview_page.blockSignals(True)
        self.preview_page.setRange(start, end)
        self.preview_page.setValue(start)
        self.preview_page.blockSignals(False)
        self.warning_cursor = start-1
        self.show_source_page(start)
        self.refresh_pair()

    def select_next_warning(self):
        if not self.report or not self.model.warnings:
            return
        index = bisect_left(self.model.warnings, self.warning_cursor+1)
        page = self.model.warnings[index % len(self.model.warnings)]
        for number, (start, finish) in enumerate(self.report["groups"]):
            if start <= page <= finish:
                if number not in self.model.rows:
                    continue
                visible = self.model.rows.index(number)
                if self.selected_row() == number:
                    self.selected(self.model.index(visible, 0), self.table.currentIndex())
                else:
                    self.table.selectRow(visible)
                self.table.scrollTo(self.model.index(visible, 0))
                self.preview_page.setValue(page)
                self.warning_cursor = page
                return
        self.warning_cursor = page
        self.preview_page.blockSignals(True)
        self.preview_page.setRange(1, self.report["pages"])
        self.preview_page.setValue(page)
        self.preview_page.blockSignals(False)
        self.detail.setPlainText("Warning is on an excluded separator page:\n" + "\n".join(
            finding["message"] for finding in self.report["findings"] if finding["page"] == page))
        self.show_source_page(page)

    def show_source_page(self, page):
        source = self.source or self.window.spec.to_dict()["source"]
        self.source_preview.request(source, page)

    def showEvent(self, event):
        super().showEvent(event)
        self.show_source_page(self.preview_page.value())
        self.refresh_pair()

    def boundary_snapshot(self):
        # History retains mutable boundaries only, not every page's scan evidence.
        return (copy.deepcopy(self.report["groups"]), copy.deepcopy(self.report["edits"]),
                self.selected_row())

    def record_boundary_edit(self, report, row):
        self.review_undo.append(self.boundary_snapshot())
        self.review_undo = self.review_undo[-20:]
        self.review_redo.clear()
        self.report = report
        self.show_report(row)

    def restore_boundary_edit(self, redo):
        history = self.review_redo if redo else self.review_undo
        destination = self.review_undo if redo else self.review_redo
        if not self.report or not history or self.scan_worker:
            return
        destination.append(self.boundary_snapshot())
        groups, edits, row = history.pop()
        self.report["groups"], self.report["edits"] = groups, edits
        self.report["accepted"] = False
        self.show_report(row)

    def split(self):
        index = self.selected_row()
        if not self.report or index < 0:
            return
        start, end = self.report["groups"][index]
        if start == end:
            self.detail.setPlainText("A one-page mailpiece cannot be split.")
            return
        page, ok = QInputDialog.getInt(self, "Split mailpiece", "Source page where the next envelope starts", start+1, start+1, end)
        if ok:
            self.record_boundary_edit(edit_boundary(self.report, index, split_page=page), index+1)

    def merge(self):
        try:
            index = self.selected_row()
            self.record_boundary_edit(edit_boundary(self.report, index, merge_previous=True), index-1)
        except (ValueError, TypeError) as exc:
            self.detail.setPlainText(str(exc))

    def apply(self):
        if (not self.apply_button.isEnabled() or self.window.active_worker
                or self.window.font_token or self.window.draft_error):
            return
        if self.window.spec.source.sha256 != self.source["sha256"]:
            self.summary.setText("The project source changed. Close this review and scan the current source.")
            return
        if self.report["config"].get("version", 1) == 2:
            # Validate bytes in the background, then commit after the worker releases
            # the project lock. Never accept stale page boundaries after a file edit.
            before = copy.deepcopy(self.window.spec.to_dict())
            generation = self.scan_generation
            verified = []
            self.form.parentWidget().setEnabled(False)
            self.acknowledge.setEnabled(False)
            self.scan_button.setEnabled(False)
            self.scan_status.setText("Checking source before accepting boundaries…")
            self.scan_status.show()
            self.scan_progress.setRange(0, 0)
            self.scan_progress.show()
            self.cancel_button.setEnabled(True)
            self.scan_worker = self.window.worker({"task": "mailpiece_review_source", "source": self.source["path"],
                                                   "expected_sha256": self.source["sha256"]}, verified.append,
                                                  self.scan_failed, active=True)
            self.update_apply()
            def ended():
                self.scan_ended()
                if not self.isVisible() or generation != self.scan_generation or not verified or not self.report:
                    return
                if self.window.spec.to_dict() != before:
                    self.scan_failed("The project changed during source validation. Scan and review again.")
                    return
                self.source = verified[-1]["source"]
                self.commit_report()
            if self.scan_worker:
                self.scan_worker.ended.connect(ended)
            else:
                self.scan_ended()
            return
        self.commit_report()

    def commit_report(self):
        raw = self.window.spec.to_dict()
        raw["source"] = self.source
        raw["settings"]["groups"] = copy.deepcopy(self.report["groups"])
        raw["settings"]["excluded_pages"] = list(self.report["excluded_pages"])
        raw["detection_review"] = copy.deepcopy(self.report)
        raw["detection_review"]["accepted"] = True
        if raw.get("source_link"):
            raw["source_link"]["review_required"] = False
        raw["detection_review"]["accepted_at"] = now()
        if self.window.commit(raw, "Apply reviewed mailpiece detection"):
            self.accept()

    def done(self, result):
        self.source_preview.stop()
        self.secondary_preview.stop()
        super().done(result)

    def reject(self):
        if self.scan_worker:
            self.scan_worker.cancel()
        self.scan_generation += 1
        self.source_preview.stop()
        self.secondary_preview.stop()
        super().reject()
