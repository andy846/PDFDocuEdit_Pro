"""Quick extraction UI composed from the existing visual region editor."""
from __future__ import annotations

import random
import tempfile
import uuid
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from composition.designer.process import Worker
from core.diagnostics import log_failure
from core.pdf_engine import parse_page_range
from core.text_extraction import signature
from dialogs.base import remember_save_directory, start_in_save_directory
from workflow.extraction import ExtractionSpec
from workflow.regions_ui import RegionEditor


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
                            self.dialog.preview_text(delivered[0])
                    elif worker.cancel_requested:
                        self.dialog.status.setText("Cancelled; previous output files are unchanged.")
                    elif errors:
                        self.dialog.status.setText(errors[0])
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


class QuickTextExtractorDialog(RegionEditor):
    def __init__(self, source, current_page, suggested, parent=None, *, spec=None,
                 temporary=None, protected=(), handoff=None, page_count=None, source_guard=None):
        host = ExtractionHost(parent, temporary)
        self.result = None
        self.last_output = None
        self.protected = [str(p) for p in protected]
        self.handoff = handoff
        self.offset = 0
        self.suggested = suggested
        self.scan_signature = None
        self.source_guard = source_guard
        self.source_stale = False
        super().__init__(host, str(source), spec or {"version": 1, "regions": []}, current_page+1)
        host.dialog = self
        # Production callers provide captured metadata; standalone callers wait
        # for the first worker preview instead of guessing a million pages.
        self.source_ready = False
        if page_count is not None:
            self.page.setMaximum(page_count)
        self.setWindowTitle("Extract Text Regions · PDFDocuEdit Pro")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.timer.setInterval(250)
        form = self.scope.parentWidget().layout()
        for control in (self.scope, self.role, self.policy):
            form.setRowVisible(control, False)
        self.buttons.hide()
        self.layout().removeWidget(self.buttons)
        self.editor_splitter = self.view.parentWidget()
        self.layout().removeWidget(self.editor_splitter)
        self.editor_page = QWidget()
        editor_layout = QVBoxLayout(self.editor_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.editor_splitter)
        self.results_page = QWidget()
        results_layout = QVBoxLayout(self.results_page)
        self.preview_details = QPlainTextEdit()
        self.preview_details.setReadOnly(True)
        self.preview_details.setMaximumHeight(100)
        self.preview_details.setPlaceholderText("Current page: Raw / Clean / Issues")
        results_layout.addWidget(self.preview_details)
        self.model = ExtractionTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setWordWrap(False)
        results_layout.addWidget(self.table, 1)
        navigation = QHBoxLayout()
        self.previous = QPushButton("Previous 100")
        self.next = QPushButton("Next 100")
        self.previous.clicked.connect(lambda: self.load_rows(max(0, self.offset-100)))
        self.next.clicked.connect(lambda: self.load_rows(self.offset+100))
        self.page_label = QLabel("No extraction yet")
        for control in (self.previous, self.page_label, self.next):
            navigation.addWidget(control)
        results_layout.addLayout(navigation)
        self.tabs = QTabWidget()
        self.wide = QSplitter(Qt.Orientation.Vertical)
        self.layout().insertWidget(1, self.tabs, 1)
        self.layout().insertWidget(2, self.wide, 1)
        selection = QHBoxLayout()
        self.page_mode = QComboBox()
        self.page_mode.addItems(["All pages", "Current preview page", "Custom pages"])
        self.page_range = QLineEdit()
        self.page_range.setPlaceholderText("Pages: 1,3,5-8")
        self.page_range.setEnabled(False)
        self.sample_mode = QComboBox()
        self.sample_mode.addItems(["All selected", "First 10", "First 50", "Random 50"])
        self.sample_button = QPushButton("Sample")
        self.sample_button.clicked.connect(lambda: self.start_scan(sample=True))
        selection.addWidget(self.page_mode)
        selection.addWidget(self.page_range, 1)
        selection.addWidget(self.sample_mode)
        selection.addWidget(self.sample_button)
        self.layout().addLayout(selection)
        self.status = QLabel("One region = one column. Multiline values stay in one cell.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.layout().addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(8)
        self.progress.setTextVisible(False)
        self.layout().addWidget(self.progress)
        actions = QHBoxLayout()
        self.extract_button = QPushButton("Extract selected pages")
        self.export_button = QPushButton("Export…")
        self.workflow_button = QPushButton("Open in Visual Workflow")
        self.cancel_button = QPushButton("Cancel task")
        self.close_button = QPushButton("Close")
        self.extract_button.clicked.connect(lambda: self.start_scan())
        self.export_button.clicked.connect(self.choose_export)
        self.workflow_button.clicked.connect(self.open_workflow)
        self.cancel_button.clicked.connect(host.cancel)
        self.close_button.clicked.connect(self.reject)
        for button in (self.extract_button, self.export_button, self.workflow_button, self.cancel_button, self.close_button):
            actions.addWidget(button)
        self.layout().addLayout(actions)
        self.page_mode.currentIndexChanged.connect(self.page_mode_changed)
        self.page_range.textChanged.connect(self.invalidate_results)
        self.page.valueChanged.connect(self.selection_changed)
        self.undo.indexChanged.connect(self.invalidate_results)
        self.source_timer = QTimer(self)
        self.source_timer.setInterval(500)
        self.source_timer.timeout.connect(self.check_source)
        self.source_timer.start()
        self.arrange()
        self.sync_actions()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "wide"):
            self.arrange()

    def arrange(self):
        wide = self.width() >= 1100
        if wide and self.tabs.count():
            while self.tabs.count():
                self.tabs.removeTab(0)
        if wide:
            self.wide.addWidget(self.editor_page)
            self.wide.addWidget(self.results_page)
            self.wide.setSizes([500, 190])
        elif not self.tabs.count():
            self.tabs.addTab(self.editor_page, "PDF & fields")
            self.tabs.addTab(self.results_page, "Preview & results")
        self.wide.setVisible(wide)
        self.tabs.setVisible(not wide)

    def config(self):
        if not self.check_source():
            raise ValueError("Source PDF changed or closed; close this tool and capture its current revision again.")
        self.save_controls()
        return ExtractionSpec.from_dict({"regions": self.regions, "version": 1})

    def check_source(self):
        if self.source_guard and not self.source_guard():
            self.source_stale = True
            self.scan_signature = None
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
        self.page_range.setEnabled(self.page_mode.currentIndex() == 2 and not self.host.active)
        if self.page_mode.currentIndex() != 0:
            self.invalidate_results()

    def page_mode_changed(self, *_):
        self.selection_changed()
        self.invalidate_results()

    def invalidate_results(self, *_):
        if self.result:
            self.status.setText("Results are stale; extract selected pages again before exporting.")
        self.scan_signature = None
        self.sync_actions()

    def sync_actions(self):
        if not hasattr(self, "extract_button"):
            return
        busy = self.host.active is not None or self.host.closing
        self.editor_page.setEnabled(not busy)
        self.page_mode.setEnabled(not busy)
        self.page_range.setEnabled(not busy and self.page_mode.currentIndex() == 2)
        self.sample_button.setEnabled(not busy and self.source_ready)
        self.sample_mode.setEnabled(not busy)
        self.extract_button.setEnabled(not busy and self.source_ready and not self.source_stale)
        self.export_button.setEnabled(not busy and not self.source_stale and self.result is not None and self.scan_signature is not None)
        self.workflow_button.setEnabled(not busy and not self.source_stale and self.source_ready and self.handoff is not None)
        self.cancel_button.setEnabled(bool(self.host.workers) and not self.host.closing)
        self.previous.setEnabled(not busy and self.offset > 0 and self.result is not None)
        self.next.setEnabled(not busy and self.result is not None and self.offset+100 < self.result["pages"])

    def preview_text(self, result):
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

    def start_scan(self, *, sample=False):
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
            self.scan_signature = None
            target = self.host.directory/(uuid.uuid4().hex+".sqlite")
            def ready(result):
                self.result = result
                self.scan_signature = None if sample else identity
                self.status.setText(f'{"Sample" if sample else "Extraction"}: {result["pages"]:,} pages · {result["issues"]:,} field issues. Review before use.')
                self.load_rows(0)
                self.sync_actions()
            self.host.request({"operation": "scan", "source": self.source, "pages": pages,
                               "extraction": spec.to_dict(), "target": str(target), "protected": self.protected}, ready)
        except ValueError as exc:
            self.status.setText(str(exc))

    def load_rows(self, offset):
        if not self.result:
            return
        self.offset = offset
        database = self.result["database"]
        def ready(result):
            if self.result and self.result["database"] == database:
                self.model.replace(result["rows"], result["fields"])
                total = self.result["pages"]
                self.page_label.setText(f"{offset+1}–{min(offset+100, total)} / {total:,}")
        self.host.request({"operation": "rows", "database": database, "offset": offset}, ready)

    def choose_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export extracted text", start_in_save_directory(self.suggested),
                                              "Excel workbook (*.xlsx);;CSV (*.csv);;Plain text (*.txt)")
        if path:
            # The native save dialog owns the explicit overwrite confirmation.
            remember_save_directory(path)
            self.export_to(path, overwrite=Path(path).exists())

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
