"""Asynchronous QProcess transport for isolated composition workers."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal


class Worker(QObject):
    resultReady = pyqtSignal(dict)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    stateChanged = pyqtSignal(dict)
    ended = pyqtSignal()

    def __init__(self, directory: Path, request: dict, parent=None, *, worker_module="composition.worker", secrets=None):
        super().__init__(parent)
        token = uuid.uuid4().hex
        self.cancel_file = directory / (token + ".cancel")
        self.events_file = directory / (token + ".events.jsonl")
        self.events_offset = 0
        self.request_file = directory / (token + ".request.json")
        directory.mkdir(parents=True, exist_ok=True)
        self.request_file.write_text(json.dumps({**request, "cancel_file": str(self.cancel_file), "events_file": str(self.events_file),
                                                **({"stdin_secrets": True} if secrets is not None else {})},
                                               ensure_ascii=True), encoding="utf-8")
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self.buffer = bytearray()
        self.stderr = bytearray()
        self.delivered = False
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        frozen_flag = "--pdf-operations-worker" if worker_module == "core.pdf_operations.worker" else "--composition-worker"
        args = ([frozen_flag] if getattr(sys, "frozen", False)
                else ["-m", worker_module]) + [str(self.request_file)]
        if secrets is not None:
            secret_bytes = json.dumps(secrets, ensure_ascii=True).encode("utf-8") + b"\n"
            def send_secrets():
                self.process.write(secret_bytes)
                self.process.closeWriteChannel()
            self.process.started.connect(send_secrets)
        self.poll = QTimer(self)
        self.poll.setInterval(50)
        self.poll.timeout.connect(self._read_events)
        self.poll.start()
        self.process.start(sys.executable, args)

    def _stderr(self):
        self.stderr.extend(bytes(self.process.readAllStandardError()))
        self.stderr = self.stderr[-8000:]

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        self._parse()

    def _read_events(self):
        if not self.events_file.exists():
            return
        with self.events_file.open("rb") as stream:
            stream.seek(self.events_offset)
            raw = stream.read(1024 * 1024)
            self.events_offset += len(raw)
        self.buffer.extend(raw)
        self._parse()

    def _parse(self):
        while b"\n" in self.buffer:
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            try:
                event = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            kind = event.get("event")
            if kind == "progress":
                self.progress.emit(event["done"], event["total"], event["message"])
            elif kind == "state":
                self.stateChanged.emit(event["state"])
            elif kind == "result" and not self.delivered:
                self.delivered = True
                self.resultReady.emit(event["result"])
            elif kind == "error" and not self.delivered:
                self.delivered = True
                self.failed.emit(event["message"])

    def _finished(self, code, status):
        self.poll.stop()
        self._read()
        self._read_events()
        self._stderr()
        if not self.delivered:
            self.delivered = True
            self.failed.emit("Composition worker exited without a result. " +
                             self.stderr.decode("utf-8", errors="replace")[-2000:])
        self.events_file.unlink(missing_ok=True)
        self.request_file.unlink(missing_ok=True)
        self.cancel_file.unlink(missing_ok=True)
        self.ended.emit()
        self.deleteLater()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._finished(-1, None)

    def cancel(self):
        self.cancel_file.touch()

    def stop_preview(self):
        """Only non-publishing previews may be terminated immediately."""
        self.process.kill()

    @property
    def running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning
