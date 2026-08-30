"""Page container with caption and a shared render cache for page pixmaps."""

from __future__ import annotations

from collections import OrderedDict

import fitz
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout

from styles.theme import is_dark
from styles.tokens import S

from .page_overlay import PageOverlay

CAPTION_H = 22
PAGE_SPACING = 16


class PageView(QFrame):
    """One page: overlay + drop shadow + optional page-number caption."""

    def __init__(self, page_num: int, page: fitz.Page, parent=None):
        super().__init__(parent)
        self.setObjectName("pageView")
        self.page_num = page_num
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S.XS)
        self.overlay = PageOverlay(page_num)
        self.overlay.set_geometry_info(
            page.rect, 1.0, page.rotation_matrix, page.derotation_matrix
        )
        self._shadow = QGraphicsDropShadowEffect(self.overlay)
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 7)
        self.overlay.setGraphicsEffect(self._shadow)
        layout.addWidget(self.overlay)
        self.caption = QLabel(self._caption_text(page))
        self.caption.setObjectName("pageCaption")
        self.caption.setFixedHeight(CAPTION_H)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.caption)
        self.update_theme()

    @staticmethod
    def _caption_text(page: fitz.Page) -> str:
        label = page.get_label()
        return f"Page {label}" if label else f"Page {page.number + 1}"

    def set_pixmap(self, pixmap: QPixmap, page: fitz.Page | None = None) -> None:
        self.overlay.set_pixmap(pixmap)
        if page is not None:
            self.caption.setText(self._caption_text(page))

    def set_show_caption(self, show: bool) -> None:
        self.caption.setVisible(show)

    def update_theme(self) -> None:
        self._shadow.setColor(QColor(0, 0, 0, 92 if is_dark() else 48))
        self._shadow.setEnabled(True)


class PageRenderCache:
    """LRU cache of rendered page pixmaps keyed by (doc, page, zoom, dpr)."""

    def __init__(self, limit: int = 24):
        self._limit = limit
        self._cache: OrderedDict[tuple, QPixmap] = OrderedDict()

    def get(self, key: tuple) -> QPixmap | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: tuple, pixmap: QPixmap) -> None:
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        while len(self._cache) > self._limit:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()

    def invalidate(self, document_id: int, pages: set[int]) -> None:
        """Drop only cached renders for the affected live-document pages."""
        stale = [
            key
            for key in self._cache
            if len(key) >= 2 and key[0] == document_id and int(key[1]) in pages
        ]
        for key in stale:
            self._cache.pop(key, None)


def render_page_image(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    dpr: float,
) -> QImage:
    """Render one page into a worker-thread-safe QImage."""
    page = doc.load_page(page_num)
    matrix = fitz.Matrix(zoom * dpr, zoom * dpr)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format.Format_RGB888,
    ).copy()
    image.setDevicePixelRatio(dpr)
    return image


def render_page_pixmap(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    dpr: float,
) -> QPixmap:
    result = QPixmap.fromImage(render_page_image(doc, page_num, zoom, dpr))
    result.setDevicePixelRatio(dpr)
    return result


def render_page_pixmap_quick(
    doc: fitz.Document,
    page_num: int,
    zoom: float,
    dpr: float,
    scale: float = 0.5,
) -> QPixmap:
    """Fast, low-resolution placeholder render shown while the full-quality
    background render catches up (keeps fast scrolling from showing blanks)."""
    page = doc.load_page(page_num)
    matrix = fitz.Matrix(zoom * dpr * scale, zoom * dpr * scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = QImage(
        pixmap.samples,
        pixmap.width,
        pixmap.height,
        pixmap.stride,
        QImage.Format.Format_RGB888,
    ).copy()
    result = QPixmap.fromImage(image)
    # The placeholder has fewer backing pixels, but it must keep the same
    # device-independent size as the final render. Using only dpr here made it
    # appear at scale of the page size (a small-page ghost) until the
    # full-quality task completed.
    result.setDevicePixelRatio(max(0.01, dpr * scale))
    return result


def page_view_size(page: fitz.Page, zoom: float) -> QSize:
    """Logical widget size for a page rendered at the given zoom."""
    return QSize(round(page.rect.width * zoom), round(page.rect.height * zoom))
