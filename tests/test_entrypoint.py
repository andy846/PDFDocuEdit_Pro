from __future__ import annotations

import os
import subprocess
import sys
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
