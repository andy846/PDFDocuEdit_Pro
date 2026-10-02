"""Bounded source preview requests with stale-result protection."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QObject, QTimer


class SourcePreview(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.generation = 0
        self.worker = None
        self.pending = None

    def request(self, source, page):
        self.generation += 1
        self.pending = (self.generation, dict(source), page)
        self.dialog.preview.loading = True
        self.dialog.preview.anchor = None
        self.dialog.preview_status.setText(f"Loading source page {page:,}…")
        if self.worker:
            self.worker.stop_preview()
        else:
            self.start_latest()

    def start_latest(self):
        if self.worker or not self.pending or self.dialog.window.close_pending:
            return
        generation, source, page = self.pending
        self.pending = None
        target = self.dialog.window.directory / f"detection-preview-{uuid4().hex}.png"
        def ready(value):
            try:
                if generation == self.generation:
                    self.dialog.preview.load(value["image"], value["geometry"])
                    self.dialog.preview_status.setText(f"Source page {page:,}")
            except (OSError, ValueError) as exc:
                failed(str(exc))
            finally:
                Path(value["image"]).unlink(missing_ok=True)
        def failed(message):
            if generation == self.generation:
                self.dialog.detail.setPlainText(message)
                self.dialog.preview_status.setText(f"Source page {page:,} could not be previewed.")
        def ended():
            self.worker = None
            target.unlink(missing_ok=True)
            QTimer.singleShot(0, self.start_latest)
        self.worker = self.dialog.window.worker({"task": "mailpiece_preview", "source": source["path"],
            "page": page, "target": str(target), "size": source["size"], "mtime_ns": source["mtime_ns"]}, ready, failed)
        if self.worker:
            self.worker.ended.connect(ended)

    def stop(self):
        self.generation += 1
        self.pending = None
        if self.worker:
            self.worker.stop_preview()
