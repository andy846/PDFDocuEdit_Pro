"""Observable safe shutdown: lock work controls, retain chrome and live readers."""
from contextlib import contextmanager
from time import monotonic

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QAction

from core.diagnostics import log_failure, log_lifecycle


class CloseLifecycle(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._retry)
        self.warning_after_ms = 3000
        self.started = None
        self.reason = None
        self.warned = False
        self._locks = 0
        self._saved = []
        self._shutdown_lock = False

    def _lock(self):
        if self._locks == 0:
            window = self.window
            widgets = []
            layout = window.centralWidget().layout()
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if widget is window.command_bar:
                    row = widget.layout()
                    widgets.extend(row.itemAt(j).widget() for j in range(row.count())
                                   if row.itemAt(j).widget() is not widget._window_controls)
                elif widget is not None:
                    widgets.append(widget)
            actions = [a for a in window.findChildren(QAction)
                       if a is not window._command_action_map.get("quit")]
            # isEnabled() includes ancestor locks (e.g. account access).
            # Restore the widget's own flag, never the inherited disabled state.
            self._saved = [
                (item, item.isEnabled() if isinstance(item, QAction)
                 else not item.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled))
                for item in (*widgets, *actions) if item is not None
            ]
            for item, _enabled in self._saved:
                item.setEnabled(False)
        self._locks += 1

    def _unlock(self):
        self._locks -= 1
        if self._locks == 0:
            for item, enabled in self._saved:
                if not sip.isdeleted(item):
                    item.setEnabled(enabled)
            self._saved.clear()

    @contextmanager
    def lock_ui(self):
        self._lock()
        try:
            yield
        finally:
            self._unlock()

    def begin(self):
        if not self._shutdown_lock:
            self._lock()
            self._shutdown_lock = True

    def cancel_preflight(self):
        if self.window._closing:
            return
        if self._shutdown_lock:
            self._shutdown_lock = False
            self._unlock()
        self.timer.stop()
        self.started = self.reason = None
        self.warned = False
        log_lifecycle("close.cancelled")

    def defer(self, reason):
        if self.started is None:
            self.started = monotonic()
        if reason != self.reason:
            self.reason = reason
            log_lifecycle("close.pending." + reason, tasks=len(self.window._tasks))
        elapsed = (monotonic() - self.started) * 1000
        if elapsed >= self.warning_after_ms:
            if not self.warned:
                self.warned = True
                self.window.info_bar.show_message(
                    "Still waiting for background work to release PDF readers. "
                    "The window will close when safe; Close remains available to retry. "
                    "A running native operation cannot be interrupted safely.", "warning", 0)
                log_lifecycle("close.deadline", tasks=len(self.window._tasks))
        else:
            self.window.info_bar.show_message("Closing safely: waiting for background work and PDF readers…", "info", 0)
        if not self.timer.isActive():
            self.timer.start(500 if self.warned else 150)

    def _ready(self):
        manager = self.window.document_windows
        windows = manager.live_windows() if manager.pending_exit else [self.window]
        for window in windows:
            if window._tasks or window._printing or window._mutation_controller.active:
                return False
            controller = getattr(window, "_mode_controller", None)
            if controller and controller.host and any(controller.host.is_busy(p) for p in controller.host.projects):
                return False
            merge = getattr(window, "_merge_controller", None)
            if merge and any(page.workers for page in merge.tool_pages()):
                return False
            if any(d._task for d in getattr(window, "_comparison_dialogs", [])):
                return False
            if any(d.worker for d in getattr(window, "_pdf_operation_dialogs", [])):
                return False
            readers = list(getattr(window, "_window_reader_events", []))
            if controller:
                readers.extend(controller.pdf_readers)
            for session in window._sessions:
                readers.extend(session.canvas.reader_events())
                readers.extend(session.nav_panel.thumbnails.reader_events())
                if session.split_canvas is not None:
                    readers.extend(session.split_canvas.reader_events())
            if not all(reader.is_set() for reader in readers):
                return False
        return True

    def _retry(self):
        if self.window._window_closed:
            return
        try:
            # After the deadline observe dependencies; do not keep re-entering
            # closeEvent / save prompts while the same native work is stuck.
            if self.warned and not self._ready():
                self.timer.start(500)
                return
            self.window.close()
        except Exception:
            self.failed()

    def failed(self):
        self.timer.stop()
        log_failure("Close lifecycle failed")
        self.window.info_bar.show_message("Safe shutdown could not finish. Close remains available to retry; see diagnostics.", "error", 0)

    def finished(self):
        self.timer.stop()
        self._saved.clear()
        log_lifecycle("close.completed", tasks=len(self.window._tasks))
