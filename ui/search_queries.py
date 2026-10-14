"""Single-flight background result queries, with superseded request rejection."""
from collections import deque

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal

from core.deep_search_runtime import read_search_query
from core.tasks import FunctionTask


class SearchQueries(QObject):
    ready = pyqtSignal(object)
    failed = pyqtSignal(object)
    discarded = pyqtSignal(object)
    idle = pyqtSignal()

    def __init__(self, path, parent):
        super().__init__(parent)
        self.path = path
        self.queue = deque()
        self.task = None
        self.closed = False

    def request(self, value):
        if self.closed:
            return
        keep = deque()
        for item in self.queue:
            superseded = (item["kind"] == value["kind"] and value["kind"] in ("header", "preview"))
            superseded |= value["kind"] == "header" and item["kind"] == "page"
            if superseded:
                self.discarded.emit(item)
            else:
                keep.append(item)
        self.queue = keep
        self.queue.appendleft(value)
        pages = [item for item in self.queue if item["kind"] == "page"]
        for item in pages[4:]:
            self.queue.remove(item)
            self.discarded.emit(item)
        self._next()

    def _next(self):
        if self.task is not None or self.closed:
            return
        if not self.queue:
            self.idle.emit()
            return
        request = self.queue.popleft()
        task = FunctionTask(read_search_query, self.path, request)
        self.task = task
        task.signals.result.connect(self._result)
        task.signals.error.connect(lambda message, r=request: self._error(r, message))
        task.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(task)

    def _result(self, result):
        if not self.closed:
            self.ready.emit(result)

    def _error(self, request, message):
        if not self.closed:
            self.failed.emit({"request": request, "message": message})

    def _finished(self):
        self.task = None
        if self.closed:
            self.idle.emit()
        else:
            self._next()

    def close(self):
        self.closed = True
        self.queue.clear()
        if self.task is not None:
            self.task.cancel()
