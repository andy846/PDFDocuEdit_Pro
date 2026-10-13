"""Controlled operation failures and reader stalls retain safe UI ownership."""
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from threading import Event, Timer
from time import monotonic

import fitz
import pytest
from PyQt6.QtCore import QRunnable, QThreadPool
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

from tests.test_document_windows import documents, wait_closed
from tests.test_document_windows import editor as editor
from tests.test_open_performance import wait_until
from ui.pdf_canvas import PdfCanvas
from ui.thumbnail_panel import ThumbnailPanel


class HeldReader(QRunnable):
    def __init__(self):
        super().__init__()
        self.setAutoDelete(False)
        self.done, self.started, self.release = Event(), Event(), Event()

    def run(self):
        self.started.set()
        self.release.wait(5)
        self.done.set()


@pytest.mark.parametrize("kind", ["canvas", "thumbnail"])
def test_reader_wait_has_deadline_and_retains_live_lease(qt_application, kind):
    reader = HeldReader()
    consumer = PdfCanvas() if kind == "canvas" else ThumbnailPanel(False)
    consumer._pool.start(reader)
    assert reader.started.wait(2)
    if kind == "canvas":
        consumer._render_jobs[(0, 0)] = reader
    else:
        consumer._tasks[0] = reader
    # The baseline cannot hang the test runner even though it ignores deadlines.
    release = Timer(.25, reader.release.set)
    release.start()
    try:
        started = monotonic()
        with pytest.raises(TimeoutError):
            if kind == "canvas":
                consumer.wait_for_renders(timeout_ms=25)
            else:
                consumer.quiesce_renders(timeout_ms=25)
        assert monotonic() - started < .2
        assert any(lease.task is reader for lease in consumer.reader_events())
        assert not reader.done.is_set()
    finally:
        reader.release.set()
        release.join()
        wait_until(reader.done.is_set)
        consumer._pool.waitForDone(2000)
        if kind == "canvas":
            consumer._render_jobs.clear()
        else:
            consumer._tasks.clear()
            consumer._retired_tasks.clear()
        consumer.close()


def test_shutdown_wait_keeps_custom_close_enabled_and_reader_document_alive(editor, tmp_path):
    session = documents(editor, tmp_path, count=1)[0]
    doc = session.engine.document
    reader = HeldReader()
    QThreadPool.globalInstance().start(reader)
    assert reader.started.wait(2)
    session.canvas._render_jobs[(session.canvas._generation, 999)] = reader
    try:
        assert not editor.close()
        assert editor.isEnabled()
        assert editor.command_bar._window_close.isEnabled()
        QTest.qWait(100)
        assert editor.isVisible() and not doc.is_closed
        editor.command_bar._window_close.click()
        assert not doc.is_closed
    finally:
        reader.release.set()
        wait_until(reader.done.is_set)
        wait_closed(editor)
    wait_until(lambda: doc.is_closed)


def test_partial_redaction_rollback_preserves_readers_and_safe_cause(editor, tmp_path, monkeypatch, caplog):
    from core import viewer as viewer_module
    session, other = documents(editor, tmp_path, count=2)
    editor.workspace.set_current_session(session)
    session.set_split(True)
    other.set_split(True)
    other.set_split_source(session)
    session.engine.rotate_pages([1], 90)
    with session.engine.mutation_transaction("Mark"):
        session.engine.document[0].add_redact_annot(fitz.Rect(60, 60, 150, 110))
        session.engine.mark_modified()
    from core.annotations import list_document_annotations
    list_document_annotations(session.engine.document)
    # MuPDF can serialize ID strings as hex or escaped literals. Force a
    # printable revision ID so this variant is deterministic, not random.
    session.engine.document.xref_set_key(-1, "ID", "[<00112233445566778899AABBCCDDEEFF><4142434445464748494A4B4C4D4E4F50>]")
    before = session.engine.document.tobytes(no_new_id=True)
    state = (session.engine.revision, session.engine.is_modified, session.undo_stack.undo_count)
    def fail(doc, *args, **kwargs):
        doc[0].apply_redactions()
        raise ValueError("PRIVATE_FIELD_VALUE_NEVER_LOG")
    monkeypatch.setattr(viewer_module, "apply_redaction_marks", fail)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    with caplog.at_level(logging.DEBUG, logger="pdfdocuedit"):
        editor._apply_redactions()
    # Thumbnail snapshot serialization updates only the trailer revision ID.
    # Preserve the first identity and every content/object byte in this comparison.
    def content_bytes(data):
        pdf_string = rb"(?:<[^>]*>|\((?:\\.|[^\\)])*\))"
        pattern = rb"(/ID\s*\[" + pdf_string + rb"\s*)" + pdf_string + rb"(\s*\])"
        normalized, matches = re.subn(pattern, rb"\1<revision>\2", data)
        assert matches == 1
        return normalized
    assert content_bytes(session.engine.document.tobytes(no_new_id=True)) == content_bytes(before)
    assert state == (session.engine.revision, session.engine.is_modified, session.undo_stack.undo_count)
    assert all(c._doc is session.engine.document for c in editor._document_canvases(session))
    assert "ValueError" in caplog.text and "PRIVATE_FIELD_VALUE_NEVER_LOG" not in caplog.text
    editor.workspace.set_current_session(other)
    editor.workspace.set_current_session(session)
    editor.goto_page(1)
    with editor._mutation_transaction("Retry") as allowed:
        assert allowed
        session.engine.rotate_pages([0], 90)
    session.undo_stack.clear()
    session.engine._is_modified = False
    editor.command_bar._window_close.click()
    wait_closed(editor)


@pytest.mark.parametrize("stage", ["none", "result", "finished"])
def test_callback_failure_does_not_cross_qt_slot_or_strand_activity(tmp_path, stage):
    script = r"""
import os,time
from PyQt6.QtWidgets import QApplication
from core import viewer as v
from core.settings import SettingsManager
app=QApplication([])
v.SettingsManager=lambda:SettingsManager(os.environ['PDFDOCUEDIT_TEST_SETTINGS'])
w=v.PDFViewer();w.show()
def broken(*args): raise ValueError('PRIVATE_CALLBACK_PAYLOAD')
stage=os.environ['PDFDOCUEDIT_TEST_STAGE']
kwargs={'on_result':broken} if stage=='result' else {'on_finished':broken} if stage=='finished' else {}
w._run_task('Controlled callback',lambda:'complete',**kwargs)
end=time.monotonic()+5
while w._tasks and time.monotonic()<end: app.processEvents();time.sleep(.01)
app.processEvents()
assert not w._tasks and w.task_bar.isHidden()
assert w.isEnabled() and w.command_bar._window_close.isEnabled()
assert w.bottom_bar._status_full==('Ready' if stage=='none' else 'Error')
w.close();app.processEvents()
assert not w.isVisible()
# Match fixture teardown: finish native runnable return and destroy owned
# widgets while QApplication, proxy styles and Python signal slots are alive.
from PyQt6.QtCore import QCoreApplication,QEvent,QThreadPool
assert QThreadPool.globalInstance().waitForDone(2000)
w.deleteLater()
app.processEvents()
QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PDFDOCUEDIT_ENABLE_COMPOSITION": "0", "PDFDOCUEDIT_TEST_SETTINGS": str(tmp_path / "settings.json"), "PDFDOCUEDIT_TEST_STAGE": stage}
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "PRIVATE_CALLBACK_PAYLOAD" not in result.stderr


def test_cleanup_exception_keeps_close_retryable_and_retries_unretired_session(editor, tmp_path, monkeypatch):
    session = documents(editor, tmp_path, count=1)[0]
    original = session.close
    calls = []
    def close_once_failed():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("PRIVATE_CLEANUP_DETAILS")
        original()
    monkeypatch.setattr(session, "close", close_once_failed)
    try:
        assert not editor.close()
        assert editor.isVisible() and editor.command_bar._window_close.isEnabled()
        editor.command_bar._window_close.click()
        wait_closed(editor)
        assert len(calls) == 2
        wait_until(lambda: not session.engine.is_loaded())
    finally:
        if session.engine.is_loaded():
            original()


def test_mutation_reader_timeout_applies_no_edit_and_restores_controls(editor, tmp_path, monkeypatch):
    session = documents(editor, tmp_path, count=1)[0]
    doc, revision = session.engine.document, session.engine.revision
    reader = HeldReader()
    QThreadPool.globalInstance().start(reader)
    assert reader.started.wait(2)
    session.canvas._render_jobs[(session.canvas._generation, 999)] = reader
    wait = session.canvas.wait_for_renders
    monkeypatch.setattr(session.canvas, "wait_for_renders", lambda: wait(timeout_ms=25))
    try:
        with pytest.raises(TimeoutError):
            with editor._mutation_transaction("Cannot edit busy document"):
                pytest.fail("mutation began with a live reader")
        assert session.engine.document is doc and session.engine.revision == revision
        assert not editor._mutation_controller.active
        assert session.canvas._reader_pause_count == 0
        assert editor.workspace.isEnabled() and editor.command_bar._window_close.isEnabled()
    finally:
        reader.release.set()
        wait_until(reader.done.is_set)


def test_shutdown_deadline_reports_wait_without_reentering_close_until_reader_finishes(editor, tmp_path, monkeypatch, caplog):
    session = documents(editor, tmp_path, count=1)[0]
    reader = HeldReader()
    QThreadPool.globalInstance().start(reader)
    assert reader.started.wait(2)
    session.canvas._render_jobs[(session.canvas._generation, 999)] = reader
    editor._close_lifecycle.warning_after_ms = 20
    closes = []
    original = editor._close_event_checked
    def closing(event):
        closes.append(True)
        original(event)
    monkeypatch.setattr(editor, "_close_event_checked", closing)
    try:
        with caplog.at_level(logging.INFO, logger="pdfdocuedit"):
            editor.close()
            wait_until(lambda: editor._close_lifecycle.warned)
            count = len(closes)
            QTest.qWait(600)
            assert len(closes) == count
            assert "close.deadline" in caplog.text
            assert editor.isVisible() and editor.command_bar._window_close.isEnabled()
    finally:
        reader.release.set()
        wait_until(reader.done.is_set)
        wait_closed(editor)


def test_failed_worker_leaves_no_busy_state_and_can_close(editor, caplog):
    def fail():
        raise ValueError("PRIVATE_WORKER_VALUE")
    with caplog.at_level(logging.INFO, logger="pdfdocuedit"):
        editor._run_task("Controlled failure", fail)
        wait_until(lambda: not editor._tasks)
    assert editor.task_bar.isHidden() and not editor.task_bar.active
    assert editor.bottom_bar._status_full == "Error"
    assert "ValueError" in caplog.text and "worker.finished" in caplog.text
    assert "PRIVATE_WORKER_VALUE" not in caplog.text
    editor.command_bar._window_close.click()
    wait_closed(editor)


def test_failed_history_install_retires_replacement_after_readers(editor, tmp_path, monkeypatch):
    session, other = documents(editor, tmp_path, count=2)
    editor.workspace.set_current_session(session)
    session.set_split(True)
    other.set_split(True)
    other.set_split_source(session)
    previous = session.engine
    snapshot = tmp_path / "history.pdf"
    snapshot.write_bytes(previous.document.tobytes(no_new_id=True))
    reader = HeldReader()
    replacements = []
    complete = editor._complete_pdf_open
    wait = session.canvas.wait_for_renders
    def install_then_fail(*args, **kwargs):
        assert complete(*args, **kwargs)
        replacements.append(session.engine)
        QThreadPool.globalInstance().start(reader)
        assert reader.started.wait(2)
        session.canvas._render_jobs[(session.canvas._generation, 999)] = reader
        monkeypatch.setattr(session.canvas, "wait_for_renders", lambda: wait(timeout_ms=25))
        raise ValueError("PRIVATE_HISTORY_INSTALL_PAYLOAD")
    monkeypatch.setattr(editor, "_complete_pdf_open", install_then_fail)
    try:
        with pytest.raises(Exception) as error:
            editor._restore_history_snapshot(session, snapshot, modified=False)
        assert replacements and replacements[0].is_loaded(), "replacement closed with a live reader"
        assert isinstance(error.value, ValueError)
        assert session.engine is previous and previous.is_loaded()
        assert all(c._doc is previous.document for c in editor._document_canvases(session))
        assert not reader.done.is_set()
    finally:
        reader.release.set()
        wait_until(reader.done.is_set)
    wait_until(lambda: not replacements[0].is_loaded())


def test_failed_exit_preflight_revokes_partial_approvals_and_keeps_work_enabled(editor, tmp_path, monkeypatch):
    first, second = documents(editor, tmp_path, count=2)
    manager = editor.document_windows
    assert manager.move(second)
    child = second.window_owner
    def failed_confirmation():
        raise OSError("PRIVATE_SAVE_PROMPT_DETAILS")
    monkeypatch.setattr(child, "_confirm_discard_changes", failed_confirmation)
    assert not editor.close()
    assert not manager.pending_exit
    assert all(not w._window_exit_approved for w in manager.live_windows())
    assert editor.workspace.isEnabled() and child.workspace.isEnabled()
    assert editor.command_bar._window_close.isEnabled()
    # The first window must be asked again; no stale approval survives failure.
    confirmations = []
    monkeypatch.setattr(editor, "_confirm_discard_changes", lambda: confirmations.append(True) or True)
    monkeypatch.setattr(child, "_confirm_discard_changes", lambda: True)
    editor.close()
    wait_closed(editor)
    assert confirmations
