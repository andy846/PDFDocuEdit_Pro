"""Scrollable page-thumbnail sidebar for visual navigation."""

from __future__ import annotations

from collections import OrderedDict

import fitz
from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.diagnostics import connect_interrupts, log_failure
from styles.tokens import D, S

from .motion import MotionIconButton

THUMBNAIL_WIDTH = 110
THUMBNAIL_SCALE = 0.25
CACHE_SIZE = 80
MAX_PENDING_RENDERS = 12
OVERSCAN = 6


class ReorderListWidget(QListWidget):
    """Thumbnail list that reports the final page order after a drag-drop."""

    orderDropped = pyqtSignal(list)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        order = [
            int(self.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.count())
        ]
        self.orderDropped.emit(order)




class _RenderSignals(QObject):
    interrupted = pyqtSignal(str)
    finished = pyqtSignal(int, object, int)
    failed = pyqtSignal(int, int)


class _RenderTask(QRunnable):
    """Background task that renders a single page thumbnail."""

    def __init__(
        self,
        doc_path: str,
        page_num: int,
        scale: float,
        password: str | None,
        generation: int,
    ):
        super().__init__()
        # The panel retains tasks until their completion signal so queued
        # off-screen renders can be safely removed with QThreadPool.tryTake().
        self.setAutoDelete(False)
        self._doc_path = doc_path
        self._page_num = page_num
        self._scale = scale
        self._password = password
        self._generation = generation
        self.signals = _RenderSignals()
        connect_interrupts(self.signals)

    def run(self) -> None:
        try:
            with fitz.open(self._doc_path) as doc:
                if self._password and doc.needs_pass:
                    doc.authenticate(self._password)
                if self._page_num >= doc.page_count:
                    raise ValueError("Thumbnail page is unavailable")
                page = doc.load_page(self._page_num)
                matrix = fitz.Matrix(self._scale, self._scale)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                image = QImage(
                    pixmap.samples,
                    pixmap.width,
                    pixmap.height,
                    pixmap.stride,
                    QImage.Format.Format_RGB888,
                ).copy()
                self.signals.finished.emit(self._page_num, image, self._generation)
        except (KeyboardInterrupt, SystemExit) as exc:
            self.signals.failed.emit(self._page_num, self._generation)
            self.signals.interrupted.emit(type(exc).__name__)
        except Exception:
            log_failure("Thumbnail render failed")
            self.signals.failed.emit(self._page_num, self._generation)


class ThumbnailPanel(QFrame):
    """Vertical list of page thumbnails that syncs with the canvas."""

    pageSelected = pyqtSignal(int)
    closed = pyqtSignal()
    reorderRequested = pyqtSignal(list)
    contextActionRequested = pyqtSignal(str)

    def __init__(self, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("thumbnailPanel")
        self._animations_enabled = animations_enabled
        self._doc_path: str | None = None
        self._password: str | None = None
        self._page_count = 0
        self._pending: set[int] = set()
        self._tasks: dict[int, _RenderTask] = {}
        self._failures: dict[int, int] = {}
        self._cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._widget_rows: set[int] = set()
        self._generation = 0
        # A panel-owned pool lets a document wait for only its own thumbnail
        # readers before deleting the editable temporary PDF on Windows.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S.XS, S.XS, S.XS, S.SM)
        layout.setSpacing(S.XS)

        header = QHBoxLayout()
        title = QLabel("Pages")
        title.setObjectName("sidebarTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._close = MotionIconButton("x", "Close thumbnails (Ctrl+T)", D.ICON_SM)
        self._close.clicked.connect(self.closed.emit)
        header.addWidget(self._close)
        layout.addLayout(header)

        self._list = ReorderListWidget()
        self._list.setObjectName("thumbnailList")
        self._list.viewport().installEventFilter(self)
        self._list.setIconSize(QSize(THUMBNAIL_WIDTH, int(THUMBNAIL_WIDTH * 1.414)))
        self._list.setSpacing(S.XS)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # _visible_range uses viewport pixels. QListWidget otherwise defaults
        # to per-item scrollbar units on Windows, so a jump to page 70 could
        # still be misread as only a few pixels from page 1.
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setUniformItemSizes(True)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setDragEnabled(True)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.orderDropped.connect(self.reorderRequested.emit)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.verticalScrollBar().valueChanged.connect(self._render_visible_thumbnails)
        layout.addWidget(self._list, 1)

    def eventFilter(self, watched, event):
        if watched is self._list.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._render_visible_thumbnails)
        return super().eventFilter(watched, event)

    def _show_context_menu(self, position) -> None:
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self._list)
        for label, key in (
            ("Insert Page…", "insert"),
            ("Delete Current Page", "delete_current"),
            ("Extract Current Page…", "extract_current"),
            ("Rotate Pages…", "rotate"),
            ("Search", "search"),
            ("Document Info", "info"),
        ):
            menu.addAction(label).triggered.connect(
                lambda _checked=False, value=key: self.contextActionRequested.emit(value)
            )
        menu.exec(self._list.viewport().mapToGlobal(position))

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._close.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        self._close.refresh_icon()

    def load_document(self, doc_path: str, page_count: int, password: str | None = None) -> None:
        """Load thumbnails for a document."""
        self._stop_renders()
        self._doc_path = doc_path
        self._password = password
        self._page_count = page_count
        self._cache.clear()
        self._pending.clear()
        self._tasks.clear()
        self._failures.clear()
        self._widget_rows.clear()
        self._list.clear()

        for page_num in range(page_count):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, page_num)
            item.setSizeHint(QSize(THUMBNAIL_WIDTH + S.MD, int(THUMBNAIL_WIDTH * 1.414) + 28))
            self._list.addItem(item)

        self._render_visible_thumbnails()

    def _make_thumbnail_widget(self, page_num: int) -> QWidget:
        widget = QWidget()
        widget.setObjectName("thumbnailItem")
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(S.XS, S.XS, S.XS, S.XS)
        outer.setSpacing(2)

        image_label = QLabel()
        image_label.setObjectName("thumbnailImage")
        image_label.setFixedSize(THUMBNAIL_WIDTH, int(THUMBNAIL_WIDTH * 1.414))
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setProperty("placeholder", True)
        image_label.setText(f"Page {page_num + 1}\nLoading…")
        outer.addWidget(image_label, 0, Qt.AlignmentFlag.AlignCenter)

        page_label = QLabel(str(page_num + 1))
        page_label.setObjectName("thumbnailPageNumber")
        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(page_label)

        widget.image_label = image_label  # type: ignore[attr-defined]
        return widget

    def _on_row_changed(self, row: int) -> None:
        if row >= 0:
            self.pageSelected.emit(row)
        self._render_visible_thumbnails()

    def set_current_page(self, page: int) -> None:
        if 0 <= page < self._list.count():
            self._list.blockSignals(True)
            self._list.setCurrentRow(page)
            self._list.blockSignals(False)
            self._list.scrollToItem(self._list.item(page))
            self._render_visible_thumbnails()

    def clear(self) -> None:
        self._stop_renders()
        self._page_count = 0
        self._cache.clear()
        self._widget_rows.clear()
        self._list.clear()

    def _stop_renders(self) -> None:
        """Invalidate queued renders and wait until their PDF handles close."""
        self._doc_path = None
        self.quiesce_renders()

    def quiesce_renders(self) -> None:
        """Release file handles while keeping the current thumbnail source."""
        self._generation += 1
        self._pool.waitForDone()
        self._pending.clear()
        self._tasks.clear()
        self._failures.clear()

    def _render_visible_thumbnails(self) -> None:
        """Schedule rendering only for pages near the visible window.

        The whole list would schedule one task per page (each re-opening the
        PDF); instead only the scroll window plus a small overscan renders,
        with a hard cap on in-flight tasks.
        """
        if not self._doc_path or self._list.count() == 0:
            return
        first, last = self._visible_range()
        wanted = set(range(first, last + 1))
        visible_first, visible_last = self._visible_range(overscan=0)
        focused = set(range(visible_first, visible_last + 1))
        # Keep page rows lightweight: widgets exist only around the viewport.
        for index in self._widget_rows - wanted:
            self._list.removeItemWidget(self._list.item(index))
        for index in wanted - self._widget_rows:
            item = self._list.item(index)
            self._list.setItemWidget(item, self._make_thumbnail_widget(index))
            if index in self._cache:
                self._display_thumbnail(index, self._cache[index])
        self._widget_rows = wanted
        # Rapid scrolling should not wait behind pages that have not started
        # rendering for the old viewport. Running workers finish normally;
        # queued stale workers are removed and their slots reused at once.
        for page_num in list(self._pending - focused):
            task = self._tasks.get(page_num)
            if task is not None and self._pool.tryTake(task):
                self._tasks.pop(page_num, None)
                self._pending.discard(page_num)
        # Render actual screen pages before prefetch pages above/below them.
        order = sorted(wanted, key=lambda page: (
            page not in focused,
            min(abs(page - visible_first), abs(page - visible_last)),
            page,
        ))
        for index in order:
            if len(self._pending) >= MAX_PENDING_RENDERS:
                return
            if index not in self._cache and self._failures.get(index, 0) == 0:
                self._schedule_render(index, priority=10 if index in focused else 0)

    def _visible_range(self, overscan: int = OVERSCAN) -> tuple[int, int]:
        first_item = self._list.item(0)
        if first_item is None:
            return (0, 0)
        item_height = first_item.sizeHint().height() + self._list.spacing()
        viewport_height = self._list.viewport().height()
        top_index = self._list.indexAt(QPoint(2, 2))
        bottom_index = self._list.indexAt(
            QPoint(2, max(2, viewport_height - 2))
        )
        first_visible = (
            top_index.row()
            if top_index.isValid()
            else self._list.verticalScrollBar().value() // max(1, item_height)
        )
        last_visible = (
            bottom_index.row()
            if bottom_index.isValid()
            else first_visible + max(1, viewport_height // max(1, item_height))
        )
        first = max(0, first_visible - overscan)
        last = min(
            self._list.count() - 1,
            last_visible + overscan,
        )
        return first, last

    def _schedule_render(self, page_num: int, priority: int = 5) -> None:
        if page_num in self._pending or not self._doc_path or self._failures.get(page_num, 0) >= 2:
            return
        self._pending.add(page_num)
        task = _RenderTask(
            self._doc_path, page_num, THUMBNAIL_SCALE, self._password, self._generation
        )
        task.signals.finished.connect(self._on_thumbnail_rendered)
        task.signals.failed.connect(self._on_thumbnail_failed)
        self._tasks[page_num] = task
        self._pool.start(task, priority)

    def _on_thumbnail_rendered(self, page_num: int, image: QImage, generation: int) -> None:
        if generation != self._generation:
            return  # stale render from a previous document
        self._tasks.pop(page_num, None)
        self._pending.discard(page_num)
        if page_num >= self._list.count():
            return
        self._failures.pop(page_num, None)
        pixmap = QPixmap.fromImage(image)
        self._cache[page_num] = pixmap
        if len(self._cache) > CACHE_SIZE:
            oldest = next(iter(self._cache))
            del self._cache[oldest]

        self._display_thumbnail(page_num, pixmap)

        # A scroll event can initially fill the pending-task cap with pages
        # from the old viewport. Keep refilling from the *current* visible
        # range as tasks finish; otherwise later thumbnails remain blank until
        # the user nudges the scrollbar again.
        self._render_visible_thumbnails()

    def _display_thumbnail(self, page_num: int, pixmap: QPixmap) -> None:
        item = self._list.item(page_num)
        widget = self._list.itemWidget(item)
        if widget:
            self._cache.move_to_end(page_num)
            label = widget.image_label  # type: ignore[attr-defined]
            label.setPixmap(pixmap.scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            label.setProperty("placeholder", False)
            label.style().unpolish(label)
            label.style().polish(label)

    def _on_thumbnail_failed(self, page_num: int, generation: int) -> None:
        if generation != self._generation:
            return
        self._tasks.pop(page_num, None)
        self._pending.discard(page_num)
        attempts = self._failures.get(page_num, 0) + 1
        self._failures[page_num] = attempts
        if attempts < 2:
            # Retry once after the worker has released its file handle. The
            # generation guard prevents a retry from leaking into a new file.
            QTimer.singleShot(
                150,
                lambda page=page_num, token=generation: (
                    self._schedule_render(page)
                    if token == self._generation
                    else None
                ),
            )
        self._render_visible_thumbnails()
