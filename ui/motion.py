"""Small motion primitives shared by the main application chrome."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize
from PyQt6.QtWidgets import QPushButton, QToolButton

from styles.theme import get_color

from .icons import icon


def _refresh_style(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class MotionIconButton(QToolButton):
    """Theme-aware toolbar button with a restrained hover/press response."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        icon_size: int = 20,
        parent=None,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._base_size = icon_size
        self._hovered = False
        self._animations_enabled = True
        self._animation = QPropertyAnimation(self, b"iconSize", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setObjectName("commandButton")
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.refresh_icon()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.refresh_icon()

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        if not enabled:
            self._animation.stop()
            self.setIconSize(QSize(self._base_size, self._base_size))

    def refresh_icon(self) -> None:
        color = get_color("primary") if self._hovered and self.isEnabled() else None
        self.setIcon(icon(self._icon_name, self._base_size + 4, color))

    def _animate(self, target: int, duration: int = 145) -> None:
        self._animation.stop()
        if not self._animations_enabled:
            self.setIconSize(QSize(self._base_size, self._base_size))
            return
        self._animation.setDuration(duration)
        self._animation.setStartValue(self.iconSize())
        self._animation.setEndValue(QSize(target, target))
        self._animation.start()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.setProperty("hovered", True)
        self.refresh_icon()
        _refresh_style(self)
        self._animate(self._base_size + 4)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.setProperty("hovered", False)
        self.refresh_icon()
        _refresh_style(self)
        self._animate(self._base_size)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._animate(max(12, self._base_size - 2), 90)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate(self._base_size + 4 if self._hovered else self._base_size, 150)


class MotionNavButton(QPushButton):
    """Sidebar item with hover lift and a click pulse, including bitmap icons."""

    def __init__(self, text: str, icon_size: int = 24, parent=None):
        super().__init__(text, parent)
        self._base_size = icon_size
        self._hovered = False
        self._animations_enabled = True
        self._animation = QPropertyAnimation(self, b"iconSize", self)
        self._animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self.setIconSize(QSize(icon_size, icon_size))

    def set_animations_enabled(self, enabled: bool) -> None:
        self._animations_enabled = enabled
        if not enabled:
            self._animation.stop()
            self.setIconSize(QSize(self._base_size, self._base_size))

    def _animate(self, target: int, duration: int = 160) -> None:
        self._animation.stop()
        if not self._animations_enabled:
            self.setIconSize(QSize(self._base_size, self._base_size))
            return
        self._animation.setDuration(duration)
        self._animation.setStartValue(self.iconSize())
        self._animation.setEndValue(QSize(target, target))
        self._animation.start()

    def animate_click(self) -> None:
        if not self._animations_enabled:
            return
        self._animation.stop()
        self._animation.setDuration(190)
        self._animation.setStartValue(self.iconSize())
        self._animation.setKeyValueAt(0.45, QSize(self._base_size + 7, self._base_size + 7))
        target = self._base_size + 4 if self._hovered else self._base_size
        self._animation.setEndValue(QSize(target, target))
        self._animation.start()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.setProperty("hovered", True)
        _refresh_style(self)
        self._animate(self._base_size + 4)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.setProperty("hovered", False)
        _refresh_style(self)
        self._animate(self._base_size)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._animate(max(16, self._base_size - 2), 80)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate(self._base_size + 4 if self._hovered else self._base_size, 145)
