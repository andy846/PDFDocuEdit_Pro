"""Top command bar for common document actions."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMenuBar,
    QToolButton,
    QWidget,
)

from styles.tokens import D, S

from .icons import brand_pixmap
from .motion import MotionIconButton


class CommandBar(QWidget):
    panelToggled = pyqtSignal()
    openClicked = pyqtSignal()
    saveClicked = pyqtSignal()
    saveAsClicked = pyqtSignal()
    searchClicked = pyqtSignal()
    printClicked = pyqtSignal()
    undoClicked = pyqtSignal()
    redoClicked = pyqtSignal()
    diagnosticsClicked = pyqtSignal()
    preferencesClicked = pyqtSignal()
    aboutClicked = pyqtSignal()
    themeChanged = pyqtSignal(str)
    canvasToolChanged = pyqtSignal(str)
    commandRequested = pyqtSignal(str)
    minimizeRequested = pyqtSignal()
    maximizeRestoreRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, theme: str = "system", parent=None):
        super().__init__(parent)
        self.setObjectName("commandBar")
        self.setFixedHeight(D.COMMAND_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.MD, S.XS, S.MD, S.XS)
        layout.setSpacing(S.XS)

        self._app_icon = QLabel()
        self._app_icon.setObjectName("appIconBadge")
        self._app_icon.setPixmap(brand_pixmap(24))
        self._app_icon.setFixedSize(24, 24)
        self._app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._app_icon.setToolTip("PDFDocuEdit Pro")
        layout.addWidget(self._app_icon)
        self._title = QLabel("PDFDocuEdit Pro")
        self._title.setObjectName("appTitle")
        self._title.setMaximumWidth(220)
        layout.addWidget(self._title)
        self._main_menu_button = MotionIconButton(
            "menu", "Main menu (Alt+M)", D.ICON_MD
        )
        self._main_menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        layout.addWidget(self._main_menu_button)

        self._panel = self._button(
            "panel-left", "Toggle tools panel (Ctrl+\\)", self.panelToggled
        )
        layout.addWidget(self._panel)

        divider = QFrame()
        divider.setObjectName("commandDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(divider)
        layout.addSpacing(S.XS)

        self._open = self._button("folder-open", "Open PDF (Ctrl+O)", self.openClicked)
        self._save = self._button("save", "Save (Ctrl+S)", self.saveClicked)
        self._save_as = self._button("save-as", "Save As (Ctrl+Shift+S)", self.saveAsClicked)
        self._search = self._button("search", "Search document (Ctrl+F)", self.searchClicked)
        self._print = self._button("printer", "Print (Ctrl+P)", self.printClicked)
        for button in (self._open, self._save, self._save_as, self._search, self._print):
            layout.addWidget(button)

        layout.addSpacing(S.XS)
        self._undo = self._button("undo", "Undo (Ctrl+Z)", self.undoClicked)
        self._redo = self._button("redo", "Redo (Ctrl+Y)", self.redoClicked)
        self._undo.setEnabled(False)
        self._redo.setEnabled(False)
        layout.addWidget(self._undo)
        layout.addWidget(self._redo)

        canvas_divider = QFrame()
        canvas_divider.setObjectName("commandDivider")
        canvas_divider.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(canvas_divider)
        self._canvas_group = QButtonGroup(self)
        self._canvas_group.setExclusive(True)
        self._canvas_buttons: dict[str, MotionIconButton] = {}
        for mode, icon_name, tooltip in (
            ("browse", "mouse-pointer", "Browse canvas"),
            ("hand", "hand", "Hand tool — drag to pan"),
            ("select", "text-cursor", "Select text"),
            ("magnifier", "search", "Magnifier"),
        ):
            button = self._button(
                icon_name,
                tooltip,
                lambda _checked=False, value=mode: (
                    self.canvasToolChanged.emit(value)
                ),
            )
            button.setCheckable(True)
            button.setProperty("canvasTool", mode)
            self._canvas_group.addButton(button)
            self._canvas_buttons[mode] = button
            layout.addWidget(button)
        self._canvas_buttons["browse"].setChecked(True)

        layout.addStretch(1)
        self._work = QLabel("●  Ready")
        self._work.setObjectName("workStatus")
        self._work.setProperty("busy", False)
        layout.addWidget(self._work)
        layout.addSpacing(S.MD)

        self._diagnostics = self._button("wrench", "External tools and diagnostics", self.diagnosticsClicked)
        layout.addWidget(self._diagnostics)

        self._theme = QComboBox()
        self._theme.setObjectName("themeSelector")
        self._theme.setAccessibleName("Theme")
        self._theme.setToolTip("Application theme")
        self._theme.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self._theme.addItem("System", "system")
        self._theme.addItem("Light", "light")
        self._theme.addItem("Dark", "dark")
        index = self._theme.findData(theme)
        self._theme.setCurrentIndex(max(0, index))
        self._theme.currentIndexChanged.connect(
            lambda: self.themeChanged.emit(str(self._theme.currentData()))
        )
        layout.addWidget(self._theme)

        self._more = MotionIconButton("more", "More commands", D.ICON_MD)
        menu = QMenu(self._more)

        def add_action(target: QMenu, label: str, callback) -> QAction:
            action = QAction(label, self)
            action.triggered.connect(callback)
            target.addAction(action)
            return action

        file_menu = menu.addMenu("File")
        add_action(file_menu, "Open…", self.openClicked.emit)
        add_action(file_menu, "Save", self.saveClicked.emit)
        add_action(file_menu, "Save As…", self.saveAsClicked.emit)
        add_action(file_menu, "Print…", self.printClicked.emit)

        view_menu = menu.addMenu("View")
        add_action(
            view_menu,
            "Page Thumbnails",
            lambda _checked=False: self.commandRequested.emit("toggle_thumbnails"),
        )
        add_action(
            view_menu,
            "Split View",
            lambda _checked=False: self.commandRequested.emit("view_split"),
        )
        add_action(view_menu, "Search Document", self.searchClicked.emit)
        canvas_menu = view_menu.addMenu("Canvas Tool")
        for mode, label in (
            ("browse", "Browse"),
            ("hand", "Hand"),
            ("select", "Select Text"),
            ("magnifier", "Magnifier"),
        ):
            add_action(
                canvas_menu,
                label,
                lambda _checked=False, value=mode: (
                    self.canvasToolChanged.emit(value)
                ),
            )

        page_menu = menu.addMenu("Page")
        for label, key in (
            ("Insert Pages…", "insert"),
            ("Delete Pages…", "delete"),
            ("Extract Pages…", "extract"),
            ("Reorder Pages…", "order"),
            ("Split PDF…", "split"),
            ("Rotate Pages…", "rotate"),
        ):
            add_action(
                page_menu,
                label,
                lambda _checked=False, value=key: (
                    self.commandRequested.emit(value)
                ),
            )

        tools_menu = menu.addMenu("Tools")
        for label, key in (
            ("Merge PDFs…", "merge"),
            ("Merge CSV / Excel…", "merge_sheet"),
            ("Batch Print…", "batch_print"),
            ("Find and Open PDF…", "find_file"),
            ("Diagnostics…", "diagnostics"),
        ):
            add_action(
                tools_menu,
                label,
                lambda _checked=False, value=key: (
                    self.commandRequested.emit(value)
                ),
            )
        menu.addSeparator()
        preferences = QAction("Preferences…", self)
        preferences.triggered.connect(self.preferencesClicked.emit)
        about = QAction("About PDFDocuEdit Pro", self)
        about.triggered.connect(self.aboutClicked.emit)
        menu.addAction(preferences)
        menu.addSeparator()
        menu.addAction(about)
        self._more.setMenu(menu)
        self._more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self._more)

        self._window_divider = QFrame()
        self._window_divider.setObjectName("commandDivider")
        self._window_divider.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(self._window_divider)
        self._window_divider.hide()

        self._window_controls = QWidget()
        self._window_controls.setObjectName("windowControls")
        controls = QHBoxLayout(self._window_controls)
        controls.setContentsMargins(S.XS, 0, 0, 0)
        controls.setSpacing(0)
        self._window_minimize = MotionIconButton(
            "minus", "Minimize", D.ICON_SM
        )
        self._window_maximize = MotionIconButton(
            "square", "Maximize", D.ICON_SM
        )
        self._window_close = MotionIconButton("x", "Close", D.ICON_SM)
        for button in (
            self._window_minimize,
            self._window_maximize,
            self._window_close,
        ):
            button.setObjectName("windowControlButton")
            button.setFixedSize(46, D.COMMAND_H - 2 * S.XS)
            controls.addWidget(button)
        self._window_close.setProperty("closeButton", True)
        self._window_minimize.clicked.connect(self.minimizeRequested.emit)
        self._window_maximize.clicked.connect(self.maximizeRestoreRequested.emit)
        self._window_close.clicked.connect(self.closeRequested.emit)
        layout.addWidget(self._window_controls)
        self._window_controls.hide()

        self._drag_targets = {self, self._title, self._app_icon, self._work}
        for target in self._drag_targets:
            target.installEventFilter(self)

        self.set_document_available(False)

    def set_application_menu(self, menu_bar: QMenuBar) -> None:
        """Expose the complete QMainWindow menu through a compact title button."""

        menu = QMenu(self._main_menu_button)
        for action in menu_bar.actions():
            source_menu = action.menu()
            if source_menu is not None:
                menu.addMenu(source_menu)
            elif not action.isSeparator():
                menu.addAction(action)
        self._main_menu_button.setMenu(menu)
        self._main_menu_button.setEnabled(bool(menu.actions()))

    def open_application_menu(self) -> None:
        if self._main_menu_button.menu() is not None:
            self._main_menu_button.showMenu()

    def set_integrated_chrome(self, enabled: bool) -> None:
        self.setProperty("integratedTitleBar", bool(enabled))
        self._main_menu_button.setVisible(bool(enabled))
        self._window_divider.setVisible(bool(enabled))
        self._window_controls.setVisible(bool(enabled))
        self.style().unpolish(self)
        self.style().polish(self)
        self._update_compact_state()

    def set_maximized(self, maximized: bool) -> None:
        self._window_maximize.set_icon_name("restore" if maximized else "square")
        self._window_maximize.setToolTip("Restore" if maximized else "Maximize")
        self._window_maximize.setAccessibleName(
            "Restore" if maximized else "Maximize"
        )

    def set_window_title(self, title: str, modified: bool = False) -> None:
        # The command bar label is the permanent product identity. Document
        # names belong in the native window title, document tabs and status
        # bar; replacing the brand here makes the upper-left area unstable.
        self._title.setText("PDFDocuEdit Pro")
        detail = str(title)
        if modified:
            detail = f"{detail} — Unsaved changes"
        self._title.setToolTip(detail)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drag_targets:
            if (
                event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.maximizeRestoreRequested.emit()
                event.accept()
                return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                window = self.window()
                handle = window.windowHandle() if window is not None else None
                if handle is not None and handle.startSystemMove():
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_compact_state()

    def _update_compact_state(self) -> None:
        width = self.width()
        for button in self._canvas_buttons.values():
            button.setVisible(width >= 900)
        self._title.setVisible(width >= 1080)
        self._save_as.setVisible(width >= 1020)
        self._print.setVisible(width >= 1100)
        self._work.setVisible(width >= 1250)
        self._diagnostics.setVisible(width >= 1180)
        self._theme.setVisible(width >= 1160)

    def _button(self, icon_name: str, tooltip: str, signal) -> MotionIconButton:
        button = MotionIconButton(icon_name, tooltip, D.ICON_MD)
        button.clicked.connect(
            signal.emit if hasattr(signal, "emit") else signal
        )
        return button

    def set_document_available(self, available: bool) -> None:
        for button in (self._save, self._save_as, self._search, self._print):
            button.setEnabled(available)
        for button in self._canvas_buttons.values():
            button.setEnabled(available)

    def set_canvas_tool(self, mode: str) -> None:
        self._canvas_group.setExclusive(False)
        for key, button in self._canvas_buttons.items():
            button.setChecked(key == mode)
        self._canvas_group.setExclusive(True)

    def set_undo_redo_enabled(self, can_undo: bool, can_redo: bool) -> None:
        self._undo.setEnabled(can_undo)
        self._redo.setEnabled(can_redo)

    def set_work_status(self, text: str) -> None:
        ready = text.strip().casefold() == "ready"
        self._work.setText(f"{'●' if ready else '◌'}  {text}")
        self._work.setProperty("busy", not ready)
        self._work.style().unpolish(self._work)
        self._work.style().polish(self._work)

    def set_animations_enabled(self, enabled: bool) -> None:
        for button in (
            self._panel,
            self._open,
            self._save,
            self._save_as,
            self._search,
            self._print,
            self._undo,
            self._redo,
            *self._canvas_buttons.values(),
            self._diagnostics,
            self._more,
            self._main_menu_button,
            self._window_minimize,
            self._window_maximize,
            self._window_close,
        ):
            button.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        for button in (
            self._panel,
            self._open,
            self._save,
            self._save_as,
            self._search,
            self._print,
            self._undo,
            self._redo,
            *self._canvas_buttons.values(),
            self._diagnostics,
            self._more,
            self._main_menu_button,
            self._window_minimize,
            self._window_maximize,
            self._window_close,
        ):
            button.refresh_icon()
        self._app_icon.setPixmap(brand_pixmap(24))
