"""Dedicated Print Composition workspace, independent from DocumentSession."""
from __future__ import annotations

import copy
import json
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
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
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from composition.template.model import CompositionError, Element, FontSpec, Template
from composition.template.serializer import load_project

from .canvas import Canvas, FieldList
from .data_dialog import DataDialog
from .process import Worker
from .properties import Properties


class TemplateEdit(QUndoCommand):
    def __init__(self, window, before, after, label, selected=None):
        super().__init__(label)
        self.window, self.before, self.after, self.selected = window, before, after, selected
    def undo(self):
        self.window._apply_template(self.before, self.selected)
    def redo(self):
        self.window._apply_template(self.after, self.selected)


class CompositionWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1240, 820)
        self.setMinimumSize(760, 580)
        self.template = Template()
        self.project_path = None
        self.temp = tempfile.TemporaryDirectory(prefix="pdfdocuedit-composition-")
        self.directory = Path(self.temp.name)
        self.workers = []
        self.preview_worker = self.production_worker = self.import_worker = None
        self.preview_generation = 0
        self.stores = {}
        self.record_count = 0
        self.clipboard = []
        self.close_pending = False
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._title)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(250)
        self.preview_timer.timeout.connect(self._render_preview)
        self._build_ui()
        self._apply_template(self.template.to_dict())
        self.undo.setClean()
        QTimer.singleShot(0, self.canvas.fit_page)

    def _build_ui(self):
        toolbar = QToolBar("Composition")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for label, slot, shortcut in [
            ("New", self.new_project, QKeySequence.StandardKey.New),
            ("Open", self.open_project, QKeySequence.StandardKey.Open),
            ("Save", self.save_project, QKeySequence.StandardKey.Save),
            ("PDF background", self.add_background, None),
        ]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(shortcut)
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action, shortcut in [
            (self.undo.createUndoAction(self, "Undo"), QKeySequence.StandardKey.Undo),
            (self.undo.createRedoAction(self, "Redo"), QKeySequence.StandardKey.Redo),
        ]:
            action.setShortcut(shortcut)
            toolbar.addAction(action)
        for label, kind in [("Text", "text"), ("Image", "image"), ("Line", "line"),
                            ("Box", "rectangle"), ("Code 128", "code128"), ("QR", "qr")]:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, value=kind: self.add_element(value))
            toolbar.addAction(action)
        toolbar.addAction("Page size", self.page_size)
        toolbar.addAction("Fit page", lambda: self.canvas.fit_page())
        menu = self.menuBar().addMenu("Project")
        menu.addAction("Save as…", lambda: self.save_project(save_as=True))
        menu.addAction("Remove background", self.remove_background)
        menu.addAction("Rename template...", self.rename_template)
        edit = self.menuBar().addMenu("Objects")
        for label, name in [("Duplicate", "duplicate"), ("Delete", "delete"),
                            ("Copy", "copy"), ("Paste", "paste")]:
            edit.addAction(label, lambda checked=False, value=name: self.object_command(value))
        edit.addSeparator()
        cjk_action = edit.addAction("Use CJK font for selected text", self.use_cjk_font)
        cjk_action.setToolTip(
            "Apply Noto Sans CJK HK to selected text. Keeps size/bold; clears custom face/italic."
        )
        outer = QWidget()
        layout = QVBoxLayout(outer)
        heading = QLabel("Print Composition")
        heading.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Create production documents using templates and variable data."))
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for name in ("Data", "Template", "Preview", "Production"):
            self.tabs.addTab(name)
        self.tabs.setCurrentIndex(1)
        self.tabs.currentChanged.connect(self._mode_changed)
        layout.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.design_page = QWidget()
        design_layout = QVBoxLayout(self.design_page)
        design_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter()
        self.data_panel = QWidget()
        data_layout = QVBoxLayout(self.data_panel)
        data_layout.addWidget(QLabel("DATA"))
        self.import_button = QPushButton("Import CSV / TXT…")
        self.import_button.clicked.connect(self.import_data)
        data_layout.addWidget(self.import_button)
        self.source_label = QLabel("No data source")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        data_layout.addWidget(self.source_label)
        self.fields = FieldList()
        self.fields.setDragEnabled(True)
        self.fields.itemDoubleClicked.connect(lambda item: self.add_field(item.text(), 20, 20))
        data_layout.addWidget(self.fields)
        help_label = QLabel("Drag a field onto the page. Double-click to add at 20 mm.")
        help_label.setWordWrap(True)
        data_layout.addWidget(help_label)
        self.data_panel.setMinimumWidth(150)
        self.canvas = Canvas()
        self.canvas.setToolTip("Ctrl + mouse wheel: zoom. Hold Space: pan. Arrow keys: move 0.5 mm; Shift: 5 mm.")
        self.canvas.selectionChanged.connect(self._selection)
        self.canvas.editCommitted.connect(lambda before, after: self._commit(before, after, "Move / resize"))
        self.canvas.fieldDropped.connect(self.add_field)
        self.canvas.command.connect(self.object_command)
        self.properties = Properties()
        self.properties.edited.connect(self._property_edit)
        self.properties_scroll = QScrollArea()
        self.properties_scroll.setWidgetResizable(True)
        self.properties_scroll.setWidget(self.properties)
        self.properties_scroll.setMinimumWidth(210)
        self.splitter.addWidget(self.data_panel)
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.properties_scroll)
        self.splitter.setSizes([220, 700, 280])
        design_layout.addWidget(self.splitter)
        self.stack.addWidget(self.design_page)
        self.data_page = QWidget()
        data_layout = QVBoxLayout(self.data_page)
        self.data_summary = QLabel("Import structured data to map fields and preview records.")
        self.data_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.data_summary.setWordWrap(True)
        data_layout.addWidget(self.data_summary)
        import_large = QPushButton("Import / remap data…")
        import_large.clicked.connect(self.import_data)
        data_layout.addWidget(import_large)
        self.sample = QTableWidget()
        self.sample.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        data_layout.addWidget(self.sample)
        self.stack.addWidget(self.data_page)
        self.production_page = QWidget()
        prod_layout = QVBoxLayout(self.production_page)
        prod_layout.addWidget(QLabel("Production: fixed one-record / one-page output"))
        prod_layout.addWidget(QLabel("Source data is an imported snapshot. Critical errors stop the job.\n"
                                    "Only validated, reconciled output is published to a new job folder."))
        self.production_summary = QPlainTextEdit()
        self.production_summary.setReadOnly(True)
        prod_layout.addWidget(self.production_summary)
        self.open_output_button = QPushButton("Open production PDF")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output)
        prod_layout.addWidget(self.open_output_button)
        self.last_output = ""
        self.stack.addWidget(self.production_page)
        layout.addWidget(self.stack, 1)
        self.message = QLabel("")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.message)
        bottom = QHBoxLayout()
        self.previous = QPushButton("◀")
        self.previous.setAccessibleName("Previous record")
        self.previous.clicked.connect(lambda: self.record.setValue(self.record.value()-1))
        self.next = QPushButton("▶")
        self.next.setAccessibleName("Next record")
        self.next.clicked.connect(lambda: self.record.setValue(self.record.value()+1))
        self.record = QSpinBox()
        self.record.setRange(1, 1)
        self.record.valueChanged.connect(self._schedule_preview)
        self.record_label = QLabel("Record / 0")
        for widget in (self.previous, self.record, self.next, self.record_label):
            bottom.addWidget(widget)
        bottom.addStretch()
        self.generate_button = QPushButton("Generate Production PDF")
        self.generate_button.setProperty("primary", True)
        self.generate_button.clicked.connect(self.generate_pdf)
        bottom.addWidget(self.generate_button)
        layout.addLayout(bottom)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel job")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_job)
        progress_row.addWidget(self.progress)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
        self.setCentralWidget(outer)

    def _title(self, *args):
        name = self.project_path.name if self.project_path else self.template.name
        self.setWindowTitle(f"{'* ' if not self.undo.isClean() else ''}{name} — Print Composition")

    def _worker(self, request, result, failure=None):
        worker = Worker(self.directory, request, self)
        self.workers.append(worker)
        worker.resultReady.connect(result)
        worker.failed.connect(failure or self._error)
        worker.ended.connect(lambda: self._worker_ended(worker))
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
        return self.stores.get(self._config_key())

    def _apply_template(self, value, selected=None):
        self.template = Template.from_dict(value)
        self.canvas.set_template(self.template, selected)
        selected_ids = selected if isinstance(selected, list) else [selected]
        self._selection(selected_ids[0] if len(selected_ids) == 1 else "")
        self._refresh_data()
        self._title()
        self._schedule_preview()

    def _commit(self, before, after, label, selected=None):
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
        self.undo.push(TemplateEdit(self, before, after, label, selected))

    def _selection(self, selected):
        element = next((e for e in self.template.elements if e.id == selected), None)
        self.properties.show_element(element)

    def _property_edit(self, values):
        if not self.properties.element:
            return
        before = self.template.to_dict()
        after = copy.deepcopy(before)
        selected = self.properties.element.id
        for element in after["elements"]:
            if element["id"] == selected:
                element.update(values)
        self._commit(before, after, "Edit object properties", selected)

    def _refresh_data(self):
        info = self._store()
        self.fields.clear()
        self.record_count = info["metadata"]["record_count"] if info else 0
        self.record.blockSignals(True)
        self.record.setRange(1, max(1, self.record_count))
        self.record.blockSignals(False)
        self.record_label.setText(f"Record / {self.record_count:,}")
        self.previous.setEnabled(self.record_count > 1)
        self.next.setEnabled(self.record_count > 1)
        if info:
            meta = info["metadata"]
            self.fields.addItems(meta["fields"])
            for index, original in enumerate(meta["original_fields"]):
                self.fields.item(index).setToolTip(f"Original: {original}")
            self.source_label.setText(Path(self.template.data.path).name + f"\n{self.record_count:,} records")
            self.data_summary.setText(f"{self.template.data.path}\n{self.record_count:,} records · "
                                      "Imported snapshot; re-import to apply source changes.")
            self.sample.setColumnCount(len(meta["fields"]))
            self.sample.setHorizontalHeaderLabels(meta["fields"])
            self.sample.setRowCount(len(info["sample"]))
            for row, record in enumerate(info["sample"]):
                for column, name in enumerate(meta["fields"]):
                    self.sample.setItem(row, column, QTableWidgetItem(record[name]))
        else:
            self.source_label.setText("Import data" if not self.template.data.path else
                                      "Data source needs importing:\n" + self.template.data.path)
            self.data_summary.setText("Import the data source to preview and generate this project.")
            self.sample.setRowCount(0)
        self._busy()

    def _busy(self):
        busy = bool(self.import_worker or self.production_worker)
        self.generate_button.setEnabled(bool(self._store()) and not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)

    def _mode_changed(self, index):
        self.stack.setCurrentIndex(1 if index == 0 else 2 if index == 3 else 0)
        self.canvas.set_preview_mode(index == 2)
        self.properties_scroll.setVisible(index != 2)
        self._schedule_preview()

    def _schedule_preview(self, *args):
        self.preview_generation += 1
        self.canvas.set_preview(None)
        self.preview_timer.start()

    def _render_preview(self):
        if self.close_pending or self.tabs.currentIndex() not in (1, 2):
            return
        if self.preview_worker and self.preview_worker in self.workers:
            self.preview_worker.stop_preview()
        generation = self.preview_generation
        info = self._store() if self.tabs.currentIndex() == 2 else None
        if self.tabs.currentIndex() == 2 and not info:
            self._error("Import data before previewing records.")
            return
        request = {"task": "preview", "template": self.template.to_dict(),
                   "record": self.record.value(), "store": info["store"] if info else "",
                   "target": str(self.directory / f"preview-{generation}.pdf")}
        self.preview_worker = self._worker(request,
            lambda result: self._preview_ready(result, generation),
            lambda error: self._preview_error(error, generation))

    def _preview_ready(self, result, generation):
        if generation == self.preview_generation:
            self.canvas.set_preview(result["image"])
            self.message.setText("")
        Path(result["pdf"]).unlink(missing_ok=True)
        Path(result["image"]).unlink(missing_ok=True)

    def _preview_error(self, error, generation):
        if generation == self.preview_generation:
            self._error(error)

    def add_element(self, kind="text", value=None, x=20, y=20, font=None):
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
        elif kind == "code128":
            element.value, element.width_mm, element.height_mm = value or "000123456", 100, 20
        elif kind == "qr":
            element.value, element.width_mm, element.height_mm = value or "https://example.com", 40, 40
        element.width_mm = min(element.width_mm, self.template.width_mm)
        element.height_mm = min(element.height_mm, self.template.height_mm)
        element.x_mm = min(max(0, x), self.template.width_mm-element.width_mm)
        element.y_mm = min(max(0, y), self.template.height_mm-element.height_mm)
        before = self.template.to_dict()
        after = copy.deepcopy(before)
        after["elements"].append(asdict(element))
        self._commit(before, after, "Add " + kind, element.id)

    def add_field(self, name, x, y):
        self.add_element("text", "{{" + name + "}}", x, y,
                         font=FontSpec(family="Noto Sans CJK HK"))

    def use_cjk_font(self):
        self.properties.apply()
        selected = self.canvas.selected_ids()
        before, after = self.template.to_dict(), self.template.to_dict()
        changed = 0
        for element in after["elements"]:
            if element["id"] in selected and element["type"] == "text":
                element["font"].update(family="Noto Sans CJK HK", file="", italic=False)
                changed += 1
        if not changed:
            self.message.setText("Select one or more text objects to apply the CJK font.")
            return
        self._commit(before, after, "Use CJK font for selected text", selected)
        self.message.setText(f"Noto Sans CJK HK applied to {changed} selected text object(s).")


    def object_command(self, command):
        selected = set(self.canvas.selected_ids())
        if command == "copy":
            self.clipboard = [asdict(e) for e in self.template.elements if e.id in selected]
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        if command == "delete":
            after["elements"] = [e for e in after["elements"] if e["id"] not in selected]
        elif command in {"paste", "duplicate"}:
            source = (self.clipboard if command == "paste" else
                      [asdict(e) for e in self.template.elements if e.id in selected])
            for element in copy.deepcopy(source):
                element["id"] = uuid.uuid4().hex
                element["x_mm"] = min(self.template.width_mm-element["width_mm"], element["x_mm"]+3)
                element["y_mm"] = min(self.template.height_mm-element["height_mm"], element["y_mm"]+3)
                after["elements"].append(element)
        self._commit(before, after, command.title())

    def _discard_check(self):
        self.properties.apply()
        if self.undo.isClean():
            return True
        answer = QMessageBox.question(self, "Unsaved composition", "Save changes to this project?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before replacing the project.")
            return
        if self._discard_check():
            self.project_path = None
            self.stores.clear()
            self.undo.clear()
            self._apply_template(Template().to_dict())
            self.tabs.setCurrentIndex(1)
            self.canvas.fit_page()
            self.undo.setClean()

    def open_project(self):
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before replacing the project.")
            return
        if not self._discard_check():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open composition", "", "Composition (*.pdcx)")
        if not path:
            return
        try:
            template = load_project(path)
        except (OSError, CompositionError, ValueError) as exc:
            self._error(str(exc))
            return
        self.stores.clear()
        self.project_path = Path(path)
        self.undo.clear()
        self._apply_template(template.to_dict())
        self.undo.setClean()
        self.tabs.setCurrentIndex(1)
        self.canvas.fit_page()
        if template.data.path:
            if Path(template.data.path).is_file():
                self._start_import(template.data)
            elif QMessageBox.question(self, "Data source not found", "Data source not found. Locate File?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.import_data()

    def save_project(self, checked=False, save_as=False):
        self.properties.apply()
        path = str(self.project_path) if self.project_path and not save_as else ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save composition", "", "Composition (*.pdcx)")
        if not path:
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
        self.message.setText("Project saved: " + str(self.project_path))
        return True

    def rename_template(self):
        name, ok = QInputDialog.getText(self, "Template name", "Name", text=self.template.name)
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
            width, ok = QInputDialog.getDouble(self, "Custom page", "Width (mm)", self.template.width_mm, 10, 2000, 2)
            if not ok:
                return
            height, ok = QInputDialog.getDouble(self, "Custom page", "Height (mm)", self.template.height_mm, 10, 2000, 2)
            if not ok:
                return
        else:
            width, height = sizes[size]
        before, after = self.template.to_dict(), self.template.to_dict()
        after.update(width_mm=width, height_mm=height)
        self._commit(before, after, "Change page size")
        self.canvas.fit_page()

    def add_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Use PDF page as static background", "", "PDF (*.pdf)")
        if not path:
            return
        page, ok = QInputDialog.getInt(self, "Background page", "Source page (one-based)", 1, 1, 1000000)
        if not ok:
            return
        self._worker({"task": "background", "source": path, "page": page-1,
                      "target": str(self.directory / f"background-{uuid.uuid4().hex}.pdf")},
                     self._background_ready)

    def _background_ready(self, result):
        before, after = self.template.to_dict(), self.template.to_dict()
        after.update(background=result["background"], width_mm=result["width_mm"], height_mm=result["height_mm"])
        self._commit(before, after, "Use PDF background")
        self.canvas.fit_page()

    def remove_background(self):
        before, after = self.template.to_dict(), self.template.to_dict()
        after["background"] = ""
        self._commit(before, after, "Remove background")

    def import_data(self):
        if self.import_worker or self.production_worker:
            self._error("Finish or cancel the active job before importing another source.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import data", self.template.data.path,
                                             "Structured data (*.csv *.txt *.tsv);;All files (*)")
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
        self._commit(before, after, "Import data")
        self._refresh_data()
        self._schedule_preview()
        self.message.setText(f"Imported {result['metadata']['record_count']:,} records.")

    def _progress(self, done, total, message):
        self.progress.setRange(0, total if total else 0)
        self.progress.setValue(done)
        self.message.setText(message)

    def generate_pdf(self):
        self.properties.apply()
        if not self._store() or self.production_worker or self.import_worker:
            self._error("Import data before production.")
            return
        output = QFileDialog.getExistingDirectory(self, "Production output folder")
        if output:
            self.start_production(output)

    def start_production(self, output):
        info = self._store()
        if not info or self.production_worker or self.import_worker:
            return
        from composition.production.model import ProductionJob
        job = ProductionJob(self.template.to_dict(), info["store"], output)
        self.tabs.setCurrentIndex(3)
        self.production_summary.setPlainText(f"Job {job.job_id}\nInput records: {self.record_count:,}\n"
                                             "Composing in an isolated process…")
        self.last_output = ""
        self.open_output_button.setEnabled(False)
        self.production_worker = self._worker({"task": "generate", "job": asdict(job)}, self._production_ready)
        self.production_worker.progress.connect(self._progress)
        self._busy()

    def _production_ready(self, result):
        lines = ["Job: " + result["job_id"], "Status: " + result["status"].upper(),
                 f"Input records: {result['input_records']:,}",
                 f"Processed records: {result['processed_records']:,}",
                 f"Successful records: {result['successful_records']:,}",
                 f"Failed records: {result['failed_records']:,}",
                 f"Generated pages: {result['generated_pages']:,}",
                 f"Published files: {result['generated_files']}",
                 "PDF: " + result["output_pdf"], "Reports: " + result["report_dir"]]
        if result["error"]:
            lines.append("Error: " + result["error"])
        lines.extend(result["warnings"])
        self.production_summary.setPlainText("\n".join(lines))
        self.last_output = result["output_pdf"]
        self.open_output_button.setEnabled(bool(self.last_output))
        self.message.setText("Production " + result["status"] + ".")

    def _open_output(self):
        if self.last_output:
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
        if self.close_pending:
            if self.workers:
                event.ignore()
                return
        elif not self._discard_check():
            event.ignore()
            return
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
