"""UI coordination only. Existing services own PDF changes and validation."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from composition.designer.process import Worker


class PdfProductionController(QObject):
    changed = pyqtSignal()
    progress = pyqtSignal(int, int, str)
    resultAdded = pyqtSignal(dict)
    idle = pyqtSignal()

    def __init__(self, panels, parent=None):
        super().__init__(parent)
        self.panels = panels
        self.directory = tempfile.TemporaryDirectory(prefix="pdf-production-")
        self.snapshot_directory = None
        self.refresh_factory = None
        self.current_check = lambda: True
        self.sources, self.label = [], ""
        self.editor_source = False
        self.stale = False
        self.stopped = False
        self.overview_worker = None
        self.overview = {}
        self.history = []
        self.active = ""
        self.active_request = {}
        self.current_entry = None
        self.generation = 0
        self.fingerprints = {}
        self.secrets = {}
        self.source_metadata = {}
        for section, panel in panels.items():
            panel.taskStarted.connect(lambda request, key=section: self.started(key, request))
            panel.taskResult.connect(lambda request, result, key=section: self.received(key, request, result))
            panel.taskFailed.connect(lambda request, error, key=section: self.failed(key, request, error))
            panel.taskEnded.connect(self.ended)
            panel.progressChanged.connect(self.progress)
        self.monitor = QTimer(self)
        self.monitor.setInterval(200)
        self.monitor.timeout.connect(self.check_source)
        self.monitor.start()

    @property
    def workers(self):
        return [w for w in [self.overview_worker, *(p.worker for p in self.panels.values())] if w is not None]

    @property
    def busy(self):
        return bool(self.workers)

    def is_current(self):
        return not self.stale and not self.stopped and self.current_check()

    def check_source(self):
        if self.stopped or self.stale or not self.sources or self.current_check():
            return
        self.stale = True
        self.overview = {}
        for entry in self.history:
            entry["outdated"] = True
        self.cancel()
        for panel in self.panels.values():
            if hasattr(panel, "plan"):
                panel.plan, panel.analyses = None, []
            else:
                panel.inventory = None
                panel.report = {}
        self.changed.emit()

    def set_sources(self, paths, *, label=None, current=None, directory=None,
                    page_count=0, current_page=0, security=None, editor=False, scan_only=False):
        if self.busy or self.stopped:
            return False
        previous = self.snapshot_directory
        self.snapshot_directory = directory
        self.sources = [str(p) for p in paths]
        self.label = label or (Path(self.sources[0]).name if len(paths) == 1 else f"{len(paths)} PDFs")
        self.current_check = current or (lambda: True)
        self.editor_source = editor
        self.source_metadata = {"page_count": page_count, "scan_only": scan_only,
                                "snapshot": editor, "label": self.label}
        self.stale = False
        self.generation += 1
        self.overview = {}
        for entry in self.history:
            entry["outdated"] = True
        self.secrets = dict(security or {})
        for section, panel in self.panels.items():
            panel.source, panel.sources = self.sources[0], list(self.sources)
            panel.source_current = self.is_current
            panel.secrets = dict(self.secrets)
            panel.password_edit.setText(self.secrets.get("password", ""))
            panel.source_label.setText(self.label)
            if section == "fonts":
                panel.scan_only, panel.editor_source = scan_only, editor
                panel.selections = {}
                panel.reference.clear()
                panel.trusted.setChecked(False)
                panel.authorized.setChecked(False)
                panel.invalidate()
                panel.details.setPlainText("Not checked. Analyze fonts to see resource status.")
            else:
                panel.page_count, panel.current_page = page_count, current_page
                panel.pages.model().item(1).setEnabled(len(paths) == 1 and editor)
                if panel.pages.currentIndex() == 1 and not editor:
                    panel.pages.setCurrentIndex(0)
                panel.signature.setChecked(False)
                panel.recovery_ack.setChecked(False)
                panel.raster_ack.setChecked(False)
                panel.signed_hint = panel.recovery_hint = False
                from core.variables import VariableContext
                panel.naming.set_context(VariableContext.for_job(input_path=self.sources[0], job_id="example-job"))
                panel.options_changed()
                panel.summary.setPlainText("Not checked. Analyze these settings before generating a copy.")
        if previous is not None and previous is not directory:
            previous.cleanup()
        self.fingerprints = {key: self.fingerprint(key) for key in self.panels}
        self.changed.emit()
        return True

    def refresh(self):
        if not self.busy and self.refresh_factory and not self.stopped:
            self.set_sources(**self.refresh_factory())

    def set_password(self, password):
        if self.busy:
            return
        self.secrets["password"] = password
        self.overview = {}
        for panel in self.panels.values():
            panel.password_edit.setText(password)
        self.changed.emit()

    def fingerprint(self, section):
        if section == "overview":
            return self.panels["fonts"].policy.currentData()
        panel = self.panels[section]
        if section == "fonts":
            return repr((panel.policy.currentData(), panel.selections, panel.reference.text(),
                         panel.authorized.isChecked(), panel.trusted.isChecked()))
        return repr((panel.mode.currentData(), panel.pages.currentIndex(), panel.range.text(), panel.dpi.value(),
                     *(getattr(panel, key).isChecked() for key in ("annotations", "forms", "raster", "javascript", "attachments", "metadata", "boxes", "preflight", "allow_errors", "signature", "raster_ack", "recovery_ack")),
                     panel.naming.text(), panel.output_folder.text()))

    def settings_changed(self, section):
        value = self.fingerprint(section)
        if self.fingerprints.get(section) == value:
            return
        self.fingerprints[section] = value
        for entry in self.history:
            if entry["section"] == section and entry.get("fingerprint") != value:
                entry["outdated"] = True
            if entry["section"] == "overview" and entry.get("fingerprint") != self.fingerprint("overview"):
                entry["outdated"] = True
                self.overview = {}
        self.changed.emit()

    def started(self, section, request):
        self.active, self.active_request = section, copy.deepcopy(request)
        self.current_entry = None
        task = request.get("task", "")
        phase = "Generating / validating" if task in {"execute", "execute_batch", "font_repair"} else "Checking settings" if task in {"font_match", "font_catalogue"} else "Analyzing"
        self.progress.emit(0, 0, phase)
        self.changed.emit()

    def received(self, section, request, result):
        kind = "production" if request["task"] in {"execute", "execute_batch", "font_repair"} else "analysis"
        entry = {"section": section, "kind": kind, "source": self.label,
                 "generation": self.generation, "outdated": not self.is_current(),
                 "fingerprint": self.fingerprint(section),
                 "settings": {k: copy.deepcopy(v) for k, v in request.items() if k in {"task", "options", "policy", "output_name", "plan"}},
                 "input_files": [Path(p).name for p in request.get("sources", [request.get("source", self.sources[0])])],
                 "result": copy.deepcopy(result)}
        self.history.append(entry)
        self.current_entry = entry
        self.resultAdded.emit(entry)
        self.changed.emit()

    def failed(self, section, request, error):
        entry = {"section": section, "kind": "failure", "source": self.label,
                 "generation": self.generation, "outdated": not self.is_current(),
                 "settings": {"task": request.get("task", "")},
                 "result": {"status": "failed", "error": error}}
        self.history.append(entry)
        self.current_entry = entry
        self.resultAdded.emit(entry)
        self.changed.emit()

    def analyze_overview(self):
        if self.busy or not self.sources or not self.is_current():
            return
        request = {"task": "production_analyze", "sources": self.sources,
                   "policy": self.panels["fonts"].policy.currentData()}
        self.overview = {}
        self.overview_worker = Worker(Path(self.directory.name), request, self,
                                      worker_module="core.pdf_operations.worker", secrets=self.secrets)
        self.overview_worker.resultReady.connect(lambda value: self.overview_ready(request, value))
        self.overview_worker.failed.connect(lambda message: self.failed("overview", request, message))
        self.overview_worker.progress.connect(self.progress)
        self.overview_worker.ended.connect(self.overview_ended)
        self.started("overview", request)

    def overview_ready(self, request, value):
        if self.is_current():
            self.overview = value
            self.received("overview", request, value)

    def overview_ended(self):
        self.overview_worker = None
        self.ended()

    def ended(self):
        if not self.busy:
            self.active = ""
            self.changed.emit()
            self.idle.emit()

    def cancel(self):
        for worker in self.workers:
            worker.cancel()

    def stop(self):
        self.stopped = True
        self.monitor.stop()
        self.cancel()
        if not self.busy:
            self.cleanup()

    def cleanup(self):
        if self.busy:
            return
        for panel in self.panels.values():
            if hasattr(panel, "monitor"):
                panel.monitor.stop()
            panel.directory.cleanup()
        if self.snapshot_directory is not None:
            self.snapshot_directory.cleanup()
            self.snapshot_directory = None
        self.directory.cleanup()
