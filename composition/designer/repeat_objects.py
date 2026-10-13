"""Exact, independent copies of a selection on existing template pages."""
from __future__ import annotations

import copy
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from composition.template.geometry import element_bounds
from composition.template.model import CompositionError, Template


def append_exact_copies(elements, page, *, vertical_offset=0):
    """Never clamp individual objects: preserve the selection's relative layout."""
    copies = copy.deepcopy(elements)
    for element in copies:
        element["id"] = uuid.uuid4().hex
        element["y_mm"] += vertical_offset
        x0, y0, x1, y1 = element_bounds(element)
        if x0 < -.001 or y0 < -.001 or x1 > page["width_mm"]+.001 or y1 > page["height_mm"]+.001:
            raise CompositionError(
                f"{page['name']}: a copied object would extend outside the page. "
                "Adjust the selection or choose another position option; nothing was copied."
            )
    page["elements"].extend(copies)
    return [element["id"] for element in copies]


def repeat_selection(value, source_id, selected_ids, target_ids, anchor="position"):
    """Return an atomic template edit; the original value is never changed."""
    if anchor not in {"position", "bottom"}:
        raise CompositionError("Unknown repeat position option.")
    after = copy.deepcopy(value)
    pages = {page["id"]: page for page in after["pages"]}
    if source_id not in pages or not target_ids or source_id in target_ids:
        raise CompositionError("Select one or more other template pages.")
    source = pages[source_id]
    selected = set(selected_ids)
    elements = [element for element in source["elements"] if element["id"] in selected]
    if not elements or len(elements) != len(selected):
        raise CompositionError("Select existing objects on the current template page.")
    for target in dict.fromkeys(target_ids):
        if target not in pages:
            raise CompositionError("A selected target page no longer exists.")
        page = pages[target]
        offset = page["height_mm"]-source["height_mm"] if anchor == "bottom" else 0
        append_exact_copies(elements, page, vertical_offset=offset)
    Template.from_dict(after)
    return after


class RepeatObjectsDialog(QDialog):
    def __init__(self, value, source_id, selected_ids, parent=None):
        super().__init__(parent)
        self.value, self.source_id, self.selected_ids = value, source_id, selected_ids
        self.setWindowTitle("Repeat on template pages")
        self.resize(480, 440)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Copy {len(selected_ids)} selected object(s) to:")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.pages = QListWidget()
        self.pages.setAccessibleName("Target template pages")
        for index, page in enumerate(value["pages"]):
            if page["id"] == source_id:
                continue
            item = QListWidgetItem(f"Page {index+1} · {page['name']} · {page['width_mm']:g} × {page['height_mm']:g} mm")
            item.setData(Qt.ItemDataRole.UserRole, page["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.pages.addItem(item)
        layout.addWidget(self.pages, 1)
        row = QHBoxLayout()
        for text, checked in (("Select all", True), ("Clear selection", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, on=checked: self.check_all(on))
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.anchor = QComboBox()
        self.anchor.setAccessibleName("Repeat position")
        self.anchor.addItem("Same X / Y position (mm)", "position")
        self.anchor.addItem("Same distance from page bottom", "bottom")
        layout.addWidget(self.anchor)
        note = QLabel("Copies keep sizes, formatting, fields, rules and spacing. "
                      "They remain independent; existing objects and backgrounds are retained.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Repeat validation")
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Repeat objects")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.pages.itemChanged.connect(self.validate_targets)
        self.anchor.currentIndexChanged.connect(self.validate_targets)
        self.validate_targets()

    def target_ids(self):
        return [self.pages.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.pages.count())
                if self.pages.item(i).checkState() == Qt.CheckState.Checked]

    def check_all(self, checked):
        self.pages.blockSignals(True)
        for index in range(self.pages.count()):
            self.pages.item(index).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.pages.blockSignals(False)
        self.validate_targets()

    def validate_targets(self, *_):
        self.result_value = None
        targets = self.target_ids()
        try:
            self.result_value = repeat_selection(self.value, self.source_id, self.selected_ids,
                                                 targets, self.anchor.currentData())
        except CompositionError as exc:
            self.status.setText(str(exc))
        else:
            source = next(page for page in self.value["pages"] if page["id"] == self.source_id)
            different = any((page["width_mm"], page["height_mm"]) != (source["width_mm"], source["height_mm"])
                            for page in self.value["pages"] if page["id"] in targets)
            message = f"{len(self.selected_ids)} object(s) × {len(targets)} page(s). One Undo restores all pages."
            if different:
                message += " Target page sizes differ. X is unchanged; " + (
                    "Y follows the page-bottom distance." if self.anchor.currentData() == "bottom"
                    else "X / Y stay at the original mm coordinates.")
            self.status.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.result_value is not None)

    def accept(self):
        self.validate_targets()
        if self.result_value is not None:
            super().accept()
