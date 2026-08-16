"""Interactive page overlay: renders a page pixmap with selection and search
highlights, and maps coordinates between widget space and PDF points."""

from __future__ import annotations

from collections.abc import Iterable

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from styles.theme import get_colors

SELECTION_ALPHA = 56
SEARCH_ALPHA = 84
SEARCH_COLOR = "#ffd54a"


def scale_for_pixmap(page_rect: fitz.Rect, zoom: float) -> float:
    """PDF points per widget (logical) pixel for a rendering at ``zoom``."""
    return 1.0 / zoom if zoom else 1.0


def widget_point_to_pdf(point: QPointF, page_rect: fitz.Rect, scale: float) -> fitz.Point:
    """Map a widget point (relative to the overlay) to PDF points."""
    return fitz.Point(
        page_rect.x0 + point.x() * scale,
        page_rect.y0 + point.y() * scale,
    )


def pdf_rect_to_widget(rect: fitz.Rect, page_rect: fitz.Rect, scale: float) -> QRectF:
    return QRectF(
        (rect.x0 - page_rect.x0) / scale,
        (rect.y0 - page_rect.y0) / scale,
        rect.width / scale,
        rect.height / scale,
    )


def words_intersecting(page: fitz.Page, rect: fitz.Rect) -> list[tuple[fitz.Rect, str]]:
    """Return (rect, text) pairs for words intersecting a PDF rectangle."""
    return [
        (fitz.Rect(word[:4]), str(word[4]))
        for word in page.get_text("words")
        if fitz.Rect(word[:4]).intersects(rect)
    ]


def extract_words_in_rect(page: fitz.Page, rect: fitz.Rect) -> str:
    """Return the words intersecting a PDF rectangle, in reading order."""
    words = page.get_text("words")
    kept = [word for word in words if fitz.Rect(word[:4]).intersects(rect)]
    if not kept:
        return ""
    kept.sort(key=lambda word: (int(word[5]), int(word[6]), float(word[7])))
    return " ".join(str(word[4]) for word in kept)


class PageOverlay(QWidget):
    """Paints one page pixmap plus selection/search highlights and a marquee."""

    selectionMade = pyqtSignal(int, object)  # (page_num, QRectF in widget coords)
    inkDrawn = pyqtSignal(int, object)  # (page_num, list[QPointF] in widget coords)
    noteClicked = pyqtSignal(int, object)  # (page_num, QPointF in widget coords)

    def __init__(self, page_num: int, parent=None):
        super().__init__(parent)
        self._page_num = page_num
        self._pixmap: QPixmap | None = None
        self._page_rect = fitz.Rect()
        self._scale = 1.0
        self._selection_rects: list[fitz.Rect] = []
        self._search_rects: list[fitz.Rect] = []
        self._select_mode = False
        self._note_mode = False
        self._ink_mode = False
        self._marquee: QRectF | None = None
        self._marquee_origin = QPointF()
        self._ink_points: list[QPointF] = []
        self._preview: dict | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)

    def set_page_number(self, page_num: int) -> None:
        self._page_num = page_num

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.setFixedSize(pixmap.deviceIndependentSize().toSize())
        self.update()

    def set_geometry_info(self, page_rect: fitz.Rect, scale: float) -> None:
        self._page_rect = page_rect
        self._scale = scale

    def set_selection_rects(self, rects: Iterable[fitz.Rect]) -> None:
        self._selection_rects = list(rects)
        self.update()

    def set_search_rects(self, rects: Iterable[fitz.Rect]) -> None:
        self._search_rects = list(rects)
        self.update()

    def clear_highlights(self) -> None:
        self._selection_rects = []
        self._search_rects = []
        self.update()

    def set_select_mode(self, enabled: bool) -> None:
        self._select_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._note_mode and not self._ink_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_note_mode(self, enabled: bool) -> None:
        self._note_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif not self._select_mode and not self._ink_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_ink_mode(self, enabled: bool) -> None:
        self._ink_mode = enabled
        self._ink_points = []
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._select_mode and not self._note_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_preview(self, preview: dict | None) -> None:
        """Preview shape while drawing: {"kind": "rect"|"ink", ...}."""
        self._preview = preview
        self.update()

    def widget_to_pdf(self, pos: QPointF) -> fitz.Point:
        return widget_point_to_pdf(pos, self._page_rect, self._scale)

    def pdf_rect_to_widget(self, rect: fitz.Rect) -> QRectF:
        return pdf_rect_to_widget(rect, self._page_rect, self._scale)

    # --- painting --------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self._pixmap:
            painter.drawPixmap(0, 0, self._pixmap)
        colors = get_colors()
        if self._search_rects:
            search = QColor(SEARCH_COLOR)
            search.setAlpha(SEARCH_ALPHA)
            for rect in self._search_rects:
                painter.fillRect(self.pdf_rect_to_widget(rect), search)
        if self._selection_rects:
            highlight = QColor(colors["primary"])
            highlight.setAlpha(SELECTION_ALPHA)
            for rect in self._selection_rects:
                painter.fillRect(self.pdf_rect_to_widget(rect), highlight)
        if self._marquee:
            border = QColor(colors["primary"])
            border.setAlpha(160)
            soft = QColor(colors["primary_soft"])
            soft.setAlpha(140)
            painter.fillRect(self._marquee, soft)
            painter.setPen(border)
            painter.drawRect(self._marquee)
        if self._preview:
            preview_color = QColor(colors["primary"])
            preview_color.setAlpha(200)
            painter.setPen(preview_color)
            if self._preview.get("kind") == "ink":
                points = self._preview.get("points", [])
                if len(points) > 1:
                    for first, second in zip(points, points[1:], strict=False):
                        painter.drawLine(first, second)
            elif self._preview.get("kind") == "rect":
                rect = self._preview.get("rect")
                if rect:
                    painter.drawRect(rect)
        painter.end()

    # --- interaction -----------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._select_mode and event.button() == Qt.MouseButton.LeftButton:
            self._marquee_origin = event.position()
            self._marquee = QRectF(self._marquee_origin, self._marquee_origin)
            self.update()
            event.accept()
            return
        if self._ink_mode and event.button() == Qt.MouseButton.LeftButton:
            self._ink_points = [event.position()]
            self.set_preview({"kind": "ink", "points": self._ink_points})
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._marquee is not None:
            self._marquee = QRectF(self._marquee_origin, event.position()).normalized()
            self.update()
            event.accept()
            return
        if self._ink_mode and self._ink_points:
            self._ink_points.append(event.position())
            self.set_preview({"kind": "ink", "points": self._ink_points})
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._marquee is not None and event.button() == Qt.MouseButton.LeftButton:
            self._marquee = QRectF(self._marquee_origin, event.position()).normalized()
            self.update()
            released = QRectF(self._marquee)
            self._marquee = None
            self.selectionMade.emit(self._page_num, released)
            event.accept()
            return
        if self._ink_points and event.button() == Qt.MouseButton.LeftButton:
            points = list(self._ink_points)
            self._ink_points = []
            self.set_preview(None)
            self.inkDrawn.emit(self._page_num, points)
            event.accept()
            return
        if self._note_mode and event.button() == Qt.MouseButton.LeftButton:
            self.noteClicked.emit(self._page_num, event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)
