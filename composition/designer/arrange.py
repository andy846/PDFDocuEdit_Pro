"""Shared arrangement UI and atomic template/overlay commits."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from composition.template.layout import OPERATIONS, arrange_elements
from composition.template.model import Template


def report(window, message):
    (window._error if hasattr(window, "template") else window.error)(str(message))


def current_elements(window):
    return [item.element for item in window.canvas.element_items]


def commit_elements(window, changed, label):
    ids = window.canvas.selected_ids()
    changes = {e["id"]: e for e in changed}
    if hasattr(window, "template"):
        before, after = window.template.to_dict(), window.template.to_dict()
        elements = after["pages"][window.page_index]["elements"]
        for i, e in enumerate(elements):
            if e["id"] in changes:
                elements[i] = changes[e["id"]]
        Template.from_dict(after)
        window._commit(before, after, label, ids)
        return True
    after = window.spec.to_dict()
    for obj in after["objects"]:
        if obj["element"]["id"] in changes:
            obj["element"] = changes[obj["element"]["id"]]
    return window.commit(after, label, ids)


def arrange(window, operation, *, reference="selection", reference_id=None, gap=5):
    if not window.canvas.editable or window.canvas.mode_preview or getattr(window, "font_requests", None) or getattr(window, "font_token", None):
        return False
    from dataclasses import asdict
    try:
        changed = arrange_elements([asdict(e) for e in current_elements(window)], window.canvas.selected_ids(), operation,
                                   (window.canvas.page_width, window.canvas.page_height), reference=reference, reference_id=reference_id, gap=gap)
        return commit_elements(window, changed, OPERATIONS[operation])
    except ValueError as exc:
        report(window, exc)
        return False


class ArrangeDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Arrange selected objects")
        self.resize(430, 280)
        root = QVBoxLayout(self)
        count = QLabel(f"{len(window.canvas.selected_ids())} selected · One Undo per operation")
        root.addWidget(count)
        form = QFormLayout()
        self.operation = QComboBox()
        for key, label in OPERATIONS.items():
            self.operation.addItem(label, key)
        self.reference = QComboBox()
        self.reference.addItem("Selection bounds / first selected size", "selection")
        self.reference.addItem("Page", "page")
        self.reference.addItem("Reference object", "object")
        self.object = QComboBox()
        for e in current_elements(window):
            self.object.addItem(f"{e.type.title()} · {e.value[:35] or e.id[:8]}", e.id)
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 2000)
        self.gap.setDecimals(2)
        self.gap.setValue(5)
        self.gap.setSuffix(" mm")
        for label, control in (("Operation", self.operation), ("Reference", self.reference), ("Object", self.object), ("Gap", self.gap)):
            form.addRow(label, control)
        root.addLayout(form)
        self.feedback = QLabel("Edges and gaps follow rotated visible bounds. Width and height use the unrotated box.")
        self.feedback.setWordWrap(True)
        root.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.operation.currentIndexChanged.connect(self.availability)
        self.reference.currentIndexChanged.connect(self.availability)
        self.availability()

    def availability(self):
        gap = self.operation.currentData().startswith("gap_")
        distributed = self.operation.currentData() in {"horizontal", "vertical"}
        self.gap.setEnabled(gap)
        self.reference.setEnabled(not gap and not distributed)
        self.object.setEnabled(self.reference.isEnabled() and self.reference.currentData() == "object")

    def apply(self):
        if arrange(self.window, self.operation.currentData(), reference=self.reference.currentData(),
                   reference_id=self.object.currentData(), gap=self.gap.value()):
            self.feedback.setText("Applied. Layout and selection retained; use Undo to revert.")
        else:
            self.feedback.setText(self.window.message.text() if hasattr(self.window, "message") else self.window.statusBar().currentMessage())
