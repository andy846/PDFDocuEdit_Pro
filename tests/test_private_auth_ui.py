from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QWidget

from auth import guard
from auth.application import PrivateApplication
from auth.config import AuthConfig
from auth.controller import AuthController
from auth.model import Approval, timestamp
from auth.store import ApprovalStore

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
        self.command_bar = QWidget(self)
        QHBoxLayout(self.command_bar)
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
    original = approved()
    private.controller.commit_approval(original)
    viewer = private.viewer
    private.controller.approval = None
    private.lock("Revoked")
    private.prepare_account(original)
    assert private.viewer is viewer and viewer.isEnabled()
    assert not private.locked and private.recovery is None


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
