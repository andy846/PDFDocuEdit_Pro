"""Small non-blocking application notification bar."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel

from styles.components import _rgba
from styles.theme import get_colors
from styles.tokens import D, S

from .motion import MotionIconButton


@dataclass
class _QueuedMessage:
    text: str
    kind: str
    timeout: int


class InfoBar(QFrame):
    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("infoBar")
        self._animations_enabled = True
        self._closing = False
        self.setVisible(False)
        self.setMaximumHeight(0)
        self._timer = QTimer(self)
        self._kind = "info"
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer_expired)
        self._queue: deque[_QueuedMessage] = deque(maxlen=10)
        self._pending_count = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(S.LG, S.XS, S.SM, S.XS)
        layout.setSpacing(S.SM)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message, 1)
        self._queue_badge = QLabel()
        self._queue_badge.setObjectName("infoBarBadge")
        self._queue_badge.hide()
        layout.addWidget(self._queue_badge)
        self._close = MotionIconButton("x", "Dismiss notification", D.ICON_SM)
        self._close.clicked.connect(self.hide_bar)
        layout.addWidget(self._close)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._motion = QParallelAnimationGroup(self)
        self._height_animation = QPropertyAnimation(self, b"maximumHeight", self)
        self._opacity_animation = QPropertyAnimation(self._opacity, b"opacity", self)
        for animation in (self._height_animation, self._opacity_animation):
            animation.setDuration(170)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._motion.addAnimation(animation)
        self._motion.finished.connect(self._motion_finished)

    def show_message(self, message: str, kind: str = "info", timeout: int = 4500) -> None:
        if self.isVisible() and not self._closing:
            self._queue.append(_QueuedMessage(message, kind, timeout))
            self._update_queue_badge()
            return
        self._show_now(message, kind, timeout)

    def _show_now(self, message: str, kind: str, timeout: int) -> None:
        self._kind = kind
        self._apply_style()
        self._message.setText(message)
        self._motion.stop()
        self._closing = False
        self.show()
        self.raise_()
        target = max(42, self.sizeHint().height())
        if self._animations_enabled:
            self.setMaximumHeight(0)
            self._opacity.setOpacity(0.0)
            self._height_animation.setStartValue(0)
            self._height_animation.setEndValue(target)
            self._opacity_animation.setStartValue(0.0)
            self._opacity_animation.setEndValue(1.0)
            self._motion.start()
        else:
            self.setMaximumHeight(target)
            self._opacity.setOpacity(1.0)
        self._timer.stop()
        if timeout > 0:
            self._timer.start(timeout)

    def _on_timer_expired(self) -> None:
        if self._queue:
            next_message = self._queue.popleft()
            self._update_queue_badge()
            self._motion.stop()
            self._show_now(next_message.text, next_message.kind, next_message.timeout)
        else:
            self.hide_bar()

    def _update_queue_badge(self) -> None:
        count = len(self._queue)
        if count > 0:
            self._queue_badge.setText(f"+{count}")
            self._queue_badge.show()
        else:
            self._queue_badge.hide()

    def _apply_style(self) -> None:
        c = get_colors()
        color = c.get(self._kind, c["primary"])
        self.setStyleSheet(
            f"QFrame#infoBar {{"
            f" background: {_rgba(c['bg_elevated'], 246)};"
            f" border: 1px solid {c['border_strong']};"
            f" border-left: 3px solid {color};"
            f" border-radius: 12px;"
            f" margin: {S.SM}px {S.SM}px 0 {S.SM}px;"
            f" }}"
        )

    def hide_bar(self) -> None:
        self._timer.stop()
        self._motion.stop()
        if self.isHidden():
            return
        self._closing = True
        self._queue.clear()
        self._update_queue_badge()
        if self._animations_enabled:
            self._height_animation.setStartValue(self.height())
            self._height_animation.setEndValue(0)
            self._opacity_animation.setStartValue(self._opacity.opacity())
            self._opacity_animation.setEndValue(0.0)
            self._motion.start()
        else:
            self._finish_hide()

    def _motion_finished(self) -> None:
        if self._closing:
            self._finish_hide()

    def _finish_hide(self) -> None:
        self.setMaximumHeight(0)
        self.hide()
        self._closing = False
        self.dismissed.emit()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        self._close.set_animations_enabled(enabled)

    def refresh_icons(self) -> None:
        self._close.refresh_icon()
        self._apply_style()
