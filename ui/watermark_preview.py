"""One-page watermark preview; PDF operations run under the shared reader lease."""
from __future__ import annotations

from threading import Event

import fitz
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from core.diagnostics import log_failure, log_lifecycle
from core.pdf_engine import DOCUMENT_LOCK
from core.watermarks import WatermarkError, add_watermark, image_bytes, list_watermarks, remove_watermark
from ui.page_view import render_page_image


class _Signals(QObject):
    finished = pyqtSignal(object)


class WatermarkPreviewTask(QRunnable):
    def __init__(self, document, page, spec, image, image_path, snapshot, generation, existing_id):
        super().__init__()
        self.setAutoDelete(False)
        self.done, self.cancelled = Event(), Event()
        self.signals = _Signals()
        self.document, self.page, self.spec = document, page, spec
        self.image, self.image_path, self.snapshot = image, image_path, snapshot
        self.generation, self.existing_id = generation, existing_id

    def run(self):
        result = dict(generation=self.generation, image=None, snapshot=None, error=None)
        try:
            if self.cancelled.is_set():
                return
            with DOCUMENT_LOCK:
                if self.snapshot is None:
                    with fitz.open() as copy:
                        copy.insert_pdf(self.document, from_page=self.page, to_page=self.page)
                        self.snapshot = copy.tobytes()
                result["snapshot"] = self.snapshot
                if self.cancelled.is_set():
                    return
                with fitz.open(stream=self.snapshot, filetype="pdf") as copy:
                    page = copy[0]
                    if self.existing_id:
                        for entry in list_watermarks(page):
                            if entry["id"] == self.existing_id:
                                remove_watermark(page, entry["xref"])
                    image = image_bytes(self.image_path) if self.image_path else self.image
                    add_watermark(page, self.spec, image=image)
                    if self.cancelled.is_set():
                        return
                    zoom = min(600 / page.rect.width, 340 / page.rect.height)
                    result["image"] = render_page_image(copy, 0, zoom, 1.)
        except WatermarkError as exc:
            result["error"] = str(exc)
        except Exception:
            log_failure("Watermark preview failed")
            result["error"] = "Preview unavailable. Check the watermark size, image and position."
        finally:
            self.done.set()
            log_lifecycle("watermark.preview_finished", generation=self.generation,
                          cancelled=self.cancelled.is_set(), failed=result["error"] is not None)
            self.signals.finished.emit(result)
