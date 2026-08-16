"""PDFDocuEdit Pro PyQt6 application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen

from core.resources import APP_NAME, resource_path
from core.settings import SettingsManager
from core.viewer import PDFViewer
from styles.components import global_style
from styles.theme import ThemeMode, apply_theme


class PDFDocuEditApplication(QApplication):
    fileOpenRequested = pyqtSignal(str)

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self._file_open_ready = False
        self._pending_file_opens: list[str] = []

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                if self._file_open_ready:
                    self.fileOpenRequested.emit(path)
                else:
                    self._pending_file_opens.append(path)
                return True
        return super().event(event)

    def activate_file_open_handler(self) -> None:
        self._file_open_ready = True
        pending, self._pending_file_opens = self._pending_file_opens, []
        for path in pending:
            self.fileOpenRequested.emit(path)


def _create_splash() -> QSplashScreen:
    splash_path = resource_path("splash.png")
    if splash_path.exists():
        pixmap = QPixmap(str(splash_path))
        # Show the splash at up to 45% of the screen width at native
        # resolution (the previous fixed 520px looked small and blurry).
        screen = QApplication.primaryScreen()
        if screen and not pixmap.isNull():
            dpr = screen.devicePixelRatio()
            max_pixels = max(320, int(screen.availableGeometry().width() * 0.45 * dpr))
            if pixmap.width() > max_pixels:
                pixmap = pixmap.scaledToWidth(
                    max_pixels, Qt.TransformationMode.SmoothTransformation
                )
            pixmap.setDevicePixelRatio(dpr)
    else:
        pixmap = QPixmap(520, 292)
        pixmap.fill(QColor("#1c1c1e"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#f2f2f4"))
        painter.setFont(QFont(QApplication.font().family(), 24, QFont.Weight.DemiBold))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, APP_NAME)
        painter.end()
    return QSplashScreen(pixmap)


def _set_windows_app_id() -> None:
    """Give the packaged app its own taskbar identity.

    The AppUserModelID makes Windows look up a registered icon for the ID,
    which only exists for the packaged executable (whose icon is embedded);
    for source runs it would replace the window icon with a generic white
    one, so it is applied only when frozen.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "PDFDocuEdit.Pro"
        )
    except Exception:
        pass


def _application_icon() -> QIcon:
    """Build the window icon from the PNG master instead of the ICO file.

    Qt's HICON conversion for the Windows title bar renders ICO masks as a
    white square; a QPixmap-based QIcon converts with correct alpha, so the
    title-bar and taskbar icons keep their real colours.
    """
    icon = QIcon()
    png_path = resource_path("icon.png")
    ico_path = resource_path("icon.ico")
    source = png_path if png_path.exists() else ico_path
    base = QPixmap(str(source))
    if base.isNull():
        return icon
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(
            base.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return icon


def _force_windows_icon(window) -> None:
    """Re-apply the title-bar icon via WM_SETICON with a GDI-built HICON.

    Qt's own HICON carries an inverted AND mask for this icon asset, which
    makes the Windows title bar render a white square instead of the icon.
    A 32bpp BMP loaded through LoadImage gets a correct mask from GDI.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import tempfile
        from ctypes import wintypes

        from PIL import Image

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            ctypes.c_uint,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        icon_source = resource_path("icon.png")
        if not icon_source.exists():
            icon_source = resource_path("icon.ico")
        with Image.open(icon_source).convert("RGBA") as master:
            with tempfile.TemporaryDirectory(prefix="pdfdocuedit-icon-") as folder:
                hwnd = int(window.winId())
                for size, message in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
                    frame = master.resize((size, size), Image.LANCZOS)
                    path = f"{folder}\\icon-{size}.bmp"
                    frame.save(path, "BMP")
                    hicon = user32.LoadImageW(
                        None, path, 1, size, size, 0x10
                    )  # IMAGE_ICON | LR_LOADFROMFILE
                    if hicon:
                        user32.SendMessageW(hwnd, 0x0080, message, hicon)
    except Exception:
        pass


def create_application(argv: list[str] | None = None) -> PDFDocuEditApplication:
    _set_windows_app_id()
    app = PDFDocuEditApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("PDFDocuEdit")
    app.setOrganizationDomain("pdfdocuedit.local")
    app.setApplicationVersion("1.0")
    app.setWindowIcon(_application_icon())
    settings = SettingsManager()
    apply_theme(app, ThemeMode(settings.get_theme()))
    app.setStyleSheet(global_style())
    return app


def pdf_arguments(argv: list[str]) -> list[Path]:
    """Existing .pdf/.ps/.eps files among the command-line arguments."""
    return [
        Path(argument).expanduser().resolve()
        for argument in argv
        if Path(argument).expanduser().is_file()
        and Path(argument).suffix.casefold() in {".pdf", ".ps", ".eps"}
    ]


def main() -> int:
    app = create_application()
    splash = _create_splash()
    splash.show()
    app.processEvents()

    # Windows passes "open with" files (single or several at once) as
    # command-line arguments; macOS delivers FileOpen events instead.
    paths = pdf_arguments(sys.argv[1:])
    initial_path = str(paths[0]) if paths else None
    viewer = PDFViewer(initial_path)
    if len(paths) > 1:
        # The first file is already open; the rest each get their own tab.
        viewer.open_files([str(path) for path in paths[1:]])
    # macOS FileOpen events each open in their own tab instead of replacing
    # the current document.
    app.fileOpenRequested.connect(lambda path: viewer.open_files([path]))
    app.activate_file_open_handler()
    try:
        app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: viewer._apply_theme("system")
            if viewer.settings.get_theme() == "system"
            else None
        )
    except AttributeError:
        pass

    viewer.show()
    splash.finish(viewer)
    # Qt's HICON mask renders the title-bar icon as a white square; hand
    # Windows a correctly-masked icon once the native window exists.
    QTimer.singleShot(150, lambda: _force_windows_icon(viewer))
    # Ask once (installed builds only) whether to become the default app.
    QTimer.singleShot(600, viewer.offer_default_app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
