"""Parent shutdown must retire visible and hidden paused Deep Search jobs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QRunnable
from PyQt6.QtTest import QTest

from core.tasks import FunctionTask
from tests.test_deep_search_responsive import wait
from tests.test_document_windows import editor as editor
from ui.deep_search_dialog import OPEN_CURRENT
from ui.search_queries import SearchQueries


@pytest.fixture
def paused_search(editor, tmp_path, monkeypatch, qt_application, request):
    folder = tmp_path / "inputs"
    folder.mkdir()
    for name, pages in (("a.pdf", 1), ("b.pdf", 3)):
        with fitz.open() as doc:
            for _ in range(pages):
                doc.new_page().insert_text((50, 50), "needle")
            doc.save(folder / name)
    entered, release = Event(), Event()
    original = fitz.Page.get_text
    def controlled(page, *args, **kwargs):
        if page.parent.name.endswith("b.pdf") and page.number == 0:
            entered.set()
            assert release.wait(8)
        return original(page, *args, **kwargs)
    monkeypatch.setattr(fitz.Page, "get_text", controlled)
    owner = editor
    if getattr(request, "param", None) == "secondary":
        from core.viewer import PDFViewer
        owner = PDFViewer(pdf_only=True, document_windows=editor.document_windows)
        owner.show()
    owner._load_file_sync(str(folder / "a.pdf"))
    owner._deep_search()
    dialog = owner._deep_search_dialog
    dialog.folder.setText(str(folder))
    dialog.query.setText("needle")
    dialog._search()
    wait(qt_application, entered.is_set)
    dialog.pause_button.click()
    release.set()
    wait(qt_application, lambda: dialog._runtime.paused)
    dialog._poll_search()
    runtime, temporary = dialog._runtime, dialog._store.path.parent
    yield editor, dialog, runtime, temporary
    # Failure cleanup must also wake the baseline's orphaned paused worker.
    release.set()
    runtime.cancel()
    if not sip.isdeleted(dialog):
        dialog.close()
    wait(qt_application, lambda: not temporary.exists())


@pytest.mark.parametrize("visibility", ["visible", "hidden", "open_current", "closing"])
def test_main_close_cancels_and_waits_for_paused_deep_search(paused_search, qt_application, visibility):
    window, dialog, runtime, temporary = paused_search
    if visibility == "hidden":
        dialog.hide()
    elif visibility == "open_current":
        dialog.open_option.setCurrentIndex(dialog.open_option.findData(OPEN_CURRENT))
        dialog._open_selected(0)
        assert not dialog.isVisible()
    elif visibility == "closing":
        dialog.close()
    # No nested event processing between requesting close and checking ownership.
    assert not window.close(), "Main window accepted close while Deep Search still owned live workers"
    assert runtime.cancelled and not runtime.pause_requested
    assert not window._window_closed
    wait(qt_application, lambda: window._window_closed)
    wait(qt_application, lambda: not temporary.exists())


def test_cancelled_main_close_keeps_paused_search_resumable(paused_search, monkeypatch):
    window, dialog, runtime, temporary = paused_search
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: False)
    assert not window.close()
    assert not runtime.cancelled and runtime.paused
    assert not dialog._closing_search and temporary.exists()


def test_close_status_counts_deep_search_background_job(paused_search):
    window, _, _, _ = paused_search
    assert window._close_lifecycle.snapshot()["tasks"] >= 1


@pytest.mark.parametrize("paused_search", ["secondary"], indirect=True)
def test_main_exit_retires_hidden_paused_search_in_secondary_window(paused_search, qt_application):
    primary, dialog, runtime, temporary = paused_search
    dialog.hide()
    assert not primary.close()
    assert runtime.cancelled and not primary._window_closed
    wait(qt_application, lambda: primary._window_closed)
    wait(qt_application, lambda: not temporary.exists())


@pytest.mark.parametrize("route", ["visible", "hidden", "open_current", "child_and_main"])
def test_paused_search_process_exits_and_can_run_again(tmp_path, route):
    # A genuine Qt event loop and actual process return catch shutdown deadlocks
    # that a test fixture's emergency cancellation would otherwise conceal.
    for attempt in range(2):
        output = tmp_path / str(attempt)
        result = subprocess.run(
            [sys.executable, "-m", "tests.qa_deep_search_shutdown", str(output), route],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PDFDOCUEDIT_ENABLE_COMPOSITION": "0",
                 "PYTHONUTF8": "1", "QT_SCALE_FACTOR": str(attempt + 1)},
            capture_output=True, encoding="utf-8", timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads((output / "exit.json").read_text(encoding="utf-8")) == {
            "route": route, "cancelled": True, "finished": True, "temporary_removed": True}


@pytest.mark.parametrize("owner", ["query", "export", "native_tail"])
def test_close_waits_for_each_background_owner_without_blocking_gui(editor, qt_application, monkeypatch, owner):
    editor._deep_search()
    dialog = editor._deep_search_dialog
    temporary = dialog._store.path.parent
    entered, release = Event(), Event()
    def work(*args):
        entered.set()
        assert release.wait(8)
    if owner == "query":
        monkeypatch.setattr("ui.search_queries.read_search_query", work)
        dialog._queries = SearchQueries(dialog._store.path, dialog)
        dialog._queries.request({"kind": "header"})
    elif owner == "export":
        task = FunctionTask(work)
        dialog._export_task = task
        task.signals.finished.connect(dialog._export_finished)
        dialog._pool.start(task)
    else:
        class Tail(QRunnable):
            def run(self):
                work()
        task = Tail()
        task.setAutoDelete(False)
        dialog._search_pool.start(task)
    try:
        wait(qt_application, entered.is_set)
        # Force the long-wait path without waiting 3 seconds per case.
        editor._close_lifecycle.warning_after_ms = 0
        assert not editor.close()
        assert not editor.close()  # repeated close must reuse ownership
        status = editor._close_lifecycle.snapshot()
        assert status["visible"] and status["reason"] == "deep_search"
        assert status["tasks"] >= 1 and not editor._close_lifecycle._ready()
        QTest.qWait(60)
        assert not editor._window_closed and temporary.exists()
    finally:
        release.set()
    wait(qt_application, lambda: editor._window_closed)
    wait(qt_application, lambda: not temporary.exists())
