"""Bounded node inspection UI. Production approval belongs to the Review screen."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .model import LABELS


class InspectionController:
    def __init__(self, window):
        self.window = window
        self.results = {}
        self.job_id = ""
        self.active = False
        self.pane = None

    def job(self):
        batch = getattr(self.window, "batch", None)
        return next((j for j in batch.jobs if j.id == self.job_id), None) if batch else None

    def current(self, node_id):
        return self.results.get((self.job_id, node_id))

    def wrap(self):
        w = self.window
        settings = w.inspector_scroll.takeWidget()
        if settings is None:
            return
        if isinstance(settings, InspectionPane):
            w.inspector_scroll.setWidget(settings)
            return
        self.pane = InspectionPane(self, settings, w.selected)
        w.inspector_scroll.setWidget(self.pane)
        self.display()

    def display(self):
        w = self.window
        w.canvas.inspections = {
            identity: value for (job, identity), value in self.results.items() if job == self.job_id
        }
        w.canvas.viewport().update()

    def invalidate(self):
        # Fast GUI invalidation; byte hashes are verified by the worker on every read.
        for value in self.results.values():
            if value.get("status") not in ("Checking", "Cancelled", "Failed"):
                value["status"] = "Out of date"
        self.display()

    def request_values(self, node_id):
        result = self.current(node_id)
        request = {"spec": self.window.spec.to_dict(), "directory": str(self.window.directory),
                   "node_id": node_id}
        if result:
            request["run_id"] = result.get("run_id", "")
        if self.window.spec.project_kind == "mail_merge_workflow":
            job = self.job()
            if job is None:
                raise ValueError("Choose one batch job above Settings before checking this step.")
            request["job"] = asdict(job)
        return request

    def check(self, node_id=None):
        w = self.window
        if w.active_worker or w.capture_active or not w.flush_settings():
            return
        node_id = node_id or w.selected
        try:
            w.spec.execution_prefix(node_id)
            request = self.request_values(node_id)
        except ValueError as exc:
            w.message(exc)
            return
        self.active = True
        self.refresh()
        def ready(payload):
            for result in payload["steps"].values():
                self.results[(result["job_id"], result["node_id"])] = result
            self.active = False
            self.refresh()
            w.message("Step check finished. Review Input, Output and Issues; production approval is unchanged.")
        def failed(message):
            self.active = False
            for value in self.results.values():
                if value.get("status") == "Checking":
                    value["status"] = "Cancelled" if "cancel" in message.lower() else "Failed"
            self.refresh()
        worker = w.request({**request, "operation": "inspect_step"}, ready, on_error=failed)
        if worker is None:
            self.active = False
            self.refresh()

    def state(self, payload):
        value = payload.get("inspection")
        if not value:
            return
        self.results[(value.get("job_id", ""), value["node_id"])] = value
        self.refresh()

    def refresh(self):
        self.display()
        if self.pane and not sip.isdeleted(self.pane):
            self.pane.refresh()


class InspectionPane(QWidget):
    def __init__(self, controller, settings, node_id):
        super().__init__()
        self.controller, self.settings, self.node_id = controller, settings, node_id
        self.generation = 0
        self.offsets = {"input": 0, "output": 0, "issues": 0}
        self.pages = {}
        self.rows = []
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        w = controller.window
        if w.spec.project_kind == "mail_merge_workflow":
            self.jobs = QComboBox()
            self.jobs.setAccessibleName("Batch job to inspect")
            self.jobs.addItem("Choose one batch job…", "")
            for job in w.batch.jobs:
                self.jobs.addItem(job.name or job.id, job.id)
            self.jobs.setCurrentIndex(max(0, self.jobs.findData(controller.job_id)))
            self.jobs.currentIndexChanged.connect(self.change_job)
            root.addWidget(self.jobs)
        self.check = QPushButton("Check to this step")
        self.check.setToolTip("Process the complete input into temporary results; no production files or approval.")
        self.check.clicked.connect(lambda: controller.check(self.node_id))
        root.addWidget(self.check)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("designerPanelTabs")
        self.tabs.setDocumentMode(True)
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.Shape.NoFrame)
        scroller.setWidget(settings)
        self.settings_scroll = scroller
        self.tabs.addTab(scroller, "Settings")
        for view in ("input", "output", "issues"):
            self.tabs.addTab(self.make_page(view), view.title())
        self.tabs.currentChanged.connect(self.tab_changed)
        root.addWidget(self.tabs, 1)
        self.refresh()

    def release_settings(self):
        self.generation += 1
        return self.settings_scroll.takeWidget()

    def change_job(self):
        self.generation += 1
        self.controller.job_id = self.jobs.currentData()
        self.offsets = dict.fromkeys(self.offsets, 0)
        for page in self.pages.values():
            page["table"].setRowCount(0)
        self.controller.display()
        self.refresh()

    def make_page(self, view):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 4, 2, 2)
        search = QLineEdit()
        search.setMaxLength(200)
        search.setPlaceholderText("Find source ID or content; press Enter")
        search.setClearButtonEnabled(True)
        search.returnPressed.connect(lambda: self.read(view, reset=True))
        layout.addWidget(search)
        table = QTableWidget(0, 0)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.itemSelectionChanged.connect(lambda: self.detail(view))
        layout.addWidget(table, 1)
        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        detail.setMaximumHeight(100)
        layout.addWidget(detail)
        count = QLabel("Check this step to view results.")
        count.setWordWrap(True)
        layout.addWidget(count)
        row = QHBoxLayout()
        previous, following = QPushButton("◀"), QPushButton("▶")
        previous.clicked.connect(lambda: self.read(view, delta=-50))
        following.clicked.connect(lambda: self.read(view, delta=50))
        previous.setToolTip("Previous 50 rows")
        following.setToolTip("Next 50 rows")
        row.addWidget(previous)
        row.addWidget(following)
        locate = QPushButton("Locate source")
        locate.clicked.connect(lambda: self.locate(view))
        row.addWidget(locate)
        layout.addLayout(row)
        if view == "output":
            plan = QPlainTextEdit()
            plan.setReadOnly(True)
            plan.setMaximumHeight(90)
            plan.setPlaceholderText("Output plan appears after a composition/media/output check.")
            layout.addWidget(plan)
            self.plan = plan
            preview = QPushButton("Preview one record…")
            preview.clicked.connect(self.preview)
            layout.addWidget(preview)
            self.preview_button = preview
        self.pages[view] = {"search": search, "table": table, "detail": detail, "count": count,
                            "previous": previous, "next": following, "rows": [], "total": 0}
        return page

    def refresh(self):
        w = self.controller.window
        result = self.controller.current(self.node_id)
        busy = bool(w.active_worker or self.controller.active or w.capture_active)
        self.check.setEnabled(not busy)
        if hasattr(self, "jobs"):
            self.jobs.setEnabled(not busy)
        if result:
            text = f"Check: {result['status']}"
            if "output_count" in result:
                text += f" · {result['input_count']:,} → {result['output_count']:,} {result['output_scope']}s"
            if result.get("error"):
                text += "\n" + result["error"]
            self.summary.setText(text)
            self.summary.setToolTip(text)
        else:
            self.summary.setText("Not checked. Production remains a separate action.")
        valid = bool(result and result.get("run_id") and result["status"] != "Out of date")
        if hasattr(self, "preview_button"):
            self.preview_button.setEnabled(bool(valid and (result.get("template") or result.get("overlay"))))
            self.plan.setPlainText(json.dumps(result.get("plan", {}), ensure_ascii=False, indent=2) if result else "")
        self.tab_changed()

    def tab_changed(self, *_):
        index = self.tabs.currentIndex()
        if index:
            self.read(("input", "output", "issues")[index - 1])

    def read(self, view, *, reset=False, delta=0):
        result = self.controller.current(self.node_id)
        page = self.pages[view]
        if not result or not result.get("run_id") or result["status"] == "Out of date":
            page["table"].setRowCount(0)
            page["detail"].clear()
            page["count"].setText("Check this step again to view current results.")
            page["previous"].setEnabled(False)
            page["next"].setEnabled(False)
            return
        if delta > 0 and self.offsets[view] + delta >= page["total"]:
            return
        self.offsets[view] = 0 if reset else max(0, self.offsets[view] + delta)
        self.generation += 1
        generation = self.generation
        try:
            request = self.controller.request_values(self.node_id)
        except ValueError as exc:
            self.controller.window.message(exc)
            return
        def ready(payload):
            if sip.isdeleted(self) or generation != self.generation:
                return
            rows = payload["rows"]
            page.update(rows=rows, total=payload["total"])
            table = page["table"]
            fields = payload.get("fields", [])[:12]
            labels = ["Node", "Source ID", "Field", "Reason"] if view == "issues" else ["Order", "Source ID", *fields]
            table.blockSignals(True)
            table.setRowCount(0)
            table.setColumnCount(len(labels))
            table.setHorizontalHeaderLabels(labels)
            table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                values = ([LABELS.get(next((n.kind for n in self.controller.window.spec.nodes if n.id == row["node_id"]), ""), row["node_id"]),
                           row["source_id"], row["field"], row["reason"]] if view == "issues" else
                          [row["ordinal"], row["source_id"], *[row["values"].get(f, "") for f in fields]])
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    table.setItem(i, column, item)
            table.blockSignals(False)
            page["detail"].clear()
            start = payload["offset"] + 1 if rows else 0
            page["count"].setText(f"{start}–{payload['offset'] + len(rows)} / {payload['total']:,} · 50 per page\nValues show up to 12 fields, 256 characters each.")
            if view == "issues" and result["status"] in ("Failed", "Cancelled"):
                page["count"].setText(page["count"].text() + "\nHistorical error evidence from this check.")
            page["previous"].setEnabled(payload["offset"] > 0)
            page["next"].setEnabled(payload["offset"] + len(rows) < payload["total"])
        def failed(message):
            if sip.isdeleted(self) or generation != self.generation:
                return
            result["status"] = "Out of date" if "out of date" in message or "changed" in message else result["status"]
            page["count"].setText(message)
            page["table"].setRowCount(0)
            self.controller.display()
        self.controller.window.request({**request, "operation": "inspection_rows", "view": view,
                                         "offset": self.offsets[view], "search": page["search"].text()},
                                        ready, preview=True, on_error=failed)

    def selected_row(self, view):
        page = self.pages[view]
        index = page["table"].currentRow()
        return page["rows"][index] if 0 <= index < len(page["rows"]) else None

    def detail(self, view):
        row = self.selected_row(view)
        if row:
            self.pages[view]["detail"].setPlainText(json.dumps(row, ensure_ascii=False, indent=2))

    def locate(self, view):
        row = self.selected_row(view)
        if not row:
            return
        w = self.controller.window
        trace = row.get("trace", {})
        if trace.get("source_file") and w.project_host:
            w.project_host.open_source_pdf(trace["source_file"], trace["source_page"] - 1)
        elif row.get("object_id") and w.project_host:
            job = self.controller.job()
            path = job.template_path if job else w.spec.node("overlay").params.get("path", "") if w.spec.node("overlay") else ""
            if path:
                project = w.project_host.open_project(path)
                if project and hasattr(project, "canvas"):
                    if hasattr(project, "template"):
                        index = next((i for i, page in enumerate(project.template.pages)
                                      if any(e.id == row["object_id"] for e in page.elements)), None)
                        if index is not None:
                            project.select_template_page(index)
                    project.canvas.select_ids([row["object_id"]])
        elif self.controller.job():
            w.tabs.setCurrentWidget(w.review_page)
            w.proxy.setFilterRegularExpression("")
            for index, job in enumerate(w.batch.jobs):
                if job.id == self.controller.job_id:
                    mapped = w.proxy.mapFromSource(w.jobs_model.index(index, 0))
                    w.jobs_table.selectRow(mapped.row())
                    break
            w.message(f"Batch job {self.controller.job().name}: source record {row['source_id']}. See selected inspection details for before/after values.")
        else:
            w.message("This finding has no source-page or object location.")

    def preview(self):
        w = self.controller.window
        result = self.controller.current(self.node_id)
        if not result or result.get("status") == "Out of date":
            return
        dialog = QDialog(w)
        dialog.setWindowTitle("Inspection preview — one record")
        dialog.resize(620, 700)
        root = QVBoxLayout(dialog)
        row = QHBoxLayout()
        record, page = QSpinBox(), QSpinBox()
        record.setPrefix("Record ")
        record.setRange(1, max(1, result["output_count"]))
        selected = self.selected_row("output")
        record.setValue(selected["ordinal"] if selected else 1)
        page.setPrefix("Page ")
        page.setRange(1, len(result["template"].get("pages", [])) or 9999)
        row.addWidget(record)
        row.addWidget(page)
        button = QPushButton("Preview")
        row.addWidget(button)
        root.addLayout(row)
        image = QLabel("Choose a record and press Preview.")
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(image)
        root.addWidget(scroll, 1)
        def render():
            try:
                request = self.controller.request_values(self.node_id)
            except ValueError as exc:
                w.message(exc)
                return
            button.setEnabled(False)
            def ready(payload):
                if not sip.isdeleted(dialog) and dialog.isVisible():
                    pixmap = QPixmap(payload["image"])
                    image.setPixmap(pixmap.scaled(580, 610, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    button.setEnabled(True)
            def failed(message):
                if not sip.isdeleted(dialog):
                    image.setText(message)
                    button.setEnabled(True)
            w.request({**request, "operation": "inspection_preview", "record": record.value(), "page": page.value(),
                       "target": str(w.directory / (uuid.uuid4().hex + ".png"))}, ready, preview=True, on_error=failed)
        button.clicked.connect(render)
        dialog.exec()
