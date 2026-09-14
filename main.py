"""PDFDocuEdit Pro PyQt6 application entry point."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QSplashScreen

from core.resources import APP_NAME, APP_SLUG, APP_VERSION, resource_path
from core.settings import SettingsManager
from core.viewer import PDFViewer
from styles.components import global_style
from styles.theme import ThemeMode, apply_theme
from updates.runtime import RESTART_EXIT_CODE, ROOT_ENV, TOKEN_ENV, FileLock, managed_root


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


SINGLE_INSTANCE_KEY = f"{APP_SLUG}-v1-1-single-instance"


class SingleInstanceRouter(QObject):
    """Forward later Windows launches to the first running application."""

    pathsReceived = pyqtSignal(list)

    def __init__(self, server_name: str = SINGLE_INSTANCE_KEY, parent=None):
        super().__init__(parent)
        self.server_name = server_name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}

    @staticmethod
    def _message(paths: list[Path] | list[str]) -> bytes:
        payload = {
            "activate": True,
            "paths": [str(Path(path).expanduser().resolve()) for path in paths],
        }
        return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    @classmethod
    def forward_to_primary(
        cls,
        paths: list[Path] | list[str],
        server_name: str = SINGLE_INSTANCE_KEY,
        timeout_ms: int = 700,
    ) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if not socket.waitForConnected(timeout_ms):
            socket.abort()
            return False
        message = cls._message(paths)
        queued = socket.write(message) == len(message)
        socket.flush()
        deadline = timeout_ms
        while queued and socket.bytesToWrite() > 0 and deadline > 0:
            application = QCoreApplication.instance()
            if application is not None:
                application.processEvents()
            step = min(50, deadline)
            socket.waitForBytesWritten(step)
            deadline -= step
        written = queued and socket.bytesToWrite() == 0
        socket.disconnectFromServer()
        return bool(written)

    def listen(self) -> bool:
        if self._server.listen(self.server_name):
            return True
        # A crashed process can leave a stale local-server endpoint. Only the
        # elected primary reaches here after a connection attempt failed.
        QLocalServer.removeServer(self.server_name)
        return self._server.listen(self.server_name)

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(
                lambda current=socket: self._read_socket(current)
            )
            socket.disconnected.connect(
                lambda current=socket: self._drop_socket(current)
            )
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        if socket not in self._buffers:
            return
        self._buffers[socket].extend(bytes(socket.readAll()))
        buffer = self._buffers[socket]
        while b"\n" in buffer:
            raw, remainder = buffer.split(b"\n", 1)
            self._buffers[socket] = buffer = bytearray(remainder)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            paths = payload.get("paths", []) if isinstance(payload, dict) else []
            if isinstance(paths, list):
                self.pathsReceived.emit([str(path) for path in paths if path])

    def _drop_socket(self, socket: QLocalSocket) -> None:
        self._read_socket(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()


def _create_splash() -> QSplashScreen:
    splash_path = resource_path("Splash.png")
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
    for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
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
                try:
                    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
                    user32.GetDpiForWindow.restype = ctypes.c_uint
                    dpi = max(96, int(user32.GetDpiForWindow(hwnd)))
                except Exception:
                    dpi = 96
                # WM_SETICON uses physical pixels. Generate the actual monitor
                # sizes from the 256 px master so 125–300% Windows scaling does
                # not enlarge a low-resolution 16/32 px bitmap.
                icon_sizes = (
                    (min(256, round(16 * dpi / 96)), 0),
                    (min(256, round(32 * dpi / 96)), 1),
                )
                for size, message in icon_sizes:  # ICON_SMALL, ICON_BIG
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
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(_application_icon())
    if managed_root() is not None:
        from updates.app_session import import_settings

        import_settings()
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
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        if not os.environ.get(TOKEN_ENV):
            from updates.protocol import UpdateError
            from updates.runtime import managed_launcher
            try:
                launcher_path = managed_launcher(Path(sys.executable))
                if launcher_path is not None:
                    environment = os.environ.copy()
                    environment.pop(ROOT_ENV, None)
                    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                    subprocess.Popen([str(launcher_path), *sys.argv[1:]], env=environment)
                    return 0
            except (OSError, UpdateError):
                from core.diagnostics import log_failure
                from launcher import notify
                log_failure("Managed launcher could not start")
                notify("Cannot start the managed application. Restore the complete deployment folder and open Launcher.exe.")
                return 1
    root = managed_root()
    app_lock = None
    if root is not None:
        from updates.protocol import read_json

        launch = read_json(root / "launch.json")
        if launch.get("token") != os.environ.get(TOKEN_ENV) or launch.get("version") != APP_VERSION:
            return 1
        app_lock = FileLock(root / "app.lock")
        if not app_lock.acquire():
            return 1
    try:
        return _run_application(root)
    finally:
        if app_lock is not None:
            app_lock.release()


def _run_application(root: Path | None) -> int:
    app = create_application()
    # A file association starts the executable again. Forward those paths to
    # the existing process before creating a splash or a second main window.
    paths = pdf_arguments(sys.argv[1:])
    server_name = SINGLE_INSTANCE_KEY if root is None else SINGLE_INSTANCE_KEY + "-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if SingleInstanceRouter.forward_to_primary(paths, server_name):
        return 0
    instance_router = SingleInstanceRouter(server_name, parent=app)
    if not instance_router.listen():
        # Cover the narrow race where two processes start at the same time.
        if SingleInstanceRouter.forward_to_primary(paths, server_name):
            return 0

    splash = _create_splash()
    splash.show()
    app.processEvents()

    viewer = PDFViewer()
    # macOS FileOpen events each open in their own tab instead of replacing
    # the current document.
    app.fileOpenRequested.connect(lambda path: viewer.queue_open_files([path]))
    app.activate_file_open_handler()

    def accept_forwarded_paths(forwarded: list[str]) -> None:
        if viewer.isMinimized():
            viewer.showNormal()
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
        if forwarded:
            viewer.queue_open_files(forwarded)

    instance_router.pathsReceived.connect(accept_forwarded_paths)
    try:
        app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: viewer.apply_theme("system")
            if viewer.settings.get_theme() == "system"
            else None
        )
    except AttributeError:
        pass

    viewer.show()
    splash.finish(viewer)
    if paths and root is None:
        viewer.queue_open_files([str(path) for path in paths])
    # Qt's HICON mask renders the title-bar icon as a white square; hand
    # Windows a correctly-masked icon once the native window exists.
    QTimer.singleShot(150, lambda: _force_windows_icon(viewer))
    # The frame theme needs the native window too.
    QTimer.singleShot(200, viewer._update_title_bar)
    # Ask once (installed builds only) whether to become the default app.
    if root is None:
        QTimer.singleShot(600, viewer.offer_default_app)
    else:
        from updates.app_session import activate

        viewer.setEnabled(False)
        pending_paths = [str(path) for path in paths]

        def managed_open(incoming):
            incoming = [*pending_paths, *incoming]
            pending_paths.clear()
            accept_forwarded_paths(incoming)

        QTimer.singleShot(300, lambda: activate(viewer, managed_open))
    result = app.exec()
    return RESTART_EXIT_CODE if getattr(viewer, "_update_restart", False) else result


if __name__ == "__main__":
    raise SystemExit(main())
