"""Final worker result must not be lost beyond the periodic read chunk."""

import json
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QTimer

from composition.designer.process import Worker


def test_finished_drains_large_final_review_event_before_cleanup(qt_application, tmp_path):
    worker = Worker.__new__(Worker)
    QObject.__init__(worker)
    worker.events_file = tmp_path / "events.jsonl"
    worker.request_file = tmp_path / "request.json"
    worker.cancel_file = tmp_path / "cancel"
    worker.events_offset = 0
    worker.buffer = bytearray()
    worker.stderr = bytearray()
    worker.delivered = False
    worker.process = SimpleNamespace(readAllStandardOutput=lambda: b"", readAllStandardError=lambda: b"")
    worker.poll = QTimer(worker)
    payload = {"review": "x" * (3 * 1024 * 1024), "complete": True}
    worker.events_file.write_text(json.dumps({"event": "result", "result": payload}) + "\n", encoding="utf-8")
    results, errors, ended = [], [], []
    worker.resultReady.connect(results.append)
    worker.failed.connect(errors.append)
    worker.ended.connect(lambda: ended.append(True))
    worker._finished(0, None)
    assert results == [payload] and not errors and ended == [True]
    assert not worker.events_file.exists()
