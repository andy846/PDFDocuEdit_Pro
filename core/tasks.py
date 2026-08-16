"""Reusable cooperative background task wrapper for UI operations."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from threading import Event
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


class TaskSignals(QObject):
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
        **kwargs,
    ):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.progress_argument = progress_argument
        self.cancel_argument = cancel_argument
        self.signals = TaskSignals()
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
                self.signals.cancelled.emit()
            else:
                self.signals.result.emit(value)
        except TaskCancelled:
            self.signals.cancelled.emit()
        except BaseException as exc:
            if self.is_cancelled():
                self.signals.cancelled.emit()
            elif isinstance(exc, Exception):
                traceback.print_exc()
                self.signals.error.emit(str(exc) or exc.__class__.__name__)
            else:
                # SystemExit / KeyboardInterrupt: never let them escape
                # QRunnable.run() — PyQt6 aborts the whole process.
                traceback.print_exc()
        finally:
            self.signals.finished.emit()

    def _report_progress(self, current: int, total: int, message: str) -> None:
        if self.is_cancelled():
            raise TaskCancelled
        self.signals.progress.emit(current, total, message)
