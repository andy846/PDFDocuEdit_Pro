"""Responsive private-account UI; no registration and no diagnostic payloads."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.resources import APP_VERSION
from styles.theme import get_colors
from ui.icons import brand_pixmap
from ui.responsive import ResponsiveDialog


class LoginWindow(ResponsiveDialog):
    signIn = pyqtSignal(str, str)
    quitRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("privateLogin")
        self.setWindowTitle("Sign in — PDFDocuEdit Pro")
        self.setWindowIcon(QIcon(brand_pixmap(64)))
        self.resize(520, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.brand = QLabel()
        self.brand.setObjectName("loginBrand")
        self.brand.setPixmap(brand_pixmap(56))
        self.brand.setFixedSize(56, 56)
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.brand)
        identity = QVBoxLayout()
        identity.setSpacing(4)
        title = QLabel("PDFDocuEdit Pro")
        title.setObjectName("loginProduct")
        identity.addWidget(title)
        version = QLabel(f"Version {APP_VERSION}  ·  Private access")
        version.setObjectName("loginSecondary")
        identity.addWidget(version)
        header.addLayout(identity, 1)
        layout.addLayout(header)
        divider = QFrame()
        divider.setObjectName("loginDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        heading = QLabel("Welcome back")
        heading.setObjectName("loginHeading")
        layout.addWidget(heading)
        description = QLabel("Sign in to your PDF editing and production workspace.")
        description.setObjectName("loginSecondary")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.email = QLineEdit()
        self.email.setObjectName("loginEmail")
        self.email.setPlaceholderText("you@example.com")
        self.email.setAccessibleName("Email address")
        self.email.setMaxLength(320)
        self.password = QLineEdit()
        self.password.setObjectName("loginPassword")
        self.password.setPlaceholderText("Password")
        self.password.setAccessibleName("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setInputMethodHints(Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText)
        self.password.setMaxLength(1024)
        for label, field in (("&Email address", self.email), ("&Password", self.password)):
            caption = QLabel(label)
            caption.setObjectName("loginFieldLabel")
            caption.setBuddy(field)
            layout.addWidget(caption)
            layout.addWidget(field)
        self.show_password = QCheckBox("Show password")
        self.show_password.toggled.connect(lambda visible: self.password.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        layout.addWidget(self.show_password)
        self.status = QLabel("Sign in with an approved account.")
        self.status.setObjectName("loginStatus")
        self.status.setAccessibleName("Sign-in status")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        note = QLabel("An approved account and internet connection are required for your first sign-in. "
                      "Saved approval allows offline use on this Windows account.")
        note.setObjectName("loginSecondary")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.submit = QPushButton("Sign in")
        self.submit.setObjectName("loginSubmit")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        footer = QHBoxLayout()
        footer.setContentsMargins(22, 4, 22, 4)
        footer.addWidget(self.submit)
        layout.addLayout(footer)
        self.email.setFocus()
        self._style_login()

    def _style_login(self):
        c = get_colors()
        self.setStyleSheet(f"""
            QDialog#privateLogin {{ background: {c['bg_surface']}; }}
            QLabel#loginProduct {{ font-size: 23px; font-weight: 600; }}
            QLabel#loginHeading {{ font-size: 21px; font-weight: 600; }}
            QLabel#loginSecondary {{ color: {c['text_secondary']}; }}
            QLabel#loginFieldLabel {{ font-weight: 600; }}
            QFrame#loginDivider {{ background: {c['border']}; border: none; }}
            QLineEdit#loginEmail, QLineEdit#loginPassword {{
                min-height: 26px; padding: 8px 12px; border-radius: 8px;
                border: 1px solid {c['border_strong']}; background: {c['bg_base']};
            }}
            QLineEdit#loginEmail:focus, QLineEdit#loginPassword:focus {{
                border: 1px solid {c['primary']};
            }}
            QLabel#loginStatus {{
                background: {c['primary_soft']}; color: {c['text_primary']};
                padding: 12px; border-radius: 8px;
            }}
            QPushButton#loginSubmit {{
                min-height: 28px; padding: 8px 20px; border-radius: 8px;
                background: {c['primary']}; color: {c['on_primary']};
                border: none; font-weight: 600;
            }}
            QPushButton#loginSubmit:hover {{ background: {c['primary_hover']}; }}
            QPushButton#loginSubmit:pressed {{ background: {c['primary_pressed']}; }}
            QPushButton#loginSubmit:disabled {{ background: {c['bg_active']}; color: {c['text_disabled']}; }}
        """)

    def showEvent(self, event):
        super().showEvent(event)
        self._style_login()

    def _submit(self):
        if not self.submit.isEnabled():
            return
        if not self.email.text().strip():
            self.status.setText("Enter your email address to continue.")
            self.email.setFocus()
        elif not self.password.text():
            self.status.setText("Enter your password to continue.")
            self.password.setFocus()
        else:
            password = self.password.text()
            self.password.clear()
            self.show_password.setChecked(False)
            self.signIn.emit(self.email.text(), password)

    def update_state(self, controller):
        self.submit.setEnabled(not controller.busy and not controller.stopping)
        self.email.setEnabled(not controller.busy)
        self.password.setEnabled(not controller.busy)
        self.show_password.setEnabled(not controller.busy)
        self.submit.setText("Signing in…" if controller.busy else "Sign in")
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
