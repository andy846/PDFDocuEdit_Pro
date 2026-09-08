"""GUI-owned printer lifecycle with one cancellable worker page in flight."""

from threading import Event

from PyQt6.QtCore import QObject, QThreadPool, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPainter
from PyQt6.QtPrintSupport import QPrinter

from core.printing import prepare_print_job, render_print_page
from core.tasks import FunctionTask, TaskCancelled


class PrintController(QObject):
    progress = pyqtSignal(str, int, int)
    file_finished = pyqtSignal(str, str, str)
    finished = pyqtSignal(int, int, int, bool)

    def __init__(self, jobs, printer_factory, settings_factory, *, parent=None,
                 thread_pool=None, should_cancel=None):
        super().__init__(parent)
        self.jobs = tuple(jobs)
        self.printer_factory = printer_factory
        self.settings_factory = settings_factory
        self.pool = thread_pool or QThreadPool.globalInstance()
        self.should_cancel = should_cancel
        self._cancel = Event()
        self._task = None
        self._outcome = None
        self._kind = ""
        self._index = -1
        self._page = 0
        self._prepared = None
        self._settings = None
        self._printer = None
        self._painter = None
        self._sent = self._failed = self._skipped = 0
        self._done = False
        self._started = False
        self._job_active = False

    def start(self):
        if self._started:
            raise RuntimeError("This print controller has already started.")
        self._started = True
        QTimer.singleShot(0, self._next_job)

    @pyqtSlot()
    def cancel(self):
        self._cancel.set()
        if self._task is not None:
            self._task.cancel()

    def _cancelled(self):
        if self.should_cancel and self.should_cancel():
            self.cancel()
        return self._cancel.is_set()

    def _submit(self, kind, function, *args):
        self._kind = kind
        self._outcome = None
        task = FunctionTask(function, *args, cancel_argument="is_cancelled")
        self._task = task
        task.signals.result.connect(self._result)
        task.signals.error.connect(self._error)
        task.signals.cancelled.connect(self._worker_cancelled)
        task.signals.finished.connect(self._worker_finished)
        self.pool.start(task)

    @pyqtSlot(object)
    def _result(self, result):
        self._outcome = ("result", result)

    @pyqtSlot(str)
    def _error(self, message):
        self._outcome = ("error", message)

    @pyqtSlot()
    def _worker_cancelled(self):
        self._outcome = ("cancelled", None)

    @pyqtSlot()
    def _worker_finished(self):
        self._task = None
        outcome, value = self._outcome or ("error", "Print worker ended without a result.")
        self._outcome = None
        if self._cancelled() or outcome == "cancelled":
            self._cancel.set()
            self._finish()
            return
        if outcome == "error":
            self._fail(value, skipped=self._kind == "prepare")
            return
        try:
            if self._kind == "prepare":
                self._prepared = value
                self._page = 0
                self._printer = self.printer_factory(self.jobs[self._index], value)
                if self._cancelled():
                    self._finish()
                    return
                self._settings = self.settings_factory(self._printer)
                # Do not start a spool job until the first page is ready.
                self._next_page()
            else:
                self._paint(value)
        except TaskCancelled:
            self._cancel.set()
            self._finish()
        except Exception as exc:
            self._fail(str(exc))

    @pyqtSlot()
    def _next_job(self):
        if self._done:
            return
        if self._cancelled():
            self._finish()
            return
        self._index += 1
        if self._index >= len(self.jobs):
            self._finish()
            return
        job = self.jobs[self._index]
        self._job_active = True
        self.progress.emit(job.key, 0, 0)
        self._submit("prepare", prepare_print_job, job)

    @pyqtSlot()
    def _next_page(self):
        if self._done:
            return
        if self._cancelled():
            self._finish()
            return
        if self._page >= len(self._prepared.pages):
            try:
                self._end_painter()
            except Exception as exc:
                self._fail(str(exc))
                return
            self._sent += 1
            self.file_finished.emit(self.jobs[self._index].key, "sent", "")
            self._release_job()
            QTimer.singleShot(0, self._next_job)
            return
        self._submit("render", render_print_page, self._prepared, self._page, self._settings)

    def _paint(self, rendered):
        if self._painter is None:
            self._painter = QPainter(self._printer)
            if not self._painter.isActive():
                raise RuntimeError("The selected printer could not start a print job.")
        elif not self._printer.newPage():
            raise RuntimeError("The printer could not create the next page.")
        image, x, y = rendered
        self._painter.drawImage(x, y, image)
        self._page += 1
        self.progress.emit(self.jobs[self._index].key, self._page, len(self._prepared.pages))
        QTimer.singleShot(0, self._next_page)

    def _end_painter(self, abort=False):
        painter, self._painter = self._painter, None
        if painter is not None and painter.isActive():
            if abort and self._printer.outputFormat() == QPrinter.OutputFormat.NativeFormat:
                self._printer.abort()
            if not painter.end() and not abort:
                raise RuntimeError("The printer could not finish the print job.")

    def _release_job(self):
        self._job_active = False
        self._prepared = self._settings = self._printer = None

    def _fail(self, message, skipped=False):
        self._end_painter(abort=True)
        if skipped:
            self._skipped += 1
        else:
            self._failed += 1
        self.file_finished.emit(self.jobs[self._index].key,
                                "skipped" if skipped else "failed", message)
        self._release_job()
        QTimer.singleShot(0, self._next_job)

    def _finish(self):
        if self._done:
            return
        self._done = True
        self._end_painter(abort=self._cancel.is_set())
        if self._cancel.is_set() and self._job_active:
            self.file_finished.emit(self.jobs[self._index].key, "cancelled", "")
        self._release_job()
        self.finished.emit(self._sent, self._failed, self._skipped, self._cancel.is_set())
