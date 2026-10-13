"""Contextual diagnostics without PDF values, credentials or exception payloads."""
from __future__ import annotations

import logging
import sys
import traceback

from PyQt6.QtCore import QObject, Qt, pyqtSlot
from PyQt6.QtWidgets import QApplication


def log_failure(context: str, level: int = logging.WARNING) -> None:
    kind, error, trace = sys.exc_info()
    seen = set()
    while True:
        frames = "\n".join(f"  {frame.filename}:{frame.lineno} in {frame.name}"
                           for frame in traceback.extract_tb(trace))
        logging.getLogger("pdfdocuedit").log(
            level, "%s [%s]\n%s", context, kind.__name__ if kind else "Failure", frames)
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
        if cause is None or id(cause) in seen:
            break
        error, kind, trace = cause, type(cause), cause.__traceback__
        context = "Caused by"


def log_lifecycle(stage, **counts):
    """Only fixed stages and numeric counters; never file paths or field values."""
    fields = " ".join(f"{key}={int(value)}" for key, value in sorted(counts.items()))
    logging.getLogger("pdfdocuedit").info("Lifecycle %s %s", stage, fields)


class _InterruptBridge(QObject):
    @pyqtSlot(str)
    def handle(self, kind: str) -> None:
        logging.getLogger("pdfdocuedit").warning("Background operation interrupted: %s", kind)
        if kind == "SystemExit":
            app = QApplication.instance()
            if app is not None:
                # Normal close handling still asks about unsaved documents.
                app.closeAllWindows()


def connect_interrupts(signals) -> None:
    """Called by task constructors on the GUI thread; delivery is always queued."""
    app = QApplication.instance()
    if app is not None:
        bridge = getattr(app, "_worker_interrupt_bridge", None)
        if bridge is None:
            bridge = _InterruptBridge(app)
            app._worker_interrupt_bridge = bridge
        signals.interrupted.connect(bridge.handle, Qt.ConnectionType.QueuedConnection)
