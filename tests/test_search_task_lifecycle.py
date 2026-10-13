"""Search replacement uses real workers; cancelled tasks stay owned until finish."""
import gc
import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import fitz
import pytest
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from tests.composition.test_workspace import wait_until
from tests.test_search_page_actions import window_for


def search_window(tmp_path, monkeypatch):
    path = tmp_path / "large.pdf"
    with fitz.open() as document:
        for _ in range(51):
            document.new_page()
        document.save(path)
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(path))
    return window


@pytest.mark.parametrize("ending", ["replace", "change", "close", "cancel", "shutdown"])
def test_search_replacement_waits_and_ignores_stale_callbacks(tmp_path, monkeypatch, ending):
    window = search_window(tmp_path, monkeypatch)
    session = window._session
    started, release = Event(), Event()
    queries, progress, errors, results = [], [], [], []

    def search(path, query, **kwargs):
        queries.append(query)
        if query == "A":
            started.set()
            assert release.wait(10)
        return []

    monkeypatch.setattr(viewer_module, "search_pdf_file", search)
    monkeypatch.setattr(session.search_panel, "show_progress", lambda *args: progress.append(args))
    monkeypatch.setattr(session.search_panel, "show_error", errors.append)
    monkeypatch.setattr(window, "_task_failed", lambda *args: errors.append(args))
    monkeypatch.setattr(window, "_finish_search", lambda *args: results.append(args[2]))
    try:
        window._run_search("A")
        wait_until(started.is_set)
        old = window._search_tasks[id(session)]
        window._run_search("B")
        window._run_search("C")
        assert old in window._tasks
        assert old.is_cancelled()
        assert queries == ["A"]
        before = len(progress)
        old.signals.progress.emit(1, 51, "stale")
        old.signals.result.emit([])
        old.signals.error.emit("stale error")
        QApplication.processEvents()
        assert len(progress) == before
        assert not errors and not results
        if ending == "change":
            # The pending request captures the old document revision.
            session.engine._revision += 1
        elif ending == "close":
            window.close_document(session)
        elif ending == "cancel":
            window._cancel_tasks()
        elif ending == "shutdown":
            window._closing = True
        release.set()
        wait_until(lambda: not window._tasks)
        assert queries == (["A", "C"] if ending == "replace" else ["A"])
        assert results == (["C"] if ending == "replace" else [])
        assert not window._search_tasks and not window._pending_searches
        if ending == "change":
            assert "Document changed" in errors[0]
    finally:
        release.set()
        wait_until(lambda: not window._tasks)
        window._closing = False
        window.close()


def test_cancelled_result_discards_resource_but_committed_batch_is_delivered(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    release, started = Event(), Event()
    discarded, batches = [], []

    def operation():
        started.set()
        assert release.wait(10)
        return "worker result"

    try:
        task = window._run_task("Test", operation, on_discard=discarded.append, on_batch=batches.append)
        wait_until(started.is_set)
        task.cancel()
        task.signals.result.emit("queued resource")
        task.signals.batch.emit("committed file")
        QApplication.processEvents()
        assert discarded == ["queued resource"]
        assert batches == ["committed file"]
        release.set()
        wait_until(lambda: not window._tasks)
        assert discarded == ["queued resource", "worker result"]
    finally:
        release.set()
        wait_until(lambda: not window._tasks)
        window.close()


def _stress(tmp_path):
    """Keep native Qt aborts outside the main pytest process."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        window = search_window(tmp_path, monkeypatch)
        try:
            for _ in range(25):
                started, release = Event(), Event()
                calls = []

                def search(path, query, *, calls=calls, started=started, release=release, **kwargs):
                    calls.append(query)
                    if query == "A":
                        started.set()
                        assert release.wait(10)
                    return []

                monkeypatch.setattr(viewer_module, "search_pdf_file", search)
                window._run_search("A")
                wait_until(started.is_set)
                window._run_search("B")
                window._run_search("C")
                gc.collect()
                release.set()
                wait_until(lambda: not window._tasks)
                gc.collect()
                QApplication.processEvents()
                assert calls == ["A", "C"]
        finally:
            release.set()
            wait_until(lambda: not window._tasks)
            window.close()


def test_search_native_lifecycle_stress_in_subprocess(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c",
         "from pathlib import Path; import sys; "
         "from tests.test_search_task_lifecycle import _stress; _stress(Path(sys.argv[1]))",
         str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
