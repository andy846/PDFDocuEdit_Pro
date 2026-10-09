"""Splash artwork with a version label drawn from application metadata."""

from pathlib import Path

from PyQt6.QtCore import QElapsedTimer, QRectF, Qt, QTimer
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


class StartupSplash(QSplashScreen):
    """Keep fast private startup visible without delaying login or readiness."""

    def __init__(self, pixmap: QPixmap, *, minimum_ms: int = 750):
        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        self._minimum_ms = max(0, minimum_ms)
        self._shown = QElapsedTimer()
        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.timeout.connect(self.close)
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.close)

    def showEvent(self, event):
        if not self._shown.isValid():
            self._shown.start()
        super().showEvent(event)

    def finish_startup(self) -> None:
        """Login is ready; dismiss asynchronously, never wait for credentials."""
        elapsed = self._shown.elapsed() if self._shown.isValid() else self._minimum_ms
        self._dismiss.start(max(0, self._minimum_ms - elapsed))

    def closeEvent(self, event):
        self._dismiss.stop()
        super().closeEvent(event)


def create_splash(path: Path, version: str) -> StartupSplash:
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    width = max(320, int(screen.availableGeometry().width() * 0.45)) if screen else 520
    source = QPixmap(str(path)) if path.is_file() else QPixmap()
    return StartupSplash(splash_pixmap(source, version, max_width=width, dpr=dpr))
