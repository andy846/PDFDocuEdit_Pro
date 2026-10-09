"""Startup/login routing and recovery around the existing main window."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QDialog, QToolButton

from . import guard
from .client import AccessClient
from .controller import AuthController
from .store import ApprovalStore
from .ui import AccountDialog, LoginWindow, RecoveryDialog


class PrivateApplication(QObject):
    def __init__(self, app, config, viewer_factory, *, root=None, controller=None):
        super().__init__(app)
        self.app, self.config, self.viewer_factory = app, config, viewer_factory
        self.root = root
        self.controller = controller or AuthController(AccessClient(config), ApprovalStore(config.project_ref), self)
        self.viewer = None
        self.viewer_account = None
        self.pending_paths = []
        self.ready = root is None
        self.locked = False
        self.recovery = None
        self.closing_for = None
        self.pending_approval = None
        self.exiting = False
        self.login = LoginWindow()
        self.login.signIn.connect(self.controller.sign_in)
        self.login.quitRequested.connect(self.quit)
        self.controller.changed.connect(lambda: self.login.update_state(self.controller))
        self.controller.approved.connect(self.admit)
        self.controller.approvalRequested.connect(self.prepare_account)
        self.controller.revoked.connect(self.lock)
        self.controller.idle.connect(self._idle)
        self.app.setQuitOnLastWindowClosed(False)
        guard.runtime_access = False

    def start(self, paths=()):
        self.pending_paths.extend(str(p) for p in paths)
        self.login.show()
        self.controller.start()

    def managed_ready(self):
        self.ready = True
        self._drain_paths()

    def accept_paths(self, paths):
        self.pending_paths.extend(str(p) for p in paths)
        target = self.viewer if self.viewer and not self.locked else self.login
        target.showNormal() if target.isMinimized() else target.show()
        target.raise_()
        target.activateWindow()
        self._drain_paths()

    def _drain_paths(self):
        if self.ready and self.viewer and not self.locked and self.controller.approval and self.pending_paths:
            paths, self.pending_paths = self.pending_paths, []
            self.viewer.queue_open_files(paths)

    def prepare_account(self, approval):
        if self.viewer and self.viewer_account != approval.user_id:
            # New account is not allowed to inherit another user's open work.
            self.pending_approval = approval
            self.closing_for = "account-change"
            self._close_viewer()
            return
        self.controller.commit_approval(approval)

    def admit(self, approval):
        if self.exiting:
            return
        guard.runtime_access = True
        self.locked = False
        if self.recovery:
            self.recovery.hide()
            self.recovery.deleteLater()
            self.recovery = None
        if self.viewer is None:
            self.viewer = self.viewer_factory()
            self.viewer_account = approval.user_id
            self.viewer.installEventFilter(self)
            button = QToolButton(self.viewer.command_bar)
            button.setText("Account")
            button.setToolTip("Private account · offline approval / check / sign out")
            button.setAccessibleName("Private account")
            button.clicked.connect(self.account)
            self.viewer.command_bar.layout().insertWidget(3, button)
            self.account_button = button
            update = self.viewer._command_action_map.get("check_updates")
            if update:
                update.setEnabled(False)
                update.setToolTip("Internal private build: public updates are disabled.")
        self.viewer.setEnabled(True)
        self.viewer.show()
        self.login.hide()
        self._drain_paths()

    def account(self):
        dialog = AccountDialog(self.controller, self.logout, self.viewer)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.login.email.setText(self.controller.approval.email if self.controller.approval else "")
            self.login.show()
            self.login.raise_()

    def lock(self, message):
        guard.runtime_access = False
        self.locked = True
        if self.viewer:
            self.viewer.setEnabled(False)
            self.viewer._queued_open_paths.clear()
            self.viewer._pending_searches.clear()
            self.viewer._cancel_tasks()
            controller = getattr(self.viewer, "_mode_controller", None)
            host = getattr(controller, "host", None)
            for project in host.projects if host else []:
                for name in ("timer", "preview_timer"):
                    timer = getattr(project, name, None)
                    if timer:
                        timer.stop()
                for worker in list(getattr(project, "workers", [])):
                    worker.cancel()
            for dialog in getattr(self.viewer, "_pdf_operation_dialogs", []):
                if dialog.worker:
                    dialog.worker.cancel()
            merge = getattr(self.viewer, "_merge_workspace", None)
            if merge and getattr(merge, "worker", None):
                merge.worker.cancel()
            if not self.recovery:
                self.recovery = RecoveryDialog(message)
                self.recovery.relogin.connect(self._relogin)
                self.recovery.exitRequested.connect(self.quit)
                self.recovery.saveRequested.connect(self.save_open_work)
            self.recovery.show()
        else:
            self.login.show()

    def _relogin(self):
        if self.recovery:
            self.recovery.hide()
        self.login.show()
        self.login.raise_()

    def save_open_work(self):
        if not self.viewer:
            return
        # The modal recovery screen keeps the underlying workspace inaccessible.
        # Save-only serializers may run in-process after secure approval is gone.
        guard.recovery_saving = True
        self.viewer.setEnabled(True)
        try:
            self.viewer.save_all_files()
            host = getattr(getattr(self.viewer, "_mode_controller", None), "host", None)
            if host:
                for project in list(host.projects):
                    if not host.confirm_project_close(project):
                        break
        finally:
            guard.recovery_saving = False
            self.viewer.setEnabled(False)

    def logout(self):
        self.closing_for = "logout"
        self._close_viewer()

    def _close_viewer(self):
        if self.viewer:
            guard.recovery_saving = self.locked
            if self.locked:
                self.viewer.setEnabled(True)
            try:
                self.viewer.close()
            finally:
                guard.recovery_saving = False
                if self.locked and self.viewer and self.viewer.isVisible():
                    self.viewer.setEnabled(False)
            # closeEvent may arrange asynchronous worker cleanup; visibility is
            # checked after the event has completed, never inside the event filter.
            QTimer.singleShot(0, self._closed)
        else:
            self._closed()

    def eventFilter(self, watched, event):
        if watched is self.viewer and event.type() == QEvent.Type.Close:
            QTimer.singleShot(0, self._closed)
        return super().eventFilter(watched, event)

    def _closed(self):
        if self.viewer is None and self.closing_for is None:
            return
        if self.viewer and self.viewer.isVisible():
            # A canceled save prompt must not sign out or restore revoked access.
            controller = getattr(self.viewer, "_mode_controller", None)
            if not getattr(controller, "exit_approved", False):
                self.closing_for = None
                self.pending_approval = None
                if self.locked and self.recovery:
                    self.recovery.show()
            return
        old, self.viewer = self.viewer, None
        if old:
            old.removeEventFilter(self)
            old.deleteLater()
        purpose, self.closing_for = self.closing_for, None
        if purpose == "account-change":
            approval, self.pending_approval = self.pending_approval, None
            if approval:
                self.controller.commit_approval(approval)
            return
        if purpose == "logout":
            guard.runtime_access = False
            self.controller.sign_out()
            self.pending_paths.clear()
            self.login.show()
            return
        self.quit()

    def quit(self):
        if self.viewer:
            self.closing_for = "exit"
            self._close_viewer()
            return
        self.exiting = True
        self.controller.stop()
        self.login.setEnabled(False)
        self.login.status.setText("Finishing account request…")
        if not self.controller.busy:
            self.app.quit()

    def _idle(self):
        if self.exiting:
            self.app.quit()
