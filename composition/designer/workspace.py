"""Dedicated Print Composition workspace, independent from DocumentSession."""
from __future__ import annotations

import copy
import json
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from composition.template.model import CompositionError, Element, FontSpec, Template
from composition.template.serializer import load_project

from .bulk_typography import BulkTypography
from .canvas import Canvas, FieldList
from .chrome import DesignerChrome
from .compact_chrome import CompactMessage
from .data_dialog import DataDialog
from .font_controls import FontOperations
from .pages import PageOperations
from .process import Worker
from .properties import Properties
from .rule_controls import RuleOperations
from .sequence_controls import SequenceOperations
from .usability import DesignerUsability


class TemplateEdit(QUndoCommand):
    def __init__(self, window, before, after, label, selected=None, page_id=None, content_only=None):
        super().__init__(label)
        self.window, self.before, self.after, self.selected = window, before, after, selected
        self.before_page = window.active_page_id
        self.after_page = page_id or window.active_page_id
        self.content_only = content_only
        self.edited_at = time.monotonic()
    def undo(self):
        self.window._apply_template(self.before, self.selected, page_id=self.before_page, content_only=bool(self.content_only))
    def redo(self):
        self.window._apply_template(self.after, self.selected, page_id=self.after_page, content_only=bool(self.content_only))

    def id(self):
        return 101 if self.content_only else -1

    def mergeWith(self, other):
        if (not self.content_only or self.content_only != other.content_only
                or self.after_page != other.after_page or self.after != other.before
                or other.edited_at-self.edited_at > 0.8):
            return False
        self.after = other.after
        self.edited_at = other.edited_at
        return True


class CompositionWindow(SequenceOperations, BulkTypography, DesignerUsability, RuleOperations, PageOperations, DesignerChrome, FontOperations, QMainWindow):
    activityChanged = pyqtSignal()
    projectClosed = pyqtSignal()

    def __init__(self, parent=None, *, embedded=False, project_host=None):
        super().__init__(parent, Qt.WindowType.Widget if embedded else Qt.WindowType.Window)
        self.embedded, self.project_host = embedded, project_host
        self._close_approved = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1240, 820)
        self.setMinimumSize(0 if embedded else 760, 0 if embedded else 580)
        self.template = Template()
        self.active_page_id = self.template.pages[0].id
        self.project_path = None
        self.temp = tempfile.TemporaryDirectory(prefix="pdfdocuedit-composition-")
        self.directory = Path(self.temp.name)
        self.workers = []
        self.preview_worker = self.production_worker = self.import_worker = None
        self.preview_generation = 0
        self.stores = {}
        self._data_ui_key = None
        self.record_count = 0
        self.clipboard = []
        self.font_requests = {}
        self.font_inspections = set()
        self.font_epoch = 0
        self._layers_updating = False
        self.preferences = QSettings()
        self.preferences.beginGroup("document_designer")

        self._init_usability()
        self.close_pending = False
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._title)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)
        self.preview_timer.timeout.connect(self._render_preview)
        self._build_ui()
        if embedded:
            self.menuBar().hide()
        self._apply_template(self.template.to_dict())
        self.undo.setClean()
        QTimer.singleShot(0, self.canvas.fit_page)
        QTimer.singleShot(0, self._load_windows_fonts)
        QTimer.singleShot(0, self._adjust_inspector)

    def _build_ui(self):
        self._build_actions()
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        self.description = QLabel("Design reusable documents with static content, variable data and production PDF output.", outer)
        self.description.hide()
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for name in ("Data", "Design", "Preview", "Production"):
            self.tabs.addTab(name)
        self.tabs.setCurrentIndex(1)
        self.tabs.currentChanged.connect(self._mode_changed)
        layout.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.design_page = QWidget()
        design_layout = QVBoxLayout(self.design_page)
        design_layout.setContentsMargins(0, 0, 0, 0)
        self._build_page_navigation(design_layout)
        self.splitter = QSplitter()
        self.data_panel = QWidget()
        data_layout = QVBoxLayout(self.data_panel)
        data_layout.addWidget(QLabel("DATA"))
        self.import_button = QPushButton("Import CSV / TXT / Excel…")
        self.import_button.clicked.connect(self.import_data)
        data_layout.addWidget(self.import_button)
        self.sequence_button = QPushButton("Running sequences…")
        self.sequence_button.clicked.connect(self.edit_sequences)
        data_layout.addWidget(self.sequence_button)
        self.source_label = QLabel("No data source")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        data_layout.addWidget(self.source_label)
        self.fields = FieldList()
        self.fields.setDragEnabled(True)
        self.fields.itemDoubleClicked.connect(lambda item: self.add_field(item.text(), 20, 20))
        self.field_filter = QLineEdit()
        self.field_filter.setPlaceholderText("Find a data field…")
        self.field_filter.setClearButtonEnabled(True)
        self.field_filter.setAccessibleName("Filter data fields")
        self.field_filter.textChanged.connect(self._filter_fields)
        data_layout.addWidget(self.field_filter)
        data_layout.addWidget(self.fields)
        help_label = QLabel("Drag a field onto the page. Double-click to add at 20 mm.")
        help_label.setWordWrap(True)
        data_layout.addWidget(help_label)
        self.data_panel.setMinimumWidth(150)
        self.left_panel = QTabWidget()
        self.left_panel.addTab(self.data_panel, "Data fields")
        self.layers = QListWidget()
        self.layers.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layers.setAccessibleName("Document layers")
        self.layers.itemSelectionChanged.connect(self._layers_selected)
        layer_page = QWidget()
        layer_layout = QVBoxLayout(layer_page)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_filter = QLineEdit()
        self.layer_filter.setPlaceholderText("Find object or field…")
        self.layer_filter.setClearButtonEnabled(True)
        self.layer_filter.setAccessibleName("Filter document objects")
        self.layer_filter.textChanged.connect(self._filter_layers)
        layer_layout.addWidget(self.layer_filter)
        layer_layout.addWidget(self.layers)
        self.left_panel.addTab(layer_page, "Layers")
        self.canvas = Canvas()
        self.canvas.setToolTip("Ctrl + mouse wheel: zoom. Hold Space: pan. Arrow keys: move 0.5 mm; Shift: 5 mm.")
        self.canvas.selectionChanged.connect(self._selection)
        self.canvas.editCommitted.connect(lambda before, after: self._commit(before, after, "Move / resize"))
        self.canvas.fieldDropped.connect(self.add_field)
        self.canvas.command.connect(self.object_command)
        self.properties = Properties()
        self.properties.edited.connect(self._property_edit)
        self.properties.fontRequested.connect(self._request_font)
        self.properties.insertFieldRequested.connect(self.insert_field_into_text)
        self.properties.glyphRepairRequested.connect(self.edit_glyph_repairs)
        self.properties.rulesRequested.connect(self.edit_object_rules)
        self.properties.rulesClearRequested.connect(self.clear_object_rules)
        self.properties.revertRequested.connect(self.revert_content_draft)
        self.properties_scroll = QScrollArea()
        self.properties_scroll.setWidgetResizable(True)
        self.properties_scroll.setWidget(self.properties)
        self.properties_scroll.setMinimumWidth(260)
        self.splitter.addWidget(self.left_panel)
        self.canvas_panel = QWidget()
        canvas_layout = QVBoxLayout(self.canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_state = QLabel("Design layout")
        self.preview_state.setWordWrap(True)
        preview_row = self.document_control_row
        preview_row.addWidget(self.preview_state, 1)
        self.preview_review = QPushButton("Review object")
        self.preview_review.hide()
        self.preview_review.clicked.connect(self.review_failed_object)
        preview_row.addWidget(self.preview_review)
        self.preview_retry = QPushButton("Refresh")
        self.preview_retry.setToolTip("Render the current template page again")
        self.preview_retry.clicked.connect(self._schedule_preview)
        preview_row.addWidget(self.preview_retry)
        canvas_layout.addWidget(self.canvas, 1)
        self.splitter.addWidget(self.canvas_panel)
        self.splitter.addWidget(self.properties_scroll)
        self.splitter.setSizes([220, 700, 280])
        design_layout.addWidget(self.splitter, 1)
        self.stack.addWidget(self.design_page)
        self.data_page = QWidget()
        data_layout = QVBoxLayout(self.data_page)
        self.data_summary = QLabel("Import structured data to map fields and preview records.")
        self.data_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.data_summary.setWordWrap(True)
        data_layout.addWidget(self.data_summary)
        import_large = self.remap_button = QPushButton("Import / remap data…")
        import_large.clicked.connect(self.import_data)
        data_layout.addWidget(import_large)
        sequences_large = QPushButton("Running sequences / generated quantity…")
        sequences_large.clicked.connect(self.edit_sequences)
        data_layout.addWidget(sequences_large)
        self.sample = QTableWidget()
        self.sample.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        data_layout.addWidget(self.sample)
        self.stack.addWidget(self.data_page)
        self.production_page = QWidget()
        prod_layout = QVBoxLayout(self.production_page)
        self.production_heading = QLabel()
        self.production_heading.setWordWrap(True)
        prod_layout.addWidget(self.production_heading)
        self.auto_repair = QCheckBox("Automatically substitute missing glyphs and report changes")
        self.auto_repair.setChecked(self.preferences.value("auto_glyph_repair", True, type=bool))
        self.auto_repair.setToolTip("Keeps each object's primary font. Only missing characters use an available embeddable font. "
                                   "Preview uses the same policy. CSV lists record, output page, character and replacement font; "
                                   "substitutions may affect text width and wrapping. Uncheck for strict font validation.")
        self.auto_repair.toggled.connect(self._auto_repair_changed)
        prod_layout.addWidget(self.auto_repair)
        prod_layout.addWidget(QLabel("Source data is an imported snapshot. Critical errors stop the job.\n"
                                    "Only validated, reconciled output is published to a new job folder."))
        self.production_summary = QPlainTextEdit()
        self.production_summary.setReadOnly(True)
        prod_layout.addWidget(self.production_summary, 1)
        self.production_actions = QHBoxLayout()
        prod_layout.addLayout(self.production_actions)
        self.open_output_button = QPushButton("Open production PDF")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output)
        self.production_actions.addWidget(self.open_output_button)
        self.open_font_report_button = QPushButton("Open font substitution report")
        self.open_font_report_button.setEnabled(False)
        self.open_font_report_button.clicked.connect(self._open_font_report)
        self.production_actions.addWidget(self.open_font_report_button)
        self.last_font_report = ""
        self.last_output = ""
        self.stack.addWidget(self.production_page)
        layout.addWidget(self.stack, 1)
        self.message = CompactMessage(self)
        self.record_navigation = QWidget()
        bottom = QHBoxLayout(self.record_navigation)
        self.first = QPushButton("|◀")
        self.first.setAccessibleName("First record")
        self.first.clicked.connect(lambda: self.record.setValue(1))
        self.previous = QPushButton("◀")
        self.previous.setAccessibleName("Previous record")
        self.previous.clicked.connect(lambda: self.record.setValue(self.record.value()-1))
        self.next = QPushButton("▶")
        self.next.setAccessibleName("Next record")
        self.next.clicked.connect(lambda: self.record.setValue(self.record.value()+1))
        self.record = QSpinBox()
        self.record.setRange(1, 1)
        self.record.valueChanged.connect(self._schedule_preview)
        self.record.valueChanged.connect(self._update_navigation)
        self.last = QPushButton("▶|")
        self.last.setAccessibleName("Last record")
        self.last.clicked.connect(lambda: self.record.setValue(self.record_count))
        self.record_label = QLabel("Record / 0")
        for widget in (self.first, self.previous, self.record, self.next, self.last, self.record_label):
            bottom.addWidget(widget)
        self.document_control_row.insertWidget(6, self.record_navigation)
        self.generate_button = QPushButton("Generate PDF")
        self.generate_button.setAccessibleName("Generate Production PDF")
        self.generate_button.setProperty("primary", True)
        self.generate_button.clicked.connect(self.generate_pdf)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel job")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_job)
        self.setCentralWidget(outer)
        self._finish_designer_ui()


    def _title(self, *args):
        name = self.project_path.name if self.project_path else self.template.name
        self.setWindowTitle(f"{'* ' if not self.undo.isClean() else ''}{name} — Document Designer")

    def _worker(self, request, result, failure=None):
        worker = Worker(self.directory, request, self)
        worker.task = request["task"]
        self.workers.append(worker)
        worker.resultReady.connect(result)
        worker.failed.connect(failure or self._error)
        worker.ended.connect(lambda: self._worker_ended(worker))
        self._busy()
        return worker

    def _worker_ended(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
        if self.import_worker is worker:
            self.import_worker = None
            self.import_button.setEnabled(True)
        if self.production_worker is worker:
            self.production_worker = None
        self._busy()
        if self.close_pending and not self.workers:
            self.close()

    def _error(self, error):
        self.message.setText(error)

    def _config_key(self):
        return json.dumps(asdict(self.template.data), sort_keys=True)

    def _store(self):
        return self._sequence_info(self.stores.get(self._config_key()))

    def _apply_template(self, value, selected=None, *, page_id=None, content_only=False):
        template = Template.from_dict(value)
        if (content_only and (page_id is None or page_id == self.active_page_id)
                and self.properties.element and self.properties.element.id == selected
                and self.canvas.selected_ids() == [selected]):
            self._apply_text_update(template, selected)
            return
        self._remember_canvas_view()
        old = {e.id: e.font for e in self.template.all_elements()}
        new = {e.id: e.font for e in template.all_elements()}
        for object_id in list(self.font_requests):
            if object_id not in new or object_id not in old or any(
                getattr(old[object_id], key) != getattr(new[object_id], key)
                for key in ("family", "file", "bold", "italic")
            ):
                self.font_requests.pop(object_id, None)
        self.template = template
        target = page_id or self.active_page_id
        self.active_page_id = target if any(p.id == target for p in template.pages) else template.pages[0].id
        if selected is None and self.active_page_id in self.page_views:
            selected = self.page_views[self.active_page_id][2]
        self.canvas.set_template(self.template, selected, page_index=self.page_index)
        self._restore_canvas_view()
        selected_ids = selected if isinstance(selected, list) else [selected]
        self._selection(selected_ids[0] if len(selected_ids) == 1 else "")
        self._refresh_data()
        self._refresh_layers()
        self._title()
        self._schedule_preview()

    def _commit(self, before, after, label, selected=None, *, page_id=None, content_only=None):
        if before == after:
            return
        try:
            Template.from_dict(after)
        except CompositionError as exc:
            self._error(str(exc))
            self._apply_template(before, selected)
            return
        if selected is None:
            selected = self.canvas.selected_ids()
        self.undo.push(TemplateEdit(self, before, after, label, selected, page_id, content_only))

    def _selection(self, selected):
        if self.content_invalid and self.properties.element:
            object_id = self.properties.element.id
            if selected != object_id:
                self.canvas.select_ids([object_id])
                self._error("Finish the unfinished content or use Revert unfinished edit before selecting another object.")
            self._sync_layers()
            return
        chosen = {selected} if selected else set(self.canvas.selected_ids())
        self.properties.show_selection([e for e in self.page.elements if e.id in chosen])
        self._inspect_selected_font(self.properties.element)
        self._sync_layers()
        self._update_actions()

    def _property_edit(self, values):
        if self.properties.bulk_ids:
            self._edit_bulk_properties(values)
        else:
            self._edit_property_values(values)

    def _filter_fields(self, text=None):
        query = self.field_filter.text().casefold()
        for index in range(self.fields.count()):
            item = self.fields.item(index)
            item.setHidden(query not in item.text().casefold() and query not in item.toolTip().casefold())

    def _refresh_data(self):
        info = self._store()
        key = (self._config_key(), id(info), repr(self.template.sequences))
        if key == self._data_ui_key:
            self._update_navigation()
            self._refresh_pages()
            self._busy()
            return
        self._data_ui_key = key
        self.fields.clear()
        self.record_count = info["metadata"]["record_count"] if info else 0
        self.record.blockSignals(True)
        self.record.setRange(1, max(1, self.record_count))
        self.record.blockSignals(False)
        self.record_label.setText(f"of {self.record_count:,}")
        self.previous.setEnabled(self.record_count > 1)
        self.next.setEnabled(self.record_count > 1)
        if info:
            meta = info["metadata"]
            self.fields.addItems(meta["fields"])
            for index, original in enumerate(meta["original_fields"]):
                self.fields.item(index).setToolTip(f"Original: {original}")
            label = "Generated records" if self.template.record_mode == "generated" else Path(self.template.data.path).name
            if self.template.record_mode == "imported" and self.template.data.sheet:
                label += " · " + self.template.data.sheet
            self.source_label.setText(label + f"\n{self.record_count:,} records")
            sequence_names = {seq.name for seq in self.template.sequences}
            for index in range(self.fields.count()):
                item = self.fields.item(index)
                if item.text() in sequence_names:
                    item.setToolTip("Running sequence · preview and production use the same values")
            self.data_summary.setText(
                f"Generated records · {self.record_count:,} records · no data file required.\n"
                "Sequence samples show template page 1; use Preview to inspect other pages."
                if self.template.record_mode == "generated" else
                f"{self.template.data.path}\n{self.record_count:,} records · Imported snapshot.\n"
                "Sequence samples show template page 1; re-import to apply source changes.")
            self.sample.setColumnCount(len(meta["fields"]))
            self.sample.setHorizontalHeaderLabels(meta["fields"])
            self.sample.setRowCount(len(info["sample"]))
            for row, record in enumerate(info["sample"]):
                for column, name in enumerate(meta["fields"]):
                    self.sample.setItem(row, column, QTableWidgetItem(record[name]))
        else:
            self.fields.addItems([seq.name for seq in self.template.sequences])
            self.source_label.setText("Import data" if not self.template.data.path else
                                      "Data source needs importing:\n" + self.template.data.path)
            self.data_summary.setText("Import the data source to preview and generate this project.")
            self.sample.setRowCount(0)
        self._filter_fields()
        self._update_navigation()
        self._refresh_pages()
        self._busy()

    def _busy(self):
        busy = bool(self.import_worker or self.production_worker)
        self.sequence_button.setEnabled(not busy and not self.font_requests and not self.content_invalid)
        self.generate_button.setEnabled(bool(self._store()) and not busy and not self.font_requests)
        self.auto_repair.setEnabled(not busy)
        self._update_actions()
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        if self.embedded:
            for key in ("new", "open", "pdf_overlay"):
                self.actions[key].setEnabled(not self.close_pending)
        self.activityChanged.emit()

    def _mode_changed(self, index):
        self.stack.setCurrentIndex(1 if index == 0 else 2 if index == 3 else 0)
        self.canvas.set_preview_mode(index == 2)
        self.record_navigation.setVisible(index == 2)
        self._show_properties(self.actions["properties"].isChecked())
        self._update_actions()
        self._schedule_preview()

    def _schedule_preview(self, *args):
        self.preview_generation += 1
        self.preview_state.setText("Updating preview…" if self.tabs.currentIndex() in (1, 2) else "")
        self.canvas.set_preview(None)
        self.preview_timer.start()

    def _render_preview(self):
        if self.close_pending or self.content_invalid or self.tabs.currentIndex() not in (1, 2):
            return
        if self.preview_worker and self.preview_worker in self.workers:
            self.preview_worker.stop_preview()
        generation = self.preview_generation
        info = self._store() if self.tabs.currentIndex() == 2 else None
        if self.tabs.currentIndex() == 2 and not info:
            self.preview_state.setText("Import data or configure generated quantity in Running sequences.")
            self._error("Import data or choose generated records before previewing.")
            return
        request = {"task": "preview", "template": self.template.to_dict(),
                   "record": self.record.value(), "page": self.page_index, "store": info["store"] if info else "",
                   "design": self.tabs.currentIndex() != 2, "auto_repair": self.auto_repair.isChecked(),
                   "target": str(self.directory / f"preview-{generation}.pdf")}
        self.preview_worker = self._worker(request,
            lambda result: self._preview_ready(result, generation),
            lambda error: self._preview_error(error, generation))

    def _preview_ready(self, result, generation):
        if generation == self.preview_generation:
            self.preview_review.hide()
            self.canvas.set_preview(result["image"])
            self.preview_state.setText(
                f"Record {result['record']:,} · template page {result.get('page', 0)+1}"
                if self.tabs.currentIndex() == 2 else "Design layout · field placeholders")
            if self.tabs.currentIndex() == 2 and result.get("rules"):
                states = result["rules"]
                hidden = sum(not row["visible"] for row in states)
                alternate = sum(row["alternative"] for row in states)
                self.preview_state.setText(self.preview_state.text() + f" · {hidden} hidden / {alternate} alternative")
            repairs = result.get("glyph_repairs", [])
            count = sum(item["occurrences"] for item in repairs)
            self.message.setText(f"Preview uses {count} glyph font substitution(s); primary fonts retained." if count else "")
        Path(result["pdf"]).unlink(missing_ok=True)
        Path(result["image"]).unlink(missing_ok=True)

    def _preview_error(self, error, generation):
        if generation == self.preview_generation:
            self.preview_state.setText("Preview failed — review the object or its content.")
            self._record_font_error(error)
            self.preview_review.setVisible(bool(self.failed_object))
            self._error(error)

    def add_element(self, kind="text", value=None, x=20, y=20, font=None):
        if self.content_invalid or self.import_worker or self.production_worker:
            return
        if self.tabs.currentIndex() != 1:
            self.tabs.setCurrentIndex(1)
        element = Element(type=kind, value=value if value is not None else "Text",
                          font=font if font is not None else FontSpec())
        if kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Static image", "", "Images (*.png *.jpg *.jpeg *.tif *.tiff)")
            if not path:
                return
            element.image, element.height_mm = path, 40
        elif kind == "line":
            element.height_mm = .1
        elif kind == "rectangle":
            element.height_mm = 30
        elif kind in {"code128", "i25"}:
            element.value, element.width_mm, element.height_mm = value or ("0001234560" if kind == "i25" else "000123456"), 100, 20
        elif kind == "qr":
            element.value, element.width_mm, element.height_mm = value or "https://example.com", 40, 40
        element.width_mm = min(element.width_mm, self.page.width_mm)
        element.height_mm = min(element.height_mm, self.page.height_mm)
        element.x_mm = min(max(0, x), self.page.width_mm-element.width_mm)
        element.y_mm = min(max(0, y), self.page.height_mm-element.height_mm)
        before = self.template.to_dict()
        after = copy.deepcopy(before)
        self._page_dict(after)["elements"].append(asdict(element))
        self._commit(before, after, "Add " + kind, element.id)

    def add_field(self, name, x, y):
        self.add_element("text", "{{" + name + "}}", x, y,
                         font=FontSpec(family="Noto Sans CJK HK"))

    def _record_font_error(self, error, record=None):
        import re
        object_match = re.search(r"object ([a-f0-9]{32})", error)
        code_match = re.search(r"U\+[0-9A-F]{4,6}", error)
        record_match = re.search(r"Record (\d+)", error)
        self.failed_object = object_match.group(1) if object_match else ""
        self.failed_codepoint = code_match.group(0) if code_match else ""
        self.failed_record = record or (int(record_match.group(1)) if record_match else None)
        self.review_error_button.setVisible(bool(self.failed_record or self.failed_object))
        self.repair_error_button.setVisible(bool(self.failed_object and self.failed_codepoint))

    def repair_failed_glyph(self):
        self.review_failed_object()
        self.edit_glyph_repairs()

    def edit_glyph_repairs(self):
        if self.content_invalid or self.production_worker or self.import_worker or self.font_requests:
            self._error("Finish the active font or job operation before configuring glyph repairs.")
            return
        element = self.properties.element
        if not element or not (element.type == "text" or element.show_barcode_text):
            self._error("Select a text object to configure missing-glyph repairs.")
            return
        from .glyph_dialog import GlyphRepairDialog
        code = self.failed_codepoint if self.failed_object == element.id else ""
        dialog = GlyphRepairDialog(element, self.properties.catalogue, code, self)
        if not dialog.exec() or not dialog.choice:
            return
        choice = dialog.choice
        if choice.get("remove"):
            self.remove_glyph_repair(element.id, choice["codepoint"])
        else:
            self._request_font(choice)

    def remove_glyph_repair(self, object_id, codepoint):
        if self.content_invalid or self.import_worker or self.production_worker:
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        target = next((e for page in after["pages"] for e in page["elements"]
                       if e["id"] == object_id), None)
        if target and codepoint in target["glyph_repairs"]:
            target["glyph_repairs"].pop(codepoint)
            self._commit(before, after, "Remove missing-glyph repair", self.canvas.selected_ids())

    def use_cjk_font(self):
        self.properties.apply()
        if self.content_invalid or self.import_worker or self.production_worker:
            return
        selected = self.canvas.selected_ids()
        before, after = self.template.to_dict(), self.template.to_dict()
        changed = 0
        for element in self._page_dict(after)["elements"]:
            if element["id"] in selected and element["type"] == "text":
                element["font"].update(family="Noto Sans CJK HK", file="", italic=False)
                changed += 1
        if not changed:
            self.message.setText("Select one or more text objects to apply the CJK font.")
            return
        self._commit(before, after, "Use CJK font for selected text", selected)
        self.message.setText(f"Noto Sans CJK HK applied to {changed} selected text object(s).")


    def object_command(self, command):
        if command != "copy" and (self.import_worker or self.production_worker or self.content_invalid or self.canvas.mode_preview):
            return
        selected = set(self.canvas.selected_ids())
        if command == "cut":
            self.object_command("copy")
            self.object_command("delete")
            return
        if command == "copy":
            self.clipboard = [asdict(e) for e in self.page.elements if e.id in selected]
            self._update_actions()
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        if command == "delete":
            self._page_dict(after)["elements"] = [e for e in self._page_dict(after)["elements"] if e["id"] not in selected]
        elif command in {"paste", "duplicate"}:
            source = (self.clipboard if command == "paste" else
                      [asdict(e) for e in self.page.elements if e.id in selected])
            for element in copy.deepcopy(source):
                if element["width_mm"] > self.page.width_mm or element["height_mm"] > self.page.height_mm:
                    self._error("The copied object is larger than this page. Resize it on the source page first.")
                    return
                element["id"] = uuid.uuid4().hex
                element["x_mm"] = min(self.page.width_mm-element["width_mm"], element["x_mm"]+3)
                element["y_mm"] = min(self.page.height_mm-element["height_mm"], element["y_mm"]+3)
                self._page_dict(after)["elements"].append(element)
        self._commit(before, after, command.title())

    def _discard_check(self):
        self.properties.apply()
        if self.undo.isClean() and not self.content_invalid:
            return True
        answer = QMessageBox.question(self, "Unsaved document design", "Save changes to this project?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        if answer == QMessageBox.StandardButton.Discard:
            self.revert_content_draft()
            return True
        return False

    def new_project(self):
        if self.project_host:
            return self.project_host.new_template()
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before replacing the project.")
            return
        if self._discard_check():
            self.font_epoch += 1
            self.font_requests.clear()
            self.page_views.clear()
            self.project_path = None
            self.stores.clear()
            self.undo.clear()
            self._apply_template(Template().to_dict(), page_id="page_1")
            self.tabs.setCurrentIndex(1)
            self.canvas.fit_page()
            self.undo.setClean()

    def open_pdf_overlay(self, checked=False, path=None):
        if self.project_host:
            return self.project_host.open_project(path) if path else self.project_host.new_overlay()
        from .overlay_workspace import OverlayWindow
        if not hasattr(self, "overlay_windows"):
            self.overlay_windows = []
        window = OverlayWindow(project_path=path)
        self.overlay_windows.append(window)
        window.show()
        return window

    def open_project(self, checked=False, path=None):
        if self.project_host:
            return self.project_host.open_project(path)
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before replacing the project.")
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open Document Designer project", "", "Document Designer projects (*.pdcx)")
        if not path:
            return
        try:
            project_file = Path(path)
            if project_file.stat().st_size > 10*1024*1024:
                raise CompositionError("Designer project exceeds 10 MB.")
            project_value = json.loads(project_file.read_text(encoding="utf-8"))
            if not isinstance(project_value, dict):
                raise CompositionError("Invalid Designer project structure.")
            if project_value.get("project_kind") == "pdf_overlay":
                self.open_pdf_overlay(path=path)
                return
            if not self._discard_check():
                return
            template = load_project(path)
        except (OSError, CompositionError, ValueError) as exc:
            self._error(str(exc))
            return
        self.font_epoch += 1
        self.font_requests.clear()
        self.page_views.clear()
        self.stores.clear()
        self.project_path = Path(path)
        self.undo.clear()
        self._apply_template(template.to_dict(), page_id=template.pages[0].id)
        self.undo.setClean()
        self.tabs.setCurrentIndex(1)
        self.canvas.fit_page()
        self._remember_project(self.project_path)
        if template.record_mode == "imported" and template.data.path:
            if Path(template.data.path).is_file():
                self._start_import(template.data)
            elif QMessageBox.question(self, "Data source not found", "Data source not found. Locate File?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.import_data()

    def save_project(self, checked=False, save_as=False):
        self.properties.apply()
        if self.content_invalid:
            self._error("Finish or revert the unfinished content before saving.")
            return False
        if self.font_requests or any(getattr(w, "task", "") == "background" for w in self.workers):
            self._error("Wait for the selected font or background to finish loading before saving.")
            return False
        path = str(self.project_path) if self.project_path and not save_as else ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save Document Designer project", "", "Document Designer projects (*.pdcx)")
        if not path:
            return False
        if self.project_host and not self.project_host.allow_save_path(self, path):
            return False
        loop = QEventLoop(self)
        dialog = QProgressDialog("Saving template and static assets...", "", 0, 0, self)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        outcome = {}

        def saved(result):
            outcome.update(result)
            loop.quit()

        def failed(message):
            outcome["error"] = message
            loop.quit()

        self._worker({"task": "save", "template": self.template.to_dict(), "target": path}, saved, failed)
        dialog.show()
        loop.exec()
        dialog.close()
        if "error" in outcome:
            self._error(outcome["error"])
            return False
        self.project_path = Path(outcome["project"])
        self._apply_template(outcome["template"], self.canvas.selected_ids())
        self.undo.setClean()
        self._title()
        self._remember_project(self.project_path)
        self.message.setText("Project saved: " + str(self.project_path))
        return True

    def rename_template(self):
        name, ok = QInputDialog.getText(self, "Project name", "Name", text=self.template.name)
        if ok and name.strip():
            before, after = self.template.to_dict(), self.template.to_dict()
            after["name"] = name.strip()
            self._commit(before, after, "Rename template")

    def page_size(self):
        size, ok = QInputDialog.getItem(self, "Page size", "Size", ["A4", "A5", "Letter", "Custom"], 0, False)
        if not ok:
            return
        sizes = {"A4": (210, 297), "A5": (148, 210), "Letter": (215.9, 279.4)}
        if size == "Custom":
            width, ok = QInputDialog.getDouble(self, "Custom page", "Width (mm)", self.page.width_mm, 10, 2000, 2)
            if not ok:
                return
            height, ok = QInputDialog.getDouble(self, "Custom page", "Height (mm)", self.page.height_mm, 10, 2000, 2)
            if not ok:
                return
        else:
            width, height = sizes[size]
        before, after = self.template.to_dict(), self.template.to_dict()
        self._page_dict(after).update(width_mm=width, height_mm=height)
        self._commit(before, after, "Change page size")
        self.canvas.fit_page()

    def add_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Use PDF page as static background", "", "PDF (*.pdf)")
        if not path:
            return
        page, ok = QInputDialog.getInt(self, "Background page", "Source page (one-based)", 1, 1, 1000000)
        if not ok:
            return
        page_id, epoch = self.active_page_id, self.font_epoch
        self._worker({"task": "background", "source": path, "page": page-1,
                      "target": str(self.directory / f"background-{uuid.uuid4().hex}.pdf")},
                     lambda result: self._background_ready(result, page_id, epoch))

    def _background_ready(self, result, page_id=None, epoch=None):
        before, after = self.template.to_dict(), self.template.to_dict()
        if epoch is not None and epoch != self.font_epoch:
            return
        if page_id and not any(p["id"] == page_id for p in after["pages"]):
            return
        self._page_dict(after, page_id).update(
            background=result["background"], width_mm=result["width_mm"], height_mm=result["height_mm"])
        self._commit(before, after, "Use PDF background")
        self.canvas.fit_page()

    def remove_background(self):
        before, after = self.template.to_dict(), self.template.to_dict()
        self._page_dict(after)["background"] = ""
        self._commit(before, after, "Remove background")

    def import_data(self):
        if self.content_invalid:
            self._error("Finish or revert the unfinished content before importing data.")
            return
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before importing another source.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import data", self.template.data.path,
                                             "Structured data (*.csv *.txt *.tsv *.xlsx *.xls);;Excel (*.xlsx *.xls);;CSV / TXT (*.csv *.txt *.tsv);;All files (*)")
        if not path:
            return
        initial = self.template.data if path == self.template.data.path else None
        dialog = DataDialog(path, self.directory, self, initial)
        if dialog.exec():
            self._start_import(dialog.config())

    def _start_import(self, config):
        self.import_button.setEnabled(False)
        self.import_worker = self._worker({"task": "import", "config": asdict(config),
            "target": str(self.directory / f"records-{uuid.uuid4().hex}.db")},
            lambda result: self._import_ready(result, config))
        self.import_worker.progress.connect(self._progress)
        self._busy()
        self.message.setText("Importing data in a background process…")

    def _import_ready(self, result, config):
        self.stores[json.dumps(asdict(config), sort_keys=True)] = result
        before, after = self.template.to_dict(), self.template.to_dict()
        after["data"] = asdict(config)
        after["record_mode"] = "imported"
        self._commit(before, after, "Import data")
        self._refresh_data()
        self._schedule_preview()
        if self._store():
            meta = result["metadata"]
            notes = f"Imported {meta['record_count']:,} records."
            if meta.get("skipped_blank_rows"):
                notes += f" Skipped {meta['skipped_blank_rows']} blank rows."
            if meta.get("warnings"):
                notes += " " + " ".join(meta["warnings"])
            self.message.setText(notes)

    def _progress(self, done, total, message):
        self.progress.setRange(0, total if total else 0)
        self.progress.setValue(done)
        self.message.setText(message)

    def _auto_repair_changed(self, enabled):
        self.preferences.setValue("auto_glyph_repair", enabled)
        self._schedule_preview()

    def generate_pdf(self):
        self.properties.apply()
        if self.content_invalid:
            self._error("Finish or revert the unfinished edit before generation.")
            return
        if not self._store() or self.production_worker or self.import_worker:
            self._error("Import data or choose generated records in Running sequences before production.")
            return
        output = QFileDialog.getExistingDirectory(self, "Production output folder")
        if output:
            self.start_production(output)

    def start_production(self, output):
        if self.content_invalid or any(getattr(w, "task", "") == "background" for w in self.workers):
            self._error("Finish the content/background operation before generation.")
            return
        if self.font_requests:
            self._error("Wait for the selected font face to finish loading before generation.")
            return
        info = self._store()
        if not info or self.production_worker or self.import_worker:
            return
        from composition.production.model import ProductionJob
        job = ProductionJob(self.template.to_dict(), info["store"], output, auto_repair=self.auto_repair.isChecked())
        self.tabs.setCurrentIndex(3)
        self.production_summary.setPlainText(f"Job {job.job_id}\nInput records: {self.record_count:,}\n"
                                             f"Pages per record: {len(self.template.pages)}\n"
                                             f"Expected pages: {self.record_count * len(self.template.pages):,}\n"
                                             "Composing in an isolated process…")
        self.last_output = ""
        self.open_output_button.setEnabled(False)
        self.last_font_report = ""
        self.open_font_report_button.setEnabled(False)
        self.production_worker = self._worker({"task": "generate", "job": asdict(job)}, self._production_ready)
        self.production_worker.progress.connect(self._progress)
        self._busy()

    def _production_ready(self, result):
        lines = ["Job: " + result["job_id"], "Status: " + result["status"].upper(),
                 f"Input records: {result['input_records']:,}",
                 f"Processed records: {result['processed_records']:,}",
                 f"Successful records: {result['successful_records']:,}",
                 f"Failed records: {result['failed_records']:,}",
                 f"Pages per record: {result.get('pages_per_record', 1)}",
                 f"Expected pages: {result.get('expected_pages', result['input_records']):,}",
                 f"Generated pages: {result['generated_pages']:,}",
                 f"Published files: {result['generated_files']}",
                 "PDF: " + result["output_pdf"], "Reports: " + result["report_dir"]]
        if result["error"]:
            lines.append("Error: " + result["error"])
        lines.extend(result["warnings"])
        scan = result.get("font_scan", {})
        lines.extend([f"Auto font substitution: {result.get('auto_repair', False)}",
                      f"Font scan records: {scan.get('checked_records', 0)}",
                      f"Font scan complete: {scan.get('complete', False)}",
                      f"Substituted characters: {result.get('repaired_glyphs', 0)}",
                      f"Automatic substitutions: {scan.get('automatic_occurrences', 0)}",
                      f"Unresolved characters: {scan.get('unresolved_occurrences', 0)}",
                      "Font substitution report: " + result.get("glyph_repair_report", "")])
        if result.get("rule_summary"):
            rules = result["rule_summary"]
            lines.extend([f"Conditional objects: {rules.get('configured_objects', 0)}",
                          f"Rules checked records: {rules.get('records_checked', 0)}",
                          f"Rules check complete: {rules.get('complete', False)}",
                          f"Hidden object occurrences: {rules.get('hidden_occurrences', 0)}",
                          f"Alternative content occurrences: {rules.get('alternate_occurrences', 0)}"])
        self.production_summary.setPlainText("\n".join(lines))
        self.failed_record = result.get("error_record")
        self._record_font_error(result["error"], result.get("error_record"))
        self.report_button.setEnabled(bool(result["report_dir"]))
        self.last_report_dir = result["report_dir"]
        self.last_output = result["output_pdf"]
        self.last_font_report = result.get("glyph_repair_report", "")
        self.open_font_report_button.setEnabled(bool(self.last_font_report))
        self.open_output_button.setEnabled(bool(self.last_output))
        self.message.setText("Production " + result["status"] + ".")

    def _open_font_report(self):
        if self.last_font_report:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_font_report))

    def _open_output(self):
        if self.last_output:
            if self.project_host:
                self.project_host.open_pdf(self.last_output)
                return
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output))

    def cancel_job(self):
        worker = self.production_worker or self.import_worker
        if worker:
            worker.cancel()
            self.message.setText("Cancelling at the next safe checkpoint…")
            self.cancel_button.setEnabled(False)

    def closeEvent(self, event):
        if self.embedded and not self._close_approved and not self.close_pending:
            event.ignore()
            QTimer.singleShot(0, lambda: self.project_host.close_project(self))
            return
        if self.close_pending:
            if self.workers:
                event.ignore()
                return
        elif not self._close_approved and not self._discard_check():
            event.ignore()
            return
        if not self.embedded:
            self.preferences.setValue("geometry", self.saveGeometry())
        self.preferences.setValue("splitter", self.splitter.saveState())
        self.close_pending = True
        self.preview_timer.stop()
        for worker in self.workers[:]:
            if worker is self.production_worker or worker is self.import_worker:
                worker.cancel()
            else:
                worker.stop_preview()
        if self.workers:
            self.message.setText("Waiting for workers to finish cleanup…")
            event.ignore()
            return
        self.temp.cleanup()
        event.accept()
        self.projectClosed.emit()
