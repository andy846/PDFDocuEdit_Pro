"""Tabbed navigation container: thumbnails, outline, bookmarks and search."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from styles.tokens import D, S

from .bookmark_panel import BookmarkPanel
from .icons import icon
from .motion import MotionIconButton
from .outline_panel import OutlinePanel
from .search_results_panel import SearchResultsPanel
from .thumbnail_panel import ThumbnailPanel

TAB_KEYS = ("thumbnails", "outline", "bookmarks")
TAB_LABELS = {
    "thumbnails": "Page thumbnails",
    "outline": "Outline",
    "bookmarks": "Bookmarks",
    "search": "Search document",
}
TAB_ICONS = {
    "thumbnails": "files",
    "outline": "list-tree",
    "bookmarks": "bookmark",
    "search": "search",
}


class NavPanel(QFrame):
    """Left-of-canvas dock hosting the four navigation panels."""

    tabChanged = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("navPanel")
        self.setFixedWidth(D.NAV_W)
        self._animations_enabled = animations_enabled
        self._active_key = "thumbnails"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        strip = QWidget()
        strip.setObjectName("navTabStrip")
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(S.XS, S.XS, S.XS, S.XS)
        strip_layout.setSpacing(S.XXS)

        self._tabs: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key in TAB_KEYS:
            button = QToolButton()
            button.setObjectName("navTabButton")
            button.setCheckable(True)
            button.setIcon(icon(TAB_ICONS[key], D.ICON_SM))
            button.setToolTip(TAB_LABELS[key])
            button.setAccessibleName(TAB_LABELS[key])
            button.clicked.connect(lambda _checked=False, value=key: self.show_panel(value))
            group.addButton(button)
            self._tabs[key] = button
            strip_layout.addWidget(button)
        strip_layout.addStretch(1)
        self._close = MotionIconButton("x", "Close navigation panel (Ctrl+T)", D.ICON_SM)
        self._close.clicked.connect(self.closed.emit)
        strip_layout.addWidget(self._close)
        layout.addWidget(strip)

        self._stack = QStackedWidget()
        self.thumbnails = ThumbnailPanel(animations_enabled=animations_enabled)
        self.thumbnails.closed.connect(self.closed.emit)
        self.outline = OutlinePanel()
        self.bookmarks = BookmarkPanel()
        self.search = SearchResultsPanel()
        for widget in (self.thumbnails, self.outline, self.bookmarks):
            self._stack.addWidget(widget)
        layout.addWidget(self._stack, 1)

        self._tabs["thumbnails"].setChecked(True)

    def show_panel(self, key: str) -> None:
        if key not in TAB_KEYS:
            return
        self._active_key = key
        self._tabs[key].setChecked(True)
        widget = {
            "thumbnails": self.thumbnails,
            "outline": self.outline,
            "bookmarks": self.bookmarks,
            "search": self.search,
        }[key]
        self._stack.setCurrentWidget(widget)
        self.show()
        self.tabChanged.emit(key)

    def active_key(self) -> str:
        return self._active_key

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_panel(self._active_key)

    def load_document(self, doc_path: str, page_count: int, password: str | None = None, *, defer_render: bool = False) -> None:
        self.thumbnails.load_document(doc_path, page_count, password, defer_render=defer_render)
        self.search.reset_query()
        self.outline.clear()
        self.bookmarks.clear()

    def clear_document(self) -> None:
        self.thumbnails.clear()
        self.outline.clear()
        self.bookmarks.clear()
        self.search.reset_query()

    def set_document_available(self, available: bool) -> None:
        for button in self._tabs.values():
            button.setEnabled(available)

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self.thumbnails.set_animations_enabled(enabled)
        self.bookmarks.set_animations_enabled(enabled)
        self._close.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        for key, button in self._tabs.items():
            button.setIcon(icon(TAB_ICONS[key], D.ICON_SM))
        self.thumbnails.refresh_icons()
        self.bookmarks.refresh_icons()
        self._close.refresh_icon()
