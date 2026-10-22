"""Closing a document must retire its owned history, never unrelated files."""
from threading import Event

import fitz
import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMessageBox

from core import viewer as viewer_module
from tests.test_document_windows import editor as editor
from tests.test_document_windows import wait_closed
from tests.test_open_performance import wait_until
from tests.test_watermark_close_reopen import choose_unsaved
from ui.document_session import DocumentSession
from updates.protocol import digest_file

CONFIRM_DISCARD = viewer_module.PDFViewer._confirm_discard_changes


def make_source(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Synthetic owned history")
        document.save(path)
    return path


def edit(session):
    with session.engine.mutation_transaction("Rotate"):
        session.engine.rotate_page(0, 90)


def history_paths(session):
    return [item.path for item in [*session.undo_stack._undo, *session.undo_stack._redo]]


@pytest.fixture
def isolated_temp(tmp_path, monkeypatch):
    root = tmp_path / "owned-temp"
    root.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(root))
    return root


@pytest.fixture
def session(qt_application, isolated_temp, tmp_path):
    item = DocumentSession(animations_enabled=False)
    item.engine.open(make_source(tmp_path / "source.pdf"))
    yield item
    item.undo_stack.clear()
    item.close()
    if item.engine.is_loaded():
        item.engine.close()
    for widget in (item.tab_widget,):
        widget.deleteLater()
    item.deleteLater()


def test_session_close_removes_undo_and_redo_on_ui_thread(session):
    edit(session)
    session.undo_stack.push_redo(str(session.engine.temp_path), "Previous redo")
    paths = history_paths(session)
    assert len(paths) == 2 and all(path.exists() for path in paths)
    signals = []
    session.undo_stack.changed.connect(lambda: signals.append(QThread.currentThread() == session.thread()))
    session.close()
    assert all(not path.exists() for path in paths)
    assert session.undo_stack.undo_count == session.undo_stack.redo_count == 0
    assert signals == [True]
    session.close()
    assert signals == [True]


def test_close_during_history_restore_keeps_document_and_history(session):
    edit(session)
    paths = history_paths(session)
    document = session.engine.document
    def apply(path, modified):
        with pytest.raises(RuntimeError, match="History cannot change"):
            session.close()
        assert session.engine.document is document and not document.is_closed
        return False
    assert not session.undo_stack.restore("undo", b"unused inverse", modified=True, apply=apply)
    assert history_paths(session) == paths and all(path.exists() for path in paths)


def test_close_during_mutation_preserves_history_and_allows_later_retirement(session):
    from core.pdf_engine import PdfEngineError
    edit(session)
    paths = history_paths(session)
    document = session.engine.document
    with session.engine.mutation_transaction("In progress"):
        with pytest.raises(PdfEngineError, match="inside a mutation transaction"):
            session.close()
        assert not getattr(session, "_retirement_started", False)
        assert session.engine.document is document and not document.is_closed
        assert all(path.exists() for path in paths)
    session.close()
    assert document.is_closed and all(not path.exists() for path in paths)


def test_history_cleanup_does_not_release_live_readers(session, monkeypatch):
    edit(session)
    paths = history_paths(session)
    document = session.engine.document
    working = session.engine.temp_path
    thumbnail = working.parent / "owned-thumbnail.pdf"
    thumbnail.write_bytes(working.read_bytes())
    session._thumbnail_snapshot = str(thumbnail)
    done = Event()
    monkeypatch.setattr(session.canvas, "reader_events", lambda: [done])
    try:
        session.close()
        assert not document.is_closed and working.exists() and thumbnail.exists()
        assert all(not path.exists() for path in paths)
    finally:
        done.set()
    wait_until(lambda: document.is_closed and not working.exists() and not thumbnail.exists())


def test_locked_history_file_logs_failure_without_breaking_close(session, monkeypatch, caplog):
    from pathlib import Path
    edit(session)
    blocked = history_paths(session)[0]
    unlink = Path.unlink
    def deny_owned(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("Synthetic locked history file")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny_owned)
    session.close()
    assert blocked.exists() and not session.engine.is_loaded()
    assert "Cannot remove undo snapshot" in caplog.text


@pytest.mark.parametrize("scope", ["tab", "window"])
@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Save,
                                   QMessageBox.StandardButton.Discard,
                                   QMessageBox.StandardButton.Cancel])
def test_real_close_decision_controls_history(editor, isolated_temp, tmp_path, monkeypatch, scope, answer):
    source = make_source(tmp_path / "decision.pdf")
    before = digest_file(source)
    item = editor._open_in_new_tab_sync(str(source))
    edit(item)
    paths = history_paths(item)
    monkeypatch.setattr(editor, "_confirm_discard_changes", lambda: CONFIRM_DISCARD(editor))
    prompts = choose_unsaved(monkeypatch, answer)
    if scope == "tab":
        editor.close_document(item)
    else:
        editor.close()
    assert prompts == [True]
    if answer == QMessageBox.StandardButton.Cancel:
        assert item.engine.is_loaded() and all(path.exists() for path in paths)
        assert editor._undo() and editor._redo()
        assert item.engine.document[0].rotation == 90
        assert digest_file(source) == before
    else:
        assert all(not path.exists() for path in paths)
        if scope == "window":
            wait_closed(editor)
        assert (digest_file(source) != before) == (answer == QMessageBox.StandardButton.Save)


def test_closing_one_tab_preserves_other_history(editor, isolated_temp, tmp_path):
    first = editor._open_in_new_tab_sync(str(make_source(tmp_path / "first.pdf")))
    edit(first)
    second = editor._open_in_new_tab_sync(str(make_source(tmp_path / "second.pdf")))
    edit(second)
    first_paths, second_paths = history_paths(first), history_paths(second)
    editor.close_document(first)
    assert all(not path.exists() for path in first_paths)
    assert all(path.exists() for path in second_paths)
    assert editor._undo() and second.engine.document[0].rotation == 0


def test_fifty_open_edit_close_cycles_do_not_accumulate_pdfs(qt_application, isolated_temp, tmp_path):
    source = make_source(tmp_path / "repeat.pdf")
    before = digest_file(source)
    unrelated = isolated_temp / "unrelated.pdf"
    unrelated.write_bytes(source.read_bytes())
    baseline = {path for path in isolated_temp.rglob("*.pdf")}
    for _ in range(50):
        item = DocumentSession(animations_enabled=False)
        item.engine.open(source)
        edit(item)
        item.close()
        assert set(isolated_temp.rglob("*.pdf")) == baseline
        item.tab_widget.deleteLater()
        item.deleteLater()
        qt_application.processEvents()
    assert digest_file(source) == before and unrelated.exists()
