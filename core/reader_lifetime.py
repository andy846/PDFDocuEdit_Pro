"""Release documents only after readers finish, without waiting in the GUI."""
from contextlib import contextmanager
from threading import Thread
from time import monotonic

from core.diagnostics import log_failure


class ReaderLease:
    """Keep a QRunnable alive while Qt may still be about to call run()."""
    def __init__(self, task):
        self.task = task

    def is_set(self):
        return self.task.done.is_set()

    def wait(self):
        return self.task.done.wait()


def after_readers(events, cleanup):
    events = tuple(events)
    def release():
        for event in events:
            event.wait()
        try:
            cleanup()
        except Exception:
            log_failure("Retired document cleanup failed")
    if all(event.is_set() for event in events):
        release()
    else:
        Thread(target=release, daemon=True, name="pdf-reader-retirement").start()


class ReaderBusyError(TimeoutError):
    """A live reader timed out; its document remains owned and unchanged."""


def wait_for_readers(events, timeout_ms=3000):
    """Await only owned leases, pumping Qt until completion or a real deadline."""
    events = tuple(events)
    if all(event.is_set() for event in events):
        return True
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    if QCoreApplication.instance() is None:
        deadline = monotonic() + max(0, timeout_ms) / 1000
        while not all(event.is_set() for event in events) and monotonic() < deadline:
            from time import sleep
            sleep(min(.01, max(0, deadline - monotonic())))
        return all(event.is_set() for event in events)
    loop, poll, deadline = QEventLoop(), QTimer(), QTimer()
    poll.setInterval(10)
    deadline.setSingleShot(True)
    def check():
        if all(event.is_set() for event in events):
            loop.quit()
    poll.timeout.connect(check)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(max(0, timeout_ms))
    try:
        loop.exec()
    finally:
        poll.stop()
        deadline.stop()
    return all(event.is_set() for event in events)


@contextmanager
def pause_readers(consumers):
    """Prevent new reads during a multi-consumer drain and document mutation."""
    consumers = tuple(consumers)
    for consumer in consumers:
        consumer._reader_pause_count = getattr(consumer, "_reader_pause_count", 0) + 1
    try:
        yield
    finally:
        for consumer in consumers:
            consumer._reader_pause_count -= 1
