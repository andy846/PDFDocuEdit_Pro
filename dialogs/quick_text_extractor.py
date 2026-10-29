"""Quick extraction UI composed from the existing visual region editor."""
from __future__ import annotations

import copy
import random
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from composition.designer.process import Worker
from core.diagnostics import log_failure
from core.pdf_engine import parse_page_range
from core.text_extraction import signature
from dialogs.base import remember_save_directory, start_in_save_directory
from workflow.extraction import ExtractionSpec, Region
from workflow.regions_ui import RegionEditor

from .extraction_canvas import ExtractionCanvas
from .extraction_workbench import ExtractionWorkbench


class ExtractionHost(QWidget):
    """One current and one latest pending preview; all I/O stays in workers."""
    def __init__(self, parent=None, temporary=None):
        super().__init__(parent)
        self.temporary = temporary or tempfile.TemporaryDirectory(prefix="pdfdocuedit-extract-")
        self.directory = Path(self.temporary.name)
        self.workers = []
        self.active = None
        self.preview_worker = None
        self.pending = None
        self.dialog = None
        self.closing = False
        self.released = False

    def request(self, request, callback, *, preview=False, on_finished=None):
        if self.closing:
            return None
        preview_token = request.get("_preview_token", self.dialog.token) if preview else None
        if preview and (self.preview_worker or self.active):
            # A dropped page/zoom preview may be the only request carrying a
            # raster. The newest field-only request must not keep the old page.
            self.pending = ({**request, "raster": True, "_preview_token": preview_token}, callback)
            if self.preview_worker:
                self.preview_worker.superseded = True
                self.preview_worker.stop_preview()
            return None
        if not preview and self.active:
            return None
        worker = Worker(self.directory, {"task": "quick_extract", **request}, self)
        worker.superseded = False
        worker.cancel_requested = False
        worker.is_preview = preview
        self.workers.append(worker)
        if preview:
            self.preview_worker = worker
        else:
            self.active = worker
            if self.preview_worker:
                self.preview_worker.superseded = True
                self.preview_worker.stop_preview()
        delivered, errors = [], []
        worker.resultReady.connect(delivered.append)
        worker.failed.connect(errors.append)
        worker.progress.connect(self.progress)

        def ended():
            self.workers.remove(worker)
            if self.active is worker:
                self.active = None
            if self.preview_worker is worker:
                self.preview_worker = None
            try:
                # A committed export remains a completed export even on late Cancel.
                committed = delivered and delivered[0].get("committed")
                if committed:
                    self.dialog.last_output = committed
                current = not preview or preview_token == self.dialog.token
                if not self.closing and not worker.superseded and current:
                    if delivered and (not worker.cancel_requested or committed):
                        callback(delivered[0])
                        if preview:
                            if request.get("raster"):
                                self.dialog.raster_page = request["page"]
                            self.dialog.preview_text(delivered[0])
                    elif worker.cancel_requested:
                        self.dialog.status.setText("Cancelled; previous output files are unchanged.")
                        if request.get("operation") == "scan":
                            self.dialog.result_state.setText("Cancelled")
                    elif errors:
                        self.dialog.status.setText(errors[0])
                        if request.get("operation") == "scan":
                            self.dialog.result_state.setText("Extraction failed")
            except Exception as exc:
                log_failure("Quick extraction callback failed")
                if not self.closing:
                    self.dialog.status.setText(f"Cannot update extraction ({type(exc).__name__}); see diagnostics.")
            finally:
                if preview and request.get("target"):
                    target = Path(request["target"]).resolve()
                    if target.is_relative_to(self.directory.resolve()):
                        target.unlink(missing_ok=True)
                if on_finished:
                    on_finished()
                self.dialog.sync_actions()
                if self.closing:
                    self.finish_close()
                elif self.pending and not self.preview_worker and not self.active:
                    next_request, next_callback = self.pending
                    self.pending = None
                    self.request(next_request, next_callback, preview=True)
        worker.ended.connect(ended)
        if self.dialog:
            self.dialog.sync_actions()
        return worker

    def progress(self, current, total, text):
        if not self.closing:
            self.dialog.progress.setRange(0, total)
            self.dialog.progress.setValue(current)
            self.dialog.status.setText(text)

    def cancel(self):
        self.pending = None
        for worker in self.workers:
            worker.cancel_requested = True
            if worker.is_preview:
                worker.stop_preview()
            else:
                worker.cancel()

    def finish_close(self):
        if not self.workers:
            try:
                self.temporary.cleanup()
            except OSError:
                log_failure("Cannot release extraction temporary directory")
                self.dialog.status.setText("Cannot release temporary files; close applications holding them, then press Close to retry.")
                return
            self.released = True
            self.dialog.closed = True
            QDialog.reject(self.dialog)


class ExtractionTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.fields = [], []

    def replace(self, rows, fields):
        self.beginResetModel()
        self.rows, self.fields = rows, fields
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.fields)+3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self.rows[index.row()]
        values = [str(row["page"]), row["status"], row["issues"], *[row["values"].get(f, "") for f in self.fields]]
        return values[index.column()]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ["Source Page", "Status", "Issues", *self.fields][section]
        return super().headerData(section, orientation, role)


class QuickTextExtractorDialog(ExtractionWorkbench, RegionEditor):
    def __init__(self, source, current_page, suggested, parent=None, *, spec=None,
                 temporary=None, protected=(), handoff=None, page_count=None, source_guard=None):
        host = ExtractionHost(parent, temporary)
        self._ui_ready = False
        self._applied_regions = []
        self._cached_preview = None
        self.raster_page = None
        self.draw_mode = False
        self.show_all_regions = True
        self.result = None
        self.last_output = None
        self.protected = [str(p) for p in protected]
        self.handoff = handoff
        self.offset = 0
        self.suggested = suggested
        self.scan_signature = None
        self.results_current = False
        self.source_guard = source_guard
        self.source_stale = False
        super().__init__(host, str(source), spec or {"version": 1, "regions": []}, current_page+1,
                         canvas_type=ExtractionCanvas, empty_draft=True)
        host.dialog = self
        # Production callers provide captured metadata; standalone callers wait
        # for the first worker preview instead of guessing a million pages.
        self.source_ready = False
        if page_count is not None:
            self.page.setMaximum(page_count)
        self.setWindowTitle("Extract Text Regions · PDFDocuEdit Pro")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.timer.setInterval(250)
        self.setup_workbench()
        self.results_page = QWidget()
        results_layout = QVBoxLayout(self.results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_header = QWidget()
        result_tools = QHBoxLayout(self.results_header)
        result_tools.setContentsMargins(0, 0, 0, 0)
        result_tools.addWidget(QLabel("Results"))
        self.result_state = QLabel("Not extracted")
        result_tools.addWidget(self.result_state)
        result_tools.addStretch()
        self.result_focus_button = QPushButton("Expand")
        self.result_focus_button.clicked.connect(self.focus_results)
        self.collapse_button = QPushButton("Hide table")
        self.collapse_button.clicked.connect(self.collapse_results)
        result_tools.addWidget(self.result_focus_button)
        result_tools.addWidget(self.collapse_button)
        results_layout.addWidget(self.results_header)
        self.model = ExtractionTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setWordWrap(False)
        self.table.clicked.connect(self.navigate_result)
        results_layout.addWidget(self.table, 1)
        self.navigation = QWidget()
        navigation = QHBoxLayout(self.navigation)
        navigation.setContentsMargins(0, 0, 0, 0)
        self.previous = QPushButton("Previous 100")
        self.next = QPushButton("Next 100")
        self.previous.clicked.connect(lambda: self.load_rows(max(0, self.offset-100)))
        self.next.clicked.connect(lambda: self.load_rows(self.offset+100))
        self.page_label = QLabel("No extraction yet")
        for control in (self.previous, self.page_label, self.next):
            navigation.addWidget(control)
        results_layout.addWidget(self.navigation)
        self.selection_row = QWidget()
        selection = QHBoxLayout(self.selection_row)
        selection.setContentsMargins(0, 0, 0, 0)
        self.page_mode = QComboBox()
        self.page_mode.addItems(["All pages", "Current preview page", "Custom pages"])
        self.page_range = QLineEdit()
        self.page_range.setPlaceholderText("Pages: 1,3,5-8")
        self.page_range.setEnabled(False)
        self.page_range.hide()
        self.sample_mode = QComboBox()
        self.sample_mode.addItems(["All selected", "First 10", "First 50", "Random 50"])
        self.sample_mode.setCurrentIndex(1)
        self.sample_mode.setMaximumWidth(110)
        self.sample_button = QPushButton("Try 10 pages")
        self.sample_button.setToolTip("Optional trial to check fields. Extract & Export Excel always uses the complete selected page range.")
        self.sample_mode.currentIndexChanged.connect(self.update_sample_label)
        self.sample_button.clicked.connect(lambda: self.start_scan(sample=True))
        selection.addWidget(self.page_mode)
        selection.addWidget(self.page_range, 1)
        selection.addWidget(self.sample_mode)
        selection.addWidget(self.sample_button)
        results_layout.insertWidget(1, self.selection_row)
        self.status = QLabel("Trial is optional. Extract & Export Excel processes the complete selected page range.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(8)
        self.progress.setTextVisible(False)
        self.action_bar = QWidget()
        actions = QHBoxLayout(self.action_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        self.extract_button = QPushButton("Extract only")
        self.export_button = QPushButton("Export complete results…")
        self.extract_export_button = QPushButton("Extract && Export Excel…")
        self.extract_export_button.setObjectName("primary")
        self.extract_export_button.setProperty("primary", True)
        self.extract_export_button.setAutoDefault(False)
        self.extract_export_button.clicked.connect(self.extract_and_export)
        self.workflow_button = QPushButton("Open in Visual Workflow")
        self.cancel_button = QPushButton("Cancel task")
        self.close_button = QPushButton("Close")
        self.extract_button.clicked.connect(lambda: self.start_scan())
        self.export_button.clicked.connect(self.choose_export)
        self.workflow_button.clicked.connect(self.open_workflow)
        self.cancel_button.clicked.connect(host.cancel)
        self.close_button.clicked.connect(self.reject)
        self.more_button = QPushButton("More")
        more = QMenu(self.more_button)
        self.more_actions = []
        for button in (self.extract_button, self.export_button, self.workflow_button):
            button.setParent(self)
            button.hide()
            action = more.addAction(button.text(), button.click)
            self.more_actions.append((action, button))
        self.more_button.setMenu(more)
        for button in (self.more_button, self.extract_export_button, self.cancel_button, self.close_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.page_mode.currentIndexChanged.connect(self.page_mode_changed)
        self.page_range.textChanged.connect(self.invalidate_results)
        self.page.valueChanged.connect(self.selection_changed)
        self.undo.indexChanged.connect(self.invalidate_results)
        self.source_timer = QTimer(self)
        self.source_timer.setInterval(500)
        self.source_timer.timeout.connect(self.check_source)
        self.source_timer.start()
        self._ui_ready = True
        self.finish_workbench()
        self.sync_actions()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "wide"):
            self.arrange()

    def changeEvent(self, event):
        super().changeEvent(event)
        if self._ui_ready and event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                                               QEvent.Type.StyleChange):
            self.view.render_regions()
            self.arrange()

    def controls_state(self):
        return (self.name.text(), *(spin.value() for spin in self.region), self.scope.currentData(),
                self.role.value(), self.policy.currentIndex(), self.format.currentText(), self.required.isChecked(),
                self.trim.isChecked(), self.join.isChecked(), self.label.text(), self.minimum.value(), self.maximum.value())

    def selection_updated(self):
        self._display_controls = self.controls_state()
        if self._ui_ready:
            if self._cached_preview:
                self.preview_text(self._cached_preview)
            else:
                self.preview_details.clear()

    def save_controls(self, *_):
        if not self.loading_controls and self.regions and self.controls_state() != getattr(self, "_display_controls", None):
            super().save_controls()

    def apply_regions(self, regions):
        changed = regions != self._applied_regions
        self._applied_regions = copy.deepcopy(regions)
        super().apply_regions(regions)
        for index, region in enumerate(self.regions):
            item = self.list.item(index)
            item.setText(f"{index+1:02d} · {region['name']}")
            item.setToolTip(f"{index+1:02d} · {region['name']}")
        self.view.render_regions()
        if self._ui_ready:
            if not self.regions:
                self.preview_details.clear()
            if changed:
                self.invalidate_results()
                self.schedule()
            self.sync_actions()

    def other_boxes(self):
        self.view.render_regions()

    def add(self):
        if self.draw_mode:
            self.cancel_add(refresh=True)
            return
        if len(self.regions) >= 200 or not self.source_ready or self.host.active:
            return
        if self.raster_page != self.page.value():
            self.schedule(True)
            self.status.setText("Wait for this page's PDF preview before drawing a new region.")
            return
        self.timer.stop()
        self.token += 1
        self.host.pending = None
        if self.host.preview_worker:
            self.raster_needed = True
            self.host.preview_worker.superseded = True
            self.host.preview_worker.stop_preview()
        self.draw_mode = True
        self.add_button.setText("Cancel new region")
        self.view.setCursor(Qt.CursorShape.CrossCursor)
        self.status.setText("Drag on the PDF to create a new field. Esc cancels without changing existing fields.")
        self.sync_actions()

    def cancel_add(self, *, refresh=False):
        self.draw_mode = False
        self.view.cancel_draft()
        self.view.setCursor(Qt.CursorShape.ArrowCursor)
        if hasattr(self, "add_button"):
            self.add_button.setText("New region")
        if self._ui_ready:
            self.sync_actions()
            if refresh and self.regions and self._cached_preview is None:
                self.schedule()

    def finish_add(self, rect):
        before = copy.deepcopy(self.regions)
        names = {r["name"] for r in self.regions}
        number = 1
        while f"Field_{number}" in names:
            number += 1
        region = Region(name=f"Field_{number}", x_mm=rect.x(), y_mm=rect.y(), width_mm=rect.width(),
                        height_mm=rect.height(), page_width_mm=self.geometry[0], page_height_mm=self.geometry[1])
        region.validate()
        self.regions.append(asdict(region))
        self.current = len(self.regions)-1
        self.cancel_add()
        self.push(before, "Draw extraction region")

    def duplicate(self):
        if not self.regions or len(self.regions) >= 200:
            return
        before = copy.deepcopy(self.regions)
        source = copy.deepcopy(before[self.current])
        base = source["name"][:54]
        names = {r["name"] for r in before}
        number, name = 1, base+"_copy"
        while name in names:
            number += 1
            name = base+"_copy"+str(number)
        source["name"] = name
        x, y = source["x_mm"], source["y_mm"]
        def shifted(delta):
            return (max(0, min(x+delta, source["page_width_mm"]-source["width_mm"])),
                    max(0, min(y+delta, source["page_height_mm"]-source["height_mm"])))
        moved = shifted(5)
        if moved == (x, y):
            moved = shifted(-5)
        source["x_mm"], source["y_mm"] = moved
        self.regions.append(source)
        self.current = len(self.regions)-1
        self.push(before, "Duplicate extraction region")

    def delete(self):
        if not self.regions:
            return
        before = copy.deepcopy(self.regions)
        self.regions.pop(self.current)
        self.push(before, "Delete extraction region")

    def keyPressEvent(self, event):
        if self.draw_mode and event.key() == Qt.Key.Key_Escape:
            self.cancel_add(refresh=True)
            event.accept()
        else:
            super().keyPressEvent(event)

    def navigate_result(self, index):
        if not index.isValid() or not self.results_current or self.host.active or not self.check_source():
            return
        self.page.setValue(self.model.rows[index.row()]["page"])
        if index.column() >= 3:
            field = self.model.fields[index.column()-3]
            for row, region in enumerate(self.regions):
                if region["name"] == field:
                    self.list.setCurrentRow(row)
                    break

    def config(self):
        if not self.check_source():
            raise ValueError("Source PDF changed or closed; close this tool and capture its current revision again.")
        if not self.regions:
            raise ValueError("Use New region, then drag on the PDF to create a field.")
        self.save_controls()
        return ExtractionSpec.from_dict({"regions": self.regions, "version": 1})

    def check_source(self):
        if self.source_guard and not self.source_guard():
            self.source_stale = True
            self.result_state.setText("Source changed")
            self.scan_signature = None
            self.results_current = False
            self.status.setText("Source PDF changed or closed; close this tool and capture its current revision again.")
            self.sync_actions()
        return not self.source_stale

    def selected_pages(self):
        if self.page_mode.currentIndex() == 1:
            return [self.page.value()-1]
        if self.page_mode.currentIndex() == 2:
            return parse_page_range(self.page_range.text(), self.page.maximum())
        return list(range(self.page.maximum()))

    def selection_changed(self, *_):
        self.page_range.setVisible(self.page_mode.currentIndex() == 2)
        self.page_range.setEnabled(self.page_mode.currentIndex() == 2 and not self.host.active)
        if self.page_mode.currentIndex() == 1:
            self.invalidate_results()

    def page_mode_changed(self, *_):
        self.selection_changed()
        self.invalidate_results()

    def invalidate_results(self, *_):
        if self.result:
            self.status.setText("Results are stale; extract selected pages again before exporting.")
            self.result_state.setText("Out of date")
        self.scan_signature = None
        self.results_current = False
        self.sync_actions()

    def sync_actions(self):
        if not hasattr(self, "extract_button"):
            return
        busy = self.host.active is not None or self.host.closing
        self.editor_page.setEnabled(not busy)
        self.view.setEnabled(not busy)
        self.page.setEnabled(not busy)
        self.inspector.setEnabled(bool(self.regions))
        self.add_button.setEnabled(not busy and self.source_ready and (self.draw_mode or len(self.regions) < 200))
        for button in (self.duplicate_button, self.delete_button):
            button.setEnabled(not busy and bool(self.regions) and not self.draw_mode)
        self.page_mode.setEnabled(not busy)
        self.page_range.setEnabled(not busy and self.page_mode.currentIndex() == 2)
        self.sample_button.setEnabled(not busy and self.source_ready and bool(self.regions) and not self.draw_mode and not self.source_stale)
        self.sample_mode.setEnabled(not busy)
        self.extract_button.setEnabled(not busy and self.source_ready and bool(self.regions) and not self.draw_mode and not self.source_stale)
        self.extract_export_button.setEnabled(self.extract_button.isEnabled())
        self.export_button.setEnabled(not busy and not self.source_stale and self.result is not None and self.scan_signature is not None)
        self.workflow_button.setEnabled(not busy and bool(self.regions) and not self.draw_mode and not self.source_stale and self.source_ready and self.handoff is not None)
        self.cancel_button.setEnabled(bool(self.host.workers) and not self.host.closing)
        self.previous.setEnabled(not busy and self.offset > 0 and self.result is not None)
        self.next.setEnabled(not busy and self.result is not None and self.offset+100 < self.result["pages"])
        for action, button in self.more_actions:
            action.setEnabled(button.isEnabled())

    def preview_text(self, result):
        self._cached_preview = result
        self.source_ready = True
        cells = result.get("cells", [])
        def display(value):
            return value[:4000] + ("\n[Preview shortened; full value is retained in export]" if len(value) > 4000 else "")
        if self.current < len(cells):
            cell = cells[self.current]
            self.preview_details.setPlainText(f'{cell["field"]}\nRaw: {display(cell["raw"])}\nClean: {display(cell["value"])}\n'
                                              + (cell["issue"] or "Extracted (not reviewed)"))
        else:
            self.preview_details.clear()
        if result.get("validation_error"):
            self.status.setText(result["validation_error"])
        self.sync_actions()

    def schedule(self, raster=False):
        self._cached_preview = None
        if hasattr(self, "preview_details"):
            self.preview_details.clear()
            self.sample.clear()
        super().schedule(raster)

    def preview(self):
        if self.host.active or self.host.preview_worker:
            # RegionEditor captures this flag in its callback. Set it before
            # constructing that callback, not only in the queued request.
            self.raster_needed = True
        super().preview()

    def update_sample_label(self, *_):
        self.sample_button.setText(["Try selected", "Try 10 pages", "Try 50 pages", "Try random 50"][self.sample_mode.currentIndex()])

    def extract_and_export(self):
        if self.host.active or self.host.closing or self.draw_mode or not self.source_ready:
            return
        try:
            identity = signature(self.config(), self.selected_pages())
            if self.results_current and self.result and self.scan_signature == identity:
                self.choose_export(excel_only=True)
            else:
                self.start_scan(on_ready=lambda: self.choose_export(excel_only=True))
        except ValueError as exc:
            self.status.setText(str(exc))

    def start_scan(self, *, sample=False, on_ready=None):
        if self.host.active or self.host.closing or self.draw_mode:
            return
        if not self.source_ready:
            self.status.setText("Wait for the first PDF preview before extracting.")
            return
        try:
            spec, pages = self.config(), self.selected_pages()
            identity = signature(spec, pages)
            if sample:
                mode = self.sample_mode.currentIndex()
                pages = sorted(random.sample(pages, min(50, len(pages)))) if mode == 3 else pages[:10 if mode == 1 else 50] if mode else pages
            self.status.setText("Extracting sample…" if sample else "Extracting selected pages…")
            self.result_state.setText("Trying sample…" if sample else "Extracting…")
            self.scan_signature = None
            self.results_current = False
            target = self.host.directory/(uuid.uuid4().hex+".sqlite")
            def ready(result):
                self.result = result
                self.results_current = True
                self.scan_signature = None if sample else identity
                self.result_state.setText(f'Sample · {result["pages"]:,} / {len(self.selected_pages()):,}' if sample else f'Complete · {result["pages"]:,} pages')
                self.status.setText(f'{"Sample" if sample else "Extraction"}: {result["pages"]:,} pages · {result["issues"]:,} field issues. Review before use.')
                self.load_rows(0, on_ready=on_ready)
                self.sync_actions()
            self.host.request({"operation": "scan", "source": self.source, "pages": pages,
                               "extraction": spec.to_dict(), "target": str(target), "protected": self.protected}, ready)
        except ValueError as exc:
            self.status.setText(str(exc))

    def load_rows(self, offset, *, on_ready=None):
        if not self.result:
            return
        self.offset = offset
        database = self.result["database"]
        def ready(result):
            if self.result and self.result["database"] == database:
                self.model.replace(result["rows"], result["fields"])
                total = self.result["pages"]
                self.page_label.setText(f"{offset+1}–{min(offset+100, total)} / {total:,}")
                if on_ready:
                    on_ready()
        self.host.request({"operation": "rows", "database": database, "offset": offset}, ready)

    def choose_export(self, *, excel_only=False):
        if self.host.active or self.host.closing:
            return
        try:
            if not self.results_current or not self.result or self.scan_signature != signature(self.config(), self.selected_pages()):
                raise ValueError("Complete results are not current; use Extract & Export Excel to extract all selected pages.")
            suggested = str(Path(self.suggested).with_suffix(".xlsx")) if excel_only else self.suggested
            filters = "Excel workbook (*.xlsx)" if excel_only else "Excel workbook (*.xlsx);;CSV (*.csv);;Plain text (*.txt)"
            path, _ = QFileDialog.getSaveFileName(self, "Export extracted text", start_in_save_directory(self, suggested), filters)
            if path:
                if excel_only and Path(path).suffix.lower() != ".xlsx":
                    raise ValueError("Use .xlsx for Excel. Other formats are available under More → Export complete results.")
                # The native save dialog owns explicit overwrite confirmation.
                remember_save_directory(self, path)
                self.export_to(path, overwrite=Path(path).exists())
            else:
                self.status.setText("Save cancelled; complete extraction results are retained.")
        except ValueError as exc:
            self.status.setText(str(exc))

    def export_to(self, target, *, overwrite=False):
        try:
            spec, pages = self.config(), self.selected_pages()
            if not self.result or self.scan_signature != signature(spec, pages):
                raise ValueError("Results are stale; extract selected pages before exporting.")
            if Path(target).suffix.lower() == ".csv":
                self.status.setText("CSV protects formula-like text. Import identifier columns as Text in Excel; use XLSX to preserve zeros automatically.")
            self.host.request({"operation": "export", "database": self.result["database"], "source": self.source,
                               "extraction": spec.to_dict(), "pages": pages, "target": str(target), "overwrite": overwrite},
                              lambda result: self.status.setText("Exported: " + result["committed"]))
        except ValueError as exc:
            self.status.setText(str(exc))

    def open_workflow(self):
        try:
            self.handoff(self, self.config(), self.selected_pages())
        except ValueError as exc:
            self.status.setText(str(exc))

    def accept(self):
        # Enter must never accept the base editor and destroy an active job.
        self.start_scan()

    def reject(self):
        if not self.host.closing:
            self.save_workbench()
            self.cancel_add()
            self.host.closing = True
            self.closed = True
            self.timer.stop()
            self.source_timer.stop()
            self.host.cancel()
            self.status.setText("Waiting for the extraction worker to release temporary files…")
            self.sync_actions()
        self.host.finish_close()

    def closeEvent(self, event):
        self.reject()
        event.setAccepted(self.host.released)
