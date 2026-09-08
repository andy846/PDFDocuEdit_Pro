"""Immutable print inputs and worker-safe preparation/rasterization."""

from dataclasses import dataclass

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QTransform

from .pdf_engine import DOCUMENT_LOCK
from .tasks import TaskCancelled


@dataclass(frozen=True)
class PrintJob:
    source: str | bytes
    name: str
    key: str
    pages: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PreparedPrintJob:
    data: bytes
    pages: tuple[int, ...]
    first_size: tuple[float, float]


@dataclass(frozen=True)
class PrintRenderSettings:
    dpi: int
    width: int
    height: int
    left: float
    top: float
    scale_mode: int
    scale: float
    center: bool
    offset_x: float
    offset_y: float


def _check_cancel(is_cancelled):
    if is_cancelled and is_cancelled():
        raise TaskCancelled


def prepare_print_job(job: PrintJob, *, is_cancelled=None) -> PreparedPrintJob:
    _check_cancel(is_cancelled)
    with DOCUMENT_LOCK:
        _check_cancel(is_cancelled)
        document = (fitz.open(stream=job.source, filetype="pdf")
                    if isinstance(job.source, bytes) else fitz.open(job.source))
        with document:
            if document.needs_pass:
                raise ValueError("The PDF requires a password.")
            pages = job.pages if job.pages is not None else tuple(range(document.page_count))
            if not pages or any(page < 0 or page >= document.page_count for page in pages):
                raise ValueError("No valid printable pages were selected.")
            rect = document[pages[0]].rect
            data = job.source if isinstance(job.source, bytes) else document.tobytes()
            prepared = PreparedPrintJob(data, pages, (rect.width, rect.height))
    _check_cancel(is_cancelled)
    return prepared


def render_page_image(page, settings: PrintRenderSettings):
    """Return an owned QImage and placement; no printer or GUI widget is accessed."""
    pix = page.get_pixmap(dpi=min(600, max(72, settings.dpi)), alpha=False)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                   QImage.Format.Format_RGB888).copy()
    if settings.scale_mode == 0:
        if (settings.width > settings.height) != (page.rect.width > page.rect.height):
            image = image.transformed(QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation)
        width, height = settings.width, settings.height
    else:
        factor = 1.0 if settings.scale_mode == 1 else settings.scale / 100.0
        width = max(1, int(page.rect.width / 72 * settings.dpi * factor))
        height = max(1, int(page.rect.height / 72 * settings.dpi * factor))
    image = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    x, y = settings.left, settings.top
    if settings.center:
        x += (settings.width - image.width()) / 2
        y += (settings.height - image.height()) / 2
    x += settings.offset_x / 25.4 * settings.dpi
    y += settings.offset_y / 25.4 * settings.dpi
    return image, int(x), int(y)


def render_print_page(prepared: PreparedPrintJob, index: int,
                      settings: PrintRenderSettings, *, is_cancelled=None):
    _check_cancel(is_cancelled)
    with DOCUMENT_LOCK:
        _check_cancel(is_cancelled)
        with fitz.open(stream=prepared.data, filetype="pdf") as document:
            result = render_page_image(document[prepared.pages[index]], settings)
    _check_cancel(is_cancelled)
    return result
