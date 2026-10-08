"""Splash artwork with a version label drawn from application metadata."""

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen

from core.resources import APP_NAME


def splash_pixmap(
    source: QPixmap, version: str, *, max_width: int = 520, dpr: float = 1.0
) -> QPixmap:
    """Compose in logical coordinates, preserving artwork alpha and aspect ratio."""
    fallback = source.isNull()
    if fallback:
        pixmap = QPixmap(round(520 * dpr), round(292 * dpr))
        pixmap.fill(QColor("#1c1c1e"))
    else:
        pixmap = source.copy()
        limit = max(1, round(max_width * dpr))
        if pixmap.width() > limit:
            pixmap = pixmap.scaledToWidth(limit, Qt.TransformationMode.SmoothTransformation)
    pixmap.setDevicePixelRatio(dpr)
    width, height = pixmap.width() / dpr, pixmap.height() / dpr
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(QColor("#ffffff"))
    if fallback:
        font = QFont(QApplication.font().family())
        font.setPixelSize(24)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, width, height * 0.60), Qt.AlignmentFlag.AlignCenter, APP_NAME)
    # Match the former baked-in label below the title; keep long prerelease
    # versions in this area rather than clipping into neighbouring artwork.
    rect = QRectF(width * 0.36, height * 0.60, width * 0.37, height * 0.075)
    label = f"Version {version}"
    font = QFont("Segoe UI")
    size = max(10, round(width * 0.026))
    font.setPixelSize(size)
    metrics = QFontMetricsF(font)
    if metrics.horizontalAdvance(label) > rect.width():
        size = max(1, int(size * rect.width() / metrics.horizontalAdvance(label)))
        font.setPixelSize(size)
    if QFontMetricsF(font).height() > rect.height():
        font.setPixelSize(max(1, int(font.pixelSize() * rect.height() / QFontMetricsF(font).height())))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    return pixmap


def create_splash(path: Path, version: str) -> QSplashScreen:
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    width = max(320, int(screen.availableGeometry().width() * 0.45)) if screen else 520
    source = QPixmap(str(path)) if path.is_file() else QPixmap()
    return QSplashScreen(splash_pixmap(source, version, max_width=width, dpr=dpr))
