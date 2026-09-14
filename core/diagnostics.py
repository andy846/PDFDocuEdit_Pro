"""Contextual diagnostics without PDF values, credentials or exception payloads."""
from __future__ import annotations

import logging
import sys
import traceback

from PyQt6.QtCore import QObject, Qt, pyqtSlot
from PyQt6.QtWidgets import QApplication


def log_failure(context: str, level: int = logging.WARNING) -> None:
    kind, _error, trace = sys.exc_info()
    # Never include exception payloads, frame locals or source-code snippets.
    frames = "\n".join(f"  {frame.filename}:{frame.lineno} in {frame.name}"
                       for frame in traceback.extract_tb(trace))
    logging.getLogger("pdfdocuedit").log(
        level, "%s [%s]\n%s", context, kind.__name__ if kind else "Failure", frames)


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
