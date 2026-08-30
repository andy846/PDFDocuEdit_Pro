"""Interactive PDF canvas: single, continuous and facing layouts with virtual
scrolling, background rendering, pan, text selection and a magnifier."""

from __future__ import annotations

from enum import StrEnum
from functools import wraps
from math import hypot

import fitz
from PyQt6.QtCore import (
    QElapsedTimer,
    QEvent,
    QEventLoop,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QWidget

from core.annotations import (
    AnnotationOp,
    AnnotationStyle,
    freetext_visual_metrics,
    list_annotations,
)
from core.pdf_engine import DOCUMENT_LOCK
from styles.theme import get_colors
from styles.tokens import S

from .page_overlay import PageOverlay, words_intersecting
from .page_view import (
    CAPTION_H,
    PAGE_SPACING,
    PageRenderCache,
    PageView,
    render_page_image,
    render_page_pixmap,
    render_page_pixmap_quick,
)

MARGIN = S.XL
RENDER_BUFFER_PAGES = 2
MAX_PENDING_RENDERS = 8
MAGNIFIER_ZOOM = 2.5


def _document_locked(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with DOCUMENT_LOCK:
            return function(*args, **kwargs)

    return wrapper
MAGNIFIER_SIZE = 200


class LayoutMode(StrEnum):
    SINGLE = "single"
    CONTINUOUS = "continuous"
    FACING = "facing"


class ToolMode(StrEnum):
    BROWSE = "browse"
    HAND = "hand"
    SELECT = "select"
    MAGNIFIER = "magnifier"
    FONT_INSPECT = "font_inspect"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    NOTE = "note"
    SQUIGGLY = "squiggly"
    LINE = "line"
    ARROW = "arrow"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"
    FREETEXT_TYPEWRITER = "freetext_typewriter"
    FREETEXT_BOX = "freetext_box"
    FREETEXT_CALLOUT = "freetext_callout"
    INK = "ink"
    RECT = "rect"
    REDACT = "redact"
    STAMP = "stamp"
    SIGNATURE = "signature"
    IMAGE = "image"


MARQUEE_TOOLS = {
    ToolMode.HIGHLIGHT,
    ToolMode.UNDERLINE,
    ToolMode.STRIKEOUT,
    ToolMode.SQUIGGLY,
    ToolMode.ELLIPSE,
    ToolMode.FREETEXT_BOX,
    ToolMode.FREETEXT_CALLOUT,
    ToolMode.RECT,
    ToolMode.REDACT,
    ToolMode.STAMP,
    ToolMode.SIGNATURE,
    ToolMode.IMAGE,
}

LINE_TOOLS = {ToolMode.LINE, ToolMode.ARROW}

TEXT_MARK_TOOLS = {
    ToolMode.HIGHLIGHT: "highlight",
    ToolMode.UNDERLINE: "underline",
    ToolMode.STRIKEOUT: "strikeout",
    ToolMode.SQUIGGLY: "squiggly",
}
STAMP_ASPECT = 0.35


def callout_line_points(
    page_bounds: fitz.Rect, text_rect: fitz.Rect
) -> tuple[tuple[float, float], ...]:
    """Return PDF /CL points ordered arrow tip, knee, text-box attachment."""
    centre_y = (text_rect.y0 + text_rect.y1) / 2
    left_space = max(0.0, text_rect.x0 - page_bounds.x0)
    right_space = max(0.0, page_bounds.x1 - text_rect.x1)
    use_left = left_space >= right_space
    available = left_space if use_left else right_space
    distance = max(12.0, min(72.0, available))
    bend = min(30.0, max(10.0, distance * 0.45))
    tip_y = min(page_bounds.y1, max(page_bounds.y0, centre_y + bend))
    if use_left:
        attach = (text_rect.x0, centre_y)
        knee = (max(page_bounds.x0, text_rect.x0 - distance * 0.4), centre_y)
        tip = (max(page_bounds.x0, text_rect.x0 - distance), tip_y)
    else:
        attach = (text_rect.x1, centre_y)
        knee = (min(page_bounds.x1, text_rect.x1 + distance * 0.4), centre_y)
        tip = (min(page_bounds.x1, text_rect.x1 + distance), tip_y)
    return (tip, knee, attach)


class _RenderSignals(QObject):
    finished = pyqtSignal(int, int, tuple, object)


class _RenderTask(QRunnable):
    def __init__(
        self,
        doc: fitz.Document,
        page_num: int,
        zoom: float,
        dpr: float,
        key: tuple,
        generation: int,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._doc = doc
        self._page_num = page_num
        self._zoom = zoom
        self._dpr = dpr
        self._key = key
        self._generation = generation
        self.signals = _RenderSignals()

    def run(self) -> None:
        # PyQt6 aborts the process when *any* exception escapes QRunnable.run(),
        # so catch BaseException and keep the pool alive.
        try:
            with DOCUMENT_LOCK:
                image = render_page_image(
                    self._doc, self._page_num, self._zoom, self._dpr
                )
            self.signals.finished.emit(
                self._page_num, self._generation, self._key, image
            )
        except BaseException:
            return


class PdfCanvas(QScrollArea):
    """Page canvas preserving the pre-P2 API while adding layout/tool modes."""

    pageChanged = pyqtSignal(int)
    zoomChanged = pyqtSignal(float)
    selectionChanged = pyqtSignal(str)
    textCopied = pyqtSignal(str)
    annotationRequested = pyqtSignal(object)  # AnnotationOp
    noteRequested = pyqtSignal(int, object)  # (page, fitz.Point)
    contextMenuRequested = pyqtSignal(object)  # global QPoint
    annotationSelected = pyqtSignal(int, int)
    annotationContextRequested = pyqtSignal(int, int, object)
    annotationGeometryChanged = pyqtSignal(int, int, object)
    annotationTextChanged = pyqtSignal(int, int, str)
    fontInspectionRequested = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: fitz.Document | None = None
        self._page = 0
        self._zoom = 1.0
        self._min_zoom = 0.25
        self._max_zoom = 4.0
        self._layout_mode = LayoutMode.SINGLE
        self._tool_mode = ToolMode.BROWSE
        self._generation = 0
        # (generation, page) tokens keep stale tasks from an earlier zoom or
        # rapid page change from clearing/replacing a newer render.
        self._pending: set[tuple[int, int]] = set()
        self._page_views: dict[int, PageView] = {}
        self._rows: list[tuple[int, list[int]]] = []
        self._cache = PageRenderCache()
        self._pool = QThreadPool.globalInstance()
        self._selection: tuple[int, str] | None = None
        self._selected_annotation: tuple[int, int] | None = None
        self._search_hits: tuple[int, list[fitz.Rect]] | None = None
        self._font_inspection: tuple[int, fitz.Rect] | None = None
        self._show_captions = True
        self._annotations_editable = True
        self._hand_anchor: QPoint | None = None
        self._temp_hand = False
        self._magnifier_popup: QLabel | None = None
        self._annot_options: dict = {
            "color": "yellow",
            "width": 1.5,
            "stamp_kind": "Draft",
            "stamp_image_path": "",
            "image_path": "",
            "fill": "",
            "opacity": 1.0,
            "font": "Helv",
            "font_size": 11.0,
            "alignment": 0,
        }

        # Preserve the pager's real width so zoomed pages can scroll sideways.
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Right-click menus: the context menu event lands on the widget under
        # the cursor (viewport or a page overlay), so forward each layer to
        # the contextMenuRequested signal.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.contextMenuRequested.emit(self.mapToGlobal(pos))
        )
        self.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(
            lambda pos: self.contextMenuRequested.emit(self.viewport().mapToGlobal(pos))
        )

        self._pager = QWidget()
        self._pager.setObjectName("canvasPager")
        self.setWidget(self._pager)

        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(70)
        self._zoom_timer.timeout.connect(self._apply_queued_zoom)
        self._pending_zoom: float | None = None

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._apply_pending_relayout)

        self._last_magnifier: tuple[int, QPoint] | None = None

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._apply_scroll_sync)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.viewport().setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.update_theme()

    # --- document lifecycle ----------------------------------------------
    def load_doc(self, doc: fitz.Document, zoom: float = 1.0) -> None:
        self._doc = doc
        self._page = 0
        self._zoom = min(self._max_zoom, max(self._min_zoom, zoom))
        self._generation += 1
        self._cache.clear()
        self._clear_search_hits()
        self._font_inspection = None
        self._selection = None
        self._selected_annotation = None
        self._teardown_views()
        self._relayout()

    def clear(self) -> None:
        self.wait_for_renders()
        self._doc = None
        self._page = 0
        self._zoom = 1.0
        self._generation += 1
        self._cache.clear()
        self._selection = None
        self._selected_annotation = None
        self._clear_search_hits()
        self._font_inspection = None
        self._teardown_views()
        self._pager.setFixedSize(QSize(0, 0))

    def wait_for_renders(self, timeout_ms: int = 3000) -> None:
        """Block until in-flight render tasks finish so the document can be
        closed safely (background tasks hold a live fitz.Document reference)."""
        self._generation += 1  # discard results of in-flight tasks
        if not self._pending:
            return
        timer = QElapsedTimer()
        timer.start()
        loop = QEventLoop(self)
        poll = QTimer(self)
        poll.setInterval(20)

        def check() -> None:
            if not self._pending or timer.elapsed() > timeout_ms:
                poll.stop()
                loop.quit()

        poll.timeout.connect(check)
        poll.start()
        loop.exec()

    def refresh(self) -> None:
        """Re-render everything after the document content changed."""
        self._generation += 1
        self._cache.clear()
        self._teardown_views()
        if self._doc:
            self._relayout()

    def invalidate_pages(self, page_numbers) -> None:
        """Re-render affected pages without clearing unrelated cache or views."""
        if not self._doc:
            return
        pages = {
            int(page)
            for page in page_numbers
            if 0 <= int(page) < self._doc.page_count
        }
        if not pages:
            return
        self._generation += 1
        self._pending = {
            token for token in self._pending if int(token[1]) not in pages
        }
        self._cache.invalidate(id(self._doc), pages)
        for page_num in pages:
            if page_num in self._page_views:
                page = self._doc.load_page(page_num)
                self._page_views[page_num].overlay.set_annotations(
                    list_annotations(page)
                )
                self._request_render(page_num, high=True)

    def selected_annotation(self) -> tuple[int, int] | None:
        return self._selected_annotation

    def select_annotation(self, page: int, xref: int) -> None:
        self._selected_annotation = (int(page), int(xref))
        for page_num, view in self._page_views.items():
            view.overlay.select_annotation(xref if page_num == page else None)

    def clear_annotation_selection(self) -> None:
        self._selected_annotation = None
        for view in self._page_views.values():
            view.overlay.select_annotation(None)

    @property
    def annotations_editable(self) -> bool:
        return self._annotations_editable

    def set_annotations_editable(self, editable: bool) -> None:
        self._annotations_editable = bool(editable)
        if not self._annotations_editable:
            self.set_tool_mode(ToolMode.BROWSE)
        for view in self._page_views.values():
            view.overlay.set_annotations_editable(self._annotations_editable)

    def _on_annotation_selected(self, page: int, xref: int) -> None:
        self.select_annotation(page, xref)
        self.annotationSelected.emit(page, xref)

    def _configure_annotation_preview(self, overlay: PageOverlay) -> None:
        overlay.set_annotation_preview_style(
            self._tool_mode.value,
            color=str(self._annot_options["color"]),
            fill=str(self._annot_options["fill"]),
            width=float(self._annot_options["width"]),
            opacity=float(self._annot_options["opacity"]),
        )

    # --- layout modes ----------------------------------------------------
    def set_layout_mode(self, mode: LayoutMode | str, emit: bool = True) -> None:
        value = mode if isinstance(mode, LayoutMode) else LayoutMode(str(mode))
        if value == self._layout_mode:
            return
        self._layout_mode = value
        self._teardown_views()
        self._relayout()
        if emit:
            self.pageChanged.emit(self._page)

    @property
    def layout_mode(self) -> LayoutMode:
        return self._layout_mode

    def set_show_captions(self, show: bool) -> None:
        self._show_captions = show
        for view in self._page_views.values():
            view.set_show_caption(show)
        if self._doc:
            self._relayout()

    @property
    def show_captions(self) -> bool:
        return self._show_captions

    # --- tool modes ------------------------------------------------------
    def set_tool_mode(self, mode: ToolMode | str) -> None:
        self._tool_mode = mode if isinstance(mode, ToolMode) else ToolMode(str(mode))
        if self._tool_mode != ToolMode.FONT_INSPECT:
            self.clear_font_inspection()
        if self._magnifier_popup:
            self._magnifier_popup.hide()
        self._refresh_cursors()

    @property
    def tool_mode(self) -> ToolMode:
        return self._tool_mode

    def set_annotation_options(self, **options) -> None:
        """Update current annotation style and image-source settings."""
        self._annot_options.update(
            {k: v for k, v in options.items() if k in self._annot_options}
        )
        self._refresh_cursors()

    def annotation_options(self) -> dict:
        """Return a copy of the active annotation options."""
        return dict(self._annot_options)

    def _annotation_style(self) -> AnnotationStyle:
        return AnnotationStyle(
            stroke=str(self._annot_options["color"]),
            fill=str(self._annot_options["fill"]),
            opacity=float(self._annot_options["opacity"]),
            width=float(self._annot_options["width"]),
            font=str(self._annot_options["font"]),
            font_size=float(self._annot_options["font_size"]),
            alignment=int(self._annot_options["alignment"]),
        )

    def _overlay_modes(self) -> tuple[bool, bool, bool, bool, bool, bool]:
        """Return select, note, ink, polygon, line and font-inspect modes."""
        select = self._tool_mode in MARQUEE_TOOLS or self._tool_mode == ToolMode.SELECT
        note = self._tool_mode in {ToolMode.NOTE, ToolMode.FREETEXT_TYPEWRITER}
        ink = self._tool_mode == ToolMode.INK
        polygon = self._tool_mode == ToolMode.POLYGON
        line = self._tool_mode in LINE_TOOLS
        font_inspect = self._tool_mode == ToolMode.FONT_INSPECT
        return select, note, ink, polygon, line, font_inspect

    def _refresh_cursors(self) -> None:
        hand = self._tool_mode == ToolMode.HAND or self._temp_hand
        if hand:
            cursor = (
                Qt.CursorShape.ClosedHandCursor
                if self._hand_anchor is not None
                else Qt.CursorShape.OpenHandCursor
            )
        elif self._tool_mode in MARQUEE_TOOLS | LINE_TOOLS or self._tool_mode in {
            ToolMode.SELECT,
            ToolMode.INK,
            ToolMode.POLYGON,
        }:
            cursor = Qt.CursorShape.CrossCursor
        elif self._tool_mode == ToolMode.FREETEXT_TYPEWRITER:
            cursor = Qt.CursorShape.IBeamCursor
        elif self._tool_mode in {ToolMode.NOTE, ToolMode.FONT_INSPECT}:
            cursor = Qt.CursorShape.PointingHandCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.viewport().setCursor(cursor)
        select, note, ink, polygon, line, font_inspect = (
            (False, False, False, False, False, False)
            if hand
            else self._overlay_modes()
        )
        for view in self._page_views.values():
            self._configure_annotation_preview(view.overlay)
            view.overlay.set_select_mode(select)
            view.overlay.set_note_mode(note)
            view.overlay.set_ink_mode(ink)
            view.overlay.set_polygon_mode(polygon)
            view.overlay.set_font_inspect_mode(font_inspect)
            view.overlay.set_line_mode(
                line,
                arrow=self._tool_mode == ToolMode.ARROW,
                color=str(self._annot_options["color"]),
                width=float(self._annot_options["width"]),
                opacity=float(self._annot_options["opacity"]),
            )
            # The PDF image is a child widget and owns the cursor while the
            # pointer is over the page. Make it transparent during panning so
            # viewport drag events and the open/closed hand cursor both apply
            # inside the PDF, not only on the surrounding canvas.
            view.overlay.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                hand,
            )
            view.overlay.setCursor(cursor)

    # --- navigation ------------------------------------------------------
    @property
    def current_page(self) -> int:
        return self._page

    @property
    def zoom_ratio(self) -> float:
        return self._zoom

    @_document_locked
    def set_page(self, page: int, *, emit: bool = True) -> None:
        if not self._doc or not 0 <= page < self._doc.page_count:
            return
        self._page = page
        self._selection = None
        if self._layout_mode == LayoutMode.SINGLE:
            # Only the latest page change may publish a render. Old tasks can
            # finish safely, but their generation no longer matches.
            self._generation += 1
            self._teardown_views()
            self._relayout()
        else:
            self._scroll_to_page(page)
        if emit:
            self.pageChanged.emit(page)

    def _scroll_to_page(self, page: int) -> None:
        rect = self._page_rect_in_layout(page)
        if rect.isValid():
            target = max(0, int(rect.top()) - MARGIN)
            self.verticalScrollBar().setValue(target)
        self._sync_views()
        self._update_current_from_scroll()

    # --- zoom ------------------------------------------------------------
    def set_zoom(self, ratio: float, *, emit: bool = True) -> None:
        value = min(self._max_zoom, max(self._min_zoom, ratio))
        if abs(value - self._zoom) < 0.001:
            return
        anchor = self._view_anchor()
        self._zoom = value
        self._generation += 1
        self._teardown_views()
        if self._doc:
            self._relayout()
            self._restore_view_anchor(anchor)
        if emit:
            self.zoomChanged.emit(value)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    @_document_locked
    def fit_width(self) -> None:
        if not self._doc:
            return
        page_width = self._doc.load_page(self._page).rect.width
        available = max(100, self.viewport().width() - MARGIN * 2)
        self.set_zoom(available / page_width)

    @_document_locked
    def fit_page(self) -> None:
        if not self._doc:
            return
        rect = self._doc.load_page(self._page).rect
        available_w = max(100, self.viewport().width() - MARGIN * 2)
        available_h = max(100, self.viewport().height() - MARGIN * 2 - CAPTION_H)
        self.set_zoom(min(available_w / rect.width, available_h / rect.height))

    def actual_size(self) -> None:
        if self._doc:
            self.set_zoom(1.0)

    # --- search hits (P1 integration) ------------------------------------
    def show_search_hits(self, page: int, rects: list[fitz.Rect]) -> None:
        self._search_hits = (page, list(rects))
        self._apply_search_hits()

    def _apply_search_hits(self) -> None:
        target_page, rects = (
            self._search_hits if self._search_hits is not None else (-1, [])
        )
        for page_num, view in self._page_views.items():
            view.overlay.set_search_rects(rects if page_num == target_page else [])

    def _clear_search_hits(self) -> None:
        self._search_hits = None

    def show_font_inspection(self, page: int, rect: fitz.Rect) -> None:
        self._font_inspection = (int(page), fitz.Rect(rect))
        self._apply_font_inspection()

    def clear_font_inspection(self) -> None:
        self._font_inspection = None
        self._apply_font_inspection()

    def _apply_font_inspection(self) -> None:
        target_page, rect = (
            self._font_inspection
            if self._font_inspection is not None
            else (-1, None)
        )
        for page_num, view in self._page_views.items():
            view.overlay.set_font_inspection_rect(
                rect if page_num == target_page else None
            )

    def _on_font_inspect(self, page_num: int, widget_point: QPointF) -> None:
        view = self._page_views.get(page_num)
        if view is None:
            return
        self.fontInspectionRequested.emit(
            page_num, view.overlay.widget_to_pdf(widget_point)
        )

    # --- selection and annotations --------------------------------------
    @_document_locked
    def _on_selection(self, page_num: int, widget_rect: QRectF) -> None:
        if not self._doc or page_num not in self._page_views:
            return
        overlay = self._page_views[page_num].overlay
        pdf_rect = fitz.Rect(
            overlay.widget_to_pdf(widget_rect.topLeft()),
            overlay.widget_to_pdf(widget_rect.bottomRight()),
        ).normalize()
        if self._tool_mode == ToolMode.SELECT:
            page = self._doc.load_page(page_num)
            kept = words_intersecting(page, pdf_rect)
            for view in self._page_views.values():
                view.overlay.set_selection_rects([])
            if not kept:
                self._selection = None
                return
            ordered = sorted(kept, key=lambda pair: (pair[0].y0, pair[0].x0))
            text = " ".join(word for _rect, word in ordered)
            overlay.set_selection_rects([rect for rect, _word in kept])
            self._selection = (page_num, text)
            self.selectionChanged.emit(text)
            return
        if self._tool_mode in TEXT_MARK_TOOLS:
            page = self._doc.load_page(page_num)
            kept = words_intersecting(page, pdf_rect)
            if not kept:
                return
            self.annotationRequested.emit(
                AnnotationOp(
                    kind=TEXT_MARK_TOOLS[self._tool_mode],
                    page=page_num,
                    rects=tuple(rect for rect, _word in kept),
                    color=self._annot_options["color"],
                    style=self._annotation_style(),
                )
            )
            return
        if self._tool_mode == ToolMode.ELLIPSE:
            self.annotationRequested.emit(
                AnnotationOp(
                    kind="ellipse",
                    page=page_num,
                    rects=(pdf_rect,),
                    color=self._annot_options["color"],
                    width=self._annot_options["width"],
                    style=self._annotation_style(),
                )
            )
            return
        if self._tool_mode in {
            ToolMode.FREETEXT_TYPEWRITER,
            ToolMode.FREETEXT_BOX,
            ToolMode.FREETEXT_CALLOUT,
        }:
            style = self._annotation_style()
            callout = (
                callout_line_points(self._doc.load_page(page_num).cropbox, pdf_rect)
                if self._tool_mode == ToolMode.FREETEXT_CALLOUT
                else ()
            )
            self.annotationRequested.emit(
                AnnotationOp(
                    kind=str(self._tool_mode),
                    page=page_num,
                    rects=(pdf_rect,),
                    points=callout,
                    color=self._annot_options["color"],
                    width=self._annot_options["width"],
                    style=style,
                )
            )
            return

        if self._tool_mode == ToolMode.RECT:
            self.annotationRequested.emit(
                AnnotationOp(
                    kind="rect",
                    page=page_num,
                    rects=(pdf_rect,),
                    color=self._annot_options["color"],
                    width=self._annot_options["width"],
                    style=self._annotation_style(),
                )
            )
            return
        if self._tool_mode == ToolMode.REDACT:
            self.annotationRequested.emit(
                AnnotationOp(kind="redact", page=page_num, rects=(pdf_rect,))
            )
            return
        if self._tool_mode == ToolMode.STAMP:
            stamp_image_path = str(self._annot_options["stamp_image_path"] or "")
            aspect = STAMP_ASPECT
            if stamp_image_path:
                image = QImage(stamp_image_path)
                if not image.isNull() and image.width() > 0:
                    aspect = max(0.1, min(3.0, image.height() / image.width()))
            height = pdf_rect.width * aspect
            stamp_rect = fitz.Rect(
                pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y0 + height
            )
            self.annotationRequested.emit(
                AnnotationOp(
                    kind="stamp",
                    page=page_num,
                    rects=(stamp_rect,),
                    stamp_kind=self._annot_options["stamp_kind"],
                    image_path=stamp_image_path,
                )
            )
            return
        if self._tool_mode in {ToolMode.SIGNATURE, ToolMode.IMAGE}:
            image_path = self._annot_options["image_path"]
            self.annotationRequested.emit(
                AnnotationOp(
                    kind=(
                        "signature_image"
                        if self._tool_mode == ToolMode.SIGNATURE
                        else "image"
                    ),
                    page=page_num,
                    rects=(pdf_rect,),
                    image_path=image_path,
                )
            )

    def _on_polygon(self, page_num: int, points_widget: list) -> None:
        if (
            self._tool_mode != ToolMode.POLYGON
            or not self._doc
            or page_num not in self._page_views
            or len(points_widget) < 3
        ):
            return
        overlay = self._page_views[page_num].overlay
        points: list[tuple[float, float]] = []
        for point_widget in points_widget:
            point = overlay.widget_to_pdf(point_widget)
            points.append((point.x, point.y))
        self.annotationRequested.emit(
            AnnotationOp(
                kind="polygon",
                page=page_num,
                points=tuple(points),
                color=self._annot_options["color"],
                width=self._annot_options["width"],
                style=self._annotation_style(),
            )
        )

    def _on_line(self, page_num: int, points_widget: list) -> None:
        if (
            self._tool_mode not in LINE_TOOLS
            or not self._doc
            or page_num not in self._page_views
            or len(points_widget) != 2
        ):
            return
        overlay = self._page_views[page_num].overlay
        start = overlay.widget_to_pdf(points_widget[0])
        end = overlay.widget_to_pdf(points_widget[1])
        if hypot(end.x - start.x, end.y - start.y) < 1.0:
            return
        self.annotationRequested.emit(
            AnnotationOp(
                kind="arrow" if self._tool_mode == ToolMode.ARROW else "line",
                page=page_num,
                points=((start.x, start.y), (end.x, end.y)),
                color=self._annot_options["color"],
                width=self._annot_options["width"],
                style=self._annotation_style(),
            )
        )

    def _on_ink(self, page_num: int, points_widget: list) -> None:
        if not self._doc or page_num not in self._page_views or len(points_widget) < 2:
            return
        overlay = self._page_views[page_num].overlay
        points = tuple(
            (overlay.widget_to_pdf(point).x, overlay.widget_to_pdf(point).y)
            for point in points_widget
        )
        self.annotationRequested.emit(
            AnnotationOp(
                kind="ink",
                page=page_num,
                points=points,
                color=self._annot_options["color"],
                width=self._annot_options["width"],
                style=self._annotation_style(),
            )
        )

    def _on_note(self, page_num: int, point_widget) -> None:
        if not self._doc or page_num not in self._page_views:
            return
        overlay = self._page_views[page_num].overlay
        if self._tool_mode == ToolMode.FREETEXT_TYPEWRITER:
            style = self._annotation_style()
            overlay.start_typewriter_editor(
                point_widget,
                font_name=style.font,
                font_size=style.font_size,
                color=style.stroke,
                opacity=style.opacity,
            )
            return
        self.noteRequested.emit(page_num, overlay.widget_to_pdf(point_widget))

    def _on_typewriter_committed(
        self, page_num: int, placement: object, text: str
    ) -> None:
        if not self._doc or page_num not in self._page_views:
            return
        overlay = self._page_views[page_num].overlay
        style = self._annotation_style()
        if isinstance(placement, dict):
            widget_rect = QRectF(placement.get("editor_rect", QRectF()))
            anchor_widget = QPointF(
                placement.get("anchor", widget_rect.center())
            )
        else:
            widget_rect = QRectF(placement)
            anchor_widget = widget_rect.center()
        midpoint, line_height = freetext_visual_metrics(
            style.font,
            style.font_size,
        )
        scale = max(0.001, overlay._scale)
        final_widget_rect = QRectF(
            anchor_widget.x(),
            anchor_widget.y() - midpoint / scale,
            max(12.0 / scale, widget_rect.width()),
            line_height / scale,
        )
        first = overlay.widget_to_pdf(final_widget_rect.topLeft())
        second = overlay.widget_to_pdf(final_widget_rect.bottomRight())
        rect = fitz.Rect(first, second).normalize()
        self.annotationRequested.emit(
            AnnotationOp(
                kind="freetext_typewriter",
                page=page_num,
                rects=(rect,),
                text=text,
                color=self._annot_options["color"],
                style=style,
            )
        )

    def clear_selection(self) -> None:
        self._selection = None
        for view in self._page_views.values():
            view.overlay.set_selection_rects([])

    def selected_text(self) -> str:
        """The currently selected text (empty when nothing is selected)."""
        return self._selection[1] if self._selection else ""

    def copy_selection(self) -> None:
        """Copy the selected text to the clipboard (same as Ctrl+C)."""
        if self._selection:
            self.textCopied.emit(self._selection[1])

    def contextMenuEvent(self, event) -> None:
        self.contextMenuRequested.emit(event.globalPos())
        event.accept()
        super().contextMenuEvent(event)

    # --- layout engine ---------------------------------------------------
    def _teardown_views(self) -> None:
        for view in self._page_views.values():
            view.setParent(None)
            view.deleteLater()
        self._page_views.clear()

    @_document_locked
    def _compute_rows(self) -> list[tuple[int, list[int]]]:
        """Ordered (row_y, [pages]) rows for the current layout and zoom."""
        if not self._doc:
            return []
        rows: list[tuple[int, list[int]]] = []
        y = MARGIN
        if self._layout_mode == LayoutMode.SINGLE:
            rows.append((y, [self._page]))
            return rows
        if self._layout_mode == LayoutMode.CONTINUOUS:
            for page_num in range(self._doc.page_count):
                rows.append((y, [page_num]))
                rect = self._doc.load_page(page_num).rect
                y += round(rect.height * self._zoom) + CAPTION_H + PAGE_SPACING
            return rows
        # Facing: page 0 alone and centred, then pairs.
        rows.append((y, [0]))
        rect = self._doc.load_page(0).rect
        y += round(rect.height * self._zoom) + CAPTION_H + PAGE_SPACING
        for first in range(1, self._doc.page_count, 2):
            pages = [first] + ([first + 1] if first + 1 < self._doc.page_count else [])
            rows.append((y, pages))
            row_height = max(
                round(self._doc.load_page(p).rect.height * self._zoom) for p in pages
            )
            y += row_height + CAPTION_H + PAGE_SPACING
        return rows

    @_document_locked
    def _page_rect_in_layout(self, page_num: int) -> QRectF:
        if not self._doc or not 0 <= page_num < self._doc.page_count:
            return QRectF()
        page = self._doc.load_page(page_num)
        width = round(page.rect.width * self._zoom)
        height = round(page.rect.height * self._zoom)
        layout_width = max(1, self.viewport().width(), self._pager.width())
        for row_y, pages in self._rows:
            if page_num not in pages:
                continue
            if len(pages) == 1:
                x = MARGIN + max(0, (layout_width - 2 * MARGIN - width) / 2)
                return QRectF(x, row_y, width, height)
            widths = [
                round(self._doc.load_page(p).rect.width * self._zoom) for p in pages
            ]
            row_width = sum(widths) + PAGE_SPACING * (len(pages) - 1)
            x = MARGIN + max(0, (layout_width - 2 * MARGIN - row_width) / 2)
            index = pages.index(page_num)
            x += sum(widths[:index]) + PAGE_SPACING * index
            return QRectF(x, row_y, width, height)
        return QRectF()

    @_document_locked
    def _total_size(self) -> QSize:
        if not self._doc or not self._rows:
            return QSize(0, 0)
        widest_row = 0
        for _row_y, pages in self._rows:
            row_width = sum(
                round(self._doc.load_page(page).rect.width * self._zoom)
                for page in pages
            ) + PAGE_SPACING * max(0, len(pages) - 1)
            widest_row = max(widest_row, row_width)
        width = max(1, self.viewport().width(), widest_row + MARGIN * 2)
        last_y, last_pages = self._rows[-1]
        last_height = max(
            round(self._doc.load_page(p).rect.height * self._zoom) for p in last_pages
        )
        height = last_y + last_height + CAPTION_H + MARGIN
        return QSize(width, max(1, height))

    @_document_locked
    def _relayout(self) -> None:
        if not self._doc:
            return
        self._rows = self._compute_rows()
        self._pager.setFixedSize(self._total_size())
        self._sync_views()
        self._update_current_from_scroll()

    @_document_locked
    def _visible_pages(self, buffer_pages: int | None = None) -> list[int]:
        if not self._doc or not self._rows:
            return []
        scroll = self.verticalScrollBar().value()
        viewport_height = self.viewport().height()
        probe = self._doc.load_page(0).rect.height * self._zoom + CAPTION_H
        buffer = RENDER_BUFFER_PAGES if buffer_pages is None else buffer_pages
        top = scroll - probe * buffer
        bottom = scroll + viewport_height + probe * buffer
        visible: list[int] = []
        for row_y, pages in self._rows:
            row_height = max(
                round(self._doc.load_page(p).rect.height * self._zoom) for p in pages
            )
            if row_y + row_height + CAPTION_H >= top and row_y <= bottom:
                visible.extend(pages)
        return visible

    @_document_locked
    def _sync_views(self) -> None:
        if not self._doc:
            return
        needed = set(self._visible_pages())
        # Pages actually on screen render first (high priority); the prefetch
        # buffer fills the pool afterwards so fast scrolling never starves the
        # visible pages behind a backlog of off-screen renders.
        focused = set(self._visible_pages(buffer_pages=0))
        for page_num in list(self._page_views):
            if page_num not in needed:
                view = self._page_views.pop(page_num)
                view.setParent(None)
                view.deleteLater()
        for page_num in needed:
            if page_num in self._page_views:
                page = self._doc.load_page(page_num)
                rect = self._page_rect_in_layout(page_num)
                view = self._page_views[page_num]
                view.setGeometry(
                    int(rect.x()),
                    int(rect.y()),
                    max(1, int(rect.width())),
                    int(rect.height()) + CAPTION_H,
                )
                view.overlay.set_geometry_info(
                    page.rect,
                    1.0 / self._zoom,
                    page.rotation_matrix,
                    page.derotation_matrix,
                )
                view.overlay.set_annotations(list_annotations(page))
                self._configure_annotation_preview(view.overlay)
                selected = self._selected_annotation
                view.overlay.select_annotation(
                    selected[1] if selected is not None and selected[0] == page_num else None
                )
                continue
            page = self._doc.load_page(page_num)
            view = PageView(page_num, page, self._pager)
            view.set_show_caption(self._show_captions)
            rect = self._page_rect_in_layout(page_num)
            view.setGeometry(
                int(rect.x()),
                int(rect.y()),
                max(1, int(rect.width())),
                int(rect.height()) + CAPTION_H,
            )
            view.show()
            select, note, ink, polygon, line, font_inspect = self._overlay_modes()
            view.overlay.set_select_mode(select)
            view.overlay.set_note_mode(note)
            view.overlay.set_ink_mode(ink)
            view.overlay.selectionMade.connect(self._on_selection)
            view.overlay.set_polygon_mode(polygon)
            view.overlay.set_font_inspect_mode(font_inspect)
            view.overlay.set_line_mode(
                line,
                arrow=self._tool_mode == ToolMode.ARROW,
                color=str(self._annot_options["color"]),
                width=float(self._annot_options["width"]),
                opacity=float(self._annot_options["opacity"]),
            )
            view.overlay.inkDrawn.connect(self._on_ink)
            view.overlay.noteClicked.connect(self._on_note)
            view.overlay.typewriterCommitted.connect(self._on_typewriter_committed)
            view.overlay.lineDrawn.connect(self._on_line)
            view.overlay.polygonDrawn.connect(self._on_polygon)
            view.overlay.fontInspectClicked.connect(self._on_font_inspect)
            view.overlay.annotationSelected.connect(self._on_annotation_selected)
            view.overlay.annotationContextRequested.connect(
                self.annotationContextRequested.emit
            )
            view.overlay.pageContextRequested.connect(self.contextMenuRequested.emit)
            view.overlay.annotationGeometryChanged.connect(
                self.annotationGeometryChanged.emit
            )
            view.overlay.annotationTextChanged.connect(
                self.annotationTextChanged.emit
            )
            view.overlay.set_geometry_info(
                page.rect,
                1.0 / self._zoom,
                page.rotation_matrix,
                page.derotation_matrix,
            )
            view.overlay.set_annotations(list_annotations(page))
            view.overlay.set_annotations_editable(self._annotations_editable)
            self._configure_annotation_preview(view.overlay)
            selected = self._selected_annotation
            view.overlay.select_annotation(
                selected[1] if selected is not None and selected[0] == page_num else None
            )
            self._page_views[page_num] = view
            self._request_render(page_num, page_num in focused)
        self._apply_search_hits()
        self._apply_font_inspection()

    @_document_locked
    def _request_render(self, page_num: int, high: bool = False) -> None:
        token = (self._generation, page_num)
        if not self._doc or token in self._pending:
            return
        dpr = self.devicePixelRatioF()
        key = (id(self._doc), page_num, round(self._zoom * dpr, 3), round(dpr, 3))
        cached = self._cache.get(key)
        if cached is not None:
            view = self._page_views.get(page_num)
            if view is not None:
                view.set_pixmap(cached)
            return
        if page_num not in self._page_views:
            return
        # Low-priority (prefetch) renders are throttled so the pool never
        # queues up behind off-screen pages while the user scrolls quickly.
        if not high and len(self._pending) >= MAX_PENDING_RENDERS:
            return
        # Show an instant low-resolution placeholder (non-blocking) so the
        # page never appears blank, then let the full render replace it.
        if DOCUMENT_LOCK.acquire(blocking=False):
            try:
                quick = render_page_pixmap_quick(self._doc, page_num, self._zoom, dpr)
                view = self._page_views.get(page_num)
                if view is not None:
                    view.set_pixmap(quick)
            except BaseException:
                pass
            finally:
                DOCUMENT_LOCK.release()
        # Encrypted documents: MuPDF's per-document decryption state is not
        # thread-safe, so render on the GUI thread to avoid corrupting the
        # document's crypto state from a worker thread.
        if self._doc.needs_pass:
            try:
                with DOCUMENT_LOCK:
                    pixmap = render_page_pixmap(self._doc, page_num, self._zoom, dpr)
            except BaseException:
                return
            self._cache.put(key, pixmap)
            view = self._page_views.get(page_num)
            if view is not None:
                view.set_pixmap(pixmap, self._doc.load_page(page_num))
            return
        self._pending.add(token)
        task = _RenderTask(self._doc, page_num, self._zoom, dpr, key, self._generation)
        task.signals.finished.connect(self._on_render_done)
        # Higher values run earlier in the pool; visible pages go first.
        self._pool.start(task, 6 if high else 0)

    @_document_locked
    def _on_render_done(
        self,
        page_num: int,
        generation: int,
        key: tuple,
        image: QImage,
    ) -> None:
        self._pending.discard((generation, page_num))
        if generation != self._generation or not self._doc:
            return
        # QPixmap is a GUI resource and must only be created on this thread.
        pixmap = QPixmap.fromImage(image)
        self._cache.put(key, pixmap)
        view = self._page_views.get(page_num)
        if view is not None:
            view.set_pixmap(pixmap, self._doc.load_page(page_num))

    def _view_anchor(self) -> tuple[float, float]:
        """Return the viewport centre as normalized pager coordinates."""
        width = max(1, self._pager.width())
        height = max(1, self._pager.height())
        return (
            (self.horizontalScrollBar().value() + self.viewport().width() / 2) / width,
            (self.verticalScrollBar().value() + self.viewport().height() / 2) / height,
        )

    def _restore_view_anchor(self, anchor: tuple[float, float]) -> None:
        x_ratio, y_ratio = anchor
        self.horizontalScrollBar().setValue(
            round(x_ratio * self._pager.width() - self.viewport().width() / 2)
        )
        self.verticalScrollBar().setValue(
            round(y_ratio * self._pager.height() - self.viewport().height() / 2)
        )

    def _update_current_from_scroll(self) -> None:
        if not self._doc or self._layout_mode == LayoutMode.SINGLE:
            return
        center = self.verticalScrollBar().value() + self.viewport().height() / 2
        best_page = self._page
        best_distance = float("inf")
        for page_num in self._visible_pages():
            rect = self._page_rect_in_layout(page_num)
            distance = abs(rect.center().y() - center)
            if distance < best_distance:
                best_distance = distance
                best_page = page_num
        if best_page != self._page:
            self._page = best_page
            self.pageChanged.emit(best_page)

    # --- theming ---------------------------------------------------------
    def update_theme(self) -> None:
        c = get_colors()
        self.setStyleSheet(
            f"""
            QScrollArea {{ background: {c['canvas']}; border: none; }}
            QWidget#canvasPager {{ background: {c['canvas']}; }}
            """
        )
        for view in self._page_views.values():
            view.update_theme()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._doc:
            # Coalesce continuous window-drag resizes into one relayout.
            self._resize_timer.start()

    def _apply_pending_relayout(self) -> None:
        if not self._doc:
            return
        anchor = self._view_anchor()
        self._relayout()
        self._restore_view_anchor(anchor)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self._queue_zoom(self._zoom * factor)
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y() or event.angleDelta().x()
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)
        if self._layout_mode != LayoutMode.SINGLE:
            self._schedule_scroll_sync()

    # --- coalesced zoom and scroll sync ----------------------------------
    def _queue_zoom(self, target: float) -> None:
        """Coalesce rapid wheel-zoom ticks into a single rebuild."""
        self._pending_zoom = min(self._max_zoom, max(self._min_zoom, target))
        self._zoom_timer.start()

    def _apply_queued_zoom(self) -> None:
        if self._pending_zoom is not None:
            value = self._pending_zoom
            self._pending_zoom = None
            self.set_zoom(value)

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self._layout_mode != LayoutMode.SINGLE and self._doc:
            self._schedule_scroll_sync()

    def _schedule_scroll_sync(self) -> None:
        self._scroll_timer.start()

    def _apply_scroll_sync(self) -> None:
        if self._layout_mode != LayoutMode.SINGLE and self._doc:
            self._sync_views()
            self._update_current_from_scroll()

    # --- input filter (pan / magnifier / click-to-page / keyboard) -------
    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                return self._viewport_mouse_press(event)
            if event.type() == QEvent.Type.MouseMove:
                return self._viewport_mouse_move(event)
            if event.type() == QEvent.Type.MouseButtonRelease:
                return self._viewport_mouse_release(event)
            if event.type() == QEvent.Type.Leave:
                if self._magnifier_popup:
                    self._magnifier_popup.hide()
            if event.type() == QEvent.Type.KeyPress:
                return self._viewport_key_press(event)
            if event.type() == QEvent.Type.KeyRelease:
                return self._viewport_key_release(event)
        return super().eventFilter(obj, event)

    def _viewport_mouse_press(self, event) -> bool:
        if self._tool_mode == ToolMode.HAND or self._temp_hand:
            if event.button() == Qt.MouseButton.LeftButton:
                self._hand_anchor = QPoint(event.position().toPoint())
                self._refresh_cursors()
                return True
            return False
        if (
            self._tool_mode == ToolMode.BROWSE
            and event.button() == Qt.MouseButton.LeftButton
            and self._layout_mode != LayoutMode.SINGLE
        ):
            # The event position is viewport-relative; convert it to the
            # pager's coordinate system before hit-testing (the pager is
            # offset by the scroll position in continuous layouts).
            pager_pos = self._to_pager(event.position().toPoint())
            if pager_pos is None:
                return False
            page = self._page_at(pager_pos)
            if page is not None and page != self._page:
                self._page = page
                self.pageChanged.emit(page)
            return False
        return False

    def _viewport_mouse_move(self, event) -> bool:
        if self._hand_anchor is not None:
            delta = event.position().toPoint() - self._hand_anchor
            self._hand_anchor = QPoint(event.position().toPoint())
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            return True
        if self._tool_mode == ToolMode.MAGNIFIER and self._doc:
            self._update_magnifier(event.position().toPoint())
            return False
        return False

    def _viewport_mouse_release(self, event) -> bool:
        if (
            self._hand_anchor is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._hand_anchor = None
            self._refresh_cursors()
            return True
        return False

    def _viewport_key_press(self, event) -> bool:
        if (
            event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and not self._temp_hand
        ):
            self._temp_hand = True
            self._refresh_cursors()
            return True
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            if self._selection:
                self.textCopied.emit(self._selection[1])
                return True
        return False

    def _viewport_key_release(self, event) -> bool:
        if (
            event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and self._temp_hand
        ):
            self._temp_hand = False
            self._refresh_cursors()
            return True
        return False

    def _to_pager(self, position: QPoint) -> QPoint | None:
        """Map a viewport position into pager coordinates, or None when the
        pager is between parents (Qt then warns about the hierarchy)."""
        if self._pager.parent() is not self.viewport():
            return None
        return self.viewport().mapTo(self._pager, position)

    def _page_at(self, position: QPoint) -> int | None:
        widget = self._pager.childAt(position)
        while widget is not None and not isinstance(widget, PageOverlay):
            widget = widget.parentWidget()
        if isinstance(widget, PageOverlay):
            for page_num, view in self._page_views.items():
                if view.overlay is widget:
                    return page_num
        return None

    def _magnifier_target(
        self, position: QPoint
    ) -> tuple[int, QPoint, fitz.Point] | None:
        """Map a viewport cursor position to the exact PDF sample point."""
        pager_pos = self._to_pager(position)
        if pager_pos is None:
            return None
        page_num = self._page_at(pager_pos)
        if page_num is None or page_num not in self._page_views:
            return None
        overlay = self._page_views[page_num].overlay
        # Map directly from viewport to overlay. This includes the scroll-area
        # offset, centred page margin and PageView layout in one Qt transform.
        local = overlay.mapFrom(self.viewport(), position)
        return page_num, pager_pos, overlay.widget_to_pdf(local)

    @_document_locked
    def _update_magnifier(self, position: QPoint) -> None:
        target = self._magnifier_target(position)
        if target is None or not self._doc:
            if self._magnifier_popup:
                self._magnifier_popup.hide()
            self._last_magnifier = None
            return
        page_num, pager_pos, pdf_point = target
        last = self._last_magnifier
        if last is not None and last[0] == page_num:
            delta = pager_pos - last[1]
            if abs(delta.x()) < 4 and abs(delta.y()) < 4:
                return  # cursor barely moved: reuse the current sample
        self._last_magnifier = (page_num, pager_pos)
        page = self._doc.load_page(page_num)
        dpr = self.devicePixelRatioF()
        half = MAGNIFIER_SIZE / (2 * MAGNIFIER_ZOOM * self._zoom)
        desired_clip = fitz.Rect(
            pdf_point.x - half,
            pdf_point.y - half,
            pdf_point.x + half,
            pdf_point.y + half,
        )
        clip = desired_clip & page.rect
        if clip.is_empty:
            return
        matrix = fitz.Matrix(
            MAGNIFIER_ZOOM * self._zoom * dpr,
            MAGNIFIER_ZOOM * self._zoom * dpr,
        )
        try:
            pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        except Exception:
            return
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        # Always build a fixed-size sample and place a clipped edge render at
        # its true offset. Without this padding, Qt enlarged an edge sample
        # and the cursor target visibly drifted away from the popup centre.
        target_pixels = max(1, round(MAGNIFIER_SIZE * dpr))
        sample = QImage(
            target_pixels,
            target_pixels,
            QImage.Format.Format_RGB888,
        )
        sample.fill(QColor(get_colors()["page"]))
        sample_painter = QPainter(sample)
        offset_x = round((clip.x0 - desired_clip.x0) * matrix.a)
        offset_y = round((clip.y0 - desired_clip.y0) * matrix.d)
        sample_painter.drawImage(offset_x, offset_y, image)
        crosshair = max(4, round(6 * dpr))
        centre = target_pixels // 2
        sample_painter.setPen(QPen(QColor(get_colors()["primary"]), max(1.0, dpr)))
        sample_painter.drawLine(
            centre - crosshair,
            centre,
            centre + crosshair,
            centre,
        )
        sample_painter.drawLine(
            centre,
            centre - crosshair,
            centre,
            centre + crosshair,
        )
        sample_painter.end()
        popup = self._magnifier_popup
        if popup is None:
            popup = QLabel(self)
            popup.setObjectName("magnifierPopup")
            popup.setWindowFlags(Qt.WindowType.ToolTip)
            popup.setFixedSize(MAGNIFIER_SIZE, MAGNIFIER_SIZE)
            popup.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._magnifier_popup = popup
        sample_pixmap = QPixmap.fromImage(sample)
        sample_pixmap.setDevicePixelRatio(dpr)
        popup.setPixmap(sample_pixmap)
        popup.move(self.viewport().mapToGlobal(position) + QPoint(16, 16))
        popup.show()
