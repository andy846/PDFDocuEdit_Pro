"""Theme-aware Lucide-style SVG icons.

The paths follow Lucide's 24px outline conventions. Lucide is licensed under
the ISC License; see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from core.resources import resource_path
from styles.theme import get_color


def _screen_dpr() -> float:
    """Device pixel ratio of the primary screen (2.0 on Retina displays)."""
    app = QApplication.instance()
    if app is not None and app.primaryScreen() is not None:
        return max(1.0, app.primaryScreen().devicePixelRatio())
    return 1.0


_PATHS: dict[str, str] = {
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "folder-open": '<path d="M6 14 8 9h12l-2 9H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 2h6a2 2 0 0 1 2 2v2"/>',
    "save": '<path d="M15 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8z"/><path d="M17 22v-8H7v8M7 2v5h8"/>',
    "save-as": '<path d="M15 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h8"/><path d="M17 22v-8H7v8M7 2v5h8M16 19l2 2 4-4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "mouse-pointer": '<path d="m3 3 7.1 17 2.5-7.4L20 10Z"/>',
    "hand": '<path d="M18 11V6a2 2 0 0 0-4 0v4M14 10V4a2 2 0 0 0-4 0v6M10 10V6a2 2 0 0 0-4 0v8l-1.4-1.4a2 2 0 0 0-2.8 2.8l5.8 5.8A6 6 0 0 0 11.8 23H15a7 7 0 0 0 7-7v-5a2 2 0 0 0-4 0Z"/>',
    "text-cursor": '<path d="M5 4h4M7 4v16M5 20h4M15 4h4M17 4v16M15 20h4"/>',
    "font-inspect": '<circle cx="12" cy="11" r="7.5"/><path d="m17.5 16.5 4 4"/><path d="m8.5 14.5 3-7h1.5l3 7M9.5 12h5"/>',
    "printer": '<path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "panel-left": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
    "panel-right": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M15 3v18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8M8 9h2"/>',
    "files": '<path d="M16 22H6a2 2 0 0 1-2-2V6"/><rect x="8" y="2" width="12" height="16" rx="2"/>',
    "scissors": '<circle cx="6" cy="7" r="3"/><circle cx="6" cy="17" r="3"/><path d="m8.6 8.5 11.4 7M8.6 15.5 20 8"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 16H6L5 6M10 11v6M14 11v6"/>',
    "lock": '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7zM2 12l10 5 10-5M2 17l10 5 10-5"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5-5L12 3.6 8.4 7.2 6.1 4.9a4 4 0 0 0 5 5l-7.8 7.8a2.1 2.1 0 0 0 3 3l7.8-7.8a4 4 0 0 0 5-5L16.8 10l-3.6-3.6z"/>',
    "more": '<circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/>',
    "undo": '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6.7 3L3 13"/>',
    "redo": '<path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6.7 3L21 13"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "list-tree": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "bookmark": '<path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "bookmark-plus": '<path d="M19 21 12 16 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><path d="M12 7v6M9 10h6"/>',
    "history": '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M18 13h.01M8 13h8"/>',
    "command": '<path d="M9 6V5a4 4 0 1 0-4 4h14a4 4 0 1 0-4-4v14a4 4 0 1 0 4-4H5a4 4 0 1 0 4 4z"/>',
    "highlighter": '<path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
    "underline": '<path d="M6 4v6a6 6 0 0 0 12 0V4"/><path d="M4 20h16"/>',
    "strikethrough": '<path d="M16 4H9a3 3 0 0 0-2.8 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><path d="M4 12h16"/>',
    "message-square": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "pen-line": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "square": '<rect x="3" y="3" width="18" height="18" rx="2"/>',
    "restore": '<rect x="5" y="7" width="14" height="13" rx="1"/><path d="M8 7V4h11a1 1 0 0 1 1 1v11h-1"/>',
    "waves": '<path d="M2 12c2.2-4 4.2-4 6.4 0s4.2 4 6.4 0 4.2-4 7.2 0"/>',
    "line-tool": '<path d="M5 19 19 5"/><circle cx="5" cy="19" r="1.5"/><circle cx="19" cy="5" r="1.5"/>',
    "arrow-up-right": '<path d="M5 19 19 5M9 5h10v10"/>',
    "circle": '<circle cx="12" cy="12" r="9"/>',
    "pentagon": '<path d="m12 2 9 6.5L17.6 20H6.4L3 8.5Z"/>',
    "text-cursor-input": '<path d="M5 4h4M7 4v16M5 20h4"/><rect x="11" y="6" width="10" height="12" rx="2"/><path d="M14 10h4M16 10v4"/>',
    "square-type": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8h8M12 8v8M9 16h6"/>',
    "message-square-more": '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
    "watermark": '<path d="M4 6h16M6 10h12M8 14h8M10 18h4"/><path d="m3 3 18 18"/>',
    "scan-search": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="11" cy="11" r="4"/><path d="m14 14 3 3"/>',
    "eraser": '<path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"/><path d="M22 21H7"/><path d="m5 11 9 9"/>',
    "stamp": '<path d="M5 22h14"/><path d="M19.27 13.73A2.5 2.5 0 0 0 17.5 13h-11A2.5 2.5 0 0 0 4 15.5V17a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1.5c0-.66-.26-1.3-.73-1.77Z"/><path d="M14 13V8.5C14 7 15 7 15 5a3 3 0 0 0-6 0c0 2 1 2 1 3.5V13"/>',
    "signature": '<path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72Z"/><path d="m14 4 3 3"/><path d="M2 6h.01M5 22h12"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
}


def _svg(name: str, color: str) -> bytes:
    body = _PATHS.get(name, _PATHS["file-text"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode()


@lru_cache(maxsize=512)
def _pixmap(name: str, size: int, color: str) -> QPixmap:
    """Render a Lucide SVG at device-pixel-ratio resolution (crisp on Retina).

    The painter draws in device-independent pixels, so the devicePixelRatio
    must be applied only after painting — otherwise only a fraction of the
    icon ends up visible.
    """
    dpr = _screen_dpr()
    pixel_size = max(1, round(size * dpr))
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def icon(name: str, size: int = 20, color: str | None = None) -> QIcon:
    return QIcon(_pixmap(name, size, color or get_color("text_primary")))


@lru_cache(maxsize=256)
def app_pixmap(filename: str, size: int) -> QPixmap:
    """Load one of the original high-resolution feature icons at UI scale.

    In dark themes the bitmap is recolored to the text colour so pre-rendered
    raster icons keep contrast, matching the monochrome SVG icons.
    """
    source = QPixmap(str(resource_path("App_icon", filename)))
    if source.isNull():
        return _pixmap("file-text", size, get_color("text_primary"))
    dpr = _screen_dpr()
    pixel_size = max(1, round(size * dpr))
    scaled = source.scaled(
        pixel_size,
        pixel_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    foreground = QColor(get_color("text_primary"))
    if foreground.lightness() > 128:
        # Dark theme: tint the bitmap to the light text colour.
        tinted = QPixmap(scaled.size())
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, scaled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), foreground)
        painter.end()
        scaled = tinted
    scaled.setDevicePixelRatio(dpr)
    return scaled


@lru_cache(maxsize=32)
def brand_pixmap(size: int) -> QPixmap:
    """Load the full-colour application mark without theme tinting.

    ``app_pixmap`` intentionally recolours feature icons in dark themes, but
    the red PDF application mark is branding rather than a monochrome action
    icon. Tinting it turns the command-bar mark into a solid white document.
    """
    source = QPixmap(str(resource_path("icon.png")))
    if source.isNull():
        source = QPixmap(str(resource_path("icon.ico")))
    if source.isNull():
        return _pixmap("file-text", size, get_color("text_primary"))
    dpr = _screen_dpr()
    pixel_size = max(1, round(size * dpr))
    scaled = source.scaled(
        pixel_size,
        pixel_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled


def app_icon(filename: str, size: int = 24) -> QIcon:
    path = resource_path("App_icon", filename)
    return QIcon(str(path)) if path.exists() else QIcon(app_pixmap(filename, size))


def clear_icon_cache() -> None:
    _pixmap.cache_clear()
    app_pixmap.cache_clear()
    brand_pixmap.cache_clear()
