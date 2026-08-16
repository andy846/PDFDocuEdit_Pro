"""Interactive PDF canvas: single, continuous and facing layouts with virtual
scrolling, background rendering, pan, text selection and a magnifier."""

from __future__ import annotations

from enum import StrEnum

import fitz
from PyQt6.QtCore import (
    QElapsedTimer,
    QEvent,
    QEventLoop,
    QObject,
    QPoint,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QWidget

from core.annotations import AnnotationOp
from core.pdf_engine import DOCUMENT_LOCK
from styles.theme import get_colors
from styles.tokens import S

from .page_overlay import PageOverlay, words_intersecting
from .page_view import (
    CAPTION_H,
    PAGE_SPACING,
    PageRenderCache,
    PageView,
    render_page_pixmap,
    render_page_pixmap_quick,
)

MARGIN = S.XL
RENDER_BUFFER_PAGES = 2
MAX_PENDING_RENDERS = 8
MAGNIFIER_ZOOM = 2.5
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
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    NOTE = "note"
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
    ToolMode.RECT,
    ToolMode.REDACT,
    ToolMode.STAMP,
    ToolMode.SIGNATURE,
    ToolMode.IMAGE,
}

TEXT_MARK_TOOLS = {
    ToolMode.HIGHLIGHT: "highlight",
    ToolMode.UNDERLINE: "underline",
    ToolMode.STRIKEOUT: "strikeout",
}

STAMP_ASPECT = 0.35


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
                pixmap = render_page_pixmap(
                    self._doc, self._page_num, self._zoom, self._dpr
                )
            self.signals.finished.emit(
                self._page_num, self._generation, self._key, pixmap
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
        self._pending: set[int] = set()
        self._page_views: dict[int, PageView] = {}
        self._rows: list[tuple[int, list[int]]] = []
        self._cache = PageRenderCache()
        self._pool = QThreadPool.globalInstance()
        self._selection: tuple[int, str] | None = None
        self._search_hits: tuple[int, list[fitz.Rect]] | None = None
        self._show_captions = True
        self._hand_anchor: QPoint | None = None
        self._temp_hand = False
        self._magnifier_popup: QLabel | None = None
        self._annot_options: dict = {
            "color": "yellow",
            "width": 1.5,
            "stamp_kind": "Draft",
            "image_path": "",
        }

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        self._pending.clear()
        self._clear_search_hits()
        self._selection = None
        self._teardown_views()
        self._relayout()

    def clear(self) -> None:
        self.wait_for_renders()
        self._doc = None
        self._page = 0
        self._zoom = 1.0
        self._generation += 1
        self._pending.clear()
        self._cache.clear()
        self._selection = None
        self._clear_search_hits()
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
        self._pending.clear()
        self._teardown_views()
        if self._doc:
            self._relayout()

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
        if self._magnifier_popup:
            self._magnifier_popup.hide()
        self._refresh_cursors()

    @property
    def tool_mode(self) -> ToolMode:
        return self._tool_mode

    def set_annotation_options(self, **options) -> None:
        """Update current annotation settings (color, width, stamp_kind, image_path)."""
        self._annot_options.update({k: v for k, v in options.items() if k in self._annot_options})

    def _overlay_modes(self) -> tuple[bool, bool, bool]:
        """Return (select_mode, note_mode, ink_mode) for the active tool."""
        select = self._tool_mode in MARQUEE_TOOLS or self._tool_mode == ToolMode.SELECT
        note = self._tool_mode == ToolMode.NOTE
        ink = self._tool_mode == ToolMode.INK
        return select, note, ink

    def _refresh_cursors(self) -> None:
        hand = self._tool_mode == ToolMode.HAND or self._temp_hand
        if hand:
            cursor = (
                Qt.CursorShape.ClosedHandCursor
                if self._hand_anchor is not None
                else Qt.CursorShape.OpenHandCursor
            )
        elif self._tool_mode in MARQUEE_TOOLS or self._tool_mode in {
            ToolMode.SELECT,
            ToolMode.INK,
        }:
            cursor = Qt.CursorShape.CrossCursor
        elif self._tool_mode == ToolMode.NOTE:
            cursor = Qt.CursorShape.PointingHandCursor
        else:
            cursor = Qt.CursorShape.ArrowCursor
        self.viewport().setCursor(cursor)
        select, note, ink = self._overlay_modes()
        for view in self._page_views.values():
            view.overlay.set_select_mode(select)
            view.overlay.set_note_mode(note)
            view.overlay.set_ink_mode(ink)

    # --- navigation ------------------------------------------------------
    @property
    def current_page(self) -> int:
        return self._page

    @property
    def zoom_ratio(self) -> float:
        return self._zoom

    def set_page(self, page: int, *, emit: bool = True) -> None:
        if not self._doc or not 0 <= page < self._doc.page_count:
            return
        self._page = page
        self._selection = None
        if self._layout_mode == LayoutMode.SINGLE:
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
        self._zoom = value
        self._generation += 1
        self._pending.clear()
        self._teardown_views()
        if self._doc:
            self._relayout()
        if emit:
            self.zoomChanged.emit(value)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def fit_width(self) -> None:
        if not self._doc:
            return
        page_width = self._doc.load_page(self._page).rect.width
        available = max(100, self.viewport().width() - MARGIN * 2)
        self.set_zoom(available / page_width)

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

    # --- selection and annotations --------------------------------------
    def _on_selection(self, page_num: int, widget_rect: QRectF) -> None:
        if not self._doc or page_num not in self._page_views:
            return
        overlay = self._page_views[page_num].overlay
        pdf_rect = fitz.Rect(
            overlay.widget_to_pdf(widget_rect.topLeft()),
            overlay.widget_to_pdf(widget_rect.bottomRight()),
        )
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
                )
            )
            return
        if self._tool_mode == ToolMode.REDACT:
            self.annotationRequested.emit(
                AnnotationOp(kind="redact", page=page_num, rects=(pdf_rect,))
            )
            return
        if self._tool_mode == ToolMode.STAMP:
            height = pdf_rect.width * STAMP_ASPECT
            stamp_rect = fitz.Rect(pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y0 + height)
            self.annotationRequested.emit(
                AnnotationOp(
                    kind="stamp",
                    page=page_num,
                    rects=(stamp_rect,),
                    stamp_kind=self._annot_options["stamp_kind"],
                )
            )
            return
        if self._tool_mode in {ToolMode.SIGNATURE, ToolMode.IMAGE}:
            image_path = self._annot_options["image_path"]
            if image_path:
                self.annotationRequested.emit(
                    AnnotationOp(
                        kind="image",
                        page=page_num,
                        rects=(pdf_rect,),
                        image_path=image_path,
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
            )
        )

    def _on_note(self, page_num: int, point_widget) -> None:
        if not self._doc or page_num not in self._page_views:
            return
        overlay = self._page_views[page_num].overlay
        self.noteRequested.emit(page_num, overlay.widget_to_pdf(point_widget))

    def clear_selection(self) -> None:
        self._selection = None
        for view in self._page_views.values():
            view.overlay.set_selection_rects([])

    # --- layout engine ---------------------------------------------------
    def _teardown_views(self) -> None:
        for view in self._page_views.values():
            view.setParent(None)
            view.deleteLater()
        self._page_views.clear()

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
            pages = [first] + (
                [first + 1] if first + 1 < self._doc.page_count else []
            )
            rows.append((y, pages))
            row_height = max(
                round(self._doc.load_page(p).rect.height * self._zoom) for p in pages
            )
            y += row_height + CAPTION_H + PAGE_SPACING
        return rows

    def _page_rect_in_layout(self, page_num: int) -> QRectF:
        if not self._doc or not 0 <= page_num < self._doc.page_count:
            return QRectF()
        page = self._doc.load_page(page_num)
        width = round(page.rect.width * self._zoom)
        height = round(page.rect.height * self._zoom)
        viewport_width = max(1, self.viewport().width())
        for row_y, pages in self._rows:
            if page_num not in pages:
                continue
            if len(pages) == 1:
                x = MARGIN + max(0, (viewport_width - 2 * MARGIN - width) / 2)
                return QRectF(x, row_y, width, height)
            widths = [
                round(self._doc.load_page(p).rect.width * self._zoom) for p in pages
            ]
            row_width = sum(widths) + PAGE_SPACING * (len(pages) - 1)
            x = MARGIN + max(0, (viewport_width - 2 * MARGIN - row_width) / 2)
            index = pages.index(page_num)
            x += sum(widths[:index]) + PAGE_SPACING * index
            return QRectF(x, row_y, width, height)
        return QRectF()

    def _total_size(self) -> QSize:
        if not self._doc or not self._rows:
            return QSize(0, 0)
        width = max(1, self.viewport().width())
        last_y, last_pages = self._rows[-1]
        last_height = max(
            round(self._doc.load_page(p).rect.height * self._zoom)
            for p in last_pages
        )
        height = last_y + last_height + CAPTION_H + MARGIN
        return QSize(width, max(1, height))

    def _relayout(self) -> None:
        if not self._doc:
            return
        self._rows = self._compute_rows()
        self._pager.setFixedSize(self._total_size())
        self._sync_views()
        self._update_current_from_scroll()

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
                round(self._doc.load_page(p).rect.height * self._zoom)
                for p in pages
            )
            if row_y + row_height + CAPTION_H >= top and row_y <= bottom:
                visible.extend(pages)
        return visible

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
            select, note, ink = self._overlay_modes()
            view.overlay.set_select_mode(select)
            view.overlay.set_note_mode(note)
            view.overlay.set_ink_mode(ink)
            view.overlay.selectionMade.connect(self._on_selection)
            view.overlay.inkDrawn.connect(self._on_ink)
            view.overlay.noteClicked.connect(self._on_note)
            view.overlay.set_geometry_info(page.rect, 1.0 / self._zoom)
            self._page_views[page_num] = view
            self._request_render(page_num, page_num in focused)
        self._apply_search_hits()

    def _request_render(self, page_num: int, high: bool = False) -> None:
        if not self._doc or page_num in self._pending:
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
                quick = render_page_pixmap_quick(
                    self._doc, page_num, self._zoom, dpr
                )
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
                    pixmap = render_page_pixmap(
                        self._doc, page_num, self._zoom, dpr
                    )
            except BaseException:
                return
            self._cache.put(key, pixmap)
            view = self._page_views.get(page_num)
            if view is not None:
                view.set_pixmap(pixmap, self._doc.load_page(page_num))
            return
        self._pending.add(page_num)
        task = _RenderTask(
            self._doc, page_num, self._zoom, dpr, key, self._generation
        )
        task.signals.finished.connect(self._on_render_done)
        # Higher values run earlier in the pool; visible pages go first.
        self._pool.start(task, 6 if high else 0)

    def _on_render_done(
        self,
        page_num: int,
        generation: int,
        key: tuple,
        pixmap: QPixmap,
    ) -> None:
        self._pending.discard(page_num)
        if generation != self._generation or not self._doc:
            return
        self._cache.put(key, pixmap)
        view = self._page_views.get(page_num)
        if view is not None:
            view.set_pixmap(pixmap, self._doc.load_page(page_num))

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
        if self._doc and self._layout_mode != LayoutMode.SINGLE:
            # Coalesce continuous window-drag resizes into one relayout.
            self._resize_timer.start()

    def _apply_pending_relayout(self) -> None:
        if not self._doc or self._layout_mode == LayoutMode.SINGLE:
            return
        self._teardown_views()
        self._relayout()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self._queue_zoom(self._zoom * factor)
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
        if self._hand_anchor is not None and event.button() == Qt.MouseButton.LeftButton:
            self._hand_anchor = None
            self._refresh_cursors()
            return True
        return False

    def _viewport_key_press(self, event) -> bool:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and not self._temp_hand:
            self._temp_hand = True
            self._refresh_cursors()
            return True
        if event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._selection:
                self.textCopied.emit(self._selection[1])
                return True
        return False

    def _viewport_key_release(self, event) -> bool:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and self._temp_hand:
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

    def _update_magnifier(self, position: QPoint) -> None:
        pager_pos = self._to_pager(position)
        if pager_pos is None:
            return
        page_num = self._page_at(pager_pos)
        if page_num is None or not self._doc:
            if self._magnifier_popup:
                self._magnifier_popup.hide()
            self._last_magnifier = None
            return
        last = self._last_magnifier
        if last is not None and last[0] == page_num:
            delta = pager_pos - last[1]
            if abs(delta.x()) < 4 and abs(delta.y()) < 4:
                return  # cursor barely moved: reuse the current sample
        self._last_magnifier = (page_num, pager_pos)
        overlay = self._page_views[page_num].overlay
        local = overlay.mapFrom(self._pager, pager_pos)
        pdf_point = overlay.widget_to_pdf(local)
        page = self._doc.load_page(page_num)
        dpr = self.devicePixelRatioF()
        half = MAGNIFIER_SIZE / (2 * MAGNIFIER_ZOOM * self._zoom)
        clip = fitz.Rect(
            pdf_point.x - half,
            pdf_point.y - half,
            pdf_point.x + half,
            pdf_point.y + half,
        )
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
        popup = self._magnifier_popup
        if popup is None:
            popup = QLabel(self)
            popup.setObjectName("magnifierPopup")
            popup.setWindowFlags(Qt.WindowType.ToolTip)
            popup.setFixedSize(MAGNIFIER_SIZE, MAGNIFIER_SIZE)
            self._magnifier_popup = popup
        popup.setPixmap(
            QPixmap.fromImage(image).scaled(
                MAGNIFIER_SIZE,
                MAGNIFIER_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        popup.move(self.viewport().mapToGlobal(position) + QPoint(16, 16))
        popup.show()
