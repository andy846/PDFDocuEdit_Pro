"""Persistent workspace modes and lightweight transitions; no document processing."""
from __future__ import annotations

import sys
from enum import StrEnum

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
)

from styles.theme import get_colors


class WorkspaceMode(StrEnum):
    PDF = "pdf"
    DESIGNER = "designer"


class ModeSwitcher(QFrame):
    modeRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceModeSwitcher")
        self.mode = WorkspaceMode.PDF
        self.animations_enabled = True
        self.compact = False
        self.busy = {mode: False for mode in WorkspaceMode}
        self.indicator = QFrame(self)
        self.indicator.setObjectName("workspaceModeIndicator")
        self.animation = QPropertyAnimation(self.indicator, b"geometry", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for mode, label in ((WorkspaceMode.PDF, "PDF Workspace"), (WorkspaceMode.DESIGNER, "Document Designer")):
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setAccessibleName(label + " mode")
            button.setToolTip(label)
            button.setObjectName("workspaceModeButton")
            self.group.addButton(button)
            self.buttons[mode] = button
            button.clicked.connect(lambda checked=False, m=mode: self.modeRequested.emit(m.value))
            row.addWidget(button)
        self.buttons[self.mode].setChecked(True)
        self.refresh_style()

    def refresh_style(self):
        colors = get_colors()
        self.setStyleSheet(f"""
            QFrame#workspaceModeSwitcher {{ background: {colors['bg_surface']}; border: 1px solid {colors['border_strong']}; border-radius: 7px; }}
            QFrame#workspaceModeIndicator {{ background: {colors['primary']}; border: none; border-radius: 5px; }}
            QPushButton#workspaceModeButton {{ background: transparent; border: none; border-radius: 5px; padding: 0 9px; min-height: 28px; max-height: 28px; color: {colors['text_primary']}; }}
            QPushButton#workspaceModeButton:checked {{ color: {colors['on_primary']}; font-weight: 600; }}
            QPushButton#workspaceModeButton:focus {{ border: 1px solid {colors['primary_glow']}; }}
        """)
        self.indicator.lower()

    def set_mode(self, mode, *, animate=True):
        self.mode = WorkspaceMode(mode)
        self.buttons[self.mode].setChecked(True)
        self.animation.stop()
        target = self.buttons[self.mode].geometry()
        if animate and self.animations_enabled and self.isVisible() and self.indicator.geometry().isValid():
            self.animation.setStartValue(self.indicator.geometry())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self.indicator.setGeometry(target)

    def set_compact(self, compact):
        if self.compact != compact:
            self.compact = compact
            self._labels()
            self.set_mode(self.mode, animate=False)

    def set_busy(self, mode, busy):
        mode = WorkspaceMode(mode)
        if self.busy[mode] != bool(busy):
            self.busy[mode] = bool(busy)
            self._labels()

    def _labels(self):
        for mode, button in self.buttons.items():
            label = ("PDF" if self.compact else "PDF Workspace") if mode == WorkspaceMode.PDF else ("Designer" if self.compact else "Document Designer")
            button.setText(label + (" ●" if self.busy[mode] else ""))
            button.setToolTip(("PDF Workspace" if mode == WorkspaceMode.PDF else "Document Designer") + (" · Background work is running" if self.busy[mode] else ""))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_mode(self.mode, animate=False)

    def set_animations_enabled(self, enabled):
        self.animations_enabled = bool(enabled)
        if not enabled:
            self.set_mode(self.mode, animate=False)


class WorkspaceModes(QStackedWidget):
    modeChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = WorkspaceMode.PDF
        self.pages = {}
        self.focus = {}
        self.animations_enabled = True
        self.overlay = self.fade = None
        self.transition_timeout = QTimer(self) if sys.platform == "darwin" else None
        if self.transition_timeout:
            self.transition_timeout.setSingleShot(True)
            self.transition_timeout.timeout.connect(self._finish_transition)

    def add_mode(self, mode, widget):
        self.pages[WorkspaceMode(mode)] = widget
        self.addWidget(widget)

    def _finish_transition(self):
        if self.transition_timeout:
            self.transition_timeout.stop()
        if self.fade:
            self.fade.stop()
            self.fade.deleteLater()
            self.fade = None
        if self.overlay:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None

    def request_mode(self, mode):
        mode = WorkspaceMode(mode)
        if mode == self.mode:
            return
        if mode not in self.pages:
            raise ValueError("Workspace mode has not been initialized.")
        old = self.currentWidget()
        self.focus[self.mode] = old.focusWidget() if old else None
        self._finish_transition()
        snapshot = old.grab() if old and self.animations_enabled and self.isVisible() else None
        self.mode = mode
        self.setCurrentWidget(self.pages[mode])
        self.modeChanged.emit(mode.value)
        target = self.focus.get(mode)
        try:
            if target and target.isVisible() and target.isEnabled():
                target.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            self.focus.pop(mode, None)
        if snapshot and not snapshot.isNull():
            self.overlay = QLabel(self)
            self.overlay.setGeometry(self.rect())
            self.overlay.setPixmap(snapshot)
            self.overlay.setScaledContents(True)
            effect = QGraphicsOpacityEffect(self.overlay)
            self.overlay.setGraphicsEffect(effect)
            self.overlay.show()
            self.overlay.raise_()
            self.fade = QPropertyAnimation(effect, b"opacity", self)
            self.fade.setDuration(200)
            self.fade.setStartValue(1.0)
            self.fade.setEndValue(0.0)
            self.fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.fade.finished.connect(self._finish_transition)
            self.fade.start()
            if self.transition_timeout:
                # The offscreen Mac animation clock can start late. Ensure an
                # outgoing screenshot never blocks the newly selected mode.
                self.transition_timeout.start(200)

    def set_animations_enabled(self, enabled):
        self.animations_enabled = bool(enabled)
        if not enabled:
            self._finish_transition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.overlay:
            self.overlay.setGeometry(self.rect())
