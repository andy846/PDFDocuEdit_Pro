"""Compact document information and page navigation bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIntValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSlider,
    QToolButton,
    QWidget,
)

from styles.tokens import D, S

from .motion import MotionIconButton


class BottomBar(QWidget):
    prevClicked = pyqtSignal()
    nextClicked = pyqtSignal()
    gotoClicked = pyqtSignal(int)
    zoomInClicked = pyqtSignal()
    zoomOutClicked = pyqtSignal()
    fitWidthClicked = pyqtSignal()
    fitPageClicked = pyqtSignal()
    actualSizeClicked = pyqtSignal()
    layoutChanged = pyqtSignal(str)
    zoomSet = pyqtSignal(float)
    zoomSliderChanged = pyqtSignal(int)
    rotateCurrentRequested = pyqtSignal(int)
    rotatePagesRequested = pyqtSignal()
    rotateBoxRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBar")
        self.setFixedHeight(D.STATUSBAR_H)
        self._page_count = 0
        self._current_page = 0
        self._document_available = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.MD, 0, S.MD, 0)
        layout.setSpacing(S.XS)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        def separator() -> QFrame:
            line = QFrame()
            line.setObjectName("statusSeparator")
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFixedHeight(18)
            return line

        self._file = QLabel("No document")
        self._file.setObjectName("fileInfo")
        self._file.setMinimumWidth(60)
        self._file_full = "No document"
        layout.addWidget(self._file, 1)
        layout.addWidget(separator())
        layout.addSpacing(S.XS)

        # --- page navigation cluster ---
        self._prev = self._button("chevron-left", "Previous page", self.prevClicked)
        layout.addWidget(self._prev)
        self._page = QLineEdit("1")
        self._page.setObjectName("pageInput")
        self._page.setValidator(QIntValidator(1, 999999, self))
        self._page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page.setFixedWidth(56)
        self._page.setFixedHeight(28)
        self._page.returnPressed.connect(self._goto)
        layout.addWidget(self._page)
        self._total = QLabel("/ 0")
        self._total.setObjectName("pageInfo")
        self._total.setMinimumWidth(36)
        layout.addWidget(self._total)
        self._next = self._button("chevron-right", "Next page", self.nextClicked)
        layout.addWidget(self._next)
        layout.addWidget(separator())
        layout.addSpacing(S.XS)

        # --- zoom cluster ---
        self._zoom_out = self._button(
            "minus",
            "Zoom out (Ctrl+-)",
            self.zoomOutClicked,
            D.ICON_MD,
        )
        layout.addWidget(self._zoom_out)
        self._zoom = QLineEdit("100%")
        self._zoom.setObjectName("zoomInput")
        self._zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom.setFixedWidth(64)
        self._zoom.setFixedHeight(28)
        self._zoom.setValidator(QIntValidator(25, 400, self))
        self._zoom.setToolTip("Click to edit zoom level (25–400%)")
        self._zoom.editingFinished.connect(self._commit_zoom)
        layout.addWidget(self._zoom)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("zoomSlider")
        self._slider.setRange(25, 400)
        self._slider.setSingleStep(25)
        self._slider.setPageStep(100)
        self._slider.setValue(100)
        self._slider.setFixedWidth(110)
        self._slider.setToolTip("Zoom slider (25–400%)")
        self._slider.setAccessibleName("Zoom slider")
        self._slider.valueChanged.connect(self._slider_changed)
        layout.addWidget(self._slider)
        self._zoom_in = self._button(
            "plus",
            "Zoom in (Ctrl+=)",
            self.zoomInClicked,
            D.ICON_MD,
        )
        layout.addWidget(self._zoom_in)

        self._fit = QToolButton()
        self._fit.setObjectName("fitButton")
        self._fit.setText("Fit")
        self._fit.setToolTip("Fit page to the window")
        self._fit.setAccessibleName("Fit page")
        self._fit.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        fit_menu = QMenu(self._fit)
        fit_width = QAction("Fit Page Width (Ctrl+0)", self._fit)
        fit_width.triggered.connect(self.fitWidthClicked.emit)
        fit_page = QAction("Fit Whole Page (Ctrl+9)", self._fit)
        fit_page.triggered.connect(self.fitPageClicked.emit)
        actual = QAction("Actual Size (Ctrl+8)", self._fit)
        actual.triggered.connect(self.actualSizeClicked.emit)
        fit_menu.addAction(fit_width)
        fit_menu.addAction(fit_page)
        fit_menu.addAction(actual)
        self._fit.setMenu(fit_menu)
        layout.addWidget(self._fit)
        layout.addWidget(separator())
        layout.addSpacing(S.XS)

        # --- page tools cluster ---
        self._rotate = QToolButton()
        self._rotate.setObjectName("rotateButton")
        self._rotate.setText("Rotate")
        self._rotate.setToolTip("Rotate pages")
        self._rotate.setAccessibleName("Rotate pages")
        self._rotate.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        rotate_menu = QMenu(self._rotate)
        for label, angle in (
            ("Rotate Current Page 90° CW", 90),
            ("Rotate Current Page 180°", 180),
            ("Rotate Current Page 90° CCW", -90),
        ):
            action = QAction(label, self._rotate)
            action.triggered.connect(
                lambda _checked=False, value=angle: self.rotateCurrentRequested.emit(value)
            )
            rotate_menu.addAction(action)
        rotate_menu.addSeparator()
        rotate_all = QAction("Rotate Pages…", self._rotate)
        rotate_all.triggered.connect(self.rotatePagesRequested.emit)
        rotate_menu.addAction(rotate_all)
        box_menu = rotate_menu.addMenu("Rotate Page(s) from Page Box")
        for label, angle in (
            ("90° Clockwise", 90),
            ("180°", 180),
            ("90° Counter-Clockwise", -90),
        ):
            action = QAction(label, self._rotate)
            action.triggered.connect(
                lambda _checked=False, value=angle: self.rotateBoxRequested.emit(value)
            )
            box_menu.addAction(action)
        self._rotate.setMenu(rotate_menu)
        layout.addWidget(self._rotate)

        self._layout = QComboBox()
        self._layout.setObjectName("layoutSelector")
        self._layout.setAccessibleName("Page layout")
        self._layout.setToolTip("Page layout")
        self._layout.setMinimumContentsLength(12)
        self._layout.setMinimumWidth(112)
        self._layout.addItem("Single", "single")
        self._layout.addItem("Continuous", "continuous")
        self._layout.addItem("Facing", "facing")
        self._layout.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        self._layout.currentIndexChanged.connect(
            lambda: self.layoutChanged.emit(str(self._layout.currentData()))
        )
        layout.addWidget(self._layout)

        layout.addStretch(1)
        self._size = QLabel("")
        self._size.setObjectName("pageInfo")
        self._size.setMinimumWidth(112)
        layout.addWidget(self._size)
        layout.addWidget(separator())
        layout.addSpacing(S.XS)
        self._status = QLabel("Ready")
        self._status.setObjectName("pageInfo")
        self._status.setMinimumWidth(56)
        layout.addWidget(self._status)
        # Explicit per-item alignment avoids style-dependent vertical fill;
        # separators, 28 px fields and 32 px icon buttons share one centre.
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.widget() is not None:
                item.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.set_document_available(False)

    def _button(
        self,
        name: str,
        tooltip: str,
        signal,
        icon_size: int = D.ICON_SM,
    ) -> MotionIconButton:
        button = MotionIconButton(name, tooltip, icon_size)
        button.clicked.connect(signal.emit)
        return button

    def set_layout_mode(self, mode: str) -> None:
        index = self._layout.findData(mode)
        if index >= 0:
            self._layout.blockSignals(True)
            self._layout.setCurrentIndex(index)
            self._layout.blockSignals(False)

    def _goto(self) -> None:
        try:
            page = int(self._page.text())
        except ValueError:
            return
        if 1 <= page <= self._page_count:
            self.gotoClicked.emit(page - 1)
        else:
            self._page.setText(str(self._current_page + 1))

    def page_box_text(self) -> str:
        """The raw text in the page box, used by the rotate-from-page-box menu."""
        return self._page.text().strip()

    def set_document_available(self, available: bool) -> None:
        self._document_available = available
        self._page.setEnabled(available)
        self._zoom.setEnabled(available)
        for widget in (self._zoom_out, self._zoom_in, self._fit, self._layout, self._rotate, self._slider):
            widget.setEnabled(available)
        self._update_navigation()

    def set_document_info(self, name: str, page_count: int, path: str = "") -> None:
        self._file_full = name or "No document"
        if path:
            self._file.setToolTip(f"{path} | {page_count} page(s)")
        else:
            self._file.setToolTip(name or "No document")
        self._page_count = page_count
        self._total.setText(f"/ {page_count}")
        self._page.validator().setTop(max(1, page_count))
        self.set_document_available(page_count > 0)
        self._elide_file_info()

    def _elide_file_info(self) -> None:
        """Elide long filenames instead of clipping them at the label edge."""
        metrics = self._file.fontMetrics()
        width = max(40, self._file.width() - 8)
        self._file.setText(
            metrics.elidedText(
                self._file_full, Qt.TextElideMode.ElideMiddle, width
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_file_info()

    def set_current_page(self, page: int) -> None:
        self._current_page = max(0, page)
        self._page.setText(str(page + 1))
        self._update_navigation()

    def _update_navigation(self) -> None:
        self._prev.setEnabled(self._document_available and self._current_page > 0)
        self._next.setEnabled(
            self._document_available and self._current_page < self._page_count - 1
        )

    def set_zoom_percent(self, percent: int) -> None:
        if not self._zoom.hasFocus():
            self._zoom.setText(f"{percent}%")
        self._slider.blockSignals(True)
        self._slider.setValue(int(percent))
        self._slider.blockSignals(False)

    def _slider_changed(self, value: int) -> None:
        self._zoom.setText(f"{value}%")
        self.zoomSliderChanged.emit(int(value))

    def _commit_zoom(self) -> None:
        text = self._zoom.text().strip().rstrip("%")
        try:
            value = int(text)
        except ValueError:
            self._zoom.setText(self._zoom.text() if "%" in self._zoom.text() else f"{self._zoom.text()}%")
            return
        value = max(25, min(400, value))
        self._zoom.setText(f"{value}%")
        self._slider.blockSignals(True)
        self._slider.setValue(value)
        self._slider.blockSignals(False)
        self.zoomSet.emit(value / 100.0)

    def set_page_size(self, width: float, height: float) -> None:
        if width and height:
            width_mm = width * 25.4 / 72.0
            height_mm = height * 25.4 / 72.0
            self._size.setText(f"{width_mm:.1f} × {height_mm:.1f} mm")
        else:
            self._size.clear()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_animations_enabled(self, enabled: bool) -> None:
        for button in (self._prev, self._next, self._zoom_out, self._zoom_in):
            button.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        for button in (self._prev, self._next, self._zoom_out, self._zoom_in):
            button.refresh_icon()
