"""Issue #18: queued opens own only their own activity, including early returns."""
from threading import Event

import fitz
from PyQt6.QtWidgets import QApplication

from tests.test_document_windows import documents
from tests.test_document_windows import editor as editor
from tests.test_open_performance import wait_until


def test_repeated_duplicate_open_focuses_once_without_ghost_activity(editor, tmp_path, monkeypatch):
    session = documents(editor, tmp_path, count=1)[0]
    original = session.engine.document
    session.engine.rotate_pages([0], 90)
    signals = []
    editor.task_bar.activityChanged.connect(signals.append)
    monkeypatch.setattr(editor, "_start_queued_pdf_open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("duplicate reloaded")))
    for _ in range(3):
        editor.queue_open_files([str(session.display_path)])
        wait_until(lambda: not editor._open_queue_scheduled)
        assert editor.task_bar.isHidden()
        assert editor.command_bar._work.text().endswith("Ready")
        assert editor.bottom_bar._status.text() == "Ready"
        assert editor.workspace.current_session() is session
        assert len(editor._sessions) == 1
        assert session.engine.document is original and session.engine.is_modified
    assert signals.count(False) == 3


def test_duplicate_queue_does_not_replace_another_running_activity(editor, tmp_path):
    session = documents(editor, tmp_path, count=1)[0]
    started, release = Event(), Event()
    def operation():
        started.set()
        assert release.wait(10)
    try:
        editor._run_task("Other work", operation)
        wait_until(started.is_set)
        editor.queue_open_files([str(session.display_path)])
        assert editor.task_bar._label.text() == "Other work"
        assert editor.command_bar._work.text().endswith("Other work")
        editor._queued_open_finished()
        assert not editor.task_bar.isHidden()
    finally:
        release.set()
        wait_until(lambda: not editor._tasks and not editor._open_queue_scheduled)
    assert editor.task_bar.isHidden()


def test_mixed_duplicate_new_queue_stays_active_until_actual_open_finishes(editor, tmp_path, monkeypatch):
    from core import viewer as viewer_module
    existing = documents(editor, tmp_path, count=1)[0]
    source = tmp_path / "new.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    prepare = viewer_module._prepare_pdf_engine
    started, release = Event(), Event()
    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)
    monkeypatch.setattr(viewer_module, "_prepare_pdf_engine", blocked)
    activity = []
    editor.task_bar.activityChanged.connect(activity.append)
    try:
        editor.queue_open_files([str(existing.display_path), str(source), str(existing.display_path)])
        wait_until(started.is_set)
        assert editor._open_queue_scheduled and not editor.task_bar.isHidden()
        assert False not in activity
    finally:
        release.set()
        wait_until(lambda: not editor._open_queue_scheduled and not editor._tasks)
    assert len(editor._sessions) == 2
    assert editor.workspace.current_session() is existing
    assert editor.task_bar.isHidden()
    assert activity.count(False) == 1


def test_empty_and_closed_target_queue_finish_idempotently(editor, tmp_path):
    from time import perf_counter

    from ui.document_session import DocumentSession
    target = DocumentSession()
    editor._queued_open_paths.append((str(tmp_path / "unused.pdf"), None, target, perf_counter()))
    editor._schedule_queued_open()
    wait_until(lambda: not editor._open_queue_scheduled)
    assert editor.task_bar.isHidden()
    activity = []
    editor.task_bar.activityChanged.connect(activity.append)
    editor._drain_open_queue()
    editor._queued_open_finished()
    QApplication.processEvents()
    assert editor.task_bar.isHidden() and not activity
    target.close()


def test_external_activity_without_a_function_task_is_not_overwritten(editor, tmp_path):
    session = documents(editor, tmp_path, count=1)[0]
    editor.task_bar.start("External validation")
    editor.queue_open_files([str(session.display_path)])
    assert editor.task_bar._label.text() == "External validation"
    editor._queued_open_finished()
    assert editor.task_bar._label.text() == "External validation"
    editor.task_bar.clear()
    wait_until(lambda: not editor._open_queue_scheduled)
    assert editor.task_bar.isHidden()


def test_load_same_file_does_not_prompt_discard_or_reload(editor, tmp_path, monkeypatch):
    session = documents(editor, tmp_path, count=1)[0]
    session.engine.rotate_pages([0], 90)
    original = session.engine.document
    monkeypatch.setattr(editor, "_confirm_discard_changes", lambda: (_ for _ in ()).throw(AssertionError("duplicate prompted discard")))
    monkeypatch.setattr(editor, "_start_queued_pdf_open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("duplicate reloaded")))
    called = []
    editor.load_file(str(session.display_path), on_open=called.append)
    wait_until(lambda: not editor._open_queue_scheduled)
    assert called == [session]
    assert session.engine.document is original and session.engine.is_modified
    assert editor.task_bar.isHidden()


def test_duplicate_in_detached_window_focuses_it_and_finishes_origin(editor, tmp_path):
    session = documents(editor, tmp_path, count=1)[0]
    assert editor.document_windows.move(session)
    detached = session.window_owner
    editor.queue_open_files([str(session.display_path)])
    wait_until(lambda: not editor._open_queue_scheduled)
    assert editor.document_windows.last_active is detached
    assert detached.workspace.current_session() is session
    assert editor.task_bar.isHidden()
    assert not editor._sessions and len(detached._sessions) == 1


def test_failed_open_keeps_error_and_clears_activity(editor, tmp_path):
    editor.queue_open_files([str(tmp_path / "missing.pdf")])
    wait_until(lambda: not editor._tasks and not editor._open_queue_scheduled)
    assert editor.task_bar.isHidden()
    assert editor.bottom_bar._status_full == "Error"
