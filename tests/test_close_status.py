"""Shutdown remains visible and recoverable without reviving retired PDFs."""
import logging
from threading import Event

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QCloseEvent

from tests.composition.test_workspace import wait_until
from tests.composition.test_workspace_modes import app as app
from tests.composition.test_workspace_modes import designer
from tests.composition.test_workspace_modes import window as window
from tests.test_document_windows import documents


def empty_designer(window):
    controller, project = designer(window)
    controller.set_animations_enabled(False)
    assert controller.host.close_project(project)
    wait_until(lambda: not controller.host.projects)
    return controller


def test_preferences_failure_precedes_retirement_and_can_return(window, tmp_path, monkeypatch):
    session = documents(window, tmp_path, count=1)[0]
    original_doc = session.engine.document
    controller = empty_designer(window)
    update = window.settings.update
    monkeypatch.setattr(window.settings, 'update', lambda *a, **k: (_ for _ in ()).throw(OSError('PRIVATE_SETTINGS_VALUE')))
    try:
        assert not window.close()
        assert session.engine.document is original_doc and not original_doc.is_closed
        assert not window._closing and not controller.shutdown_started
        assert not controller.exit_approved
        lifecycle = window._close_lifecycle
        assert lifecycle.status_bar.isVisible()
        assert lifecycle.status_bar.return_button.isVisible()
        lifecycle.status_bar.return_button.click()
        assert lifecycle.status_bar.isHidden() and controller.host.start.isEnabled()
        assert controller.designer_actions['new'].isEnabled()
    finally:
        monkeypatch.setattr(window.settings, 'update', update)


def test_empty_designer_wait_status_is_global_and_brand_remains_enabled(window):
    controller = empty_designer(window)
    started, release = Event(), Event()
    def operation(is_cancelled):
        started.set()
        release.wait(5)
    window._run_task('Synthetic worker', operation, cancel_argument='is_cancelled')
    wait_until(started.is_set)
    lifecycle = window._close_lifecycle
    lifecycle.warning_after_ms = 25
    try:
        assert not window.close()
        wait_until(lambda: lifecycle.warned)
        bar = lifecycle.status_bar
        assert bar.isVisible() and bar.isEnabled()
        assert not controller.host.start.isEnabled()
        assert window.command_bar._app_icon.isEnabled()
        assert window.command_bar._window_close.isEnabled()
        assert not bar.return_button.isVisible()
        assert '1 background' in bar.message.text()
        window.close()
        assert not bar.return_button.isVisible()
    finally:
        release.set()
        wait_until(lambda: not window.isVisible())


def test_failed_teardown_only_retries_and_never_returns(window, tmp_path, monkeypatch):
    session = documents(window, tmp_path, count=1)[0]
    empty_designer(window)
    original = window._retire_pdf_sessions
    called = []
    def fail_once():
        result = original()
        called.append(True)
        if len(called) == 1:
            raise OSError('PRIVATE_TEARDOWN_VALUE')
        return result
    monkeypatch.setattr(window, '_retire_pdf_sessions', fail_once)
    assert not window.close()
    lifecycle = window._close_lifecycle
    assert lifecycle.teardown_started and window._closing
    assert lifecycle.status_bar.isVisible()
    assert not lifecycle.status_bar.return_button.isVisible()
    assert not lifecycle.timer.isActive()
    assert not lifecycle.return_to_work()
    assert not window._mode_controller.host.start.isEnabled()
    lifecycle.status_bar.retry_button.click()
    wait_until(lambda: not window.isVisible())
    assert session in window._retired_pdf_sessions and len(called) == 2


def test_all_windows_prepare_before_any_teardown(window, tmp_path, monkeypatch):
    first, second = documents(window, tmp_path, count=2)
    empty_designer(window)
    assert window.document_windows.move(second)
    child = second.window_owner
    original = window.settings.update
    monkeypatch.setattr(window.settings, 'update', lambda *a, **k: (_ for _ in ()).throw(OSError('PRIVATE_PRIMARY_PREF')))
    try:
        assert not window.close()
        assert window.isVisible() and child.isVisible()
        assert first.engine.is_loaded() and second.engine.is_loaded()
        assert not window.document_windows.pending_exit
        assert not window._closing and not child._closing
    finally:
        monkeypatch.setattr(window.settings, 'update', original)


def test_idle_and_last_project_close_show_no_status(window):
    controller = empty_designer(window)
    lifecycle = window._close_lifecycle
    assert lifecycle.status_bar.isHidden()
    assert lifecycle.warning_after_ms == 3000
    assert window.command_bar._app_icon.isEnabled()
    controller.request_mode('pdf')
    controller.request_mode('designer')
    assert lifecycle.status_bar.isHidden() and controller.host.start.isEnabled()


def test_preflight_failure_preserves_account_and_explicit_action_locks(window, monkeypatch):
    empty_designer(window)
    from PyQt6.QtGui import QAction
    action = QAction('Independently disabled action', window)
    action.setEnabled(False)
    update = window.settings.update
    window.setEnabled(False)
    monkeypatch.setattr(window.settings, 'update', lambda *a, **k: (_ for _ in ()).throw(OSError('PRIVATE_LOCK')))
    try:
        assert not window.close()
        assert not window.isEnabled() and not action.isEnabled()
        assert window._close_lifecycle.return_to_work()
        assert not window.isEnabled() and not action.isEnabled()
    finally:
        window.setEnabled(True)
        monkeypatch.setattr(window.settings, 'update', update)


def test_cancel_new_exit_after_preflight_error_hides_previous_error(window, monkeypatch):
    empty_designer(window)
    original = window.settings.update
    monkeypatch.setattr(window.settings, 'update', lambda *a, **k: (_ for _ in ()).throw(OSError('PRIVATE_PREF')))
    assert not window.close()
    monkeypatch.setattr(window.settings, 'update', original)
    monkeypatch.setattr(window._mode_controller.host, 'confirm_all', lambda: False)
    assert not window.close()
    assert window._close_lifecycle.status_bar.isHidden()
    assert not window._mode_controller.exit_approved


def test_waiting_before_deadline_does_not_show_extra_chrome(window):
    empty_designer(window)
    lifecycle = window._close_lifecycle
    lifecycle.begin()
    lifecycle.defer('pdf_readers')
    try:
        assert lifecycle.status_bar.isHidden() and not lifecycle.warned
    finally:
        lifecycle.cancel_preflight()


def test_numeric_lock_diagnostics_contain_mode_and_no_private_values(window, caplog):
    empty_designer(window)
    with caplog.at_level(logging.INFO, logger='pdfdocuedit'):
        with window._close_lifecycle.lock_ui():
            assert not window._mode_controller.host.start.isEnabled()
    assert 'close.locked' in caplog.text and 'close.unlocked' in caplog.text
    assert 'designer=1' in caplog.text and 'tabs=0' in caplog.text
    assert 'modal=' in caplog.text and 'readers=' in caplog.text and 'locks=' in caplog.text


def test_printing_lock_is_not_released_by_failed_close_or_return(window):
    empty_designer(window)
    with window._suspend_print_actions():
        assert not window.close()
        assert window._printing and not window.command_bar.isEnabled()
        assert window._close_lifecycle.return_to_work()
        assert window._printing and not window.command_bar.isEnabled()
    assert not window._printing and window.command_bar.isEnabled()


def test_reentrant_close_during_preflight_does_not_duplicate_preparation(window, monkeypatch):
    empty_designer(window)
    lifecycle = window._close_lifecycle
    called = []
    def preflight():
        called.append(True)
        QCoreApplication.sendEvent(window, QCloseEvent())
        return False
    monkeypatch.setattr(window._mode_controller.host, 'confirm_all', preflight)
    assert not window.close()
    assert called == [True] and not lifecycle.handling_close
    assert not lifecycle.teardown_started


def test_retry_in_child_resumes_whole_application_exit(window, tmp_path, monkeypatch):
    _, session = documents(window, tmp_path, count=2)
    empty_designer(window)
    assert window.document_windows.move(session)
    child = session.window_owner
    original = child._retire_pdf_sessions
    calls = []
    def fail_once():
        calls.append(True)
        if len(calls) == 1:
            raise OSError('PRIVATE_CHILD_CLOSE')
        return original()
    monkeypatch.setattr(child, '_retire_pdf_sessions', fail_once)
    assert not window.close()
    assert window._close_lifecycle.is_failed and child._close_lifecycle.is_failed
    child._close_lifecycle.status_bar.retry_button.click()
    try:
        wait_until(lambda: not window.isVisible(), timeout=1)
    finally:
        window.close()


def test_detached_print_block_is_visible_in_empty_designer(window, tmp_path):
    _, session = documents(window, tmp_path, count=2)
    empty_designer(window)
    assert window.document_windows.move(session)
    child = session.window_owner
    child._printing = True
    try:
        assert not window.close()
        assert window._close_lifecycle.status_bar.isVisible()
        assert 'Finish printing' in window._close_lifecycle.status_bar.message.text()
        assert child._printing and session.engine.is_loaded()
    finally:
        child._printing = False


def test_closed_participant_keeps_group_teardown_boundary(window, tmp_path, monkeypatch):
    _, session = documents(window, tmp_path, count=2)
    empty_designer(window)
    assert window.document_windows.move(session)
    original = window._close_lifecycle.prepare_preferences
    calls = []
    def fault_after_child_closed():
        calls.append(True)
        if len(calls) == 2:
            raise OSError('PRIVATE_PRIMARY_AFTER_CHILD')
        return original()
    monkeypatch.setattr(window._close_lifecycle, 'prepare_preferences', fault_after_child_closed)
    try:
        assert not window.close()
        assert not window._close_lifecycle.can_return_to_work()
        assert not window._close_lifecycle.status_bar.return_button.isVisible()
        assert window.document_windows.pending_exit
    finally:
        monkeypatch.setattr(window._close_lifecycle, 'prepare_preferences', original)
