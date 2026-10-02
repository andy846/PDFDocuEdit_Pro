"""Background scan and explicit operator review of mailpiece boundaries."""
from __future__ import annotations

import copy
from bisect import bisect_left
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QRectF, Qt
from PyQt6.QtGui import QColor, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
from composition.template.model import MM_TO_PT

METHODS = [("Page number pattern", "page_number"), ("Document / Account ID changes", "document_id"),
           ("First-page text markers (all)", "first_text"), ("Separator page", "separator"),
           ("Text present in selected region", "region_present"), ("Combine boundary rules", "combined")]


class BoundaryTable(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups, self.warnings = [], []

    def replace(self, report):
        self.beginResetModel()
        self.groups = report["groups"]
        self.warnings = sorted({f["page"] for f in report["findings"]})
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.groups)

    def columnCount(self, parent=None):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("Envelope", "Source pages", "Count", "Review")[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        start, end = self.groups[index.row()]
        warning_index = bisect_left(self.warnings, start)
        needs_review = warning_index < len(self.warnings) and self.warnings[warning_index] <= end
        return (f"{index.row()+1:06}", f"{start}–{end}", end-start+1,
                "Needs review" if needs_review else "Check boundaries")[index.column()]


class RegionView(QGraphicsView):
    """Source-page preview; a drag selects a search rectangle in millimetres."""
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.setScene(QGraphicsScene(self))
        self.setMinimumHeight(140)
        self.setBackgroundBrush(QColor("#59616b"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.anchor = self.region_item = None
        self.setToolTip("Drag on the PDF page to set the search region. Ctrl+wheel zooms; coordinates use the visible page top-left.")

    def load(self, path, geometry):
        self.scene().clear()
        self.region_item = None
        pixmap = QPixmap(path)
        item = self.scene().addPixmap(pixmap)
        item.setScale(geometry["width_pt"]/MM_TO_PT/pixmap.width())
        self.scene().setSceneRect(item.sceneBoundingRect())
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.scale(1.2 if event.angleDelta().y() > 0 else 1/1.2, 1.2 if event.angleDelta().y() > 0 else 1/1.2)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.sceneRect().isEmpty():
            self.anchor = self.mapToScene(event.pos())
            if self.region_item:
                self.scene().removeItem(self.region_item)
            pen = QPen(QColor("#d42b91"), 1)
            pen.setCosmetic(True)
            self.region_item = self.scene().addRect(QRectF(self.anchor, self.anchor), pen)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            rect = QRectF(self.anchor, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.region_item.setRect(rect)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            rect = QRectF(self.anchor, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self.anchor = None
            if rect.width() > .1 and rect.height() > .1:
                self.dialog.whole.setChecked(False)
                for control, value in zip(self.dialog.region, (rect.x(), rect.y(), rect.width(), rect.height()), strict=True):
                    control.setValue(value)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class MailpieceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.context_sha256 = window.spec.source.sha256
        self.setWindowTitle("Mailpiece detection · Scan → Review → Apply")
        self.resize(880, 650)
        self.report = self.source = None
        self.scan_worker = None
        self.preview_generation = 0
        outer = QVBoxLayout(self)
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        left = QWidget()
        form = QFormLayout(left)
        self.form = form
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
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        splitter.addWidget(scroll)
        right = QWidget()
        layout = QVBoxLayout(right)
        self.model = BoundaryTable(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.selectionModel().currentRowChanged.connect(self.selected)
        layout.addWidget(self.table, 2)
        self.preview_page = QSpinBox()
        self.preview_page.setPrefix("Source page ")
        self.preview_page.setRange(1, window.spec.source.pages)
        self.preview_page.valueChanged.connect(self.show_source_page)
        navigation = QHBoxLayout()
        navigation.addWidget(self.preview_page, 1)
        fit = QPushButton("Fit page")
        fit.clicked.connect(lambda: self.preview.fitInView(self.preview.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
        navigation.addWidget(fit)
        layout.addLayout(navigation)
        self.preview = RegionView(self)
        layout.addWidget(self.preview, 2)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(90)
        layout.addWidget(self.detail)
        edits = QHBoxLayout()
        self.split_button = QPushButton("Split here…")
        self.merge_button = QPushButton("Merge with previous")
        self.split_button.clicked.connect(self.split)
        self.merge_button.clicked.connect(self.merge)
        edits.addWidget(self.split_button)
        edits.addWidget(self.merge_button)
        layout.addLayout(edits)
        splitter.addWidget(right)
        splitter.setSizes([300, 560])
        self.summary = QLabel("Configure detection, scan, then review every boundary before applying. No barcode is added by scanning.")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
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
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.method.currentIndexChanged.connect(self.update_method)
        self.update_method()
        self.cancel_button.setEnabled(False)
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

    def config(self):
        kind = self.method.currentData()
        kinds = [key for key, check in self.combined.items() if check.isChecked()] if kind == "combined" else [kind]
        rules = []
        for key in kinds:
            rule = {"kind": key}
            if key in ("page_number", "document_id"):
                rule["pattern"] = (self.number_pattern if key == "page_number" else self.id_pattern).text()
                if key == "document_id" and self.first_ids.isChecked():
                    rule["allow_missing_continuation"] = True
            elif key in ("first_text", "separator"):
                rule["terms"] = ([self.separator.text()] if key == "separator" else self.markers.toPlainText().splitlines())
            rules.append(rule)
        result = DetectionConfig(rules, self.combine.currentData(), None if self.whole.isChecked() else [c.value() for c in self.region], self.remove.isChecked())
        result.validate()
        return result

    def restore_config(self, config):
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
            self.summary.setText("Detection options changed. Scan again before applying boundaries.")
        self.acknowledge.setChecked(False)
        self.update_apply()

    def scan(self):
        if self.window.active_worker or self.window.draft_error:
            return
        try:
            config = self.config()
        except ValueError as exc:
            self.summary.setText(str(exc))
            return
        self.report = None
        self.update_apply()
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.scan_worker = self.window.worker({"task": "mailpiece_scan", "source": self.window.spec.source.path,
            "expected_sha256": self.window.spec.source.sha256, "config": asdict(config)}, self.scanned, self.scan_failed, active=True)
        if self.scan_worker:
            self.scan_worker.ended.connect(self.scan_ended)

    def scan_ended(self):
        self.scan_worker = None
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.update_apply()

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
        self.show_report()

    def scan_failed(self, message):
        self.summary.setText(message)
        self.report = None
        self.update_apply()

    def show_report(self):
        self.model.replace(self.report)
        groups = self.report["groups"]
        counts = [sum(end-start+1 == n for start,end in groups) for n in (1,2,3)]
        counts.append(len(groups)-sum(counts))
        self.summary.setText(f"{self.report['pages']:,} source pages · {len(groups):,} mailpieces · {len(self.report['excluded_pages']):,} excluded separators\n"
                             f"1 page: {counts[0]:,} · 2: {counts[1]:,} · 3: {counts[2]:,} · 4+: {counts[3]:,} · {len(self.report['findings']):,} warnings")
        self.acknowledge.setChecked(False)
        self.update_apply()
        if groups:
            self.table.selectRow(0)

    def update_apply(self):
        self.apply_button.setEnabled(bool(self.report and not self.scan_worker and self.acknowledge.isChecked()))
        index = self.table.currentIndex().row()
        selected = self.report and 0 <= index < len(self.report["groups"])
        self.split_button.setEnabled(bool(selected and not self.scan_worker and
                                         self.report["groups"][index][0] < self.report["groups"][index][1]))
        adjacent = selected and index > 0 and self.report["groups"][index-1][1]+1 == self.report["groups"][index][0]
        self.merge_button.setEnabled(bool(adjacent and not self.scan_worker))

    def selected(self, current, previous):
        if not self.report or not current.isValid():
            return
        start, end = self.report["groups"][current.row()]
        self.update_apply()
        reasons = [f"Source page {f['page']}: {f['message']}" for f in self.report["findings"] if start <= f["page"] <= end]
        matches = next((e["matched"] for e in self.report["evidence"] if e["page"] == start), [])
        self.detail.setPlainText(f"Source pages {start}–{end}; boundary evidence: {', '.join(matches) or 'operator/manual start'}\n" + "\n".join(reasons))
        self.preview_page.blockSignals(True)
        self.preview_page.setRange(start, end)
        self.preview_page.setValue(start)
        self.preview_page.blockSignals(False)
        self.show_source_page(start)

    def show_source_page(self, page):
        self.preview_generation += 1
        generation = self.preview_generation
        target = self.window.directory/f"detection-preview-{generation}.png"
        source = self.source or self.window.spec.to_dict()["source"]
        def ready(value):
            if self.isVisible() and generation == self.preview_generation:
                self.preview.load(value["image"], value["geometry"])
            Path(value["image"]).unlink(missing_ok=True)
        self.window.worker({"task": "mailpiece_preview", "source": source["path"], "page": page,
                            "target": str(target), "size": source["size"], "mtime_ns": source["mtime_ns"]},
                           ready, lambda message: self.detail.setPlainText(message))

    def split(self):
        index = self.table.currentIndex().row()
        if not self.report or index < 0:
            return
        start, end = self.report["groups"][index]
        if start == end:
            self.detail.setPlainText("A one-page mailpiece cannot be split.")
            return
        page, ok = QInputDialog.getInt(self, "Split mailpiece", "Source page where the next envelope starts", start+1, start+1, end)
        if ok:
            self.report = edit_boundary(self.report, index, split_page=page)
            self.show_report()

    def merge(self):
        try:
            self.report = edit_boundary(self.report, self.table.currentIndex().row(), merge_previous=True)
            self.show_report()
        except (ValueError, TypeError) as exc:
            self.detail.setPlainText(str(exc))

    def apply(self):
        if not self.apply_button.isEnabled() or self.window.active_worker:
            return
        if self.window.spec.source.sha256 != self.source["sha256"]:
            self.summary.setText("The project source changed. Close this review and scan the current source.")
            return
        raw = self.window.spec.to_dict()
        raw["source"] = self.source
        raw["settings"]["groups"] = copy.deepcopy(self.report["groups"])
        raw["settings"]["excluded_pages"] = list(self.report["excluded_pages"])
        raw["detection_review"] = copy.deepcopy(self.report)
        raw["detection_review"]["accepted"] = True
        raw["detection_review"]["accepted_at"] = now()
        if self.window.commit(raw, "Apply reviewed mailpiece detection"):
            self.accept()

    def reject(self):
        if self.scan_worker:
            self.scan_worker.cancel()
        self.preview_generation += 1
        super().reject()
