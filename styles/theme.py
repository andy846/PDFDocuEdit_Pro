"""System-aware light and dark palette support for PyQt6."""

from __future__ import annotations

from enum import StrEnum

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPalette, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QMenu,
    QProxyStyle,
    QStyle,
    QStyleFactory,
)


class ThemeMode(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


_current_theme = ThemeMode.SYSTEM
_effective_dark = False
_system_palette: QPalette | None = None
_effective_colors: dict[str, str] | None = None


class _RoundMenuStyle(QProxyStyle):
    """Makes popup menus and combo dropdowns translucent so the stylesheet's
    rounded corners are real, not square-patched.

    Only widget attributes are touched inside polish(): mutating window flags
    while Qt re-polishes the widget tree is unsafe.
    """

    def polish(self, widget):
        result = super().polish(widget)
        if isinstance(widget, QMenu):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        elif (
            isinstance(widget, QFrame)
            and isinstance(widget.parent(), QComboBox)
            and widget.findChild(QAbstractItemView) is not None
        ):
            # QComboBox private popup container: let the item view's rounded
            # background show through instead of a square frame.
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        return result

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        """Draw visible +/- glyphs for all integer and decimal spin boxes."""
        if element in {
            QStyle.PrimitiveElement.PE_IndicatorSpinUp,
            QStyle.PrimitiveElement.PE_IndicatorSpinDown,
        }:
            enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
            group = (
                QPalette.ColorGroup.Active
                if enabled
                else QPalette.ColorGroup.Disabled
            )
            color = option.palette.color(group, QPalette.ColorRole.ButtonText)
            painter.save()
            pen = QPen(color)
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            center = option.rect.center()
            radius = max(3.0, min(option.rect.width(), option.rect.height()) * 0.28)
            painter.drawLine(
                QPointF(center.x() - radius, center.y()),
                QPointF(center.x() + radius, center.y()),
            )
            if element == QStyle.PrimitiveElement.PE_IndicatorSpinUp:
                painter.drawLine(
                    QPointF(center.x(), center.y() - radius),
                    QPointF(center.x(), center.y() + radius),
                )
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


# Owned platform style used as the proxy base: the style QApplication currently
# uses gets deleted on setStyle(), which would leave a dangling base pointer.
_platform_style = None
_round_style = None


def _install_round_menu_style(app: QApplication) -> None:
    global _platform_style, _round_style
    try:
        already = isinstance(app.style(), _RoundMenuStyle)
    except RuntimeError:
        already = False
    if already:
        return
    if _round_style is not None:
        try:
            # QApplication owns the style; if a previous QApplication instance
            # was destroyed, Qt deleted the C++ object behind our reference.
            app.setStyle(_round_style)
            return
        except RuntimeError:
            _round_style = None
            _platform_style = None
    keys = QStyleFactory.keys()
    _platform_style = QStyleFactory.create(keys[0] if keys else "Fusion")
    _round_style = _RoundMenuStyle(_platform_style)
    app.setStyle(_round_style)


LIGHT = {
    "bg_base": "#f5f5f7",
    "bg_surface": "#ffffff",
    "bg_sidebar": "#f8f8fa",
    "bg_elevated": "#ffffff",
    "bg_hover": "#e9e9ed",
    "bg_active": "#dedee4",
    "text_primary": "#1d1d1f",
    "text_secondary": "#68686d",
    "text_disabled": "#98989e",
    "border": "#d8d8dc",
    "border_strong": "#c5c5ca",
    "primary": "#0a64d8",
    "primary_hover": "#0759c4",
    "primary_pressed": "#054ba6",
    "primary_soft": "#e4efff",
    "primary_glow": "#a9ccff",
    "on_primary": "#ffffff",
    "success": "#18864b",
    "success_soft": "#e3f5ea",
    "warning": "#a66100",
    "warning_soft": "#fff0d8",
    "error": "#c93434",
    "error_soft": "#ffe6e6",
    "accent_cyan": "#007f9f",
    "accent_cyan_soft": "#ddf5fa",
    "accent_violet": "#7057d9",
    "accent_violet_soft": "#eee9ff",
    "accent_coral": "#cc4652",
    "accent_coral_soft": "#ffe7ea",
    "legacy_green": "#02F78E",
    "legacy_green_text": "#0b8a45",
    "legacy_green_soft": "rgba(2, 247, 142, 0.18)",
    "canvas": "#ececef",
    "page": "#ffffff",
}

DARK = {
    "bg_base": "#1c1c1e",
    "bg_surface": "#252527",
    "bg_sidebar": "#222224",
    "bg_elevated": "#303033",
    "bg_hover": "#353538",
    "bg_active": "#414145",
    "text_primary": "#f2f2f4",
    "text_secondary": "#aaaab0",
    "text_disabled": "#707077",
    "border": "#3d3d41",
    "border_strong": "#515157",
    "primary": "#5a9cf5",
    "primary_hover": "#70aaf7",
    "primary_pressed": "#4389e6",
    "primary_soft": "#263f60",
    "primary_glow": "#426b9f",
    "on_primary": "#0d1b2c",
    "success": "#52b77b",
    "success_soft": "#203d2c",
    "warning": "#e0a34a",
    "warning_soft": "#49371f",
    "error": "#f06b6b",
    "error_soft": "#4a282c",
    "accent_cyan": "#56d3ed",
    "accent_cyan_soft": "#193a43",
    "accent_violet": "#b39cff",
    "accent_violet_soft": "#37304e",
    "accent_coral": "#ff7f8a",
    "accent_coral_soft": "#4b2930",
    "legacy_green": "#02F78E",
    "legacy_green_text": "#02F78E",
    "legacy_green_soft": "rgba(2, 247, 142, 0.16)",
    "canvas": "#161618",
    "page": "#ffffff",
}


def _system_is_dark(app: QApplication) -> bool:
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:
        pass
    color = app.palette().color(QPalette.ColorRole.Window)
    return color.lightness() < 128


def get_theme() -> ThemeMode:
    return _current_theme


def set_theme(theme: ThemeMode | str) -> ThemeMode:
    global _current_theme
    try:
        _current_theme = ThemeMode(theme)
    except ValueError:
        _current_theme = ThemeMode.SYSTEM
    return _current_theme


def get_colors() -> dict[str, str]:
    return _effective_colors or (DARK if _effective_dark else LIGHT)


def get_color(name: str) -> str:
    return get_colors().get(name, "#000000")


def is_dark() -> bool:
    return _effective_dark


def toggle_theme() -> ThemeMode:
    target = ThemeMode.LIGHT if _effective_dark else ThemeMode.DARK
    set_theme(target)
    return target


def apply_theme(app: QApplication, theme: ThemeMode | str | None = None) -> ThemeMode:
    global _effective_colors, _effective_dark, _system_palette
    _install_round_menu_style(app)
    previous_theme = _current_theme
    if _system_palette is None:
        _system_palette = QPalette(app.palette())
    if theme is not None:
        set_theme(theme)

    _effective_dark = (
        _system_is_dark(app) if _current_theme == ThemeMode.SYSTEM else _current_theme == ThemeMode.DARK
    )
    if _current_theme == ThemeMode.SYSTEM:
        if previous_theme != ThemeMode.SYSTEM:
            app.setPalette(app.style().standardPalette())
        _system_palette = QPalette(app.palette())

    colors = dict(DARK if _effective_dark else LIGHT)
    native = _system_palette.color(QPalette.ColorRole.Highlight) if _system_palette else QColor()
    if native.isValid() and native.alpha() > 0:
        colors["primary"] = native.name()
        colors["primary_hover"] = (
            native.lighter(112).name() if _effective_dark else native.darker(108).name()
        )
        colors["primary_pressed"] = (
            native.darker(112).name() if _effective_dark else native.darker(120).name()
        )
        colors["on_primary"] = "#111111" if native.lightness() > 155 else "#ffffff"
        red, green, blue, _alpha = native.getRgb()
        colors["primary_soft"] = f"rgba({red}, {green}, {blue}, {46 if _effective_dark else 28})"
        colors["primary_glow"] = f"rgba({red}, {green}, {blue}, {105 if _effective_dark else 78})"
    colors["info"] = colors["primary"]

    if _current_theme != ThemeMode.SYSTEM:
        c = colors
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c["bg_base"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text_primary"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(c["bg_surface"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["bg_sidebar"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(c["text_primary"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(c["bg_surface"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text_primary"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c["primary"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["on_primary"]))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["text_disabled"]))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["text_disabled"]))
        app.setPalette(palette)
    _effective_colors = colors
    return _current_theme
