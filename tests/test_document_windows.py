"""Live-session edit/undo ownership and multi-window lifecycle regressions."""

import time

import fitz
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from core import viewer as viewer_module
from core.settings import SettingsManager


@pytest.fixture
def editor(tmp_path, monkeypatch, qt_application):
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION", "0")
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    monkeypatch.setattr(viewer_module.PDFViewer, "_confirm_discard_changes", lambda self: True)
    window = viewer_module.PDFViewer()
    window.resize(1100, 760)
    window.show()
    yield window
    manager = window.document_windows
    for w in manager.live_windows():
        w._printing = False
        w._confirm_discard_changes = lambda: True
        for task in list(w._tasks):
            task.cancel()
    deadline = time.monotonic() + 10
    while any(w._tasks for w in manager.live_windows()) and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.01)
    window.close()
    qt_application.processEvents()


def documents(window, tmp_path, count=3):
    sessions = []
    for i in range(count):
        path = tmp_path / f"document-{i}.pdf"
        with fitz.open() as doc:
            for page in range(3):
                doc.new_page().insert_text((72, 72), f"Document {i} page {page}")
            doc.save(path)
        sessions.append(window._open_in_new_tab_sync(str(path)))
    return sessions


def test_pair_focus_edit_and_undo_are_isolated(editor, tmp_path):
    first, second, third = documents(editor, tmp_path)
    editor.workspace.set_current_session(first)
    assert editor._split_documents(first, second)
    pair = editor.workspace._pair
    assert first.canvas.annotations_editable and second.canvas.annotations_editable
    assert first.canvas._doc is first.engine.document
    assert second.canvas._doc is second.engine.document
    pair.activate(second)
    assert editor.engine is second.engine
    assert editor.workspace.canvas is second.canvas
    editor._snapshot_before("Rotate")
    editor.engine.rotate_page(0, 90)
    assert second.engine.document[0].rotation == 90
    assert first.engine.document[0].rotation == 0
    editor._undo()
    assert second.engine.document[0].rotation == 0
    editor.workspace.set_current_session(third)
    assert editor.workspace.current_session() is third
    editor.workspace.set_current_session(second)
    assert editor.workspace.current_session() is second
    assert pair.isVisible()
    pair.swap()
    pair.toggle_orientation()
    assert pair.splitter.orientation() == Qt.Orientation.Vertical
    editor.workspace.end_pair()
    assert editor.workspace.current_session() is second
    assert first.tab_widget.parent() is not pair
    assert first.editable_split is None
    assert editor.workspace.session_count() == 3


def test_focus_changes_before_mouse_edit(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    editor._split_documents(first, second)
    viewport = second.canvas.viewport()
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(viewport.mapToGlobal(viewport.rect().center())),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, event)
    assert editor.engine is second.engine


def test_move_retains_dirty_state_undo_and_signal_owner(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    editor.workspace.set_current_session(second)
    second.canvas.set_page(1)
    second.canvas.set_zoom(1.4)
    editor._snapshot_before("Rotate")
    second.engine.rotate_page(0, 90)
    engine, undo, canvas = second.engine, second.undo_stack, second.canvas
    assert editor.document_windows.move(second)
    detached = second.window_owner
    assert detached is not editor
    assert second.engine is engine and second.undo_stack is undo and second.canvas is canvas
    assert second.engine.is_modified
    assert second.canvas.current_page == 1 and second.canvas.zoom_ratio == 1.4
    assert second not in editor._sessions and second in detached._sessions
    assert detached.engine is second.engine
    second.canvas.set_page(2)
    assert detached._page == 2
    assert editor._session is not second
    assert editor.document_windows.move(second, editor)
    assert second.window_owner is editor
    second.canvas.set_page(0)
    assert editor._page == 0
    editor._undo()
    assert second.engine.document[0].rotation == 0
    assert first.engine.document[0].rotation == 0


def test_move_one_paired_document_restores_other(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    editor._split_documents(first, second)
    assert editor.document_windows.move(second)
    assert editor.workspace._pair is None
    assert first.editable_split is None
    assert first in editor._sessions
    assert first.canvas._doc is first.engine.document


def test_busy_move_and_attach_failure_leave_source_intact(editor, tmp_path, monkeypatch):
    first, second, _ = documents(editor, tmp_path)
    editor._printing = True
    assert not editor.document_windows.move(first)
    editor._printing = False
    assert editor.document_windows.move(second)
    target = second.window_owner

    def fail(*args, **kwargs):
        raise RuntimeError("attach failed")

    monkeypatch.setattr(target.workspace, "attach_session", fail)
    assert not editor.document_windows.move(first, target)
    assert first.window_owner is editor
    assert first in editor._sessions and first in editor.workspace._sessions.values()
    assert first.engine.is_loaded()


def test_cancel_main_exit_keeps_all_windows_and_pair(editor, tmp_path):
    first, second, third = documents(editor, tmp_path)
    editor._split_documents(first, second)
    assert editor.document_windows.move(third)
    detached = third.window_owner
    detached._confirm_discard_changes = lambda: False
    assert not editor.close()
    assert editor.isVisible() and detached.isVisible()
    assert editor.workspace._pair is not None
    assert not editor.document_windows.pending_exit
    assert editor.isEnabled()
    detached._confirm_discard_changes = lambda: True


def test_close_secondary_does_not_close_main(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    detached = second.window_owner
    assert detached.close()
    assert editor.isVisible()
    assert editor.engine.is_loaded()
    assert first in editor._sessions


def test_external_duplicate_focuses_existing_window(editor, tmp_path):
    _, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    target = second.window_owner
    found = editor.document_windows.find_path(second.display_path)
    assert found == (target, second)
    editor._queued_open_paths.append((str(second.display_path), None, None, time.perf_counter()))
    editor._drain_open_queue()
    assert editor.document_windows.active_window() is target
    assert len(target._sessions) == 1


def test_pair_repeated_replacement_and_close_buttons(editor, tmp_path):
    first, second, third = documents(editor, tmp_path)
    app = QApplication.instance()
    for other in (second, third, second):
        editor._split_documents(first, other)
        editor.workspace.set_current_session(other)
        editor.workspace.end_pair()
        app.processEvents()
        for index in range(editor.workspace._tabs.count()):
            button = editor.workspace._tabs.tabBar().tabButton(
                index, editor.workspace._tabs.tabBar().ButtonPosition.RightSide
            )
            assert button is not None and button.isVisible()
    editor.close_document(second)
    assert editor.workspace.session_count() == 2


def test_pair_sync_uses_each_document_limits(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    editor._split_documents(first, second)
    editor._set_split_sync_page(True)
    editor._set_split_sync_zoom(True)
    first.canvas.set_page(2)
    first.canvas.set_zoom(1.3)
    assert second.canvas.current_page == 2
    assert second.page == 2
    assert second.canvas.zoom_ratio == 1.3
