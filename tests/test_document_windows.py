"""Live-session edit/undo ownership and multi-window lifecycle regressions."""

import time

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt
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
    wait_closed(window)
    qt_application.processEvents()
    # A QApplication spans the module. Dispose this fixture's retired Qt
    # roots rather than leaving every closed widget in global QSS repolish.
    for owned in qt_application.topLevelWidgets():
        if isinstance(owned, viewer_module.PDFViewer) and getattr(owned, "document_windows", None) is manager:
            owned.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_closed(window):
    deadline = time.monotonic() + 10
    while not sip.isdeleted(window) and window.isVisible() and time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.01)
    assert sip.isdeleted(window) or not window.isVisible()


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
    QApplication.instance().processEvents()
    assert first.tab_widget.isVisible() and second.tab_widget.isVisible()
    assert first.canvas.isVisible() and second.canvas.isVisible()
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
    detached.close()
    wait_closed(detached)
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


def test_locked_secondary_cannot_move_and_unlock_restores(editor, tmp_path):
    _, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    child = second.window_owner
    editor.document_windows.set_locked(True)
    assert not child.isEnabled()
    assert not editor.document_windows.move(second, editor)
    editor.document_windows.set_locked(False)
    assert child.isEnabled()
    assert editor.document_windows.move(second, editor)


def test_cancel_drag_keeps_session_in_original_window(editor, tmp_path, monkeypatch):
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QKeyEvent

    from ui import document_windows as module

    first, _, _ = documents(editor, tmp_path)
    manager = editor.document_windows

    class CancelDrag:
        def __init__(self, parent):
            pass

        def setMimeData(self, mime):
            pass

        def exec(self, action):
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(editor, event)
            return Qt.DropAction.IgnoreAction

        def deleteLater(self):
            pass

    monkeypatch.setattr(module, "QDrag", CancelDrag)
    monkeypatch.setattr(
        module.QCursor, "pos", lambda: editor.frameGeometry().bottomRight() + QPoint(100, 100)
    )
    manager.start_drag(first, editor.workspace._tabs.tabBar())
    assert first.window_owner is editor
    assert len(manager.live_windows()) == 1
    assert manager._drag_session is None


def test_drop_authenticated_live_tab_into_existing_window(editor, tmp_path):
    from PyQt6.QtCore import QMimeData
    from PyQt6.QtGui import QDropEvent

    from ui.document_windows import TAB_MIME

    first, second, _ = documents(editor, tmp_path)
    manager = editor.document_windows
    assert manager.move(second)
    child = second.window_owner
    manager._drag_session, manager._drag_token = first, "local-test-token"
    mime = QMimeData()
    mime.setData(TAB_MIME, b"local-test-token")
    event = QDropEvent(
        QPointF(2, 2),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert manager.eventFilter(child.workspace._tabs.tabBar(), event)
    assert event.isAccepted()
    assert first.window_owner is child
    manager._drag_session = manager._drag_token = None


def test_pair_with_designer_mode_keeps_documents_on_return(editor, tmp_path, monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from ui.workspace_mode_controller import WorkspaceModeController

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)

    # The normal primary window has the mode controller; secondary windows do not.
    controller = WorkspaceModeController(editor, editor.centralWidget().layout())
    editor._mode_controller = controller
    first, second, _ = documents(editor, tmp_path)
    editor._split_documents(first, second)
    controller.request_mode("designer")
    controller.request_mode("pdf")
    QApplication.instance().processEvents()
    assert editor.workspace._pair is not None
    assert first.engine.is_loaded() and second.engine.is_loaded()
    assert editor.document_windows.move(second)
    child = second.window_owner
    assert not hasattr(child, "_mode_controller")
    editor.close()
    wait_closed(editor)
    assert sip.isdeleted(child) or not child.isVisible()


def test_save_action_writes_only_active_pane_and_moved_document(editor, tmp_path):
    first, second, _ = documents(editor, tmp_path)
    editor._split_documents(first, second)
    editor.workspace._pair.activate(second)
    editor._snapshot_before("Rotate second PDF")
    second.engine.rotate_page(0, 90)
    editor.save_action.trigger()
    with fitz.open(first.display_path) as original:
        assert original[0].rotation == 0
    with fitz.open(second.display_path) as saved:
        assert saved[0].rotation == 90
    assert editor.document_windows.move(second)
    child = second.window_owner
    child._snapshot_before("Rotate moved PDF")
    second.engine.rotate_page(0, 90)
    child.save_action.trigger()
    with fitz.open(second.display_path) as saved:
        assert saved[0].rotation == 180
    with fitz.open(first.display_path) as original:
        assert original[0].rotation == 0


def test_no_new_documents_during_approved_exit(editor, tmp_path):
    first, _, _ = documents(editor, tmp_path)
    editor.document_windows.pending_exit = True
    editor.queue_open_files([str(first.display_path)])
    assert not editor._queued_open_paths
    editor.document_windows.pending_exit = False


def test_external_route_uses_last_active_pdf_window(editor, tmp_path, monkeypatch):
    from main import route_open_files
    _, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    child = second.window_owner
    requests = []
    monkeypatch.setattr(child, "queue_open_files", lambda paths: requests.extend(paths))
    route_open_files(editor, [str(tmp_path / "new.pdf")])
    assert requests == [str(tmp_path / "new.pdf")]


def test_reapplying_unchanged_theme_does_not_repolish_application(editor, monkeypatch):
    app = QApplication.instance()
    original = app.setStyleSheet
    changes = []

    def capture(style):
        changes.append(style)
        original(style)

    monkeypatch.setattr(app, "setStyleSheet", capture)
    before = app.styleSheet()
    editor.apply_theme(editor.settings.get_theme())
    assert app.styleSheet() == before
    assert changes == []


def test_shared_theme_change_updates_global_style_once(editor, tmp_path, monkeypatch):
    from styles.components import global_style

    editor._theme_changed("light")
    _, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    child = second.window_owner
    app = QApplication.instance()
    original = app.setStyleSheet
    changes = []

    def capture(style):
        changes.append(style)
        original(style)

    monkeypatch.setattr(app, "setStyleSheet", capture)
    editor._theme_changed("dark")
    assert changes == [global_style()]
    assert app.styleSheet() == global_style()
    assert child.palette().color(child.backgroundRole()) == editor.palette().color(editor.backgroundRole())
    assert editor.isVisible() and child.isVisible()


def test_closed_secondary_releases_qt_widgets_after_safe_cleanup(editor, tmp_path):
    _, second, _ = documents(editor, tmp_path)
    assert editor.document_windows.move(second)
    child = second.window_owner
    child.close()
    wait_closed(child)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(child)
    assert editor.isVisible()
    assert editor.document_windows.live_windows() == [editor]


def sized_documents(window, tmp_path):
    sessions = []
    for name, sizes in (
        ("a4", [(595, 842)]),
        ("mixed", [(842, 1191), (432, 612)]),
    ):
        path = tmp_path / f"{name}.pdf"
        with fitz.open() as doc:
            for width, height in sizes:
                doc.new_page(width=width, height=height)
            doc.save(path)
        sessions.append(window._open_in_new_tab_sync(str(path)))
    return sessions


def assert_active_page_size(window, session):
    assert window._session is window.workspace.current_session() is session
    width, height = session.engine.get_page_size(session.page)
    expected = f"{width * 25.4 / 72:.1f} × {height * 25.4 / 72:.1f} mm"
    assert window.bottom_bar._size.text() == expected
    assert window.bottom_bar._current_page == session.page


def test_page_size_follows_tab_activation_without_navigation(editor, tmp_path):
    first, second = sized_documents(editor, tmp_path)
    assert_active_page_size(editor, second)
    for session in (first, second, first, second, first):
        editor.workspace.set_current_session(session)
        assert_active_page_size(editor, session)


def test_page_size_restores_mixed_page_and_ignores_inactive_navigation(editor, tmp_path):
    first, second = sized_documents(editor, tmp_path)
    editor.goto_page(1)
    assert second.page == 1
    assert_active_page_size(editor, second)
    editor.workspace.set_current_session(first)
    assert_active_page_size(editor, first)
    second.canvas.set_page(0)
    assert second.page == 0
    assert_active_page_size(editor, first)
    second.canvas.set_page(1)
    assert_active_page_size(editor, first)
    editor.workspace.set_current_session(second)
    assert second.page == 1
    assert_active_page_size(editor, second)
    editor.goto_page(0)
    assert_active_page_size(editor, second)


def test_page_size_refreshes_remaining_tab_and_clears_last_close(editor, tmp_path):
    first, second = sized_documents(editor, tmp_path)
    assert_active_page_size(editor, second)
    editor.close_document(second)
    assert_active_page_size(editor, first)
    editor.close_document(first)
    assert editor.workspace.current_session() is None
    assert editor.bottom_bar._size.text() == ""


def test_page_size_clears_unloaded_placeholder_and_restores_loaded_tab(editor, tmp_path):
    first, _ = sized_documents(editor, tmp_path)
    placeholder = editor._create_session()
    assert editor._session is placeholder
    assert not placeholder.engine.is_loaded()
    assert editor.bottom_bar._size.text() == ""
    editor.workspace.set_current_session(first)
    assert_active_page_size(editor, first)
    editor.workspace.set_current_session(placeholder)
    assert editor.bottom_bar._size.text() == ""


def test_page_size_follows_split_focus_and_restores_after_split(editor, tmp_path):
    first, second = sized_documents(editor, tmp_path)
    editor.goto_page(1)
    assert editor._split_documents(first, second)
    pair = editor.workspace._pair
    assert_active_page_size(editor, first)
    for session in (second, first, second):
        pair.activate(session)
        assert_active_page_size(editor, session)
    editor.workspace.end_pair()
    assert_active_page_size(editor, second)


def test_page_size_follows_live_document_move_between_windows(editor, tmp_path):
    first, second = sized_documents(editor, tmp_path)
    editor.goto_page(1)
    assert editor.document_windows.move(second)
    child = second.window_owner
    assert_active_page_size(child, second)
    assert_active_page_size(editor, first)
    assert editor.document_windows.move(second, editor)
    assert_active_page_size(editor, second)
