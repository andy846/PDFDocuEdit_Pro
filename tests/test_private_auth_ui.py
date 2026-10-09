from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMainWindow, QMenuBar, QToolButton

from auth import guard
from auth.application import PrivateApplication
from auth.config import AuthConfig
from auth.controller import AuthController
from auth.model import Approval, timestamp
from auth.store import ApprovalStore
from tests.test_private_auth import pump
from ui.command_bar import CommandBar
from ui.workspace_modes import WorkspaceMode

CONFIG = AuthConfig("qatest", "https://qatest.supabase.co", "sb_publishable_qa")


class Memory:
    value = None
    def get_password(self, *args):
        return self.value
    def set_password(self, *args):
        self.value = args[-1]
    def delete_password(self, *args):
        self.value = None


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.command_bar = CommandBar(parent=self)
        self.command_bar.set_application_menu(self.menuBar())
        self.setCentralWidget(self.command_bar)
        self._command_action_map = {}
        self.opened = []
        self._queued_open_paths = []
        self._pending_searches = {}
        self.allow_close = False
        self.cancelled = False

    def queue_open_files(self, paths):
        self.opened.extend(paths)

    def _cancel_tasks(self):
        self.cancelled = True

    def closeEvent(self, event):
        event.accept() if self.allow_close else event.ignore()


@pytest.fixture
def private(qt_application):
    store = ApprovalStore(CONFIG.project_ref, backend=Memory())
    controller = AuthController(NS(), store)
    session = PrivateApplication(qt_application, CONFIG, Window, root="managed", controller=controller)
    yield session
    controller.stop()
    if session.viewer:
        session.viewer.allow_close = True
        session.viewer.removeEventFilter(session)
        session.viewer.close()
        session.viewer.deleteLater()
    if session.recovery:
        session.recovery.hide()
        session.recovery.deleteLater()
    session.login.hide()
    session.login.deleteLater()
    session.deleteLater()
    guard.runtime_access = None
    guard.recovery_saving = False
    qt_application.setQuitOnLastWindowClosed(True)


def approved(user="f63613d9-81b8-4a36-b765-a37b6e9e0916"):
    now = timestamp()
    return Approval(CONFIG.project_ref, user, "test@example.invalid", "secret", now, now)


def test_no_viewer_before_approval_and_paths_wait_for_managed_ready(private, qt_application):
    private.start(["first.pdf"])
    private.accept_paths(["second.pdf"])
    assert private.viewer is None
    private.controller.commit_approval(approved())
    assert private.viewer.opened == []
    private.managed_ready()
    assert private.viewer.opened == ["first.pdf", "second.pdf"]
    assert not private.login.isVisible()


def test_cancel_logout_keeps_approval_and_workspace(private, qt_application):
    original = approved()
    private.controller.commit_approval(original)
    viewer = private.viewer
    private.logout()
    qt_application.processEvents()
    assert private.viewer is viewer and private.controller.approval == original
    assert private.controller.store.load() is not None
    assert guard.runtime_access is True


def test_successful_logout_returns_login_without_double_quit(private, qt_application):
    private.controller.commit_approval(approved())
    private.viewer.allow_close = True
    private.logout()
    qt_application.processEvents()
    qt_application.processEvents()
    assert private.viewer is None and private.controller.approval is None
    assert private.controller.store.load() is None
    assert private.login.isVisible() and not private.exiting


def test_revocation_cancel_exit_never_restores_access(private, qt_application):
    private.controller.commit_approval(approved())
    viewer = private.viewer
    private.controller.approval = None
    private.controller.store.clear()
    private.lock("Revoked")
    private.quit()
    qt_application.processEvents()
    assert private.viewer is viewer and viewer.cancelled
    assert not viewer.isEnabled() and guard.runtime_access is False
    assert private.recovery.isVisible()


def test_account_change_cancel_does_not_replace_cached_account(private, qt_application):
    original = approved()
    private.controller.commit_approval(original)
    private.prepare_account(approved("f63613d9-81b8-4a36-b765-a37b6e9e0917"))
    qt_application.processEvents()
    assert private.controller.approval == original
    assert private.controller.store.load() == original
    assert private.viewer_account == original.user_id


def test_same_account_relogin_resumes_retained_workspace(private, qt_application):
    private.managed_ready()
    original = approved()
    private.controller.commit_approval(original)
    viewer = private.viewer
    private.controller.approval = None
    private.lock("Revoked")
    private.prepare_account(original)
    assert private.viewer is viewer and viewer.isEnabled()
    assert not private.locked and private.recovery is None


def test_private_update_restart_retains_supervisor_exit_code(private, qt_application, monkeypatch):
    from updates.runtime import RESTART_EXIT_CODE
    codes = []
    monkeypatch.setattr(qt_application, "exit", codes.append)
    private.controller.commit_approval(approved())
    private.viewer.allow_close = True
    private.viewer._update_restart = True
    private.quit()
    pump(qt_application, lambda: bool(codes))
    assert codes == [RESTART_EXIT_CODE]
    assert private.viewer is None


def test_login_narrow_layout_and_password_cleared_on_submit(private, qt_application):
    login = private.login
    login.resize(450, 350)
    login.show()
    qt_application.processEvents()
    received = []
    login.signIn.disconnect()
    login.signIn.connect(lambda email, password: received.append((email, password)))
    login.email.setText("test@example.invalid")
    login.password.setText("中文Pass")
    login._submit()
    assert received == [("test@example.invalid", "中文Pass")]
    assert login.password.text() == ""
    assert login.submit.isVisible()


def test_login_keyboard_submit_validation_and_branding(private, qt_application):
    login = private.login
    login.show()
    qt_application.processEvents()
    assert not login.brand.pixmap().isNull()
    assert not login.windowIcon().isNull()
    received = []
    login.signIn.disconnect()
    login.signIn.connect(lambda email, password: received.append((email, password)))
    login._submit()
    assert not received and "email" in login.status.text()
    login.email.setText("test@example.invalid")
    login._submit()
    assert not received and "password" in login.status.text()
    login.password.setText("中文Pass")
    login.show_password.setChecked(True)
    QTest.keyClick(login.password, Qt.Key.Key_Return)
    assert received == [("test@example.invalid", "中文Pass")]
    assert login.password.text() == ""
    assert not login.show_password.isChecked()


def test_account_is_in_settings_across_modes_and_updates_status(private, qt_application, monkeypatch):
    opened = []
    monkeypatch.setattr(private, "account", lambda: opened.append(True))
    private.controller.commit_approval(approved())
    bar = private.viewer.command_bar
    action = private.account_action
    assert "test@example.invalid" in action.text() and "Signed in" in action.text()
    assert not any(button.text() == "Account" for button in bar.findChildren(QToolButton))
    for mode in (WorkspaceMode.DESIGNER, WorkspaceMode.PDF, WorkspaceMode.DESIGNER):
        bar.set_mode(mode)
        menus = QMenuBar(private.viewer)
        menus.addMenu("Workspace")
        bar.set_application_menu(menus)
        if mode == WorkspaceMode.PDF:
            assert bar._more.menu().actions().count(action) == 1
        else:
            settings = [item.menu() for item in bar._more.menu().actions() if item.text() == "Settings"]
            assert len(settings) == 1 and settings[0].actions().count(action) == 1
        action.trigger()
        menus.deleteLater()
    assert len(opened) == 3
    private.controller.message = "Using saved offline approval."
    private.controller.changed.emit()
    assert "Signed in" in action.text() and "offline" in action.toolTip()
    private.controller.approval = None
    private.controller.changed.emit()
    assert "Sign-in required" in action.text() and "test@example.invalid" not in action.text()


def test_locked_worker_refuses_production_without_writing_ipc(tmp_path, qt_application, monkeypatch):
    from composition.designer.process import Worker
    monkeypatch.setattr(guard, "runtime_access", False)
    monkeypatch.setattr(guard, "recovery_saving", True)
    folder = tmp_path / "ipc"
    worker = Worker(folder, {"task": "generate", "target": str(tmp_path / "production.pdf")})
    errors = []
    worker.failed.connect(errors.append)
    pump(qt_application, lambda: bool(errors))
    assert "paused" in errors[0]
    assert not folder.exists() and not (tmp_path / "production.pdf").exists()


def test_locked_worker_can_save_template_draft_without_ipc(tmp_path, qt_application, monkeypatch):
    from composition.designer.process import Worker
    from composition.template.model import Element, Template
    from composition.template.serializer import load_project
    monkeypatch.setattr(guard, "runtime_access", False)
    monkeypatch.setattr(guard, "recovery_saving", True)
    target = tmp_path / "retained.pdcx"
    template = Template(elements=[Element(value="Unsaved {{Customer}}")])
    worker = Worker(tmp_path / "ipc", {"task": "save", "target": str(target), "template": template.to_dict()})
    results, ended = [], []
    worker.resultReady.connect(results.append)
    worker.ended.connect(lambda: ended.append(True))
    pump(qt_application, lambda: bool(ended))
    assert results[0]["project"] == str(target)
    assert load_project(target).elements[0].value == "Unsaved {{Customer}}"
    assert not (tmp_path / "ipc").exists()
