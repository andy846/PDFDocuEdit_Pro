"""Small UI adapter: Workflow shares the existing detection review dialog."""
from __future__ import annotations

import copy

from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.model import EnvelopeSettings, SourceInfo

from .process import Worker


class WorkflowDetectionHost(QWidget):
    def __init__(self, owner, source):
        super().__init__(owner)
        self.hide()
        self.owner = owner
        self.source_path = owner.run.source
        self.database = owner.run.database
        self.directory = owner.directory
        self.font_token = None
        self.spec = EnvelopeSpec(SourceInfo(**source), EnvelopeSettings(pages_per_envelope=1))
        report = owner.spec.node("group").params.get("detection_review")
        if report and owner.run.groups and report.get("source_sha256") == source["sha256"]:
            from workflow.engine import detection_audit
            self.spec.settings.groups = copy.deepcopy(owner.run.groups)
            self.spec.detection_review = detection_audit(self.spec, report)

    @property
    def close_pending(self):
        return sip.isdeleted(self.owner) or self.owner.close_pending

    @property
    def active_worker(self):
        return self.owner.active_worker

    @property
    def draft_error(self):
        return self.owner.draft_error

    def worker(self, request, ready, failed=None, *, active=False):
        if self.close_pending or (active and self.active_worker):
            return None
        owner = self.owner
        worker = Worker(owner.directory, request, owner)
        owner.workers.append(worker)
        values, errors = [], []
        worker.resultReady.connect(values.append)
        worker.failed.connect(errors.append)
        if active:
            owner.active_worker = worker
            owner.lock()
        def ended():
            if sip.isdeleted(owner):
                return
            if worker in owner.workers:
                owner.workers.remove(worker)
            if worker is owner.active_worker:
                owner.active_worker = None
            if not owner.close_pending:
                if values:
                    ready(values[-1])
                elif errors and failed:
                    failed(errors[-1])
                owner.lock()
            elif not owner.workers:
                owner.close()
        worker.ended.connect(ended)
        return worker

    def commit(self, raw, label):
        if self.close_pending or self.owner.run.source != self.source_path or self.owner.run.database != self.database:
            self.owner.message("Workflow source changed. Scan and review again.")
            return False
        report = copy.deepcopy(raw["detection_review"])
        if not self.owner.params(self.owner.spec.node("group"), {"method": "reviewed_detection", "detection_review": report}):
            return False
        self.spec = EnvelopeSpec.from_dict(raw)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.owner.execute("review") if not self.close_pending else None)
        return True
