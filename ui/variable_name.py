"""Compact naming editor with the same resolver as production."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from core.variables import VariableContext, VariableError, resolve_filename, validate_filename
from core.variables.model import ResolvedValue


class VariableNameEdit(QWidget):
    def __init__(self, value="production.pdf", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.edit = QLineEdit(value)
        self.edit.setAccessibleName("Production PDF filename or variable naming template")
        self.edit.setPlaceholderText("{{input.stem}}_{{JobID}}.pdf")
        self.edit.setToolTip("Use {{input.stem}}, {{job.id}}, {{system.date}}, or {{workflow.sequence|pad:6}}. "
                             "Single-job names cannot use varying customer fields.")
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.edit)
        layout.addWidget(self.preview)
        self.context = VariableContext.for_job(input_path="example.csv", job_id="example-job", sequence=1)
        self.prepared = False
        self.edit.textChanged.connect(self.refresh)
        self.refresh()

    def set_context(self, context, *, prepared=False):
        self.context = context
        self.prepared = prepared
        self.refresh()

    def resolution(self):
        value = self.edit.text().strip()
        if "{{" in value:
            return resolve_filename(value, self.context, extension=".pdf")
        return ResolvedValue(validate_filename(value, extension=".pdf"))

    def resolved(self):
        return self.resolution().value

    def refresh(self, *_):
        try:
            result = self.resolution()
            details = "\n".join(result.issues)
            self.preview.setText(("Prepared output: " if self.prepared else "Example output: ") + result.value
                                 + ("\n" + details if details else ""))
            self.preview.setToolTip(result.value + ("\n" + details if details else ""))
            self.edit.setProperty("invalid", False)
        except VariableError as exc:
            self.preview.setText("Output naming: " + str(exc))
            self.preview.setToolTip(str(exc))
            self.edit.setProperty("invalid", True)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        self.edit.update()

    def text(self):
        return self.edit.text().strip()
