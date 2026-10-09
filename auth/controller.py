"""Single-flight Qt coordinator. Only sanitized results cross worker signals."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .model import AuthResult, Outcome
from .store import StorageError


class RequestThread(QThread):
    completed = pyqtSignal(object)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation()
        except Exception:
            result = AuthResult(Outcome.UNAVAILABLE, "Account verification is unavailable.")
        finally:
            self.operation = None
        self.completed.emit(result)


class AuthController(QObject):
    changed = pyqtSignal()
    approved = pyqtSignal(object)
    approvalRequested = pyqtSignal(object)
    revoked = pyqtSignal(str)
    response = pyqtSignal(object)
    idle = pyqtSignal()

    def __init__(self, client, store, parent=None):
        super().__init__(parent)
        self.client, self.store = client, store
        self.approval = None
        self.message = "Sign in with an approved account."
        self.thread = None
        self.generation = 0
        self.stopping = False
        self.timer = QTimer(self)
        self.timer.setInterval(10 * 60 * 1000)
        self.timer.timeout.connect(self.check)

    @property
    def busy(self):
        return self.thread is not None

    def start(self):
        try:
            self.approval = self.store.load()
        except StorageError as error:
            self.message = str(error)
        if self.approval:
            self.message = "Using saved offline approval."
            self.approved.emit(self.approval)
            self.timer.start()
            QTimer.singleShot(0, self.check)
        self.changed.emit()

    def _begin(self, operation, *, login=False):
        if self.busy or self.stopping:
            return False
        generation = self.generation
        thread = RequestThread(operation, self)
        self.thread = thread
        thread.completed.connect(lambda result: self._receive(result, generation, login))
        thread.finished.connect(lambda: self._finished(thread))
        thread.start()
        self.changed.emit()
        return True

    def _finished(self, thread):
        if self.thread is thread:
            self.thread = None
        thread.deleteLater()
        self.changed.emit()
        self.idle.emit()

    def sign_in(self, email, password):
        # The owned thread releases this closure immediately after the request.
        return self._begin(lambda: self.client.sign_in(email.strip(), password), login=True)

    def check(self):
        approval = self.approval
        if approval:
            return self._begin(lambda: self.client.verify(approval))
        return False

    def _receive(self, result, generation, login):
        if generation != self.generation or self.stopping:
            return
        if result.outcome == Outcome.APPROVED:
            if login:
                self.approvalRequested.emit(result.approval)
                return
            result = self.commit_approval(result.approval)
            return
        elif result.outcome == Outcome.REVOKED:
            self.approval = None
            self.timer.stop()
            try:
                self.store.clear()
            except StorageError:
                result = AuthResult(Outcome.REVOKED, "Access revoked. Windows could not remove the saved credential; contact support before restarting.")
            self.revoked.emit(result.message)
        self.message = result.message
        self.response.emit(result)
        self.changed.emit()

    def commit_approval(self, approval):
        result = AuthResult(Outcome.APPROVED, "Account verified online.", approval)
        # Persist before admitting a new account. Background storage errors
        # retain existing offline approval and never publish new credentials.
        try:
            self.store.save(approval)
        except (StorageError, ValueError):
            result = AuthResult(Outcome.UNAVAILABLE, "Cannot save Windows credentials. Try signing in again.")
        else:
            self.approval = approval
            self.timer.start()
            self.approved.emit(self.approval)
        self.message = result.message
        self.response.emit(result)
        self.changed.emit()
        return result

    def sign_out(self):
        # Caller must finish save/close confirmation first.
        self.generation += 1
        self.timer.stop()
        self.approval = None
        try:
            self.store.clear()
        except StorageError as error:
            self.message = str(error)
            self.revoked.emit(self.message)
            self.changed.emit()
            return False
        self.message = "Signed out. Sign in to continue."
        self.changed.emit()
        return True

    def stop(self):
        self.stopping = True
        self.generation += 1
        self.timer.stop()
