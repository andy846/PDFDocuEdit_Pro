"""One read-only production review pane; all IO runs in the existing worker."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from composition.designer.process import Worker
from ui.combo_popup import WideComboBox

from .dashboard import ReviewDashboard
from .presentation import ReviewDashboardModel, dashboard_inputs


def table(headers):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels(headers)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setStretchLastSection(True)
    view.setMinimumSize(0, 0)
    return view


class FaceView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(0, 0)
        self.label = QLabel("Select a physical sheet")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.original = QPixmap()
        self.zoom = 0

    def refresh(self):
        if self.original.isNull():
            return
        width = (max(20, min(self.viewport().width() - 8,
                 int((self.viewport().height() - 8) * self.original.width() / self.original.height())))
                 if not self.zoom else int(self.original.width() * self.zoom))
        self.label.setPixmap(self.original.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation))
        self.label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def display(self, path):
        self.original = QPixmap(path)
        self.refresh()

    def clear(self, message):
        self.original = QPixmap()
        self.label.setPixmap(QPixmap())
        self.label.setText(message)
        self.label.adjustSize()


class ProductionReviewPane(QWidget):
    editRequested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("productionReviewPane")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("PRODUCTION REVIEW"))
        self.jobs = WideComboBox()
        self.jobs.setMinimumSize(0, 0)
        heading.addWidget(self.jobs, 1)
        layout.addLayout(heading)
        self.status = QLabel("Check complete inputs before confirming production.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.blocker_reason = QLabel()
        self.blocker_reason.setWordWrap(True)
        self.blocker_reason.setTextFormat(Qt.TextFormat.PlainText)
        self.blocker_reason.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.blocker_reason.setMinimumWidth(0)
        self.blocker_reason.hide()
        layout.addWidget(self.blocker_reason)
        self.list_page = QWidget()
        lists = QVBoxLayout(self.list_page)
        lists.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search record data… (Enter)")
        lists.addWidget(self.search)
        jump = QHBoxLayout()
        self.jump = QSpinBox()
        self.jump.setRange(1, 1_000_000_000)
        self.jump_kind = WideComboBox()
        self.jump_kind.addItems(["Envelope", "Output page"])
        self.go = QPushButton("Go")
        jump.addWidget(self.jump_kind)
        jump.addWidget(self.jump, 1)
        jump.addWidget(self.go)
        lists.addLayout(jump)
        self.envelopes = table(["Envelope", "Source", "Output pages", "Sheets"])
        lists.addWidget(self.envelopes, 1)
        pager = QHBoxLayout()
        self.previous, self.next = QPushButton("Previous 50"), QPushButton("Next 50")
        self.position = QLabel("0 records")
        self.position.setWordWrap(True)
        self.position.setMinimumWidth(0)
        pager.addWidget(self.previous)
        pager.addWidget(self.position, 1)
        pager.addWidget(self.next)
        lists.addLayout(pager)
        self.details = QTabWidget()
        self.details.setMinimumSize(0, 0)
        self.overview = QLabel("No checked production plan.")
        self.overview.setWordWrap(True)
        self.overview.setTextFormat(Qt.TextFormat.PlainText)
        self.overview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        self.dashboard = ReviewDashboard()
        overview_layout.addWidget(self.dashboard)
        self.plan_details = QPushButton("Show full checked plan details")
        self.plan_details.setCheckable(True)
        self.plan_details.toggled.connect(self.overview.setVisible)
        overview_layout.addWidget(self.plan_details)
        self.overview.hide()
        overview_layout.addWidget(self.overview)
        self.dashboard.issuesRequested.connect(self.show_issues)
        self.dashboard.barcodeRequested.connect(self.show_barcode_details)
        self.font_report = QPushButton("Open font substitution report")
        self.font_report.hide()
        overview_layout.addWidget(self.font_report)
        overview_layout.addStretch()
        overview_scroll.setWidget(overview_page)
        self.details.addTab(overview_scroll, "Summary")
        self.sheet_page = QWidget()
        sheets = QVBoxLayout(self.sheet_page)
        sheets.setContentsMargins(2, 2, 2, 2)
        self.pages = table(["Output", "Sheet", "Side", "Source / Template", "Media", "Barcode"])
        self.pages.setMaximumHeight(125)
        sheets.addWidget(self.pages)
        paper_pager = QHBoxLayout()
        self.paper_previous, self.paper_next = QPushButton("Previous pages"), QPushButton("Next pages")
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit", "50%", "100%", "200%"])
        paper_pager.addWidget(self.paper_previous)
        paper_pager.addWidget(self.paper_next)
        paper_pager.addStretch()
        paper_pager.addWidget(self.zoom)
        sheets.addLayout(paper_pager)
        self.source = QPushButton("Open source PDF at this page")
        self.source.setEnabled(False)
        self.source.hide()
        sheets.addWidget(self.source)
        self.faces = QWidget()
        self.faces_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.faces)
        self.faces_layout.setContentsMargins(0, 0, 0, 0)
        self.front, self.back = FaceView(), FaceView()
        for title, face in (("Front", self.front), ("Back", self.back)):
            box = QWidget()
            side = QVBoxLayout(box)
            side.setContentsMargins(0, 0, 0, 0)
            side.addWidget(QLabel(title))
            side.addWidget(face, 1)
            self.faces_layout.addWidget(box, 1)
        sheets.addWidget(self.faces, 1)
        self.payload = QLabel("Barcode: not configured / not applicable.")
        self.payload.setWordWrap(True)
        self.payload.setTextFormat(Qt.TextFormat.PlainText)
        self.payload.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.payload)
        self.details.addTab(self.sheet_page, "Paper sheets")
        self.details.addTab(scroll, "Barcode values")
        self.issue_page = QWidget()
        issue_layout = QVBoxLayout(self.issue_page)
        self.issues = table(["Severity", "Envelope / Record", "Output page", "Field / Object", "Reason"])
        issue_layout.addWidget(self.issues, 1)
        self.edit = QPushButton("Return to settings / Review object")
        self.edit.clicked.connect(self.edit_issue)
        issue_layout.addWidget(self.edit)
        self.details.addTab(self.issue_page, "Issues")
        self.splitter = QSplitter()
        self.splitter.addWidget(self.list_page)
        self.splitter.addWidget(self.details)
        self.splitter.setSizes([300, 760])
        layout.addWidget(self.splitter, 1)
        self.compact = QTabWidget()
        self.compact.hide()
        layout.addWidget(self.compact, 1)
        self.acknowledge = QCheckBox("I have reviewed the production warnings")
        self.acknowledge.setToolTip("Review Issues, including physical printer and inserter verification where applicable.")
        self.acknowledge.setVisible(False)
        layout.addWidget(self.acknowledge)
        footer = QHBoxLayout()
        self.recheck = QPushButton("Check again")
        self.cancel = QPushButton("Cancel check")
        self.confirm = QPushButton("Confirm production")
        self.confirm.setEnabled(False)
        footer.addWidget(self.recheck)
        footer.addWidget(self.cancel)
        footer.addStretch()
        footer.addWidget(self.confirm)
        layout.addLayout(footer)
        self.zoom.currentIndexChanged.connect(self.change_zoom)
        self._narrow = False
        self._wide_sizes = [300, 760]

    def show_issues(self, severity=""):
        self.details.setCurrentWidget(self.issue_page)
        if self._narrow:
            self.compact.setCurrentWidget(self.details)
        for row in range(self.issues.rowCount()):
            item = self.issues.item(row, 0)
            if item and (not severity or item.text() == severity):
                self.issues.selectRow(row)
                break

    def show_barcode_details(self):
        for row in range(self.issues.rowCount()):
            item = self.issues.item(row, 0)
            issue = item.data(Qt.ItemDataRole.UserRole) if item else None
            if issue and issue.get("action") == "barcode":
                self.show_issues()
                self.issues.selectRow(row)
                return
        self.details.setCurrentIndex(2)
        if self._narrow:
            self.compact.setCurrentWidget(self.details)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 1080
        if narrow != self._narrow:
            self._narrow = narrow
            if narrow:
                self._wide_sizes = self.splitter.sizes()
                self.compact.addTab(self.list_page, "Mailpieces")
                self.compact.addTab(self.details, "Details")
                if not self.blocker_reason.isHidden() and self.details.currentWidget() is self.issue_page:
                    self.compact.setCurrentWidget(self.details)
            else:
                while self.compact.count():
                    self.compact.removeTab(0)
                self.splitter.addWidget(self.list_page)
                self.splitter.addWidget(self.details)
                self.list_page.show()
                self.details.show()
                self.splitter.setSizes(self._wide_sizes)
            self.splitter.setVisible(not narrow)
            self.compact.setVisible(narrow)
        self.faces_layout.setDirection(QBoxLayout.Direction.TopToBottom if self.width() < 600 else QBoxLayout.Direction.LeftToRight)

    def change_zoom(self):
        value = (0, .5, 1, 2)[self.zoom.currentIndex()]
        for face in (self.front, self.back):
            face.zoom = value
            face.refresh()

    def edit_issue(self):
        row = self.issues.currentRow()
        issue = self.issues.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else {"action": "settings"}
        self.editRequested.emit(issue)


class ReviewController:
    """Own live workers until ended; latest selection wins without stale UI updates."""
    def __init__(self, owner, pane, current, edit):
        self.owner, self.pane, self.current = owner, pane, current
        self.continuation = None
        self.contexts, self.results = [], []
        self.epoch, self.view_epoch = 0, 0
        self.check_worker = None
        self.offset = self.page_offset = self.envelope = 0
        self.original_state = None
        self.images = []
        self.session_valid = False
        self.rows_serial = 0
        self.view_workers = {}
        self.consumed = False
        self.dashboard_stale = self.dashboard_cancelled = self.dashboard_failed = False
        self.generations = {}
        self.dashboard_origin = None
        self.generation_serial = 0
        pane.jobs.currentIndexChanged.connect(self.select_job)
        pane.search.returnPressed.connect(lambda: self.rows(reset=True))
        pane.previous.clicked.connect(lambda: self.rows(delta=-50))
        pane.next.clicked.connect(lambda: self.rows(delta=50))
        pane.go.clicked.connect(self.jump)
        pane.envelopes.itemSelectionChanged.connect(self.select_envelope)
        pane.pages.itemSelectionChanged.connect(self.select_page)
        pane.paper_previous.clicked.connect(lambda: self.paper_rows(-50))
        pane.paper_next.clicked.connect(lambda: self.paper_rows(50))
        pane.recheck.clicked.connect(self.recheck)
        pane.cancel.clicked.connect(self.cancel)
        pane.confirm.clicked.connect(self.confirm)
        pane.acknowledge.toggled.connect(self.refresh_confirm)
        pane.editRequested.connect(edit)
        pane.source.clicked.connect(self.open_source)
        pane.font_report.clicked.connect(self.open_font_report)
        pane.dashboard.fontRequested.connect(self.open_dashboard_font_report)

    def state(self):
        try:
            return hashlib.sha256(json.dumps(self.current(), sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        except (ValueError, OSError, AttributeError, RuntimeError):
            return None

    def dashboard_state(self):
        # Read-only status projection; original state/fingerprint still controls approval.
        try:
            return json.dumps(dashboard_inputs(self.current()), sort_keys=True, ensure_ascii=True)
        except (ValueError, OSError, AttributeError, RuntimeError, TypeError):
            return None

    def alive(self):
        return not sip.isdeleted(self.owner) and not sip.isdeleted(self.pane)

    def invalidate(self, *_):
        if not self.alive() or getattr(self.owner, "close_pending", False):
            self.session_valid = False
            return
        if not self.results and not self.check_worker:
            return
        if self.original_state != self.state():
            self.session_valid = False
            self.dashboard_stale = (self.dashboard_stale or not self.consumed or self.dashboard_origin is None
                                    or self.dashboard_origin != self.dashboard_state())
            self.epoch += 1
            self.view_epoch += 1
            if self.check_worker:
                self.check_worker.cancel()
            self.pane.status.setText("Settings changed. This review is stale; check again."
                                    if self.dashboard_stale else
                                    "Showing the confirmed plan. See dashboard for output status.")
            self.pane.confirm.setEnabled(False)
            self.refresh_dashboard()

    def _request(self, task, callback, *, checking=False, **values):
        epoch = self.epoch
        key = task + ("_pages" if values.get("envelope") else "_jump" if values.get("output_page") else "_records")
        if not checking and key in self.view_workers:
            self.view_workers[key].stop_preview()
        worker = Worker(self.owner.directory, {"task": "production_review_" + task,
            "directory": str(self.owner.directory), **values}, self.owner)
        self.owner.workers.append(worker)
        worker.task = "production_review_" + task
        delivered = []
        worker.resultReady.connect(lambda result: delivered.append((True, result)))
        worker.failed.connect(lambda error: delivered.append((False, error)))
        if not checking:
            self.view_workers[key] = worker
        if checking:
            self.check_worker = worker
            if hasattr(self.owner, "active_worker"):
                self.owner.active_worker = worker
            elif hasattr(self.owner, "production_worker"):
                self.owner.production_worker = worker
            self._busy()
            self.refresh_confirm()
            worker.progress.connect(lambda n, total, message: self.pane.status.setText(f"{message} · {n:,}/{total:,}") if epoch == self.epoch else None)
        def ended():
            if worker in self.owner.workers:
                self.owner.workers.remove(worker)
            if self.check_worker is worker:
                self.check_worker = None
            if getattr(self.owner, "active_worker", None) is worker:
                self.owner.active_worker = None
            if getattr(self.owner, "production_worker", None) is worker:
                self.owner.production_worker = None
            if not self.alive():
                return
            self._busy()
            superseded = not checking and self.view_workers.get(key) is not worker
            if not checking and not superseded:
                self.view_workers.pop(key, None)
            if getattr(self.owner, "close_pending", False) and not self.owner.workers:
                QTimer.singleShot(0, self.owner.close)
            if superseded or epoch != self.epoch or getattr(self.owner, "close_pending", False):
                for success, value in delivered:
                    if success and isinstance(value, dict):
                        for face in value.get("images", []):
                            Path(face["image"]).unlink(missing_ok=True)
                return
            if delivered and delivered[-1][0]:
                callback(delivered[-1][1])
            else:
                self.session_valid = False
                self.dashboard_failed = True
                self.pane.status.setText(str(delivered[-1][1] if delivered else "Review worker returned no result."))
                self.pane.confirm.setEnabled(False)
                self.refresh_dashboard()
        worker.ended.connect(ended)
        return worker

    def _busy(self):
        if not self.alive():
            return
        callback = getattr(self.owner, "_busy", None) or getattr(self.owner, "busy", None) or getattr(self.owner, "lock", None)
        if callback:
            callback()

    def start(self, contexts, continuation):
        self.cancel()
        self.epoch += 1
        self.contexts, self.results = contexts, []
        self.continuation = continuation
        self.original_state = self.state()
        self.session_valid = self.original_state is not None
        self.consumed = False
        self.dashboard_stale = self.dashboard_cancelled = self.dashboard_failed = False
        self.generations.clear()
        self.dashboard_origin = self.dashboard_state()
        self.generation_serial += 1
        for view in (self.pane.envelopes, self.pane.pages, self.pane.issues):
            view.setRowCount(0)
        self.pane.front.clear("Select a checked sheet")
        self.pane.back.clear("Select a checked sheet")
        self.pane.blocker_reason.clear()
        self.pane.blocker_reason.hide()
        self.pane.overview.setText("Checking complete production inputs…")
        self.pane.payload.setText("Select a checked sheet to inspect barcode values.")
        self.pane.source.hide()
        self.pane.font_report.hide()
        self.pane.jobs.blockSignals(True)
        self.pane.jobs.clear()
        for context in contexts:
            self.pane.jobs.addItem(context.get("label") or context["job"]["job_id"])
        self.pane.jobs.blockSignals(False)
        self.pane.confirm.setEnabled(False)
        self.pane.acknowledge.setChecked(False)
        self.pane.status.setText("Checking complete production inputs… No formal output is being generated.")
        self._check_next()

    def _check_next(self):
        index = len(self.results)
        if index == len(self.contexts):
            self.select_job()
            self.refresh_confirm()
            return
        def checked(result):
            self.contexts[index] = result["context"]
            self.results.append(result)
            if result["status"] == "cancelled":
                self.select_job()
                return
            self._check_next()
        self._request("check", checked, checking=True, context=self.contexts[index])

    def recheck(self):
        if self.check_worker:
            return
        # Rebuild job settings from the caller; never check an obsolete template.
        rebuild = getattr(self, "rebuild", None)
        if rebuild:
            rebuild()
        elif self.contexts and self.original_state == self.state():
            self.start(self.contexts, self.continuation)

    def cancel(self):
        if self.check_worker:
            self.session_valid = False
            self.dashboard_cancelled = True
            self.check_worker.cancel()
            self.epoch += 1
            self.pane.status.setText("Cancellation requested. Completed results remain available; approval is disabled.")
        self.pane.confirm.setEnabled(False)
        self.refresh_dashboard()

    def selected(self):
        index = max(0, self.pane.jobs.currentIndex())
        return self.results[index] if index < len(self.results) else None

    def select_job(self, *_):
        self.view_epoch += 1
        self.offset = self.page_offset = self.envelope = 0
        result = self.selected()
        if not result:
            self.refresh_dashboard()
            return
        summary = result["summary"]
        titles = {"job_id": "Job ID", "label": "Job", "records": "Mailpieces / records", "pages": "Output pages",
                  "input_records": "Input records / envelopes", "excluded_records": "Excluded records / envelopes",
                  "sheets": "Physical sheets", "inserted_blanks": "Inserted blank backs", "printing": "Printing",
                  "source": "Source", "output_name": "PDF name", "output_dir": "Output folder",
                  "printer_profile": "Printer profile", "media_source": "Print settings source",
                  "font_substitutions": "Font substitutions", "conditional_objects": "Conditional objects",
                  "hidden_objects": "Hidden object occurrences"}
        lines = [f"{title}: {summary[key]}" for key, title in titles.items() if key in summary]
        from .presentation import next_step
        lines.append("Next: "+next_step(result["status"],stale=not self.session_valid and not self.consumed))
        if "expected_barcodes" in summary:
            count=str(summary["expected_barcodes"]) if summary.get("barcode_check_complete",result.get("complete",False)) else "Not fully checked"
            lines.append("Planned barcodes: "+count)
        backend = summary.get("backend", "pdf")
        lines.append("Output: " + {"pdf": "PDF", "postscript": "PDF + PostScript", "canon_prismasync": "PDF + JDF"}.get(backend, backend))
        lines += [f"Stock {stock}: {count:,} physical sheets" for stock, count in summary.get("stock_sheets", {}).items()]
        for key in ("output_limits","output_partition_estimate","output_naming","output_pattern","output_naming_preview"):
            if summary.get(key):
                lines.append(summary[key])
        if summary.get("outputs"):
            lines.append("Split outputs: " + " · ".join(f"{p['name']} ({p['records']:,} records)" for p in summary["outputs"]))
        self.pane.overview.setText("\n".join(lines) + "\n\nPreview and planned payloads only; final PDF decoding runs after generation.")
        self.pane.font_report.setVisible(bool(summary.get("font_report")))
        self.pane.status.setText(f"{result['status'].title()} · {summary.get('records', 0):,} mailpieces · {summary.get('pages', 0):,} output pages"
                                if self.session_valid else "Production confirmed. This checked plan is read-only."
                                if self.consumed else "This review is stale or cancelled. Check again before production.")
        self.pane.issues.setRowCount(len(result["issues"]))
        for row, issue in enumerate(result["issues"]):
            self.fill(self.pane.issues, row, [issue["severity"], issue["envelope"] or "—",
                issue['output_page'] or '—', issue['field'] or issue['object_id'] or '—', issue["reason"]], issue)
        errors = [(row, issue) for row, issue in enumerate(result["issues"])
                  if issue["severity"] == "error"]
        blocked = result["status"] == "blocked"
        self.pane.blocker_reason.setVisible(blocked or bool(errors))
        if blocked or errors:
            reason = errors[0][1]["reason"] if errors else "Check Issues and return to settings before checking again."
            concise = " ".join(reason.split())
            if len(concise) > 280:
                concise = concise[:277] + "…"
            self.pane.blocker_reason.setText(f"Production blocked: {concise} — See Issues for details.")
            self.pane.blocker_reason.setToolTip(reason)
            self.pane.details.setCurrentWidget(self.pane.issue_page)
            if self.pane._narrow:
                self.pane.compact.setCurrentWidget(self.pane.details)
            if errors:
                self.pane.issues.selectRow(errors[0][0])
        else:
            self.pane.blocker_reason.clear()
            self.pane.blocker_reason.setToolTip("")
            self.pane.details.setCurrentIndex(0)
            if self.pane._narrow:
                self.pane.compact.setCurrentWidget(self.pane.details)
        self.pane.front.clear("Select a sheet to preview its front")
        self.pane.back.clear("Select a sheet to preview its back")
        self.pane.pages.setRowCount(0)
        self.pane.source.setEnabled(False)
        self.pane.source.hide()
        self.rows(reset=True)
        self.refresh_confirm()

    @staticmethod
    def fill(view, row, values, raw):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            item.setData(Qt.ItemDataRole.UserRole, raw)
            view.setItem(row, column, item)

    def rows(self, *, reset=False, delta=0):
        self.invalidate()
        result = self.selected()
        if not result or (self.original_state != self.state() and not (self.consumed and not self.dashboard_stale)):
            return
        if reset:
            self.offset = 0
        self.offset = max(0, self.offset + delta)
        epoch = self.view_epoch
        self.rows_serial += 1
        serial, offset = self.rows_serial, self.offset
        def ready(data):
            if epoch != self.view_epoch or serial != self.rows_serial:
                return
            view = self.pane.envelopes
            view.blockSignals(True)
            view.setRowCount(len(data["rows"]))
            for index, row in enumerate(data["rows"]):
                self.fill(view, index, [row["envelope"], row["source_record"],
                    f"{row['output_start']}–{row['output_end']}", row["sheets"]], row)
            view.blockSignals(False)
            if result["status"] == "blocked" and not data["total"] and not self.pane.search.text():
                planned = result["summary"].get("records", 0)
                self.pane.position.setText(f"0 checked / {planned:,} planned — See Issues")
            else:
                self.pane.position.setText(f"{offset+1 if data['rows'] else 0}–{offset+len(data['rows'])} / {data['total']:,}")
            self.pane.previous.setEnabled(self.offset > 0)
            self.pane.next.setEnabled(self.offset + 50 < data["total"])
        self._request("rows", ready, snapshot_id=result["snapshot_id"], offset=offset, search=self.pane.search.text())

    def jump(self):
        result = self.selected()
        if not result:
            return
        number = self.pane.jump.value()
        if self.pane.jump_kind.currentIndex() == 0:
            self.envelope, self.page_offset = number, 0
            self.paper_rows()
        else:
            epoch = self.view_epoch
            def ready(data):
                if epoch != self.view_epoch:
                    return
                self.envelope, self.page_offset = data["envelope"], data.get("page_offset", 0)
                self.paper_rows(target=number)
            self._request("rows", ready, snapshot_id=result["snapshot_id"], output_page=number)

    def select_envelope(self):
        row = self.pane.envelopes.currentRow()
        if row >= 0:
            self.envelope = self.pane.envelopes.item(row, 0).data(Qt.ItemDataRole.UserRole)["envelope"]
            self.page_offset = 0
            self.paper_rows()

    def paper_rows(self, delta=0, *, target=None):
        result = self.selected()
        if not result or not self.envelope:
            return
        self.view_epoch += 1
        epoch = self.view_epoch
        self.page_offset = max(0, self.page_offset + delta)
        def ready(data):
            if epoch != self.view_epoch:
                return
            view = self.pane.pages
            view.blockSignals(True)
            view.setRowCount(len(data["pages"]))
            for index, row in enumerate(data["pages"]):
                self.fill(view, index, [row["output_page"], row["sheet"], row["side"],
                    "Inserted blank" if row["blank"] else row["template_page"] or row["source_page"], row["stock"],
                    " / ".join(m["payload"] for m in row["barcodes"]) or "Not configured / not applicable"], row)
            view.blockSignals(False)
            self.pane.paper_previous.setEnabled(self.page_offset > 0)
            self.pane.paper_next.setEnabled(len(data["pages"]) == 50)
            self.pane.details.setCurrentIndex(1)
            if self.pane._narrow:
                self.pane.compact.setCurrentIndex(1)
            if data["pages"]:
                view.selectRow(next((i for i, p in enumerate(data["pages"]) if p["output_page"] == target), 0))
        self._request("rows", ready, snapshot_id=result["snapshot_id"], envelope=self.envelope, offset=self.page_offset)

    def select_page(self):
        result, index = self.selected(), self.pane.pages.currentRow()
        if not result or index < 0:
            return
        self.invalidate()
        if self.original_state != self.state() and not (self.consumed and not self.dashboard_stale):
            return
        self.view_epoch += 1
        epoch = self.view_epoch
        row = self.pane.pages.item(index, 0).data(Qt.ItemDataRole.UserRole)
        self.pane.source.setEnabled(bool(row.get("source_file") and row.get("original_page")))
        self.pane.source.setVisible(self.pane.source.isEnabled())
        lines = [f"Output page {row['output_page']} · Job sheet {row['job_sheet']} · {row['reason']}"]
        for mark in row["barcodes"]:
            lines.append(f"{mark['symbology'].upper()} · {mark['profile']} · {mark['payload']}")
            lines.append(f"Position {mark['x_mm']:g}, {mark['y_mm']:g} mm · Size {mark['width_mm']:g} × {mark['height_mm']:g} mm · Rotation {mark['rotation']:g}°")
            if mark["parts"]:
                lines.append(" · ".join(f"{k}: {v}" for k, v in mark["parts"].items()))
            if mark["segments"]:
                lines.append(" · ".join(f"{s['name']}: {s['formatted']}" for s in mark["segments"]))
        self.pane.payload.setText("\n".join(lines if row["barcodes"] else [*lines, "Barcode: not configured / not applicable."]))
        def ready(data):
            if epoch != self.view_epoch:
                for face in data["images"]:
                    Path(face["image"]).unlink(missing_ok=True)
                return
            self.pane.front.clear("No front")
            self.pane.back.clear("Simplex — no back")
            for face in data["images"]:
                target = self.pane.back if face["page"]["side"] == "Back" else self.pane.front
                target.display(face["image"])
                Path(face["image"]).unlink(missing_ok=True)
        self._request("preview", ready, snapshot_id=result["snapshot_id"], output_page=row["output_page"])

    def open_source(self):
        index = self.pane.pages.currentRow()
        if index >= 0:
            row = self.pane.pages.item(index, 0).data(Qt.ItemDataRole.UserRole)
            if row.get("source_file") and row.get("original_page"):
                self.pane.editRequested.emit({"action": "source", "path": row["source_file"], "page": row["original_page"]})

    def open_font_report(self):
        result = self.selected()
        if result and result["summary"].get("font_report"):
            from core.platform_service import PlatformService
            PlatformService.open_path(result["summary"]["font_report"])

    def refresh_confirm(self, *_):
        if not self.alive() or getattr(self.owner, "close_pending", False):
            return
        warnings = any(issue["severity"] == "warning" for r in self.results for issue in r["issues"])
        self.pane.acknowledge.setVisible(warnings)
        valid = self.session_valid and bool(self.contexts) and len(self.results) == len(self.contexts) and not self.check_worker
        valid = valid and all(r["complete"] and r["status"] == "checked" for r in self.results)
        self.pane.confirm.setEnabled(valid and self.original_state == self.state()
                                     and (not warnings or self.pane.acknowledge.isChecked()))
        self.pane.cancel.setEnabled(bool(self.check_worker))
        self.pane.recheck.setEnabled(not self.check_worker)
        self.refresh_dashboard()

    def refresh_dashboard(self):
        if not self.alive() or getattr(self.owner, "close_pending", False):
            return
        result = self.selected()
        task = getattr(self.check_worker, "task", "")
        model = ReviewDashboardModel.from_review(result,
            current=not self.dashboard_stale,
            checking=bool(self.check_worker) and not task.endswith("_approve"),
            confirming=bool(self.check_worker) and task.endswith("_approve"),
            confirmed=self.consumed,
            confirmation_available=self.pane.confirm.isEnabled(),
            acknowledged=self.pane.acknowledge.isChecked(),
            cancelled=self.dashboard_cancelled,
            check_failed=self.dashboard_failed,
            generation=self.generations.get(result.get("snapshot_id")) if result else None)
        self.pane.dashboard.display(model)

    def open_dashboard_font_report(self):
        if self.alive() and self.pane.dashboard.model.fonts.report:
            from core.platform_service import PlatformService
            PlatformService.open_path(self.pane.dashboard.model.fonts.report)

    def watch_generation(self, worker, receipts):
        """Observe this pane's approved continuation only; never start or approve work."""
        if worker is None or not self.consumed or not self.alive():
            return
        serial = self.generation_serial
        bindings = {}
        for result in self.results:
            for receipt in receipts:
                if (receipt.get("snapshot_id") == result["snapshot_id"]
                        and receipt.get("context") == result.get("context")):
                    bindings[result["summary"]["job_id"]] = {
                        "snapshot_id": result["snapshot_id"], "fingerprint": result["fingerprint"],
                        "job_id": result["summary"]["job_id"], "phase": "running"}
        if not bindings:
            return
        self.generations.update({b["snapshot_id"]: b for b in bindings.values()})
        delivered, failed = [], []
        worker.resultReady.connect(delivered.append)
        worker.failed.connect(failed.append)
        def ended():
            if not self.alive() or serial != self.generation_serial or getattr(self.owner, "close_pending", False):
                return
            values = self._generation_results(delivered[-1]) if delivered else []
            keys = {"job_id", "status", "expected_pages", "generated_pages", "generated_files", "published_files",
                    "output_pdf", "report_dir", "expected_barcodes", "rendered_barcodes", "decoded_barcodes",
                    "repaired_glyphs", "repaired_records", "glyph_repair_report", "font_scan"}
            for job_id, binding in bindings.items():
                matches = [r for r in values if r.get("job_id") == job_id]
                binding = {**binding, "phase": "failed" if failed else "finished"}
                if len(matches) == 1:
                    binding["result"] = {key: value for key, value in matches[0].items() if key in keys}
                self.generations[binding["snapshot_id"]] = binding
            self.refresh_dashboard()
        worker.ended.connect(ended)
        self.refresh_dashboard()

    @staticmethod
    def _generation_results(value):
        # Whitelisted result envelopes, never recursively traverse record data.
        results = []
        if not isinstance(value, dict):
            return results
        if value.get("job_id") and "status" in value:
            results.append(value)
        if isinstance(value.get("output"), dict):
            results.append(value["output"])
        batch = value.get("batch", {})
        if isinstance(batch, dict):
            results.extend(job["result"] for job in batch.get("jobs", []) if isinstance(job.get("result"), dict))
        run = value.get("run", {})
        if isinstance(run, dict):
            for entry in run.get("jobs", []):
                if isinstance(entry.get("result"), dict):
                    results.append(entry["result"])
                child = entry.get("batch", {})
                if isinstance(child, dict):
                    results.extend(job["result"] for job in child.get("jobs", []) if isinstance(job.get("result"), dict))
        return results

    def confirm(self):
        self.invalidate()
        self.refresh_confirm()
        if not self.pane.confirm.isEnabled():
            return
        self.pane.confirm.setEnabled(False)
        receipts = []
        def next_receipt(index):
            if index == len(self.results):
                self.invalidate()
                if self.session_valid and self.original_state == self.state():
                    self.session_valid = False
                    self.consumed = True
                    self.refresh_dashboard()
                    before = set(getattr(self.owner, "workers", []))
                    self.continuation(receipts)
                    worker = getattr(self.owner, "production_worker", None) or getattr(self.owner, "active_worker", None)
                    if worker is not None and worker not in before:
                        self.watch_generation(worker, receipts)
                return
            context = self.contexts[index]
            result = self.results[index]
            receipt = {"directory": str(self.owner.directory), "snapshot_id": result["snapshot_id"],
                       "context": context, "acknowledge": self.pane.acknowledge.isChecked()}
            def approved(value):
                receipt["authorization"] = value["authorization"]
                receipts.append(receipt)
                next_receipt(index + 1)
            self._request("approve", approved,
                          checking=True, context=context, snapshot_id=result["snapshot_id"], acknowledge=receipt["acknowledge"])
        next_receipt(0)
