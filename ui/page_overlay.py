"""Interactive page overlay: renders a page pixmap with selection and search
highlights, and maps coordinates between widget space and PDF points."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from math import hypot

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget

from core.measurement import SavedMeasurement, distance_mm, format_distance
from core.page_images import IMAGE_KINDS
from styles.theme import get_colors

SELECTION_ALPHA = 56
SEARCH_ALPHA = 84
SEARCH_COLOR = "#ffd54a"


class InlineTextEditor(QLineEdit):
    """Small canvas editor with explicit commit/cancel keyboard semantics."""

    finishRequested = pyqtSignal(bool)
    nudgeRequested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._finished = False

    def keyPressEvent(self, event) -> None:
        if (
            str(self.property("editorMode") or "") == "typewriter"
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
            and event.key()
            in {
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
            }
        ):
            step = (
                5
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                else 1
            )
            offsets = {
                Qt.Key.Key_Left: (-step, 0),
                Qt.Key.Key_Right: (step, 0),
                Qt.Key.Key_Up: (0, -step),
                Qt.Key.Key_Down: (0, step),
            }
            self.nudgeRequested.emit(*offsets[event.key()])
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._request_finish(False)
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._request_finish(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._request_finish(True)

    def _request_finish(self, commit: bool) -> None:
        if self._finished:
            return
        self._finished = True
        self.finishRequested.emit(commit)


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
    FONT_INSPECT = "font_inspect"
    FORM = "form"
    NOTE = "note"
    INK = "ink"
    LINE = "line"
    MEASURE = "measure"
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
    lineDrawn = pyqtSignal(int, object)  # (page_num, [start, end] QPointF)
    measurementDrawn = pyqtSignal(int, object)  # page, two PDF points
    measurementSelected = pyqtSignal(int, int)  # page, temporary line index
    measurementContextRequested = pyqtSignal(int, int, object)
    savedMeasurementSelected = pyqtSignal(int, str)
    savedMeasurementContextRequested = pyqtSignal(int, str, object)
    legacyMeasurementSelected = pyqtSignal(int, int)
    measurementMoved = pyqtSignal(int, object, object)
    polygonDrawn = pyqtSignal(int, object)  # (page_num, list[QPointF])
    annotationSelected = pyqtSignal(int, int)
    annotationSelectionCleared = pyqtSignal(int)
    annotationContextRequested = pyqtSignal(int, int, object)
    pageContextRequested = pyqtSignal(object)
    annotationGeometryChanged = pyqtSignal(int, int, object)
    annotationTextChanged = pyqtSignal(int, int, str)
    typewriterCommitted = pyqtSignal(int, object, str)
    fontInspectClicked = pyqtSignal(int, object)
    formClicked = pyqtSignal(int, object)

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
        self._form_rects: list[fitz.Rect] = []
        self._font_inspection_rect: fitz.Rect | None = None
        self._interaction_state = InteractionState.IDLE
        self._marquee: QRectF | None = None
        self._marquee_origin = QPointF()
        self._ink_points: list[QPointF] = []
        self._line_origin: QPointF | None = None
        self._line_endpoint: QPointF | None = None
        self._line_arrow = False
        self._line_color = "#1a73e8"
        self._line_width = 1.5
        self._line_opacity = 1.0
        self._measure_origin: fitz.Point | None = None
        self._measure_endpoint: fitz.Point | None = None
        self._measure_press_pos: QPointF | None = None
        self._measure_press_dragged = False
        self._reference_guides = ()
        self._measure_snapper = None
        self._measurements: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._selected_measurement: int | None = None
        self._measure_unit = "mm"
        self._measure_factor = 1.0
        self._measure_scale_state = "paper"
        self._measure_scale_missing = False
        self._saved_measurements: list[SavedMeasurement] = []
        self._selected_saved_measurement: str | None = None
        self._measure_drag: dict | None = None
        self._measure_preview: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._polygon_points: list[QPointF] = []
        self._preview: dict | None = None
        self._annotations: list[dict] = []
        self._annotations_editable = True
        self._selected_xref: int | None = None
        self._geometry_drag: dict | None = None
        self._active_preview_style: dict[str, object] = {
            "kind": "rect", "color": "#1a73e8", "fill": "",
            "width": 1.5, "opacity": 1.0,
        }
        self._inline_editor: InlineTextEditor | None = None
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

    def set_form_rects(self, rects: Iterable[fitz.Rect]) -> None:
        self._form_rects = list(rects)
        self.update()

    def set_font_inspection_rect(self, rect: fitz.Rect | None) -> None:
        self._font_inspection_rect = fitz.Rect(rect) if rect is not None else None
        self.update()

    def set_annotations(self, annotations: Iterable[dict]) -> None:
        self._annotations = list(annotations)
        if self._selected_xref is not None and not any(
            int(entry.get("xref", -1)) == self._selected_xref
            for entry in self._annotations
        ):
            self._selected_xref = None
        self.update()

    def set_measurements(
        self,
        measurements: Iterable[tuple[tuple[float, float], tuple[float, float]]],
        unit: str = "mm",
        selected: int | None = None,
        *,
        scale: float = 1.0,
        saved: Iterable[SavedMeasurement] = (),
        selected_saved: str | None = None,
        scale_state: str = "paper",
        missing_calibration: bool = False,
    ) -> None:
        self._measurements = list(measurements)
        self._measure_unit = unit
        self._selected_measurement = selected
        self._measure_factor = scale
        self._measure_scale_state = scale_state
        self._measure_scale_missing = missing_calibration
        self._saved_measurements = list(saved)
        self._selected_saved_measurement = selected_saved
        self.update()

    def set_measure_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.MEASURE)
        elif self._interaction_state == InteractionState.MEASURE:
            self.set_interaction_state(InteractionState.IDLE)

    def cancel_measurement(self) -> None:
        self._measure_origin = None
        self._measure_endpoint = None
        self._measure_press_pos = None
        self._measure_press_dragged = False
        if self._measure_drag is not None:
            drag = self._measure_drag
            if drag["kind"] == "temporary":
                self._measurements[drag["key"]] = drag["original"]
            self._measure_drag = None
            self._measure_preview = None
        self.update()

    def set_annotations_editable(self, editable: bool) -> None:
        """Allow annotation selection while blocking mutation in comparison panes."""

        self._annotations_editable = bool(editable)
        if not self._annotations_editable:
            self._geometry_drag = None
            self.cancel_measurement()
            if self._inline_editor is not None:
                self._finish_inline_editor(False)

    def select_annotation(self, xref: int | None) -> None:
        self._selected_xref = int(xref) if xref is not None else None
        self.update()

    def clear_highlights(self) -> None:
        self._selection_rects = []
        self._search_rects = []
        self._font_inspection_rect = None
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
        self._line_origin = None
        self._line_endpoint = None
        self.cancel_measurement()
        self._polygon_points = []
        self._preview = None
        self.releaseMouse()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if next_state in {InteractionState.NOTE, InteractionState.FONT_INSPECT, InteractionState.FORM}
            else (
                Qt.CursorShape.CrossCursor
                if next_state
                in {
                    InteractionState.SELECT,
                    InteractionState.INK,
                    InteractionState.LINE,
                    InteractionState.MEASURE,
                    InteractionState.POLYGON,
                }
                else Qt.CursorShape.ArrowCursor
            )
        )
        self.setCursor(cursor)
        self.update()

    def set_form_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.FORM)
        elif self._interaction_state == InteractionState.FORM:
            self.set_interaction_state(InteractionState.IDLE)

    def set_font_inspect_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.FONT_INSPECT)
        elif self._interaction_state == InteractionState.FONT_INSPECT:
            self.set_interaction_state(InteractionState.IDLE)

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

    def set_line_mode(
        self,
        enabled: bool,
        *,
        arrow: bool = False,
        color: str = "#1a73e8",
        width: float = 1.5,
        opacity: float = 1.0,
    ) -> None:
        self._line_arrow = bool(arrow)
        self._line_color = str(color)
        self._line_width = max(0.5, float(width))
        self._line_opacity = max(0.0, min(1.0, float(opacity)))
        if enabled:
            self.set_interaction_state(InteractionState.LINE)
        elif self._interaction_state == InteractionState.LINE:
            self.set_interaction_state(InteractionState.IDLE)
        self.update()

    def set_polygon_mode(self, enabled: bool) -> None:
        if enabled:
            self.set_interaction_state(InteractionState.POLYGON)
        elif self._interaction_state == InteractionState.POLYGON:
            self.set_interaction_state(InteractionState.IDLE)

    def set_preview(self, preview: dict | None) -> None:
        """Preview the active geometry while drawing."""
        self._preview = preview
        self.update()

    def set_annotation_preview_style(
        self,
        kind: str,
        *,
        color: str,
        fill: str = "",
        width: float = 1.5,
        opacity: float = 1.0,
    ) -> None:
        self._active_preview_style = {
            "kind": str(kind), "color": str(color), "fill": str(fill),
            "width": max(0.5, float(width)),
            "opacity": max(0.0, min(1.0, float(opacity))),
        }
        self.update()

    def widget_to_pdf(self, pos: QPointF) -> fitz.Point:
        return widget_point_to_pdf(
            pos, self._page_rect, self._scale, self._derotation_matrix
        )

    def pdf_point_to_widget(self, point: tuple[float, float] | fitz.Point) -> QPointF:
        pdf = fitz.Point(point)
        if self._rotation_matrix is not None:
            pdf = pdf * self._rotation_matrix
        return QPointF(
            (pdf.x - self._page_rect.x0) / self._scale,
            (pdf.y - self._page_rect.y0) / self._scale,
        )

    def _bounded_pdf_point(self, pos: QPointF) -> fitz.Point:
        point = self.widget_to_pdf(pos)
        bounds = fitz.Rect(self._page_rect)
        if self._derotation_matrix is not None:
            bounds = bounds * self._derotation_matrix
        return fitz.Point(
            max(bounds.x0, min(point.x, bounds.x1)),
            max(bounds.y0, min(point.y, bounds.y1)),
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
        if self._form_rects:
            painter.setPen(QPen(QColor(colors["primary"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for rect in self._form_rects:
                painter.drawRoundedRect(self.pdf_rect_to_widget(rect), 3.0, 3.0)
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
        if self._font_inspection_rect is not None:
            rect = self.pdf_rect_to_widget(self._font_inspection_rect)
            fill = QColor(colors["accent_cyan_soft"])
            fill.setAlpha(145)
            painter.fillRect(rect, fill)
            pen = QPen(QColor(colors["accent_cyan"]))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4.0, 4.0)
        if self._marquee:
            style = self._active_preview_style
            border = QColor(str(style.get("color") or colors["primary"]))
            border.setAlpha(
                max(110, round(255 * float(style.get("opacity", 1.0))))
            )
            fill_name = str(style.get("fill") or style.get("color") or colors["primary_soft"])
            soft = QColor(fill_name)
            soft.setAlpha(max(28, min(100, border.alpha())))
            painter.fillRect(self._marquee, soft)
            pen = QPen(border)
            pen.setWidthF(max(1.0, float(style.get("width", 1.5)) / max(self._scale, 0.001)))
            painter.setPen(pen)
            painter.drawRect(self._marquee)
            if style.get("kind") == "redact":
                step = 10
                x = int(self._marquee.left() - self._marquee.height())
                while x < int(self._marquee.right()):
                    painter.drawLine(
                        QPointF(x, self._marquee.bottom()),
                        QPointF(x + self._marquee.height(), self._marquee.top()),
                    )
                    x += step
            guide = QPen(QColor(colors["primary"]))
            guide.setWidthF(2.0)
            guide.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._marquee.adjusted(-2, -2, 2, 2))
            painter.setBrush(QColor(colors["primary"]))
            for point in (
                self._marquee.topLeft(),
                self._marquee.topRight(),
                self._marquee.bottomLeft(),
                self._marquee.bottomRight(),
            ):
                painter.drawEllipse(point, 3.5, 3.5)
        if self._preview:
            style = self._active_preview_style
            preview_color = QColor(str(style.get("color") or colors["primary"]))
            preview_color.setAlpha(round(255 * float(style.get("opacity", 1.0))))
            preview_pen = QPen(preview_color)
            preview_pen.setWidthF(
                max(1.0, float(style.get("width", 1.5)) / max(self._scale, 0.001))
            )
            painter.setPen(preview_pen)
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
            elif self._preview.get("kind") in {"line", "arrow"}:
                points = self._preview.get("points", [])
                if len(points) == 2:
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    color = QColor(str(self._preview.get("color", colors["primary"])))
                    opacity = max(
                        0.0, min(1.0, float(self._preview.get("opacity", 1.0)))
                    )
                    color.setAlpha(round(255 * opacity))
                    width = max(
                        1.0,
                        float(self._preview.get("width", 1.5))
                        / max(self._scale, 0.001),
                    )
                    pen = QPen(color)
                    pen.setWidthF(width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    start, end = points
                    painter.drawLine(start, end)
                    if self._preview.get("kind") == "arrow":
                        self._paint_arrow_head(painter, start, end, width)
                    handle_radius = max(3.5, min(7.0, width + 2.0))
                    handle = QColor(color)
                    handle.setAlpha(max(120, color.alpha()))
                    painter.setBrush(handle)
                    painter.drawEllipse(start, handle_radius, handle_radius)
                    painter.drawEllipse(end, handle_radius, handle_radius)
        if self._reference_guides:
            painter.save()
            pen = QPen(QColor(colors["accent_cyan"]), 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for first, last in self._reference_guides:
                painter.drawLine(self.pdf_point_to_widget(first), self.pdf_point_to_widget(last))
            painter.restore()
        self._paint_measurements(painter, colors)
        self._paint_selected_annotation(painter, colors)
        painter.end()

    def _paint_measurements(self, painter: QPainter, colors: dict) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._interaction_state == InteractionState.MEASURE:
            if self._measure_scale_state == "calibrated":
                scale_label = f"Actual size 1:{self._measure_factor:g}"
            elif self._measure_scale_state == "invalid":
                scale_label = "Paper size · invalid calibration"
            else:
                scale_label = "Paper size · uncalibrated"
            if self._measure_scale_missing:
                scale_label += " · previous scale missing"
            bounds = QFontMetrics(painter.font()).boundingRect(scale_label)
            badge = QRectF(8, 8, bounds.width() + 18, bounds.height() + 10)
            painter.fillRect(badge, QColor("#ffffff"))
            painter.setPen(QColor(colors["primary"]))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, scale_label)
        entries = list(self._measurements)
        if self._measure_origin is not None and self._measure_endpoint is not None:
            entries.append((
                (self._measure_origin.x, self._measure_origin.y),
                (self._measure_endpoint.x, self._measure_endpoint.y),
            ))
        for index, (start_pdf, end_pdf) in enumerate(entries):
            start = self.pdf_point_to_widget(start_pdf)
            end = self.pdf_point_to_widget(end_pdf)
            selected = index == self._selected_measurement
            pen = QPen(QColor(colors["primary"]), 1.5 if selected else 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(colors["primary"]))
            painter.drawLine(start, end)
            self._paint_measure_endpoint(painter, start, colors["primary"], end)
            self._paint_measure_endpoint(painter, end, colors["primary"], start)
            label = format_distance(
                distance_mm(start_pdf, end_pdf) * self._measure_factor,
                self._measure_unit,
            )
            midpoint = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            font = QFont(painter.font())
            font.setPointSizeF(10.0)
            painter.setFont(font)
            bounds = QFontMetrics(font).boundingRect(label)
            label_rect = QRectF(midpoint.x() - bounds.width() / 2 - 5,
                                midpoint.y() - bounds.height() - 10,
                                bounds.width() + 10, bounds.height() + 4)
            painter.fillRect(label_rect, QColor("#ffffff"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
        for record in self._saved_measurements:
            if record.identifier != self._selected_saved_measurement:
                continue
            points = (self._measure_preview if self._measure_drag is not None
                      and self._measure_drag["kind"] == "saved"
                      and self._measure_drag["key"] == record.identifier
                      else record.points)
            start = self.pdf_point_to_widget(points[0])
            end = self.pdf_point_to_widget(points[1])
            painter.setPen(QPen(QColor(colors["primary"]), 2.5))
            painter.setBrush(QColor(colors["primary"]))
            if self._measure_preview is not None:
                painter.drawLine(start, end)
                label = format_distance(distance_mm(*points) * self._measure_factor,
                                        record.unit)
                painter.drawText(QPointF((start.x() + end.x()) / 2,
                                          (start.y() + end.y()) / 2 - 10), label)
            self._paint_measure_endpoint(painter, start, colors["primary"], end)
            self._paint_measure_endpoint(painter, end, colors["primary"], start)

    @staticmethod
    def _paint_measure_endpoint(painter, point, color, toward=None):
        """A short dimension tick centred on the exact endpoint; no filled handle."""
        dx = toward.x()-point.x() if toward is not None else 1
        dy = toward.y()-point.y() if toward is not None else 0
        length = hypot(dx, dy)
        nx, ny = (-dy/length*5, dx/length*5) if length else (0, 5)
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for stroke, width in (("#ffffff", 2.5), (color, 1.0)):
            pen = QPen(QColor(stroke), width)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(point.x()-nx, point.y()-ny), QPointF(point.x()+nx, point.y()+ny))
        painter.restore()

    def _measure_target(self, pos: QPointF):
        candidates = [("temporary", index, points)
                      for index, points in enumerate(self._measurements)]
        candidates += [("saved", item.identifier, item.points)
                       for item in self._saved_measurements]
        for kind, key, points in reversed(candidates):
            first, second = (self.pdf_point_to_widget(value) for value in points)
            for endpoint, handle in enumerate((first, second)):
                if hypot(pos.x() - handle.x(), pos.y() - handle.y()) <= 10:
                    return kind, key, endpoint, points
            if self._distance_to_segment(pos, first, second) <= 8:
                return kind, key, None, points
        return None

    def _measure_point(self, position, modifiers, anchor=None):
        position = QPointF(position)
        fixed_axis = None
        if anchor is not None and modifiers & Qt.KeyboardModifier.ShiftModifier:
            fixed = self.pdf_point_to_widget(anchor)
            if abs(position.x()-fixed.x()) >= abs(position.y()-fixed.y()):
                position.setY(fixed.y())
                fixed_axis = "y"
            else:
                position.setX(fixed.x())
                fixed_axis = "x"
        if self._measure_snapper is not None:
            position = self._measure_snapper(self, position, modifiers, fixed_axis)
        return self._bounded_pdf_point(position)

    def _move_measure_endpoint(self, position, modifiers):
        drag = self._measure_drag
        previous = self._measure_preview or drag["original"]
        points = list(drag["original"])
        fixed = points[1-drag["endpoint"]]
        point = self._measure_point(position-drag["grab_offset"], modifiers, fixed)
        points[drag["endpoint"]] = (point.x, point.y)
        preview = (points[0], points[1])
        self._measure_preview = preview
        if drag["kind"] == "temporary":
            self._measurements[drag["key"]] = preview
        self._update_measure_area(previous, preview)

    def _update_measure_area(self, previous, current):
        """Repaint old/new line and labels, rather than the entire zoomed page."""
        font = QFont(self.font())
        font.setPointSizeF(10)
        metrics = QFontMetrics(font)
        dirty = QRectF()
        unit = self._measure_unit
        if self._measure_drag is not None and self._measure_drag["kind"] == "saved":
            record = next((item for item in self._saved_measurements
                           if item.identifier == self._measure_drag["key"]), None)
            if record is not None:
                unit = record.unit
        for points in (previous, current):
            start, end = (self.pdf_point_to_widget(point) for point in points)
            line = QRectF(start, end).normalized().adjusted(-9, -9, 9, 9)
            text = format_distance(distance_mm(*points)*self._measure_factor, unit)
            bounds = metrics.boundingRect(text)
            midpoint = QPointF((start.x()+end.x())/2, (start.y()+end.y())/2)
            # Temporary labels are centred; saved previews start at midpoint.
            label = QRectF(midpoint.x()-bounds.width()/2-8, midpoint.y()-bounds.height()-14,
                           bounds.width()*1.5+16, bounds.height()+20)
            dirty = dirty.united(line).united(label)
        self.update(dirty.toAlignedRect())

    def _hit_measurement(self, pos: QPointF) -> int | None:
        for index in range(len(self._measurements) - 1, -1, -1):
            start_pdf, end_pdf = self._measurements[index]
            start = self.pdf_point_to_widget(start_pdf)
            end = self.pdf_point_to_widget(end_pdf)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length2 = dx * dx + dy * dy
            if length2 < 1:
                continue
            t = max(0.0, min(1.0,
                ((pos.x() - start.x()) * dx + (pos.y() - start.y()) * dy) / length2))
            if hypot(pos.x() - start.x() - t * dx,
                     pos.y() - start.y() - t * dy) <= 8.0:
                return index
        return None

    def _selected_entry(self) -> dict | None:
        return next(
            (
                entry
                for entry in self._annotations
                if int(entry.get("xref", -1)) == self._selected_xref
            ),
            None,
        )

    def _entry_widget_points(self, entry: dict) -> list[QPointF]:
        return [
            self.pdf_rect_to_widget(fitz.Rect(x, y, x, y)).topLeft()
            for x, y in entry.get("vertices", ())
        ]

    def _paint_selected_annotation(self, painter: QPainter, colors: dict) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(colors["primary"]))
        pen.setWidthF(1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(colors["primary"]))
        if str(entry.get("kind")) == "Line":
            points = self._entry_widget_points(entry)[:2]
            if self._geometry_drag and self._geometry_drag.get("points"):
                points = self._geometry_drag["points"]
            if len(points) == 2:
                painter.drawLine(points[0], points[1])
                for point in points:
                    if entry.get("subject") == "Measurement":
                        other = points[1] if point == points[0] else points[0]
                        self._paint_measure_endpoint(painter, point, colors["primary"], other)
                    else:
                        painter.drawEllipse(point, 5.0, 5.0)
            return
        rect = self.pdf_rect_to_widget(fitz.Rect(entry["rect"]))
        if self._geometry_drag and self._geometry_drag.get("rect") is not None:
            rect = self._geometry_drag["rect"]
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.setBrush(QColor(colors["primary"]))
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))

    @staticmethod
    def _paint_arrow_head(
        painter: QPainter, start: QPointF, end: QPointF, width: float
    ) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = hypot(dx, dy)
        if length < 0.001:
            return
        unit_x = dx / length
        unit_y = dy / length
        head = max(10.0, min(26.0, 9.0 + width * 3.0))
        wing = head * 0.5
        base_x = end.x() - unit_x * head
        base_y = end.y() - unit_y * head
        perpendicular_x = -unit_y
        perpendicular_y = unit_x
        first = QPointF(
            base_x + perpendicular_x * wing,
            base_y + perpendicular_y * wing,
        )
        second = QPointF(
            base_x - perpendicular_x * wing,
            base_y - perpendicular_y * wing,
        )
        painter.drawLine(end, first)
        painter.drawLine(end, second)

    # --- interaction -----------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._interaction_state == InteractionState.MEASURE:
            target = (self._measure_target(event.position())
                      if self._measure_origin is None else None)
            if target is not None:
                kind, key, endpoint, points = target
                if kind == "temporary":
                    self._selected_measurement = key
                    self._selected_saved_measurement = None
                    self.measurementSelected.emit(self._page_num, key)
                else:
                    self._selected_measurement = None
                    self._selected_saved_measurement = key
                    self.savedMeasurementSelected.emit(self._page_num, key)
                self.update()
                if event.button() == Qt.MouseButton.RightButton:
                    position = self.mapToGlobal(event.position().toPoint())
                    if kind == "temporary":
                        self.measurementContextRequested.emit(self._page_num, key, position)
                    else:
                        self.savedMeasurementContextRequested.emit(self._page_num, key, position)
                elif (event.button() == Qt.MouseButton.LeftButton
                      and endpoint is not None and self._annotations_editable):
                    self._measure_drag = {"kind": kind, "key": key,
                                          "endpoint": endpoint, "original": points,
                                          "grab_offset": event.position()-self.pdf_point_to_widget(points[endpoint])}
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
            legacy = self._hit_annotation(event.position())
            if (legacy is not None and legacy.get("kind") == "Line"
                    and legacy.get("subject") == "Measurement"):
                self.legacyMeasurementSelected.emit(self._page_num, legacy["xref"])
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self.pageContextRequested.emit(self.mapToGlobal(event.position().toPoint()))
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                if not self._annotations_editable:
                    event.accept()
                    return
                point = self._measure_point(event.position(), event.modifiers(), self._measure_origin)
                if self._measure_origin is None:
                    self._measure_origin = point
                    self._measure_endpoint = point
                    self._measure_press_pos = QPointF(event.position())
                    self._measure_press_dragged = False
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                else:
                    start = self._measure_origin
                    self.cancel_measurement()
                    if hypot(point.x - start.x, point.y - start.y) > 0.01:
                        self.measurementDrawn.emit(self._page_num, (
                            (start.x, start.y), (point.x, point.y)
                        ))
                self.update()
                event.accept()
                return
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
        if (
            self._interaction_state == InteractionState.LINE
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._line_origin = QPointF(event.position())
            self._line_endpoint = QPointF(event.position())
            self._update_line_preview()
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
        if self._interaction_state == InteractionState.IDLE:
            entry = self._hit_annotation(event.position())
            if event.button() == Qt.MouseButton.RightButton:
                if entry is not None:
                    self._select_entry(entry)
                    if self._annotations_editable:
                        self.annotationContextRequested.emit(
                            self._page_num,
                            int(entry["xref"]),
                            self.mapToGlobal(event.position().toPoint()),
                        )
                    else:
                        self.pageContextRequested.emit(
                            self.mapToGlobal(event.position().toPoint())
                        )
                else:
                    self.pageContextRequested.emit(
                        self.mapToGlobal(event.position().toPoint())
                    )
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                if entry is None:
                    self._selected_xref = None
                    self.annotationSelectionCleared.emit(self._page_num)
                    self.update()
                else:
                    self._select_entry(entry)
                    if self._annotations_editable:
                        self._begin_geometry_drag(entry, event.position())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._measure_drag is not None:
            self._move_measure_endpoint(event.position(), event.modifiers())
            event.accept()
            return
        if self._interaction_state == InteractionState.MEASURE and self._measure_origin is not None:
            previous = (self._measure_origin, self._measure_endpoint)
            self._measure_endpoint = self._measure_point(event.position(), event.modifiers(), self._measure_origin)
            if self._measure_press_pos is not None:
                delta = event.position()-self._measure_press_pos
                self._measure_press_dragged |= hypot(delta.x(), delta.y()) >= QApplication.startDragDistance()
            self._update_measure_area(previous, (self._measure_origin, self._measure_endpoint))
            event.accept()
            return
        if self._geometry_drag is not None:
            self._update_geometry_drag(event.position())
            event.accept()
            return
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
        if (
            self._interaction_state == InteractionState.LINE
            and self._line_origin is not None
        ):
            self._line_endpoint = QPointF(event.position())
            self._update_line_preview()
            event.accept()
            return
        if self._interaction_state == InteractionState.POLYGON and self._polygon_points:
            self._update_polygon_preview(event.position())
            event.accept()
            return

        if self._interaction_state == InteractionState.IDLE and self._annotations_editable:
            entry = self._hit_annotation(event.position())
            cursor = Qt.CursorShape.ArrowCursor
            if entry is not None and entry.get("kind") in IMAGE_KINDS:
                rect = self.pdf_rect_to_widget(fitz.Rect(entry["rect"]))
                corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
                handle = next((index for index, value in enumerate(corners)
                               if hypot(event.position().x() - value.x(), event.position().y() - value.y()) <= 10), None)
                cursor = (Qt.CursorShape.SizeFDiagCursor if handle in {0, 3}
                          else Qt.CursorShape.SizeBDiagCursor if handle is not None
                          else Qt.CursorShape.SizeAllCursor)
            self.setCursor(cursor)

        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self._interaction_state == InteractionState.MEASURE:
            # The mouse press already opened the measurement or page menu.
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._measure_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            drag = self._measure_drag
            self._move_measure_endpoint(event.position(), event.modifiers())
            points = self._measure_preview
            self._measure_drag = None
            self._measure_preview = None
            if points is not None and points != drag["original"]:
                self.measurementMoved.emit(self._page_num, drag["key"], points)
            self.update()
            event.accept()
            return
        if (self._interaction_state == InteractionState.MEASURE
                and self._measure_origin is not None and self._measure_press_pos is not None
                and event.button() == Qt.MouseButton.LeftButton):
            delta = event.position()-self._measure_press_pos
            dragged = self._measure_press_dragged or hypot(delta.x(), delta.y()) >= QApplication.startDragDistance()
            self._measure_press_pos = None
            if dragged:
                start = self._measure_origin
                end = self._measure_point(event.position(), event.modifiers(), start)
                self.cancel_measurement()
                if hypot(end.x-start.x, end.y-start.y) > .01:
                    self.measurementDrawn.emit(self._page_num, ((start.x, start.y), (end.x, end.y)))
            event.accept()
            return
        if self._geometry_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            payload = self._finish_geometry_drag(event.position())
            if payload is not None and self._selected_xref is not None:
                self.annotationGeometryChanged.emit(
                    self._page_num, self._selected_xref, payload
                )
            event.accept()
            return
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
            self._interaction_state == InteractionState.LINE
            and self._line_origin is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            start = QPointF(self._line_origin)
            end = QPointF(event.position())
            self._line_origin = None
            self._line_endpoint = None
            self.set_preview(None)
            if hypot(end.x() - start.x(), end.y() - start.y()) >= 3.0:
                self.lineDrawn.emit(self._page_num, [start, end])
            event.accept()
            return
        if (
            self._interaction_state == InteractionState.NOTE
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.noteClicked.emit(self._page_num, event.position())
            event.accept()
            return
        if (
            self._interaction_state == InteractionState.FONT_INSPECT
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.fontInspectClicked.emit(self._page_num, event.position())
            event.accept()
            return
        if (
            self._interaction_state == InteractionState.FORM
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.formClicked.emit(self._page_num, event.position())
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
        if (
            self._interaction_state == InteractionState.IDLE
            and self._annotations_editable
            and event.button() == Qt.MouseButton.LeftButton
        ):
            entry = self._hit_annotation(event.position())
            if entry is not None and str(entry.get("kind")) in {"Text", "FreeText"}:
                self._select_entry(entry)
                self._start_inline_editor(entry)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _start_inline_editor(self, entry: dict) -> None:
        if self._inline_editor is not None:
            self._finish_inline_editor(False)
        editor = InlineTextEditor(self)
        editor.setObjectName("inlineAnnotationEditor")
        editor.setText(str(entry.get("text") or ""))
        rect = self.pdf_rect_to_widget(fitz.Rect(entry["rect"]))
        rect.setWidth(max(180.0, rect.width()))
        rect.setHeight(max(32.0, rect.height()))
        rect = rect.intersected(QRectF(self.rect()))
        editor.setGeometry(rect.toAlignedRect())
        editor.setProperty("annotationXref", int(entry["xref"]))
        editor.setProperty("originalText", str(entry.get("text") or ""))
        editor.setProperty("editorMode", "existing")
        editor.finishRequested.connect(self._finish_inline_editor)
        self._inline_editor = editor
        editor.show()
        editor.raise_()
        editor.selectAll()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def start_typewriter_editor(
        self,
        position: QPointF,
        *,
        font_name: str = "Helv",
        font_size: float = 14.0,
        color: str = "#202124",
        opacity: float = 1.0,
    ) -> None:
        """Start point-based Typewriter input directly on the PDF page."""
        if self._inline_editor is not None:
            self._finish_inline_editor(False)
        editor = InlineTextEditor(self)
        editor.setObjectName("inlineAnnotationEditor")
        editor.setPlaceholderText("Type text…  Enter: finish · Esc: cancel")
        editor.setToolTip(
            "Alt + Arrow: move 1 px; Alt + Shift + Arrow: move 5 px"
        )
        x = max(0, min(int(position.x()), max(0, self.width() - 24)))
        y = max(0, min(int(position.y()), max(0, self.height() - 24)))
        families = {
            "Helv": "Arial",
            "Cour": "Courier New",
            "Times-Roman": "Times New Roman",
        }
        font = QFont(families.get(font_name, font_name or "Arial"))
        font.setPixelSize(max(8, round(float(font_size) / max(self._scale, 0.001))))
        editor.setFont(font)
        editor.setTextMargins(0, 0, 0, 0)
        editor_height = max(24, QFontMetrics(font).height() + 8)
        editor.setProperty("editorMode", "typewriter")
        foreground = QColor(color)
        if not foreground.isValid():
            foreground = QColor("#202124")
        foreground.setAlphaF(max(0.05, min(1.0, float(opacity))))
        editor.setStyleSheet(
            "QLineEdit { background: rgba(255, 255, 255, 210); "
            f"color: {foreground.name(QColor.NameFormat.HexArgb)}; "
            "border: 2px dashed #1a73e8; border-radius: 3px; padding: 0px; }"
        )
        editor.ensurePolished()
        editor_height = max(
            editor_height,
            editor.sizeHint().height(),
            editor.minimumSizeHint().height(),
        )
        # The I-beam hotspot represents the vertical centre of the intended
        # text line. Anchoring the editor's top edge at that point places the
        # editable text (and the committed FreeText appearance) one line too
        # low. Centre the fully styled line editor on the click instead.
        y = max(
            0,
            min(
                round(float(position.y()) - editor_height / 2.0),
                max(0, self.height() - editor_height),
            ),
        )
        editor.setGeometry(
            x,
            y,
            min(180, max(24, self.width() - x)),
            editor_height,
        )
        editor.setProperty("typewriterAnchor", QPointF(position))

        def resize_to_text(value: str) -> None:
            metrics = QFontMetrics(editor.font())
            content = value or editor.placeholderText()
            desired = max(80, metrics.horizontalAdvance(content) + 12)
            editor.resize(min(desired, max(24, self.width() - editor.x())), editor.height())

        editor.textChanged.connect(resize_to_text)
        editor.nudgeRequested.connect(self._nudge_typewriter_editor)
        editor.finishRequested.connect(self._finish_inline_editor)
        self._inline_editor = editor
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def _nudge_typewriter_editor(self, dx: int, dy: int) -> None:
        editor = self._inline_editor
        if editor is None or str(editor.property("editorMode") or "") != "typewriter":
            return
        next_x = max(0, min(editor.x() + int(dx), self.width() - editor.width()))
        next_y = max(0, min(editor.y() + int(dy), self.height() - editor.height()))
        moved_x = next_x - editor.x()
        moved_y = next_y - editor.y()
        if moved_x == 0 and moved_y == 0:
            return
        editor.move(next_x, next_y)
        anchor = editor.property("typewriterAnchor")
        if isinstance(anchor, QPointF):
            editor.setProperty(
                "typewriterAnchor",
                QPointF(anchor.x() + moved_x, anchor.y() + moved_y),
            )

    def _finish_inline_editor(self, commit: bool = True) -> None:
        editor = self._inline_editor
        if editor is None:
            return
        self._inline_editor = None
        editor._finished = True
        text = editor.text()
        mode = str(editor.property("editorMode") or "existing")
        editor.deleteLater()
        if not commit:
            return
        if mode == "typewriter":
            value = text.strip()
            if value:
                anchor = editor.property("typewriterAnchor")
                self.typewriterCommitted.emit(
                    self._page_num,
                    {
                        "anchor": QPointF(anchor)
                        if isinstance(anchor, QPointF)
                        else QRectF(editor.geometry()).center(),
                        "editor_rect": QRectF(editor.geometry()),
                    },
                    value,
                )
            return
        xref = int(editor.property("annotationXref"))
        original = str(editor.property("originalText") or "")
        if text != original:
            self.annotationTextChanged.emit(self._page_num, xref, text)

    @staticmethod
    def _distance_to_segment(point: QPointF, first: QPointF, second: QPointF) -> float:
        dx = second.x() - first.x()
        dy = second.y() - first.y()
        if dx == 0 and dy == 0:
            return hypot(point.x() - first.x(), point.y() - first.y())
        ratio = max(0.0, min(1.0, ((point.x() - first.x()) * dx + (point.y() - first.y()) * dy) / (dx * dx + dy * dy)))
        return hypot(point.x() - (first.x() + ratio * dx), point.y() - (first.y() + ratio * dy))

    def _hit_annotation(self, point: QPointF) -> dict | None:
        selected = self._selected_entry()
        if selected is not None and selected.get("kind") in IMAGE_KINDS:
            rect = self.pdf_rect_to_widget(fitz.Rect(selected["rect"]))
            if any(hypot(point.x() - corner.x(), point.y() - corner.y()) <= 10
                   for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())):
                return selected
        for entry in reversed(self._annotations):
            if str(entry.get("kind")) == "Line":
                points = self._entry_widget_points(entry)[:2]
                if len(points) == 2 and self._distance_to_segment(point, *points) <= 8.0:
                    return entry
                continue
            rect = self.pdf_rect_to_widget(fitz.Rect(entry["rect"])).adjusted(-6, -6, 6, 6)
            if rect.contains(point):
                return entry
        return None

    def _select_entry(self, entry: dict) -> None:
        self._selected_xref = int(entry["xref"])
        self.annotationSelected.emit(self._page_num, self._selected_xref)
        self.update()

    def _begin_geometry_drag(self, entry: dict, point: QPointF) -> None:
        if str(entry.get("kind")) == "Line":
            points = self._entry_widget_points(entry)[:2]
            if len(points) != 2:
                return
            endpoint = next(
                (index for index, value in enumerate(points) if hypot(point.x() - value.x(), point.y() - value.y()) <= 10.0),
                None,
            )
            self._geometry_drag = {
                "origin": QPointF(point), "original_points": points,
                "points": list(points), "endpoint": endpoint,
            }
            return
        rect = self.pdf_rect_to_widget(fitz.Rect(entry["rect"]))
        corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
        handle = next(
            (index for index, value in enumerate(corners) if hypot(point.x() - value.x(), point.y() - value.y()) <= 10.0),
            None,
        )
        self._geometry_drag = {
            "origin": QPointF(point), "original_rect": QRectF(rect),
            "rect": QRectF(rect), "handle": handle,
            "image": entry.get("kind") in IMAGE_KINDS,
            "keep_aspect": bool(entry.get("keep_aspect", True)),
        }

    def _update_geometry_drag(self, point: QPointF) -> None:
        drag = self._geometry_drag
        if drag is None:
            return
        delta = point - drag["origin"]
        if "original_points" in drag:
            points = [QPointF(value) for value in drag["original_points"]]
            endpoint = drag["endpoint"]
            if endpoint is None:
                points = [value + delta for value in points]
            else:
                points[endpoint] = QPointF(point)
            drag["points"] = points
        else:
            rect = QRectF(drag["original_rect"])
            handle = drag["handle"]
            if handle is None:
                rect.translate(delta)
            else:
                if handle == 0:
                    rect.setTopLeft(point)
                elif handle == 1:
                    rect.setTopRight(point)
                elif handle == 2:
                    rect.setBottomLeft(point)
                else:
                    rect.setBottomRight(point)
                rect = rect.normalized()
                if drag.get("image") and drag.get("keep_aspect") and not (
                    QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    original = drag["original_rect"]
                    ratio = original.width() / original.height()
                    width = max(2.0, rect.width(), rect.height() * ratio)
                    height = width / ratio
                    anchor = (original.bottomRight(), original.bottomLeft(),
                              original.topRight(), original.topLeft())[handle]
                    x = anchor.x() - width if handle in {0, 2} else anchor.x()
                    y = anchor.y() - height if handle in {0, 1} else anchor.y()
                    rect = QRectF(x, y, width, height)
            if drag.get("image"):
                bounds = QRectF(self.rect())
                if handle is None:
                    rect.moveLeft(max(0.0, min(rect.left(), bounds.width() - rect.width())))
                    rect.moveTop(max(0.0, min(rect.top(), bounds.height() - rect.height())))
                elif not bounds.contains(rect):
                    return
            drag["rect"] = rect
        self.update()

    def _finish_geometry_drag(self, point: QPointF) -> dict | None:
        self._update_geometry_drag(point)
        drag = self._geometry_drag
        self._geometry_drag = None
        if drag is None:
            return None
        if "points" in drag:
            if all(
                hypot(current.x() - original.x(), current.y() - original.y()) < 1.0
                for current, original in zip(
                    drag["points"], drag["original_points"], strict=True
                )
            ):
                return None
            return {
                "points": [
                    (self.widget_to_pdf(value).x, self.widget_to_pdf(value).y)
                    for value in drag["points"]
                ]
            }
        rect = drag["rect"]
        original = drag["original_rect"]
        if all(
            abs(current - before) < 1.0
            for current, before in zip(
                (rect.x(), rect.y(), rect.width(), rect.height()),
                (original.x(), original.y(), original.width(), original.height()),
                strict=True,
            )
        ):
            return None
        first = self.widget_to_pdf(rect.topLeft())
        second = self.widget_to_pdf(rect.bottomRight())
        return {"rect": fitz.Rect(first, second).normalize()}

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

    def _update_line_preview(self) -> None:
        if self._line_origin is None or self._line_endpoint is None:
            self.set_preview(None)
            return
        self.set_preview(
            {
                "kind": "arrow" if self._line_arrow else "line",
                "points": [
                    QPointF(self._line_origin),
                    QPointF(self._line_endpoint),
                ],
                "color": self._line_color,
                "width": self._line_width,
                "opacity": self._line_opacity,
            }
        )

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
