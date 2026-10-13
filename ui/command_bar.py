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
from .workspace_modes import ModeSwitcher, WorkspaceMode


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
    modeRequested = pyqtSignal(str)

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

        self._designer_action: QAction | None = None
        self._mode = WorkspaceMode.PDF
        self.mode_switcher = ModeSwitcher(self)
        self._designer = self.mode_switcher.buttons[WorkspaceMode.DESIGNER]
        self.mode_switcher.modeRequested.connect(self._request_mode)
        self._designer.hide()
        self.mode_switcher.hide()
        layout.addWidget(self.mode_switcher)

        divider = QFrame()
        divider.setObjectName("commandDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        self._document_divider = divider
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
        self._canvas_divider = canvas_divider
        layout.addWidget(canvas_divider)
        self._canvas_group = QButtonGroup(self)
        self._canvas_group.setExclusive(True)
        self._canvas_buttons: dict[str, MotionIconButton] = {}
        for mode, icon_name, tooltip in (
            ("browse", "mouse-pointer", "Browse canvas"),
            ("hand", "hand", "Hand tool — drag to pan"),
            ("select", "text-cursor", "Select text"),
            ("magnifier", "search", "Magnifier"),
            ("measure", "line-tool", "Measure PDF paper distance (mm/cm): drag or click two points; Shift aligns, Alt disables snapping. Drag from rulers for guides; click the ruler corner for settings."),
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
        self._document_menu_actions: list[QAction] = []

        def add_action(target: QMenu, label: str, callback, *, needs_document: bool = False) -> QAction:
            action = QAction(label, self)
            action.triggered.connect(callback)
            target.addAction(action)
            if needs_document:
                self._document_menu_actions.append(action)
            return action

        file_menu = menu.addMenu("File")
        add_action(file_menu, "Open…", self.openClicked.emit)
        add_action(file_menu, "Save", self.saveClicked.emit, needs_document=True)
        add_action(file_menu, "Save As…", self.saveAsClicked.emit, needs_document=True)
        add_action(file_menu, "Print…", self.printClicked.emit, needs_document=True)

        view_menu = menu.addMenu("View")
        add_action(
            view_menu,
            "Page Thumbnails",
            lambda _checked=False: self.commandRequested.emit("toggle_thumbnails"),
            needs_document=True,
        )
        add_action(
            view_menu,
            "Split View",
            lambda _checked=False: self.commandRequested.emit("view_split"),
            needs_document=True,
        )
        add_action(view_menu, "Search Document", self.searchClicked.emit, needs_document=True)
        canvas_menu = view_menu.addMenu("Canvas Tool")
        for mode, label in (
            ("browse", "Browse"),
            ("hand", "Hand"),
            ("select", "Select Text"),
            ("magnifier", "Magnifier"),
            ("measure", "Measure Distance"),
        ):
            add_action(
                canvas_menu,
                label,
                lambda _checked=False, value=mode: (
                    self.canvasToolChanged.emit(value)
                ),
                needs_document=True,
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
                needs_document=True,
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
        self._preferences_action = preferences
        self._settings_menu: QMenu | None = None
        about = QAction("About PDFDocuEdit Pro", self)
        about.triggered.connect(self.aboutClicked.emit)
        menu.addAction(preferences)
        menu.addSeparator()
        menu.addAction(about)
        self._pdf_more_menu = menu
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

    def set_designer_action(self, action: QAction) -> None:
        """Expose the feature-gated editor action without coupling this bar to Composition."""
        self._designer_action = action
        self._designer.setEnabled(action.isEnabled())
        action.changed.connect(lambda: self._designer.setEnabled(action.isEnabled()))
        self._designer.show()
        self.mode_switcher.show()
        self._update_compact_state()

    def set_application_menu(self, menu_bar: QMenuBar) -> None:
        """Expose the complete QMainWindow menu through a compact title button."""

        menu = self._main_menu_button.menu() or QMenu(self._main_menu_button)
        menu.clear()
        for action in menu_bar.actions():
            source_menu = action.menu()
            if source_menu is not None:
                menu.addMenu(source_menu)
            elif not action.isSeparator():
                menu.addAction(action)
        if self._settings_menu is not None:
            menu.addSeparator()
            menu.addMenu(self._settings_menu)
        self._main_menu_button.setMenu(menu)
        self._main_menu_button.setEnabled(bool(menu.actions()))
        self._more.setMenu(menu if self._mode == WorkspaceMode.DESIGNER else self._pdf_more_menu)

    def add_settings_action(self, action: QAction) -> None:
        """Keep optional application actions beside settings across mode changes."""
        if action not in self._pdf_more_menu.actions():
            self._pdf_more_menu.insertAction(self._preferences_action, action)
        if self._settings_menu is None:
            self._settings_menu = QMenu("Settings", self)
            self._settings_menu.addAction(self._preferences_action)
            menu = self._main_menu_button.menu()
            if menu is not None:
                menu.addSeparator()
                menu.addMenu(self._settings_menu)
        if action not in self._settings_menu.actions():
            self._settings_menu.insertAction(self._preferences_action, action)

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

    def _request_mode(self, mode):
        if mode == WorkspaceMode.DESIGNER and self._designer_action is not None:
            self._designer_action.trigger()
        else:
            self.modeRequested.emit(mode)

    def set_mode(self, mode):
        self._mode = WorkspaceMode(mode)
        self._update_compact_state()
        self.mode_switcher.set_mode(mode)

    def _update_compact_state(self) -> None:
        width = self.width()
        pdf = self._mode == WorkspaceMode.PDF
        if self._designer_action is not None:
            self.mode_switcher.set_compact(width < 900)
            width -= self.mode_switcher.sizeHint().width() + S.XS
        for button in (self._panel, self._open, self._save, self._undo):
            button.setVisible(pdf and width >= 420)
        self._search.setVisible(pdf and width >= 650)
        self._redo.setVisible(pdf and width >= 700)
        self._document_divider.setVisible(pdf and width >= 420)
        self._canvas_divider.setVisible(pdf and width >= 900)
        for button in self._canvas_buttons.values():
            button.setVisible(pdf and width >= 900)
        self._title.setVisible(width >= 1080)
        self._save_as.setVisible(pdf and width >= 1020)
        self._print.setVisible(pdf and width >= 1100)
        self._work.setVisible(pdf and width >= 1250)
        self._diagnostics.setVisible(pdf and width >= 1180)
        self._theme.setVisible(width >= 1160)

    def _button(self, icon_name: str, tooltip: str, signal) -> MotionIconButton:
        button = MotionIconButton(icon_name, tooltip, D.ICON_MD)
        button.clicked.connect(
            signal.emit if hasattr(signal, "emit") else signal
        )
        return button

    def set_document_available(self, available: bool) -> None:
        for action in self._document_menu_actions:
            action.setEnabled(available)
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

    def set_shortcut_hints(self, commands) -> None:
        from core.commands import command_shortcuts
        buttons = {"open": self._open, "save": self._save, "save_as": self._save_as,
                   "search": self._search, "print": self._print, "undo": self._undo,
                   "redo": self._redo, "main_menu": self._main_menu_button, "toggle_tools": self._panel}
        for command in commands:
            if command.id in buttons:
                sequences = " / ".join(command_shortcuts(command))
                label = command.label.replace("&", "")
                buttons[command.id].setToolTip(f"{label} ({sequences})" if sequences else label)

    def set_work_status(self, text: str) -> None:
        ready = text.strip().casefold() == "ready"
        self._work.setText(f"{'●' if ready else '◌'}  {text}")
        self._work.setProperty("busy", not ready)
        self._work.style().unpolish(self._work)
        self._work.style().polish(self._work)

    def set_animations_enabled(self, enabled: bool) -> None:
        self.mode_switcher.set_animations_enabled(enabled)
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
        self.mode_switcher.refresh_style()
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
