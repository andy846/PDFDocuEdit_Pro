from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


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
assert paths == [first.resolve(), second.resolve()]
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
        lambda self, _session, path, password: (
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
