"""Release documents only after readers finish, without waiting in the GUI."""
from threading import Thread

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
