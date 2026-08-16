"""Central empty/document workspace with drag-and-drop and document tabs."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.platform_service import PlatformService
from styles.theme import get_color
from styles.tokens import D, S

from .document_session import DocumentSession
from .icons import icon
from .motion import MotionIconButton
from .pdf_canvas import PdfCanvas

RECENT_THUMB_SCALE = 0.08
RECENT_ICON_W = 32
RECENT_ICON_H = 44


class _RecentSignals(QObject):
    finished = pyqtSignal(str, object)  # (path, QPixmap)


class _RecentThumbTask(QRunnable):
    """Background render of a recent file's first page."""

    def __init__(self, path: str, scale: float = RECENT_THUMB_SCALE):
        super().__init__()
        self.setAutoDelete(True)
        self._path = path
        self._scale = scale
        self.signals = _RecentSignals()

    def run(self) -> None:
        try:
            with fitz.open(self._path) as doc:
                page = doc.load_page(0)
                matrix = fitz.Matrix(self._scale, self._scale)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                ).copy()
                self.signals.finished.emit(self._path, QPixmap.fromImage(image))
        except BaseException:
            return


class EmptyState(QWidget):
    openRequested = pyqtSignal()
    recentRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_active = False
        self._animations_enabled = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(S.XXL, S.XL, S.XXL, S.XL)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zone = QFrame()
        self._zone.setObjectName("emptyDropZone")
        self._zone.setMinimumSize(520, 370)
        self._zone.setMaximumWidth(720)
        layout = QVBoxLayout(self._zone)
        layout.setContentsMargins(S.XXL, S.XL, S.XXL, S.XL)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(S.MD)
        eyebrow = QLabel("YOUR PDF WORKSPACE")
        eyebrow.setObjectName("emptyEyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(eyebrow)
        self._image = QLabel()
        self._image.setObjectName("emptyIconBadge")
        self._image.setFixedSize(76, 76)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._image)
        self._title = QLabel("Make documents easier to work with")
        self._title.setObjectName("emptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        self._description = QLabel(
            "Open a PDF to edit, convert, secure and automate it — all in one focused workspace."
        )
        self._description.setObjectName("emptyDescription")
        self._description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._description.setWordWrap(True)
        self._description.setMaximumWidth(540)
        layout.addWidget(self._description)
        self._open_button = QPushButton("Open PDF…")
        self._open_button.setProperty("primary", True)
        self._open_button.setIcon(icon("folder-open", D.ICON_SM, get_color("on_primary")))
        self._open_button.clicked.connect(self.openRequested.emit)
        layout.addWidget(self._open_button, 0, Qt.AlignmentFlag.AlignCenter)
        self._drop_hint = QLabel("or drop PDF / PostScript anywhere here")
        self._drop_hint.setObjectName("dropHint")
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._drop_hint)
        self._recent_title = QLabel("Recent files")
        self._recent_title.setObjectName("sectionTitle")
        self._recent_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._recent_title)
        self._recent = QListWidget()
        self._recent.setMaximumWidth(560)
        self._recent.setMaximumHeight(150)
        self._recent.setIconSize(QSize(RECENT_ICON_W, RECENT_ICON_H))
        self._recent.itemActivated.connect(lambda item: self.recentRequested.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self._recent)
        outer.addWidget(self._zone)
        self._recent_items: dict[str, QListWidgetItem] = {}
        self._thumb_done: set[str] = set()
        self._recent_pool = QThreadPool.globalInstance()

        self._image_opacity = QGraphicsOpacityEffect(self._image)
        self._image.setGraphicsEffect(self._image_opacity)
        self._pulse = QPropertyAnimation(self._image_opacity, b"opacity", self)
        self._pulse.setDuration(1450)
        self._pulse.setStartValue(0.62)
        self._pulse.setEndValue(1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self.refresh_icons()
        self._pulse.start()

    def set_recent_files(self, paths: list[str]) -> None:
        self._recent.clear()
        self._recent_items.clear()
        self._thumb_done.clear()
        for value in paths[:5]:
            path = Path(value)
            item = QListWidgetItem(icon("file-text", D.ICON_SM), path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setSizeHint(QSize(0, RECENT_ICON_H + 4))
            self._recent.addItem(item)
            self._recent_items[str(path)] = item
            self._schedule_recent_thumb(str(path))
        visible = bool(paths)
        self._recent_title.setVisible(visible)
        self._recent.setVisible(visible)

    def _schedule_recent_thumb(self, path: str) -> None:
        task = _RecentThumbTask(path)
        task.signals.finished.connect(self._on_recent_thumb)
        self._recent_pool.start(task)

    def _on_recent_thumb(self, path: str, pixmap: QPixmap) -> None:
        item = self._recent_items.get(path)
        if item is None or self._recent.row(item) < 0:
            return  # stale result for a list that has since changed
        self._thumb_done.add(path)
        item.setIcon(
            QIcon(
                pixmap.scaled(
                    QSize(RECENT_ICON_W, RECENT_ICON_H),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        )

    def refresh_icons(self) -> None:
        name = "folder-open" if self._drag_active else "file-text"
        self._image.setPixmap(
            icon(name, 42, get_color("primary")).pixmap(QSize(42, 42))
        )
        self._open_button.setIcon(icon("folder-open", D.ICON_SM, get_color("on_primary")))
        for index in range(self._recent.count()):
            item = self._recent.item(index)
            if item.data(Qt.ItemDataRole.UserRole) not in self._thumb_done:
                item.setIcon(icon("file-text", D.ICON_SM))

    def set_drag_active(self, active: bool) -> None:
        if self._drag_active == active:
            return
        self._drag_active = active
        self._zone.setProperty("dragActive", active)
        self._zone.style().unpolish(self._zone)
        self._zone.style().polish(self._zone)
        self._title.setText("Release to open this document" if active else "Make documents easier to work with")
        self._description.setText(
            "PDFDocuEdit Pro will open it in the focused document canvas."
            if active
            else "Open a PDF to edit, convert, secure and automate it — all in one focused workspace."
        )
        self._drop_hint.setText("Ready — let go to open" if active else "or drop PDF / PostScript anywhere here")
        self.refresh_icons()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        if enabled and self.isVisible():
            self._pulse.start()
        else:
            self._pulse.stop()
            self._image_opacity.setOpacity(1.0)

    def set_active(self, active: bool) -> None:
        if active and self._animations_enabled:
            if self._pulse.state() != QAbstractAnimation.State.Running:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._image_opacity.setOpacity(1.0)


class TabCloseButton(MotionIconButton):
    """Tab close button that tolerates the drift of a real mouse click.

    A real click on a 24 px target almost always drifts a few pixels. Qt
    cancels the press as soon as the cursor leaves the widget rect, and the
    release event is then delivered to whatever widget sits under the cursor
    (the tab bar), so the button never even sees it. This subclass grabs the
    mouse on press, routing every move/release back to the button, and
    widens the hit area by HIT_MARGIN so a normal tremor still counts.
    Dragging well away cancels the click.
    """

    _HIT_MARGIN = 10

    def __init__(self, parent=None):
        super().__init__("x", "Close tab", D.ICON_SM, parent=parent)
        self.setObjectName("tabCloseButton")
        self._press_inside = False

    def _hit_rect(self):
        return self.rect().adjusted(
            -self._HIT_MARGIN,
            -self._HIT_MARGIN,
            self._HIT_MARGIN,
            self._HIT_MARGIN,
        )

    def mousePressEvent(self, event) -> None:
        self._press_inside = (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        )
        super().mousePressEvent(event)
        if self._press_inside:
            # Keep every move/release coming to this button even when the
            # cursor slides off it mid-press.
            self.grabMouse()

    def mouseReleaseEvent(self, event) -> None:
        press_inside = self._press_inside
        self._press_inside = False
        self.releaseMouse()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and press_inside
            and self._hit_rect().contains(event.position().toPoint())
        ):
            will_click = self.isDown() and self.rect().contains(
                event.position().toPoint()
            )
            if not will_click:
                # The pointer drifted outside the widget during the press, so
                # Qt cancelled the click. The release is still inside the
                # forgiving hit area, so complete the click ourselves.
                self.setDown(False)
                self._animate(
                    self._base_size + 4 if self._hovered else self._base_size, 150
                )
                self.released.emit()
                self.clicked.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)


class DocumentWorkspace(QFrame):
    """Tabbed document area. Compatibility properties ``canvas`` and
    ``nav_panel`` resolve to the current tab's widgets."""

    openRequested = pyqtSignal()
    fileDropped = pyqtSignal(str)
    extraFilesDropped = pyqtSignal(list)
    tabCloseRequested = pyqtSignal(object)  # DocumentSession
    tabCloseOthersRequested = pyqtSignal(object)  # DocumentSession to keep
    tabCloseAllRequested = pyqtSignal()
    tabChanged = pyqtSignal(object)  # DocumentSession

    def __init__(self, recent_files: list[str] | None = None, animations_enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._animations_enabled = animations_enabled
        self._sessions: dict[int, DocumentSession] = {}
        # The tab close buttons are Python subclasses (TabCloseButton). The
        # C++ QTabBar owns the underlying QToolButton, but nothing else keeps
        # the Python wrapper alive — without this reference the wrapper gets
        # garbage-collected and reverts to a plain QToolButton, silently
        # dropping the overridden mouse handlers and the clicked connection.
        self._close_buttons: dict[int, TabCloseButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        self._empty = EmptyState()
        self._empty.openRequested.connect(self.openRequested.emit)
        self._empty.recentRequested.connect(self.fileDropped.emit)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("documentTabs")
        # Use an explicit icon button: Windows may not paint QTabBar's native
        # close primitive under the dark stylesheet.
        self._tabs.setTabsClosable(False)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tabs.currentChanged.connect(self._on_current_changed)
        tab_bar = self._tabs.tabBar()
        tab_bar.setUsesScrollButtons(True)
        tab_bar.setExpanding(False)
        tab_bar.setElideMode(Qt.TextElideMode.ElideMiddle)
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._on_tab_context_menu)
        tab_bar.installEventFilter(self)

        self._tab_list_menu = QMenu(self._tabs)
        self._tab_list_menu.aboutToShow.connect(self._rebuild_tab_list_menu)
        self._tab_list_button = QToolButton(self._tabs)
        self._tab_list_button.setObjectName("documentTabListButton")
        self._tab_list_button.setAutoRaise(True)
        self._tab_list_button.setFixedSize(D.CONTROL_H, D.CONTROL_H)
        self._tab_list_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._tab_list_button.setMenu(self._tab_list_menu)
        self._tab_list_button.setToolTip("Show all open documents")
        self._tab_list_button.setAccessibleName("All open document tabs")
        self._tab_list_button.setVisible(False)
        self._tabs.setCornerWidget(
            self._tab_list_button, Qt.Corner.TopRightCorner
        )
        self._refresh_tab_navigation_icons()

        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._tabs)
        layout.addWidget(self._stack)

        self.set_recent_files(recent_files or [])

    # --- tab management --------------------------------------------------
    def create_tab(self, session: DocumentSession) -> None:
        index = self._tabs.addTab(session.tab_widget, session.tab_title)
        close_button = TabCloseButton()
        close_button.set_animations_enabled(self._animations_enabled)
        close_button.installEventFilter(self)
        self._tabs.tabBar().setTabButton(
            index, QTabBar.ButtonPosition.RightSide, close_button
        )
        # Keep the Python wrapper alive so the subclass mouse handlers and
        # any clicked connection survive (see the _close_buttons comment).
        self._close_buttons[index] = close_button
        self._sessions[index] = session
        self._stack.setCurrentWidget(self._tabs)
        self._tabs.setCurrentIndex(index)
        self._empty.set_active(False)
        self._update_tab_navigation()

    def close_tab(self, session: DocumentSession) -> None:
        for index, candidate in list(self._sessions.items()):
            if candidate is session:
                bar = self._tabs.tabBar()
                close_button = bar.tabButton(
                    index, QTabBar.ButtonPosition.RightSide
                )
                if close_button is not None:
                    # QTabBar can leave a custom button alive after
                    # removeTab(), producing a visible but inert ghost X.
                    close_button.removeEventFilter(self)
                    close_button.hide()
                    bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
                    close_button.deleteLater()
                self._close_buttons.pop(index, None)
                self._tabs.removeTab(index)
                del self._sessions[index]
                # Rebuild the index mapping after removal.
                rebuilt: dict[int, DocumentSession] = {}
                rebuilt_buttons: dict[int, TabCloseButton] = {}
                for tab_index in range(self._tabs.count()):
                    widget = self._tabs.widget(tab_index)
                    for candidate_session in self._sessions.values():
                        if candidate_session.tab_widget is widget:
                            rebuilt[tab_index] = candidate_session
                            button = bar.tabButton(
                                tab_index, QTabBar.ButtonPosition.RightSide
                            )
                            if isinstance(button, TabCloseButton):
                                rebuilt_buttons[tab_index] = button
                            break
                self._sessions = rebuilt
                self._close_buttons = rebuilt_buttons
                break
        if not self._sessions:
            self._stack.setCurrentWidget(self._empty)
            self._empty.set_active(True)
        self._update_tab_navigation()
        self._tabs.tabBar().update()
        self._stack.update()

    def session_at(self, index: int) -> DocumentSession | None:
        return self._sessions.get(index)

    def session_count(self) -> int:
        return len(self._sessions)

    def current_session(self) -> DocumentSession | None:
        return self.session_at(self._tabs.currentIndex())

    def set_current_session(self, session: DocumentSession) -> None:
        for index, candidate in self._sessions.items():
            if candidate is session:
                self._tabs.setCurrentIndex(index)
                return

    def update_tab_title(self, session: DocumentSession) -> None:
        for index, candidate in self._sessions.items():
            if candidate is session:
                self._tabs.setTabText(index, session.tab_title)
                self._tabs.setTabToolTip(
                    index,
                    str(session.display_path) if session.display_path else session.document_name,
                )
                return

    def _update_tab_navigation(self) -> None:
        self._tab_list_button.setVisible(self._tabs.count() > 1)
        # Scroll buttons are owned by QTabBar and can be created lazily.
        QTimer.singleShot(0, self._refresh_tab_navigation_icons)

    def _refresh_tab_navigation_icons(self) -> None:
        colour = get_color("text_secondary")
        for object_name, icon_name, tooltip in (
            ("ScrollLeftButton", "chevron-left", "Show previous tabs"),
            ("ScrollRightButton", "chevron-right", "Show next tabs"),
        ):
            button = self._tabs.tabBar().findChild(QToolButton, object_name)
            if button is None:
                continue
            button.setIcon(icon(icon_name, D.ICON_SM, colour))
            button.setAutoRaise(True)
            button.setToolTip(tooltip)

        self._tab_list_button.setIcon(
            icon("list-tree", D.ICON_SM, colour)
        )
        self._tab_list_button.setIconSize(QSize(D.ICON_SM, D.ICON_SM))

    def _rebuild_tab_list_menu(self) -> None:
        self._tab_list_menu.clear()
        current_index = self._tabs.currentIndex()
        for index in range(self._tabs.count()):
            session = self.session_at(index)
            if session is None:
                continue
            action = self._tab_list_menu.addAction(
                icon("file-text", D.ICON_SM),
                session.tab_title,
            )
            action.setCheckable(True)
            action.setChecked(index == current_index)
            path = session.display_path or session.document_name
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda checked=False, tab_index=index: self._tabs.setCurrentIndex(
                    tab_index
                )
            )

    def _on_tab_close_requested(self, index: int) -> None:
        session = self.session_at(index)
        if session is not None:
            self.tabCloseRequested.emit(session)

    def _on_tab_context_menu(self, position) -> None:
        bar = self._tabs.tabBar()
        index = bar.tabAt(position)
        if index < 0:
            return
        session = self.session_at(index)
        if session is None:
            return
        menu = QMenu(self)
        close = menu.addAction("Close Tab")
        close.triggered.connect(lambda: self.tabCloseRequested.emit(session))
        close_others = menu.addAction("Close Other Tabs")
        close_others.setEnabled(len(self._sessions) > 1)
        close_others.triggered.connect(lambda: self.tabCloseOthersRequested.emit(session))
        close_all = menu.addAction("Close All Tabs")
        close_all.triggered.connect(self.tabCloseAllRequested.emit)
        menu.addSeparator()
        reveal_path = session.display_path or session.engine.original_path
        reveal = menu.addAction("Reveal in Folder")
        reveal.setEnabled(bool(reveal_path and Path(reveal_path).exists()))
        if reveal.isEnabled():
            reveal.triggered.connect(
                lambda: PlatformService.open_folder(Path(reveal_path).parent)
            )
        menu.exec(bar.mapToGlobal(position))

    def eventFilter(self, obj, event) -> bool:
        bar = self._tabs.tabBar()
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            close_index = -1
            # PyQt can occasionally wrap the same C++ close button as a plain
            # QToolButton on Windows.  The Qt object name and its position are
            # stable across wrappers; a Python isinstance/identity check is not.
            object_name = obj.objectName() if hasattr(obj, "objectName") else ""
            if object_name == "tabCloseButton":
                try:
                    point = obj.mapTo(bar, event.position().toPoint())
                    close_index = bar.tabAt(point)
                except (AttributeError, RuntimeError):
                    close_index = -1

                if close_index < 0:
                    for index in range(self._tabs.count()):
                        button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                        if button is not None and button == obj:
                            close_index = index
                            break
            elif obj is bar:
                point = event.position().toPoint()
                for index in range(self._tabs.count()):
                    button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                    if button is not None and button.geometry().contains(point):
                        close_index = index
                        break
            if close_index >= 0:
                session = self.session_at(close_index)
                if session is not None:
                    # Defer removal until Qt has returned from dispatching
                    # this event to either the button or movable tab bar.
                    QTimer.singleShot(
                        0, lambda session=session: self.tabCloseRequested.emit(session)
                    )
                event.accept()
                return True
        if obj is bar and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                index = bar.tabAt(event.position().toPoint())
                if index >= 0:
                    session = self.session_at(index)
                    if session is not None:
                        self.tabCloseRequested.emit(session)
                    return True
        return super().eventFilter(obj, event)

    def _on_current_changed(self, index: int) -> None:
        session = self.session_at(index)
        if session is not None:
            self.tabChanged.emit(session)

    def activate_next(self) -> None:
        count = self._tabs.count()
        if count > 1:
            self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % count)

    def activate_previous(self) -> None:
        count = self._tabs.count()
        if count > 1:
            self._tabs.setCurrentIndex((self._tabs.currentIndex() - 1) % count)

    # --- compatibility properties ---------------------------------------
    @property
    def canvas(self) -> PdfCanvas | None:
        session = self.current_session()
        return session.canvas if session else None

    @property
    def nav_panel(self):
        session = self.current_session()
        return session.nav_panel if session else None

    # --- behaviour preserved from the pre-tab API ------------------------
    def toggle_thumbnails(self) -> None:
        session = self.current_session()
        if not session:
            return
        if session.nav_panel.isVisible():
            session.nav_panel.hide()
        else:
            session.nav_panel.show_panel("thumbnails")

    def show_thumbnails(self, show: bool) -> None:
        session = self.current_session()
        if not session:
            return
        if show:
            session.nav_panel.show_panel(session.nav_panel.active_key())
        else:
            session.nav_panel.hide()

    def show_nav_tab(self, key: str) -> None:
        session = self.current_session()
        if session:
            session.nav_panel.show_panel(key)

    def show_document(self, show: bool) -> None:
        self._stack.setCurrentWidget(self._tabs if show else self._empty)
        self._empty.set_active(not show)

    def set_recent_files(self, paths: list[str]) -> None:
        self._empty.set_recent_files(paths)

    def refresh_icons(self) -> None:
        self._empty.refresh_icons()
        for session in set(self._sessions.values()):
            session.refresh_icons()
        for index in range(self._tabs.count()):
            button = self._tabs.tabBar().tabButton(
                index, QTabBar.ButtonPosition.RightSide
            )
            if button is not None and hasattr(button, "refresh_icon"):
                button.refresh_icon()
        self._refresh_tab_navigation_icons()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._empty.set_animations_enabled(enabled)
        for session in set(self._sessions.values()):
            session.set_animations_enabled(enabled)

    def set_drag_active(self, active: bool) -> None:
        self._empty.set_drag_active(active)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(
            url.toLocalFile().lower().endswith((".pdf", ".ps", ".eps"))
            for url in event.mimeData().urls()
        ):
            self._empty.set_drag_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._empty.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._empty.set_drag_active(False)
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith((".pdf", ".ps", ".eps"))
        ]
        if not paths:
            return
        self.fileDropped.emit(paths[0])
        if len(paths) > 1:
            self.extraFilesDropped.emit(paths[1:])
        event.acceptProposedAction()
