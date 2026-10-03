"""Bounded source preview requests with stale-result protection."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QLabel, QVBoxLayout, QWidget


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
        if sip.isdeleted(self.dialog) or self.worker or not self.pending or self.dialog.window.close_pending:
            return
        generation, source, page = self.pending
        self.pending = None
        target = self.dialog.window.directory / f"detection-preview-{uuid4().hex}.png"
        def ready(value):
            try:
                if not sip.isdeleted(self.dialog) and generation == self.generation:
                    self.dialog.preview.load(value["image"], value["geometry"])
                    self.dialog.preview_status.setText(f"Source page {page:,}")
            except (OSError, ValueError) as exc:
                failed(str(exc))
            finally:
                Path(value["image"]).unlink(missing_ok=True)
        def failed(message):
            if not sip.isdeleted(self.dialog) and generation == self.generation:
                if getattr(self.dialog, "detail", None) is not None:
                    self.dialog.detail.setPlainText(message)
                self.dialog.preview_status.setText(f"Source page {page:,} could not be previewed.")
        def ended():
            self.worker = None
            target.unlink(missing_ok=True)
            QTimer.singleShot(0, self.start_latest)
        self.worker = self.dialog.window.worker({"task": "mailpiece_preview", "source": source["path"],
            "page": page, "target": str(target), "size": source["size"], "mtime_ns": source["mtime_ns"],
            "scale": max(1.5, self.dialog.preview.devicePixelRatioF()*1.5)}, ready, failed)
        if self.worker:
            self.worker.ended.connect(ended)

    def stop(self):
        self.generation += 1
        self.pending = None
        if self.worker:
            self.worker.stop_preview()


class ReadOnlySourceView(QGraphicsView):
    def __init__(self, parent):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumHeight(140)
        self.setMinimumWidth(120)
        self.loading = False
        self.fit_mode = True
        self.anchor = None

    def load(self, path, geometry):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            raise ValueError("Source preview could not be loaded.")
        self.scene().clear()
        item = self.scene().addPixmap(pixmap)
        item.setTransform(QTransform.fromScale(geometry["width_pt"]/pixmap.width(), geometry["height_pt"]/pixmap.height()))
        self.scene().setSceneRect(0, 0, geometry["width_pt"], geometry["height_pt"])
        self.fit_page()
        self.loading = False

    def fit_page(self):
        self.fit_mode = True
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
            if .05 <= self.transform().m11()*factor <= 8:
                self.fit_mode = False
                self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_page()


class PairedSourcePreview(QWidget):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.window = dialog.window
        self.detail = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.preview_status = QLabel("Second page")
        self.preview_status.setTextFormat(Qt.TextFormat.PlainText)
        self.preview = ReadOnlySourceView(self)
        self.controller = SourcePreview(self)
        layout.addWidget(self.preview)
        layout.addWidget(self.preview_status)

    def request(self, source, page):
        self.controller.request(source, page)

    def stop(self):
        self.controller.stop()
