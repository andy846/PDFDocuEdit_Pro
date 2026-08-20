"""Interactive page overlay: renders a page pixmap with selection and search
highlights, and maps coordinates between widget space and PDF points."""

from __future__ import annotations

from enum import StrEnum
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


def widget_point_to_pdf(
    point: QPointF,
    page_rect: fitz.Rect,
    scale: float,
    derotation_matrix: fitz.Matrix | None = None,
) -> fitz.Point:
    """Map a widget point to the unrotated coordinates required by PyMuPDF."""
    rotated = fitz.Point(
        page_rect.x0 + point.x() * scale,
        page_rect.y0 + point.y() * scale,
    )
    return rotated * derotation_matrix if derotation_matrix is not None else rotated


def pdf_rect_to_widget(
    rect: fitz.Rect,
    page_rect: fitz.Rect,
    scale: float,
    rotation_matrix: fitz.Matrix | None = None,
) -> QRectF:
    if rotation_matrix is not None:
        rect = rect * rotation_matrix
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


class InteractionState(StrEnum):
    IDLE = "idle"
    SELECT = "select"
    NOTE = "note"
    INK = "ink"
    POLYGON = "polygon"


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
    polygonDrawn = pyqtSignal(int, object)  # (page_num, list[QPointF])

    def __init__(self, page_num: int, parent=None):
        super().__init__(parent)
        self._page_num = page_num
        self._pixmap: QPixmap | None = None
        self._page_rect = fitz.Rect()
        self._scale = 1.0
        self._rotation_matrix: fitz.Matrix | None = None
        self._derotation_matrix: fitz.Matrix | None = None
        self._selection_rects: list[fitz.Rect] = []
        self._search_rects: list[fitz.Rect] = []
        self._interaction_state = InteractionState.IDLE
        self._marquee: QRectF | None = None
        self._marquee_origin = QPointF()
        self._ink_points: list[QPointF] = []
        self._polygon_points: list[QPointF] = []
        self._preview: dict | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)

    def set_page_number(self, page_num: int) -> None:
        self._page_num = page_num

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.setFixedSize(pixmap.deviceIndependentSize().toSize())
        self.update()

    def set_geometry_info(
        self,
        page_rect: fitz.Rect,
        scale: float,
        rotation_matrix: fitz.Matrix | None = None,
        derotation_matrix: fitz.Matrix | None = None,
    ) -> None:
        self._page_rect = page_rect
        self._scale = scale
        self._rotation_matrix = rotation_matrix
        self._derotation_matrix = derotation_matrix

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

    def set_interaction_state(self, state: InteractionState | str) -> None:
        next_state = (
            state if isinstance(state, InteractionState) else InteractionState(state)
        )
        if next_state == self._interaction_state:
            return
        self._interaction_state = next_state
        self._marquee = None
        self._ink_points = []
        self._polygon_points = []
        self._preview = None
        self.releaseMouse()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if next_state == InteractionState.NOTE
            else (
                Qt.CursorShape.CrossCursor
                if next_state
                in {
                    InteractionState.SELECT,
                    InteractionState.INK,
                    InteractionState.POLYGON,
                }
                else Qt.CursorShape.ArrowCursor
            )
        )
        self.setCursor(cursor)
        self.update()

    def set_select_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.SELECT)
        elif self._interaction_state == InteractionState.SELECT:
            self.set_interaction_state(InteractionState.IDLE)

    def set_note_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.NOTE)
        elif self._interaction_state == InteractionState.NOTE:
            self.set_interaction_state(InteractionState.IDLE)

    def set_ink_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.INK)
        elif self._interaction_state == InteractionState.INK:
            self.set_interaction_state(InteractionState.IDLE)

    def set_polygon_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.POLYGON)
        elif self._interaction_state == InteractionState.POLYGON:
            self.set_interaction_state(InteractionState.IDLE)

    def set_preview(self, preview: dict | None) -> None:
        """Preview shape while drawing: {"kind": "rect"|"ink", ...}."""
        self._preview = preview
        self.update()

    def widget_to_pdf(self, pos: QPointF) -> fitz.Point:
        return widget_point_to_pdf(
            pos, self._page_rect, self._scale, self._derotation_matrix
        )

    def pdf_rect_to_widget(self, rect: fitz.Rect) -> QRectF:
        return pdf_rect_to_widget(
            rect, self._page_rect, self._scale, self._rotation_matrix
        )

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
            elif self._preview.get("kind") == "polygon":
                points = self._preview.get("points", [])
                fixed_count = int(self._preview.get("fixed_count", 0))
                if len(points) > 1:
                    for first, second in zip(points, points[1:], strict=False):
                        painter.drawLine(first, second)
                    if fixed_count >= 2:
                        painter.drawLine(points[-1], points[0])
                for point in points[:fixed_count]:
                    painter.drawEllipse(point, 3.0, 3.0)
        painter.end()

    # --- interaction -----------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if (
            self._interaction_state == InteractionState.SELECT
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._marquee_origin = event.position()
            self._marquee = QRectF(self._marquee_origin, self._marquee_origin)
            self.update()
            event.accept()
            return
        if (
            self._interaction_state == InteractionState.INK
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._ink_points = [event.position()]
            self.set_preview({"kind": "ink", "points": self._ink_points})
            event.accept()
            return
        if self._interaction_state == InteractionState.POLYGON:
            if event.button() == Qt.MouseButton.LeftButton:
                self._append_polygon_point(event.position())
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self._finish_polygon()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._marquee is not None:
            self._marquee = QRectF(self._marquee_origin, event.position()).normalized()
            self.update()
            event.accept()
            return
        if self._interaction_state == InteractionState.INK and self._ink_points:
            self._ink_points.append(event.position())
            self.set_preview({"kind": "ink", "points": self._ink_points})
            event.accept()
            return
        if self._interaction_state == InteractionState.POLYGON and self._polygon_points:
            self._update_polygon_preview(event.position())
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
        if (
            self._interaction_state == InteractionState.NOTE
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.noteClicked.emit(self._page_num, event.position())
            event.accept()
            return
        if self._interaction_state == InteractionState.POLYGON and event.button() in {
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        }:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if (
            self._interaction_state == InteractionState.POLYGON
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._append_polygon_point(event.position())
            self._finish_polygon()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _points_close(first: QPointF, second: QPointF, tolerance: float = 3.0) -> bool:
        return (
            abs(first.x() - second.x()) <= tolerance
            and abs(first.y() - second.y()) <= tolerance
        )

    def _append_polygon_point(self, point: QPointF) -> None:
        candidate = QPointF(point)
        if self._polygon_points and self._points_close(
            self._polygon_points[-1], candidate
        ):
            return
        self._polygon_points.append(candidate)
        self._update_polygon_preview()

    def _update_polygon_preview(self, hover: QPointF | None = None) -> None:
        points = list(self._polygon_points)
        if hover is not None:
            points.append(QPointF(hover))
        self.set_preview(
            {
                "kind": "polygon",
                "points": points,
                "fixed_count": len(self._polygon_points),
            }
        )

    def _finish_polygon(self) -> None:
        points = list(self._polygon_points)
        self._polygon_points = []
        self.set_preview(None)
        if len(points) >= 3:
            self.polygonDrawn.emit(self._page_num, points)
