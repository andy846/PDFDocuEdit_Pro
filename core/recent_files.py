"""Bounded, disposable availability probes. Never execute a filesystem call in UI code.

Daemon workers deliberately do not participate in Qt pool shutdown: a Windows
redirector can block a stat indefinitely. At most two such calls can exist.
"""
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread

_queue = Queue(maxsize=20)
_lock = Lock()
_started = False

def is_network_path(path):
    return str(path).replace("\\", "/").startswith("//")

def _worker():
    while True:
        path, token, signals = _queue.get()
        try:
            try:
                available = Path(path).is_file()
            except OSError:
                available = False
            try:
                signals.available.emit(path, token, available)
            except RuntimeError:
                pass  # window was destroyed
        finally:
            _queue.task_done()

def check_availability(path, token, signals):
    global _started
    with _lock:
        if not _started:
            for _ in range(2):
                Thread(target=_worker, daemon=True, name="recent-availability").start()
            _started = True
    try:
        _queue.put_nowait((path, token, signals))
    except Full:
        pass  # leave status unknown; never grow a backlog on a dead share
