"""Detailed PDF encryption and decryption dialogs."""

from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .base import (
    PathLineEdit,
    ToolDialog,
    password_line_edit,
    remember_save_directory,
    start_in_save_directory,
)


def _save_picker(edit: QLineEdit, title: str, suggested: str) -> QWidget:
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    edit.setText(suggested)
    edit.setMinimumWidth(240)
    button = QPushButton("Browse…")

    def browse() -> None:
        current = edit.path()
        start = (
            current
            if current and Path(current).is_absolute()
            else start_in_save_directory(container, Path(suggested).name or "document.pdf")
        )
        value, _ = QFileDialog.getSaveFileName(container, title, start, "PDF (*.pdf)")
        if value:
            remember_save_directory(container, value)
            edit.setText(value if value.lower().endswith(".pdf") else f"{value}.pdf")

    button.clicked.connect(browse)
    row.addWidget(edit, 1)
    row.addWidget(button)
    return container


class EncryptDialog(ToolDialog):
    def __init__(self, source: Path, parent=None):
        super().__init__("Encrypt PDF", "encrypt-pdf", parent)
        self.source = source.resolve()
        self.details: dict[str, object] | None = None
        password_group = QGroupBox("Passwords")
        form = QFormLayout(password_group)
        self.user_password = password_line_edit()
        self.user_password.setToolTip("Password required to open the PDF (ASCII characters only)")
        self.confirm_password = password_line_edit()
        self.confirm_password.setToolTip("Re-enter the open password to confirm")
        self.owner_password = password_line_edit("Optional; a secure owner password is generated if blank")
        self.owner_password.setToolTip("Password to change permissions; leave blank for auto-generated")
        self.algorithm = QComboBox()
        self.algorithm.addItems(["AES-256 (recommended)", "AES-128"])
        self.algorithm.setToolTip("Encryption strength. AES-256 is stronger and widely supported.")
        form.addRow("Open password", self.user_password)
        form.addRow("Confirm password", self.confirm_password)
        form.addRow("Owner password", self.owner_password)
        form.addRow("Encryption", self.algorithm)
        self._root.addWidget(password_group)

        permissions = QGroupBox("Permissions for users who open the PDF")
        permissions_layout = QVBoxLayout(permissions)
        self.allow_print = QCheckBox("Allow printing")
        self.allow_print.setToolTip("Permit printing the document")
        self.allow_high_quality = QCheckBox("Allow high-quality printing")
        self.allow_high_quality.setToolTip("Permit high-resolution printing (requires printing enabled)")
        self.allow_copy = QCheckBox("Allow copying text and graphics")
        self.allow_copy.setToolTip("Permit copying text and images to the clipboard")
        self.allow_modify = QCheckBox("Allow document changes")
        self.allow_modify.setToolTip("Permit editing the document content")
        self.allow_annotate = QCheckBox("Allow comments and annotations")
        self.allow_annotate.setToolTip("Permit adding comments and annotations")
        self.allow_forms = QCheckBox("Allow filling form fields")
        self.allow_forms.setToolTip("Permit filling in interactive form fields")
        self.allow_assemble = QCheckBox("Allow page assembly")
        self.allow_assemble.setToolTip("Permit inserting, rotating, or deleting pages")
        self.allow_accessibility = QCheckBox("Allow accessibility extraction")
        self.allow_accessibility.setToolTip("Permit text extraction for assistive technology")
        self.allow_print.setChecked(True)
        self.allow_accessibility.setChecked(True)
        for box in (
            self.allow_print,
            self.allow_high_quality,
            self.allow_copy,
            self.allow_modify,
            self.allow_annotate,
            self.allow_forms,
            self.allow_assemble,
            self.allow_accessibility,
        ):
            permissions_layout.addWidget(box)
        self.allow_high_quality.toggled.connect(
            lambda checked: self.allow_print.setChecked(True) if checked else None
        )
        # Unchecking printing must also clear high-quality printing, whose
        # tooltip says it requires printing to be enabled.
        self.allow_print.toggled.connect(
            lambda checked: self.allow_high_quality.setChecked(False)
            if not checked
            else None
        )
        self._root.addWidget(permissions)

        output_group = QGroupBox("Output")
        output_form = QFormLayout(output_group)
        self.output = PathLineEdit()
        output_form.addRow(
            "Encrypted PDF",
            _save_picker(self.output, "Save encrypted PDF", str(source.with_name(f"{source.stem}_encrypted.pdf"))),
        )
        self._root.addWidget(output_group)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Encrypt")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        password = self.user_password.text()
        if not password:
            self.show_error("Enter a password required to open the PDF.")
            return
        if password != self.confirm_password.text():
            self.show_error("The open passwords do not match.")
            return
        output = Path(self.output.path())
        if not self.output.path().strip() or not output.parent.is_dir():
            self.show_error("Choose a valid output PDF location.")
            return
        if output.suffix.casefold() != ".pdf":
            output = output.with_suffix(".pdf")
        if output.resolve() == self.source:
            self.show_error("Choose a new output file instead of overwriting the open PDF.")
            return
        permissions = 0
        pairs = (
            (self.allow_print, fitz.PDF_PERM_PRINT),
            (self.allow_high_quality, fitz.PDF_PERM_PRINT_HQ),
            (self.allow_copy, fitz.PDF_PERM_COPY),
            (self.allow_modify, fitz.PDF_PERM_MODIFY),
            (self.allow_annotate, fitz.PDF_PERM_ANNOTATE),
            (self.allow_forms, fitz.PDF_PERM_FORM),
            (self.allow_assemble, fitz.PDF_PERM_ASSEMBLE),
            (self.allow_accessibility, fitz.PDF_PERM_ACCESSIBILITY),
        )
        for box, flag in pairs:
            if box.isChecked():
                permissions |= int(flag)
        self.details = {
            "user_password": password,
            "owner_password": self.owner_password.text(),
            "algorithm": fitz.PDF_ENCRYPT_AES_256 if self.algorithm.currentIndex() == 0 else fitz.PDF_ENCRYPT_AES_128,
            "permissions": permissions,
            "output": str(output),
        }
        self.accept()


class DecryptDialog(ToolDialog):
    def __init__(self, source: Path, parent=None):
        super().__init__("Remove PDF Security", "decrypt-pdf", parent)
        self.source = source.resolve()
        self.output_path = ""
        note = QLabel(
            "The document has already been authenticated when it was opened. Save a new copy "
            "without encryption and password restrictions."
        )
        note.setWordWrap(True)
        note.setObjectName("secondary")
        self._root.addWidget(note)
        output = QGroupBox("Output")
        form = QFormLayout(output)
        self.output = PathLineEdit()
        form.addRow(
            "Decrypted PDF",
            _save_picker(self.output, "Save decrypted PDF", str(source.with_name(f"{source.stem}_decrypted.pdf"))),
        )
        self._root.addWidget(output)
        self._root.addStretch(1)
        self.add_validation()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Remove Security")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)

    def _validate(self) -> None:
        output = Path(self.output.path())
        if not self.output.path().strip() or not output.parent.is_dir():
            self.show_error("Choose a valid output PDF location.")
            return
        if output.suffix.casefold() != ".pdf":
            output = output.with_suffix(".pdf")
        if output.resolve() == self.source:
            self.show_error("Choose a new output file instead of overwriting the open PDF.")
            return
        self.output_path = str(output)
        self.accept()
