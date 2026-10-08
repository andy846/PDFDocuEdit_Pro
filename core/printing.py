"""Immutable print inputs and worker-safe preparation/rasterization."""

import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QTransform

from .tasks import TaskCancelled


@dataclass(frozen=True)
class PrintJob:
    source: str | bytes
    name: str
    key: str
    pages: tuple[int, ...] | None = None


@dataclass(frozen=True)
class PreparedPrintJob:
    session: object
    pages: tuple[int, ...]
    first_size: tuple[float, float]

    @property
    def data(self):
        """Compatibility access; production never loads the PDF back into memory."""
        return (self.session.directory / "input.pdf").read_bytes()


class PrintSession:
    """Sequential process transport, used by worker tasks without Qt ownership."""
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pdfdocuedit-print-")
        self.directory = Path(self.temporary.name)
        self.serial = 0
        self.worker_pid = None
        self.closed = False
        self.stderr = (self.directory / "worker.stderr").open("wb")
        args = (["--print-worker"] if getattr(sys, "frozen", False)
                else ["-m", "core.print_worker"]) + [str(self.directory)]
        try:
            self.process = subprocess.Popen(
                [sys.executable, *args], cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            self.stderr.close()
            self.temporary.cleanup()
            raise

    def request(self, command, **values):
        self.serial += 1
        payload = {"id": self.serial, "command": command, **values}
        self.process.stdin.write((json.dumps(payload) + "\n").encode())
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Print rendering process exited without a result.")
        result = json.loads(line)
        if result.get("event") == "ready":
            self.worker_pid = int(result["pid"])
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("Print rendering process exited without a result.")
            result = json.loads(line)
        if result.get("id") != self.serial:
            raise RuntimeError("Unexpected print rendering response.")
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def cancel(self):
        if not self.closed:
            (self.directory / "cancel").touch()

    def kill(self):
        if not self.closed and self.process.poll() is None:
            # Windows venv python.exe may be a redirector owning a child process.
            if self.worker_pid is not None and self.worker_pid != self.process.pid:
                try:
                    os.kill(self.worker_pid, signal.SIGTERM)
                except OSError:
                    pass
            self.process.kill()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.poll() is None:
                try:
                    self.process.stdin.write(b'{"id":0,"command":"shutdown"}\n')
                    self.process.stdin.flush()
                except OSError:
                    pass
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if self.worker_pid is not None and self.worker_pid != self.process.pid:
                        try:
                            os.kill(self.worker_pid, signal.SIGTERM)
                        except OSError:
                            pass
                    self.process.kill()
                    self.process.wait()
        finally:
            for handle in (self.process.stdin, self.process.stdout, self.stderr):
                try:
                    handle.close()
                except OSError:
                    # A killed worker may leave a buffered write in stdin.
                    # Closing the other handles and temp directory must continue.
                    pass
            self.temporary.cleanup()


@dataclass(frozen=True)
class PrintRenderSettings:
    dpi: int
    width: int
    height: int
    left: float
    top: float
    scale_mode: int
    scale: float
    center: bool
    offset_x: float
    offset_y: float


def _check_cancel(is_cancelled):
    if is_cancelled and is_cancelled():
        raise TaskCancelled


def prepare_print_job(job: PrintJob, *, is_cancelled=None, session=None) -> PreparedPrintJob:
    _check_cancel(is_cancelled)
    owned = session is None
    session = session or PrintSession()
    try:
        source = job.source
        if isinstance(source, bytes):
            source = session.directory / "input.pdf"
            with source.open("wb") as output:
                for offset in range(0, len(job.source), 1024 * 1024):
                    _check_cancel(is_cancelled)
                    output.write(job.source[offset:offset + 1024 * 1024])
        _check_cancel(is_cancelled)
        result = session.request("prepare", source=str(source), pages=job.pages)
        _check_cancel(is_cancelled)
        return PreparedPrintJob(session, tuple(result["pages"]), tuple(result["first_size"]))
    except Exception:
        if owned:
            session.close()
        raise


def render_page_image(page, settings: PrintRenderSettings):
    """Return an owned QImage and placement; no printer or GUI widget is accessed."""
    pix = page.get_pixmap(dpi=min(600, max(72, settings.dpi)), alpha=False)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                   QImage.Format.Format_RGB888).copy()
    return place_print_image(image, page.rect.width, page.rect.height, settings)


def place_print_image(image, page_width, page_height, settings):
    if settings.scale_mode == 0:
        if (settings.width > settings.height) != (page_width > page_height):
            image = image.transformed(QTransform().rotate(90), Qt.TransformationMode.SmoothTransformation)
        width, height = settings.width, settings.height
    else:
        factor = 1.0 if settings.scale_mode == 1 else settings.scale / 100.0
        width = max(1, int(page_width / 72 * settings.dpi * factor))
        height = max(1, int(page_height / 72 * settings.dpi * factor))
    image = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    x, y = settings.left, settings.top
    if settings.center:
        x += (settings.width - image.width()) / 2
        y += (settings.height - image.height()) / 2
    x += settings.offset_x / 25.4 * settings.dpi
    y += settings.offset_y / 25.4 * settings.dpi
    return image, int(x), int(y)


def render_print_page(prepared: PreparedPrintJob, index: int,
                      settings: PrintRenderSettings, *, is_cancelled=None):
    _check_cancel(is_cancelled)
    frame = prepared.session.request("render_page", index=index, dpi=settings.dpi)
    _check_cancel(is_cancelled)
    path = prepared.session.directory / "page.rgb"
    try:
        raw = path.read_bytes()
        if len(raw) != frame["stride"] * frame["height"]:
            raise RuntimeError("Incomplete print raster data.")
        image = QImage(raw, frame["width"], frame["height"], frame["stride"],
                       QImage.Format.Format_RGB888).copy()
        result = place_print_image(image, *frame["page_size"], settings)
    finally:
        path.unlink(missing_ok=True)
    _check_cancel(is_cancelled)
    return result
