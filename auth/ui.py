"""Responsive private-account UI; no registration and no diagnostic payloads."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ui.responsive import ResponsiveDialog


class LoginWindow(ResponsiveDialog):
    signIn = pyqtSignal(str, str)
    quitRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFDocuEdit Pro — Private Account")
        self.resize(540, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("PDFDocuEdit Pro")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        description = QLabel("Sign in with an approved account.\nAfter approval, this Windows account can work offline.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.email = QLineEdit()
        self.email.setPlaceholderText("Email address")
        self.email.setAccessibleName("Email address")
        self.email.setMaxLength(320)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setAccessibleName("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setInputMethodHints(Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText)
        self.password.setMaxLength(1024)
        layout.addWidget(self.email)
        layout.addWidget(self.password)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda visible: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        layout.addWidget(show)
        self.status = QLabel("Sign in with an approved account.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.submit = QPushButton("Sign in")
        self.submit.clicked.connect(self._submit)
        self.password.returnPressed.connect(self._submit)
        layout.addWidget(self.submit)

    def _submit(self):
        if self.submit.isEnabled() and self.email.text().strip() and self.password.text():
            password = self.password.text()
            self.password.clear()
            self.signIn.emit(self.email.text(), password)

    def update_state(self, controller):
        self.submit.setEnabled(not controller.busy and not controller.stopping)
        self.email.setEnabled(not controller.busy)
        self.password.setEnabled(not controller.busy)
        self.status.setText("Verifying account…" if controller.busy else controller.message)

    def closeEvent(self, event):
        event.ignore()
        self.quitRequested.emit()

    def reject(self):
        self.quitRequested.emit()


class AccountDialog(ResponsiveDialog):
    def __init__(self, controller, logout, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Private account")
        layout = QVBoxLayout(self)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.check = QPushButton("Check now")
        self.check.clicked.connect(controller.check)
        self.relogin = QPushButton("Sign in again")
        self.relogin.clicked.connect(self.accept)
        self.logout = QPushButton("Sign out…")
        self.logout.clicked.connect(lambda: (self.reject(), logout()))
        row.addWidget(self.check)
        row.addWidget(self.relogin)
        row.addWidget(self.logout)
        layout.addLayout(row)
        done = QPushButton("Close")
        done.clicked.connect(self.reject)
        layout.addWidget(done)

        def refresh():
            approval = controller.approval
            self.details.setText((f"Account: {approval.email}\nLast verified: {approval.last_verified}\n\n"
                                  if approval else "") + controller.message)
            self.check.setEnabled(not controller.busy and approval is not None)
            self.relogin.setEnabled(not controller.busy)
        controller.changed.connect(refresh)
        self.finished.connect(lambda: controller.changed.disconnect(refresh))
        refresh()
        self.resize(560, 260)


class RecoveryDialog(ResponsiveDialog):
    relogin = pyqtSignal()
    exitRequested = pyqtSignal()
    saveRequested = pyqtSignal()

    def __init__(self, message):
        super().__init__()
        self.setWindowTitle("Account access paused")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(self)
        text = QLabel(message + "\n\nYour open work is retained. New work is locked. Save your work, sign in again, or exit.")
        text.setWordWrap(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        for label, signal in (("Save open work…", self.saveRequested), ("Sign in again", self.relogin), ("Exit…", self.exitRequested)):
            button = QPushButton(label)
            button.clicked.connect(signal.emit)
            row.addWidget(button)
        layout.addLayout(row)
        self.resize(620, 230)

    def reject(self):
        # Dismissing the recovery screen never restores access.
        self.exitRequested.emit()
