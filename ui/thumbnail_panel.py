"""Scrollable page-thumbnail sidebar for visual navigation."""

from __future__ import annotations

from collections import OrderedDict

import fitz
from PyQt6.QtCore import (
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
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
    finished = pyqtSignal(int, object, int)


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
        self.setAutoDelete(True)
        self._doc_path = doc_path
        self._page_num = page_num
        self._scale = scale
        self._password = password
        self._generation = generation
        self.signals = _RenderSignals()

    def run(self) -> None:
        try:
            with fitz.open(self._doc_path) as doc:
                if self._password and doc.needs_pass:
                    doc.authenticate(self._password)
                if self._page_num >= doc.page_count:
                    return
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
        except BaseException:
            # Never let an exception escape QRunnable.run(): PyQt6 aborts the
            # process, and a thumbnail task failing must not kill the app.
            return


from PyQt6.QtCore import QObject  # noqa: E402 (already imported above, re-import for clarity)


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
        self._cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._generation = 0
        self._pool = QThreadPool.globalInstance()

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
        self._list.setIconSize(QSize(THUMBNAIL_WIDTH, int(THUMBNAIL_WIDTH * 1.414)))
        self._list.setSpacing(S.XS)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self._generation += 1
        self._doc_path = doc_path
        self._password = password
        self._page_count = page_count
        self._cache.clear()
        self._pending.clear()
        self._list.clear()

        for page_num in range(page_count):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, page_num)
            item.setSizeHint(QSize(THUMBNAIL_WIDTH + S.MD, int(THUMBNAIL_WIDTH * 1.414) + 28))
            self._list.addItem(item)
            widget = self._make_thumbnail_widget(page_num)
            self._list.setItemWidget(item, widget)

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
        self._generation += 1
        self._doc_path = None
        self._page_count = 0
        self._cache.clear()
        self._pending.clear()
        self._list.clear()

    def _render_visible_thumbnails(self) -> None:
        """Schedule rendering only for pages near the visible window.

        The whole list would schedule one task per page (each re-opening the
        PDF); instead only the scroll window plus a small overscan renders,
        with a hard cap on in-flight tasks.
        """
        if not self._doc_path or self._list.count() == 0:
            return
        first, last = self._visible_range()
        for index in range(first, last + 1):
            if len(self._pending) >= MAX_PENDING_RENDERS:
                return
            if index not in self._cache:
                self._schedule_render(index)

    def _visible_range(self) -> tuple[int, int]:
        first_item = self._list.item(0)
        if first_item is None:
            return (0, 0)
        item_height = first_item.sizeHint().height() + self._list.spacing()
        scroll = self._list.verticalScrollBar().value()
        viewport_height = self._list.viewport().height()
        first = max(0, scroll // item_height - OVERSCAN)
        last = min(
            self._list.count() - 1,
            (scroll + viewport_height) // item_height + OVERSCAN,
        )
        return first, last

    def _schedule_render(self, page_num: int) -> None:
        if page_num in self._pending or not self._doc_path:
            return
        self._pending.add(page_num)
        task = _RenderTask(
            self._doc_path, page_num, THUMBNAIL_SCALE, self._password, self._generation
        )
        task.signals.finished.connect(self._on_thumbnail_rendered)
        self._pool.start(task)

    def _on_thumbnail_rendered(self, page_num: int, image: QImage, generation: int) -> None:
        if generation != self._generation:
            return  # stale render from a previous document
        self._pending.discard(page_num)
        if page_num >= self._list.count():
            return
        pixmap = QPixmap.fromImage(image)
        self._cache[page_num] = pixmap
        if len(self._cache) > CACHE_SIZE:
            oldest = next(iter(self._cache))
            del self._cache[oldest]

        item = self._list.item(page_num)
        widget = self._list.itemWidget(item)
        if widget:
            label = widget.image_label  # type: ignore[attr-defined]
            label.setPixmap(pixmap.scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            label.setProperty("placeholder", False)
            label.style().unpolish(label)
            label.style().polish(label)
