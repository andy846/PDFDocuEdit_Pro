"""Type filtering and current-page selection for both Designer workspaces."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QComboBox, QPushButton, QSizePolicy

from .arrange import current_elements, report


def filter_types(window):
    chosen = window.layer_type.currentData()
    if not chosen:
        return
    if hasattr(window, "template"):
        types = {e.id: e.type for e in window.page.elements}
    else:
        types = {obj.element.id: obj.element.type for obj in window.spec.objects} if window.spec else {}
    for row in range(window.layers.count()):
        item = window.layers.item(row)
        if types.get(item.data(Qt.ItemDataRole.UserRole)) != chosen:
            item.setHidden(True)


def selected_type(window):
    chosen = window.layer_type.currentData()
    if chosen:
        return chosen
    ids = set(window.canvas.selected_ids())
    types = {e.type for e in current_elements(window) if e.id in ids}
    return next(iter(types)) if len(types) == 1 else None


def update_type_action(window):
    if window.close_pending or not hasattr(window, "layer_type"):
        return
    allowed = bool(selected_type(window) and window.canvas.editable and not window.canvas.mode_preview
                   and not getattr(window, "batch_pending", False))
    window.actions["select_type"].setEnabled(allowed)
    window.select_type_button.setEnabled(allowed)


def install_selection_tools(window, menu):
    window.layer_type = QComboBox()
    window.layer_type.setMinimumWidth(0)
    window.layer_type.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    window.layer_type.setAccessibleName("Filter objects by type")
    for title, kind in (("All object types", ""), ("Text", "text"), ("Code 128", "code128"),
                        ("I25", "i25"), ("QR code", "qr"), ("Image", "image"),
                        ("Line", "line"), ("Rectangle", "rectangle")):
        window.layer_type.addItem(title, kind)
    action = QAction("Select same type on current page", window)
    window.actions["select_type"] = action
    menu.addAction(action)
    button = window.select_type_button = QPushButton("Select type")
    button.setAccessibleName("Select all objects of this type on current page")
    button.setToolTip("Select the filtered type, or the selected object's type, on this page only.")
    button.clicked.connect(action.trigger)
    layout = window.layers.parentWidget().layout()
    layout.insertWidget(0, window.layer_type)
    layout.insertWidget(1, button)

    def select(*args):
        kind = selected_type(window)
        if not kind:
            report(window, "Choose an object type or select one type first.")
            return
        if window.canvas.editable and not window.canvas.mode_preview:
            window.canvas.select_ids([e.id for e in current_elements(window) if e.type == kind])

    def changed(*args):
        (window._filter_layers if hasattr(window, "template") else window.filter_layers)()
        update_type_action(window)

    action.triggered.connect(select)
    window.layer_type.currentIndexChanged.connect(changed)
    window.canvas.selectionChanged.connect(lambda *args: update_type_action(window))
    update_type_action(window)
