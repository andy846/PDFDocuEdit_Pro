from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


@pytest.mark.parametrize("case", ["public", "private-login", "private-cache", "forwarded"])
def test_primary_gui_startup_shows_splash_without_blocking_login(case):
    script = """
import sys
import traceback
from types import SimpleNamespace as NS
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMainWindow
import main
import auth.application
import auth.config
from auth.controller import AuthController
from auth.model import Approval, timestamp
from ui.splash import StartupSplash
from PyQt6.QtGui import QPixmap

case = sys.argv[1]
class App(main.PDFDocuEditApplication):
    def exec(self):
        QTimer.singleShot(350, check)
        return super().exec()
app = App(['splash-entrypoint-test'])
main.create_application = lambda: app
main.SingleInstanceRouter.forward_to_primary = staticmethod(lambda *args: case == 'forwarded')
main.SingleInstanceRouter.listen = lambda self: True
auth.config.configuration = lambda: None if case == 'public' else NS(project_ref='splashfixture')
splashes = []
def create():
    splash = StartupSplash(QPixmap(100, 100), minimum_ms=100)
    splashes.append(splash)
    return splash
main._create_splash = create
main._force_windows_icon = lambda viewer: None
class Window(QMainWindow):
    def __init__(self):
        assert len(splashes) == 1 and splashes[0].isVisible()
        super().__init__()
        self.command_bar = NS(add_settings_action=lambda action: None)
        self._command_action_map = {}
        self.settings = NS(get_theme=lambda: 'dark')
        self._update_title_bar = lambda: None
        self.offer_default_app = lambda: None
        self.queue_open_files = lambda paths: None
main.PDFViewer = Window
class Controller(AuthController):
    def start(self, **kwargs):
        if case == 'private-cache':
            now = timestamp()
            self.approval = Approval('splashfixture', 'fixture', 'test@example.invalid', 'fixture', now, now)
            self.approved.emit(self.approval)
        self.changed.emit()
class Session(auth.application.PrivateApplication):
    def __init__(self, app, config, factory, **kwargs):
        assert splashes[0].isVisible()
        super().__init__(app, config, factory, controller=Controller(NS(), NS()), **kwargs)
auth.application.PrivateApplication = Session
checks = []
errors = []
def check():
    try:
        assert len(splashes) == 1 and not splashes[0].isVisible()
        if case.startswith('private'):
            private = app._private_session
            if case == 'private-cache':
                assert private.viewer.isVisible() and not private.login.isVisible()
            else:
                assert private.viewer is None and private.login.isVisible()
        checks.append(True)
    except Exception:
        errors.append(traceback.format_exc())
    finally:
        app.quit()
assert main._run_application(None) == 0
assert not errors, errors
assert checks == ([] if case == 'forwarded' else [True])
assert len(splashes) == (0 if case == 'forwarded' else 1)
"""
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", script, case],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_pdf_arguments_picks_pdf_files_from_argv(tmp_path) -> None:
    script = """
import sys
from pathlib import Path
from main import pdf_arguments

root = Path(sys.argv[1])
first = root / 'a.pdf'
second = root / 'b.PDF'
text = root / 'notes.txt'
missing = root / 'gone.pdf'
for name in ('a.pdf', 'b.PDF', 'notes.txt'):
    (root / name).write_bytes(b'%PDF-1.4 x')
paths = pdf_arguments([str(first), str(text), str(missing), str(second)])
assert paths == [first.resolve(), missing.resolve(), second.resolve()]
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_file_open_event_is_queued_until_viewer_connects() -> None:
    script = """
from PyQt6.QtCore import QEvent
from main import PDFDocuEditApplication

class FileOpenEvent:
    def type(self):
        return QEvent.Type.FileOpen
    def file(self):
        return '/tmp/finder-open.pdf'

app = PDFDocuEditApplication(['entrypoint-test'])
received = []
assert app.event(FileOpenEvent())
app.fileOpenRequested.connect(received.append)
app.activate_file_open_handler()
assert received == ['/tmp/finder-open.pdf']
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_initial_pdf_open_waits_until_window_event_loop(
    tmp_path, monkeypatch
) -> None:
    import fitz
    from PyQt6.QtWidgets import QApplication

    from core.viewer import PDFViewer

    app = QApplication.instance() or QApplication(
        ["pdfdocuedit-deferred-open-test"]
    )
    source = tmp_path / "large-shell-open.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)

    opened: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        PDFViewer,
        "_start_queued_pdf_open",
        lambda self, _session, path, password, **kwargs: (
            opened.append((path, password)),
            self._queued_open_finished(),
        ),
    )
    viewer = PDFViewer(str(source))
    assert opened == []
    assert viewer._open_queue_scheduled

    app.processEvents()
    assert opened == [(str(source.resolve()), None)]
    assert not viewer._open_queue_scheduled
    viewer.close()


def test_queued_pdf_open_completes_in_background(tmp_path) -> None:
    import fitz
    from PyQt6.QtWidgets import QApplication

    from core.viewer import PDFViewer

    app = QApplication.instance() or QApplication(
        ["pdfdocuedit-background-open-test"]
    )
    source = tmp_path / "associated.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)

    viewer = PDFViewer()
    viewer.queue_open_files([str(source)])
    deadline = time.monotonic() + 5
    while viewer._open_queue_scheduled and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert viewer.engine.is_loaded()
    assert viewer._display_path == source.resolve()
    viewer.close()


def test_queued_encrypted_pdf_resumes_after_modal_password_prompt(
    tmp_path, monkeypatch
) -> None:
    """The prompt's nested event loop may finish the first open task early."""
    import fitz
    from PyQt6.QtWidgets import QApplication

    from core import viewer as viewer_module
    from core.viewer import PDFViewer

    app = QApplication.instance() or QApplication(
        ["pdfdocuedit-encrypted-background-open-test"]
    )
    source = tmp_path / "associated-encrypted.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(
            source,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="open-secret",
        )

    def enter_password(*_args, **_kwargs):
        # QInputDialog.exec() runs a nested event loop. Reproduce the important
        # part: the worker's queued ``finished`` signal can be delivered before
        # ask_password returns the password to _queued_pdf_prepared().
        app.processEvents()
        return "open-secret", True

    monkeypatch.setattr(viewer_module, "ask_password", enter_password)
    viewer = PDFViewer()
    viewer.queue_open_files([str(source)])
    deadline = time.monotonic() + 5
    while not viewer.engine.is_loaded() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert viewer.engine.is_loaded()
    assert viewer.engine.password == "open-secret"
    assert not viewer._queued_open_paths
    viewer.close()


def test_single_instance_router_forwards_pdf_paths(tmp_path) -> None:
    from PyQt6.QtNetwork import QLocalServer
    from PyQt6.QtWidgets import QApplication

    from main import SingleInstanceRouter

    app = QApplication.instance() or QApplication(
        ["pdfdocuedit-single-instance-test"]
    )
    server_name = f"PDFDocuEditPro-test-{uuid.uuid4().hex}"
    router = SingleInstanceRouter(server_name)
    assert router.listen()
    received: list[list[str]] = []
    router.pathsReceived.connect(received.append)
    source = tmp_path / "forwarded.pdf"
    source.write_bytes(b"%PDF-1.4 test")

    assert SingleInstanceRouter.forward_to_primary(
        [source],
        server_name=server_name,
    )
    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert received == [[str(source.resolve())]]
    router._server.close()
    QLocalServer.removeServer(server_name)


def test_single_instance_router_releases_pending_connections() -> None:
    """Late disconnects must not retain or call an already collected router."""
    script = """
import gc
import sys
import time
import traceback
import uuid
import weakref
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication
from main import SingleInstanceRouter

app = QApplication(['router-lifetime-test'])
errors = []
sys.excepthook = lambda *args: errors.append(''.join(traceback.format_exception(*args)))
for _ in range(20):
    name = 'PDFDocuEditPro-lifetime-' + uuid.uuid4().hex
    router = SingleInstanceRouter(name)
    assert router.listen()
    endpoint = router.server_name
    client = QLocalSocket()
    client.connectToServer(router.server_name)
    assert client.waitForConnected(1000)
    deadline = time.monotonic() + 3
    while not router._buffers and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert router._buffers
    reference = weakref.ref(router)
    router._server.close()
    del router
    # Qt must disconnect slots belonging to the deleted QObject without a
    # Python lambda/socket cycle keeping that QObject alive until cyclic GC.
    assert reference() is None
    client.disconnectFromServer()
    gc.collect()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QLocalServer.removeServer(endpoint)
assert not errors, errors
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
