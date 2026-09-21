"""Background manual update UI; the editor owns unsaved-document handling."""

from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from core.diagnostics import log_failure
from core.resources import APP_VERSION
from ui.responsive import ResponsiveDialog
from updates.protocol import Cancelled, check_release, download
from updates.runtime import managed_root, request_restart
from updates.trust import PUBLIC_KEY_HEX, REPOSITORY


class UpdateWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, root, release=None, parent=None):
        super().__init__(parent)
        self.root = root
        self.release = release
        self.cancelled = threading.Event()

    def run(self):
        try:
            if self.release is None:
                result = check_release(REPOSITORY, PUBLIC_KEY_HEX, APP_VERSION)
            else:
                result = download(
                    self.release, self.root / "staging",
                    lambda done, total: self.progress.emit(done * 100 // total),
                    self.cancelled.is_set,
                )
            if self.cancelled.is_set():
                raise Cancelled("Update cancelled.")
            self.result.emit(result)
        except Exception as exc:
            log_failure('update_dialog.run: fallback after failure', 10)
            self.failed.emit(str(exc))


class UpdateDialog(ResponsiveDialog):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.root = managed_root()
        self.release = None
        self.worker = None
        self.downloaded = False
        self.setWindowTitle("Check for Updates")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(530, 350)
        layout = QVBoxLayout(self)
        self.status = QLabel(f"Current version: {APP_VERSION}")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes)
        buttons = QHBoxLayout()
        self.action = QPushButton("Check for Updates")
        self.action.clicked.connect(self.perform)
        self.cancel = QPushButton("Close")
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.action)
        buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        if self.root is None:
            self.status.setText("Automatic ZIP updates require the managed portable edition. Extract the deployment ZIP once and open Launcher.exe.")
            self.action.setEnabled(False)
        else:
            QTimer.singleShot(0, self.perform)

    def busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def perform(self):
        if self.busy():
            return
        if self.downloaded:
            self.accept()
            QTimer.singleShot(0, self.restart)
            return
        self.action.setEnabled(False)
        self.cancel.setText("Cancel")
        self.status.setText("Downloading and verifying update…" if self.release else "Checking GitHub Releases…")
        self.worker = UpdateWorker(self.root, self.release, self)
        self.worker.result.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.progress.connect(lambda percent: self.status.setText(f"Downloading update: {percent}%"))
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def finished_work(self):
        self.action.setEnabled(True)
        self.cancel.setEnabled(True)
        self.cancel.setText("Close")

    def completed(self, result):
        if self.release is not None:
            self.downloaded = True
            self.status.setText("Download verified. Save your work, then update and restart.")
            self.action.setText("Update and Restart")
        elif result is None:
            self.status.setText(f"Version {APP_VERSION} is up to date.")
        else:
            self.release = result
            self.status.setText(f"Version {result.manifest.version} is available ({result.manifest.size / 1024**2:.1f} MB).")
            self.notes.setPlainText(result.notes)
            self.action.setText("Download Update")

    def failed(self, message):
        self.status.setText(message)

    def restart(self):
        try:
            request_restart(self.root)
            if self.viewer.close():
                self.viewer._update_restart = True
            else:
                (self.root / "restart.json").unlink(missing_ok=True)
                self.show()
                self.status.setText("Update postponed. Finish saving or printing, then retry.")
        except OSError as exc:
            self.show()
            self.status.setText(f"Could not request restart: {exc}")

    def reject(self):
        if self.busy():
            self.worker.cancelled.set()
            self.status.setText("Cancelling… (a network request may take up to 20 seconds)")
            self.cancel.setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy():
            self.reject()
            event.ignore()
        else:
            event.accept()
