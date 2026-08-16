"""Top command bar for common document actions."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

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

    def __init__(self, theme: str = "system", parent=None):
        super().__init__(parent)
        self.setObjectName("commandBar")
        self.setFixedHeight(D.COMMAND_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.MD, S.XS, S.MD, S.XS)
        layout.setSpacing(S.XS)

        self._panel = self._button("panel-left", "Toggle tools panel (Ctrl+\\)", self.panelToggled)
        layout.addWidget(self._panel)
        self._title = QLabel("PDFDocuEdit Pro")
        self._title.setObjectName("appTitle")
        layout.addWidget(self._title)
        self._app_icon = QLabel()
        self._app_icon.setObjectName("appIconBadge")
        self._app_icon.setPixmap(brand_pixmap(24))
        self._app_icon.setFixedSize(24, 24)
        self._app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._app_icon.setToolTip("PDFDocuEdit Pro")
        layout.addWidget(self._app_icon)
        layout.addSpacing(S.LG)

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

        self.set_document_available(False)

    def _button(self, icon_name: str, tooltip: str, signal) -> MotionIconButton:
        button = MotionIconButton(icon_name, tooltip, D.ICON_MD)
        button.clicked.connect(signal.emit)
        return button

    def set_document_available(self, available: bool) -> None:
        for button in (self._save, self._save_as, self._search, self._print):
            button.setEnabled(available)

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
            self._diagnostics,
            self._more,
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
            self._diagnostics,
            self._more,
        ):
            button.refresh_icon()
        self._app_icon.setPixmap(brand_pixmap(24))
