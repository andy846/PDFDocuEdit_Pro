"""Per-document staged AcroForm state and its embedded inspector."""

from __future__ import annotations

from dataclasses import dataclass, field

import fitz
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.forms import FormField, apply_values, enumerate_fields


@dataclass
class FormDraft:
    identity: tuple[object, int]
    snapshot: bytes
    fields: list[FormField]
    staged: dict[str, object] = field(default_factory=dict)
    signatures: dict[str, bytes] = field(default_factory=dict)
    preview: fitz.Document | None = None

    @classmethod
    def from_snapshot(cls, identity: tuple[object, int], snapshot: bytes) -> FormDraft:
        with fitz.open(stream=snapshot, filetype="pdf") as document:
            fields = enumerate_fields(document)
        return cls(identity, snapshot, fields)

    @property
    def changed(self) -> bool:
        return bool(self.staged or self.signatures)

    def field_at(self, page: int, point: fitz.Point) -> tuple[FormField, object] | None:
        for item in self.fields:
            for ref in item.widgets:
                if ref.page == page and fitz.Rect(ref.rect).contains(point):
                    return item, ref
        return None

    def stage(self, item: FormField, value: object) -> None:
        if value == item.value:
            self.staged.pop(item.name, None)
        else:
            self.staged[item.name] = value

    def current_value(self, item: FormField) -> object:
        return self.staged.get(item.name, item.value)

    def build_preview(self) -> fitz.Document:
        document = fitz.open(stream=self.snapshot, filetype="pdf")
        try:
            apply_values(document, self.staged, self.signatures, acknowledge_scripts=True)
        except Exception:
            document.close()
            raise
        return document

    def release(self) -> None:
        if self.preview is not None and not self.preview.is_closed:
            self.preview.close()
        self.preview = None


class FormPanel(QWidget):
    fieldSelected = pyqtSignal(str)
    applyRequested = pyqtSignal()
    discardRequested = pyqtSignal()
    previewRequested = pyqtSignal()
    reloadRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.notice = QLabel(
            "Click a field on the PDF to fill it. Changes stay in this document until Apply."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.fields = QListWidget()
        self.fields.setObjectName("formFields")
        def select_field(item):
            self.fieldSelected.emit(str(item.data(Qt.ItemDataRole.UserRole)))

        self.fields.itemClicked.connect(select_field)
        self.fields.itemActivated.connect(select_field)
        layout.addWidget(self.fields, 1)
        self.preview_button = QPushButton("Update preview")
        self.preview_button.clicked.connect(self.previewRequested.emit)
        layout.addWidget(self.preview_button)
        row = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.applyRequested.emit)
        row.addWidget(self.apply_button)
        self.discard_button = QPushButton("Discard draft")
        self.discard_button.clicked.connect(self.discardRequested.emit)
        row.addWidget(self.discard_button)
        layout.addLayout(row)
        self.reload_button = QPushButton("Reload fields")
        self.reload_button.clicked.connect(self.reloadRequested.emit)
        layout.addWidget(self.reload_button)
        note = QLabel("Signature appearances are pictures only; they do not digitally sign the PDF.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.set_draft(None)

    def set_draft(self, draft: FormDraft | None, *, stale: bool = False) -> None:
        self.fields.clear()
        if draft is None:
            self.status.setText("No PDF form is active.")
            self.apply_button.setEnabled(False)
            self.discard_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.reload_button.hide()
            return
        for item in draft.fields:
            flags = ", ".join(
                label
                for label, present in (
                    ("Read only", item.readonly),
                    ("Required", item.required),
                    ("Calculated", bool(item.calculation)),
                    ("Signed", item.signed),
                )
                if present
            )
            value = draft.current_value(item)
            label = f"{item.name} · {value if value is not None else ''}"
            if flags:
                label += f" · {flags}"
            entry = QListWidgetItem(label)
            entry.setData(Qt.ItemDataRole.UserRole, item.name)
            self.fields.addItem(entry)
        self.status.setText(
            "Document changed. Reload fields before applying this draft."
            if stale
            else f"{len(draft.fields)} field(s) · {'Unapplied changes' if draft.changed else 'No changes'}"
        )
        self.apply_button.setEnabled(draft.changed and not stale)
        self.discard_button.setEnabled(draft.changed)
        self.preview_button.setEnabled(draft.changed and not stale)
        self.reload_button.setVisible(stale)


class FormMultilineEditor(QPlainTextEdit):
    finishRequested = pyqtSignal(bool)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finishRequested.emit(False)
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.finishRequested.emit(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.finishRequested.emit(True)


class FormChoiceEditor(QFrame):
    valueCommitted = pyqtSignal(object)

    def __init__(self, choices, value, *, multiple: bool = False, editable: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("formChoiceEditor")
        layout = QVBoxLayout(self)
        options = [
            (choice[0], choice[1]) if isinstance(choice, (tuple, list)) else (choice, choice)
            for choice in choices
        ]
        if multiple:
            self.list = QListWidget()
            self.list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            for export, label in options:
                item = QListWidgetItem(str(label), self.list)
                item.setData(Qt.ItemDataRole.UserRole, export)
                item.setSelected(export in (value if isinstance(value, list) else [value]))
            layout.addWidget(self.list)
            apply_button = QPushButton("Use selected options")
            apply_button.clicked.connect(
                lambda: self.valueCommitted.emit(
                    [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
                )
            )
            layout.addWidget(apply_button)
        else:
            self.combo = QComboBox()
            for export, label in options:
                self.combo.addItem(str(label), export)
            self.combo.setEditable(editable)
            if editable:
                self.combo.setCurrentText(str(value or ""))
            else:
                self.combo.setCurrentIndex(max(0, self.combo.findData(value)))
            layout.addWidget(self.combo)
            apply_button = QPushButton("Use value")
            apply_button.clicked.connect(
                lambda: self.valueCommitted.emit(
                    self.combo.currentText() if editable else self.combo.currentData()
                )
            )
            layout.addWidget(apply_button)
