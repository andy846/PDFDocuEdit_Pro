"""Reusable cooperative background task wrapper for UI operations."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from core.diagnostics import connect_interrupts, log_failure


class TaskSignals(QObject):
    interrupted = pyqtSignal(str)
    started = pyqtSignal()
    progress = pyqtSignal(int, int, str)
    result = pyqtSignal(object)
    cancelled = pyqtSignal()
    error = pyqtSignal(str)
    finished = pyqtSignal()


class TaskCancelled(RuntimeError):
    pass


class FunctionTask(QRunnable):
    def __init__(
        self,
        function: Callable[..., Any],
        *args,
        progress_argument: str | None = None,
        cancel_argument: str | None = None,
        discard_result: Callable[[Any], None] | None = None,
        **kwargs,
    ):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.progress_argument = progress_argument
        self.cancel_argument = cancel_argument
        self.discard_result = discard_result
        self.signals = TaskSignals()
        connect_interrupts(self.signals)
        self._cancelled = Event()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            if self.progress_argument:
                self.kwargs[self.progress_argument] = self._report_progress
            if self.cancel_argument:
                self.kwargs[self.cancel_argument] = self.is_cancelled
            if self.is_cancelled():
                raise TaskCancelled
            value = self.function(*self.args, **self.kwargs)
            if self.is_cancelled():
                if self.discard_result is not None:
                    self.discard_result(value)
                self.signals.cancelled.emit()
            else:
                self.signals.result.emit(value)
        except TaskCancelled:
            self.signals.cancelled.emit()
        except (KeyboardInterrupt, SystemExit) as exc:
            log_failure("Background task interrupted")
            self.signals.cancelled.emit()
            self.signals.interrupted.emit(type(exc).__name__)
        except Exception as exc:
            if self.is_cancelled():
                self.signals.cancelled.emit()
            else:
                log_failure("Background task failed")
                self.signals.error.emit(str(exc) or exc.__class__.__name__)
        finally:
            self.signals.finished.emit()

    def _report_progress(self, current: int, total: int, message: str) -> None:
        if self.is_cancelled():
            raise TaskCancelled
        self.signals.progress.emit(current, total, message)
