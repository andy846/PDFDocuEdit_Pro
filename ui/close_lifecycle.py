"""Observable safe shutdown: lock work controls, retain chrome and live readers."""
from contextlib import contextmanager
from enum import IntEnum
from time import monotonic

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication

from core.diagnostics import log_failure, log_lifecycle


class ClosePhase(IntEnum):
    IDLE = 0
    PREPARING = 1
    WAITING = 2
    CLEANING = 3
    FAILED = 4
    CLOSED = 5


class CloseLifecycle(QObject):
    stateChanged = pyqtSignal(object)

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
        self.teardown_started = False
        self.phase = ClosePhase.IDLE
        self.handling_close = False
        self._preferences_saved = False
        from .close_status import CloseStatusBar
        self.status_bar = CloseStatusBar(window.centralWidget())
        layout = window.centralWidget().layout()
        layout.insertWidget(layout.indexOf(window.command_bar) + 1, self.status_bar)
        self.stateChanged.connect(self.status_bar.update_status)
        self.status_bar.retryRequested.connect(self.retry)
        self.status_bar.returnRequested.connect(self.return_to_work)
        self.status_bar.diagnosticsRequested.connect(self.show_diagnostics)

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
                                   if row.itemAt(j).widget() not in (widget._window_controls, widget._app_icon, widget._title))
                elif widget is not None and widget is not self.status_bar:
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
        self._diagnose("close.locked")

    def _unlock(self):
        if self._locks <= 0:
            return
        self._locks -= 1
        if self._locks == 0:
            for item, enabled in self._saved:
                if not sip.isdeleted(item):
                    item.setEnabled(enabled)
            self._saved.clear()
        self._diagnose("close.unlocked")

    @contextmanager
    def lock_ui(self):
        self._lock()
        try:
            yield
        finally:
            self._unlock()

    @property
    def is_failed(self):
        return self.phase == ClosePhase.FAILED

    def _participants(self):
        manager = getattr(self.window, 'document_windows', None)
        return manager.live_windows() if manager else [self.window]

    def can_return_to_work(self):
        manager = getattr(self.window, 'document_windows', None)
        if manager and manager.pending_exit and manager.exit_teardown_started:
            return False
        return not any(w._close_lifecycle.teardown_started for w in self._participants())

    def snapshot(self):
        windows = self._participants()
        readers = []
        for window in windows:
            readers.extend(getattr(window, '_window_reader_events', []))
            for session in window._sessions:
                readers.extend(session.canvas.reader_events())
                readers.extend(session.nav_panel.thumbnails.reader_events())
                if session.split_canvas is not None:
                    readers.extend(session.split_canvas.reader_events())
        tasks = 0
        for window in windows:
            tasks += len(window._tasks) + int(window._printing) + int(window._mutation_controller.active)
            mode = getattr(window, '_mode_controller', None)
            if mode and mode.host:
                tasks += sum(mode.host.is_busy(p) for p in mode.host.projects)
            merge = getattr(window, '_merge_controller', None)
            if merge:
                tasks += sum(len(p.workers) for p in merge.tool_pages())
            tasks += sum(d._task is not None for d in getattr(window, '_comparison_dialogs', []))
            tasks += sum(d.worker is not None for d in getattr(window, '_pdf_operation_dialogs', []))
        elapsed = 0 if self.started is None else max(0, int(monotonic() - self.started))
        return dict(phase=int(self.phase), reason=self.reason or 'preparation',
                    failed=self.is_failed, can_return=self.can_return_to_work(),
                    visible=self.is_failed or (self.warned and self.phase == ClosePhase.WAITING),
                    elapsed=elapsed, tasks=tasks, readers=sum(not r.is_set() for r in readers))

    def _publish(self):
        self.stateChanged.emit(self.snapshot())

    def _diagnose(self, stage):
        state = self.snapshot()
        mode = getattr(self.window, '_mode_controller', None)
        host = mode.host if mode else None
        manager = getattr(self.window, 'document_windows', None)
        log_lifecycle(stage, phase=self.phase, locks=self._locks, teardown=self.teardown_started,
                      pending_exit=bool(manager and manager.pending_exit),
                      group_teardown=bool(manager and manager.exit_teardown_started),
                      exit_approved=bool(getattr(mode, 'exit_approved', self.window._window_exit_approved)),
                      closing=self.window._closing, tasks=state['tasks'], readers=state['readers'],
                      designer=bool(mode and mode.modes.mode.value == 'designer'),
                      tabs=host.tabs.count() if host else 0,
                      modal=QApplication.activeModalWidget() is not None)

    def start_attempt(self):
        if self.phase in (ClosePhase.IDLE, ClosePhase.FAILED):
            self.phase = ClosePhase.CLEANING if self.teardown_started else ClosePhase.PREPARING
            self.reason = 'cleanup' if self.teardown_started else 'preparation'
            self._publish()

    def begin(self):
        if self.started is None:
            self.started = monotonic()
        if not self._shutdown_lock:
            self._lock()
            self._shutdown_lock = True
        if not self.teardown_started:
            self.phase = ClosePhase.PREPARING
        self._publish()

    def prepare_preferences(self):
        if self._preferences_saved or self.teardown_started:
            return
        self.reason = 'preferences'
        if not self.window._pdf_only_window:
            window = self.window
            window.settings.update({
                'window_size': [window.width(), window.height()],
                'window_position': [window.x(), window.y()],
                'window_maximized': window.isMaximized(),
                'left_panel_collapsed': False if getattr(window, '_auto_collapsed_sidebar', False)
                                        else window.side_panel.is_collapsed(),
            })
        self._preferences_saved = True
        self.reason = None

    def mark_teardown_started(self):
        self.begin()
        self.teardown_started = True
        manager = self.window.document_windows
        if manager.pending_exit:
            manager.exit_teardown_started = True
        self.window._closing = True
        self.phase = ClosePhase.CLEANING
        self.reason = 'cleanup'
        self._diagnose('close.teardown')
        self._publish()

    def cancel_preflight(self):
        if not self.can_return_to_work():
            return
        if self._shutdown_lock:
            self._shutdown_lock = False
            self._unlock()
        self.timer.stop()
        self.started = self.reason = None
        self.warned = False
        self._preferences_saved = False
        self.phase = ClosePhase.IDLE
        self._publish()
        log_lifecycle('close.cancelled')

    def return_to_work(self):
        if not self.can_return_to_work():
            return False
        manager = self.window.document_windows
        manager.pending_exit = False
        manager.exit_teardown_started = False
        for window in manager.live_windows():
            window._closing = False
        manager._reset_approvals(manager.live_windows())
        return True

    def retry(self):
        if self.handling_close:
            return
        for window in self._participants():
            lifecycle = window._close_lifecycle
            if lifecycle.is_failed:
                lifecycle.phase = ClosePhase.CLEANING if lifecycle.teardown_started else ClosePhase.PREPARING
        manager = self.window.document_windows
        target = manager.primary if manager.pending_exit else self.window
        target.close()

    def show_diagnostics(self):
        from .diagnostics_dialog import DiagnosticsDialog
        DiagnosticsDialog(self.window).exec()

    def defer(self, reason):
        if self.is_failed:
            return
        if self.started is None:
            self.started = monotonic()
        self.phase = ClosePhase.WAITING
        if reason != self.reason:
            self.reason = reason
            self._diagnose('close.pending.' + reason)
        elapsed = (monotonic() - self.started) * 1000
        if elapsed >= self.warning_after_ms and not self.warned:
            self.warned = True
            self._diagnose('close.deadline')
        self._publish()
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
            if self.handling_close or QApplication.activeModalWidget() is not None:
                self.timer.start(500)
                return
            # After the deadline observe dependencies; do not keep re-entering
            # closeEvent / save prompts while the same native work is stuck.
            if self.warned and not self._ready():
                self._publish()
                self.timer.start(500)
                return
            self.window.close()
        except Exception:
            self.failed()

    def failed(self, reason=None):
        reason = reason or self.reason or ('cleanup' if self.teardown_started else 'preparation')
        self.timer.stop()
        log_failure('Close lifecycle failed')
        if self.can_return_to_work():
            self.return_to_work()
        self.reason = reason
        self.phase = ClosePhase.FAILED
        self._diagnose('close.failed')
        self._publish()

    def finished(self):
        self.timer.stop()
        self._saved.clear()
        self.phase = ClosePhase.CLOSED
        self._publish()
        log_lifecycle('close.completed', tasks=len(self.window._tasks))
