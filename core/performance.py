"""Lightweight, path-free performance spans for production diagnostics."""
import json
import logging
from contextlib import contextmanager
from time import perf_counter
from uuid import uuid4

LARGE_DOCUMENT_PAGES = 1000

class PerformanceTrace:
    def __init__(self, operation, started=None):
        self.operation = operation
        self.started = perf_counter() if started is None else started
        self.values = {}
        self.trace_id = uuid4().hex[:12]

    @contextmanager
    def span(self, name):
        start = perf_counter()
        try:
            yield
        finally:
            self.values[name] = round((perf_counter() - start) * 1000, 3)

    def mark(self, name):
        self.values[name] = round((perf_counter() - self.started) * 1000, 3)

    def report(self, event):
        logging.getLogger("pdfdocuedit").info(
            "PERF %s: %s", self.operation,
            json.dumps(dict(self.values, event=event, trace_id=self.trace_id, units="ms"), sort_keys=True),
        )
