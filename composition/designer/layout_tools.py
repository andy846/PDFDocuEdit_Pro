"""Shared layout commands for templates and PDF overlays."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QToolButton

from composition.template.geometry import fit_rotated_position
from composition.template.model import Template
from ui.icons import icon

GEOMETRY_KEYS = frozenset({"width_mm", "height_mm", "rotation_deg"})


def edit_geometry(window, values, *, relative_rotation=False):
    canvas = window.canvas
    if (not canvas.editable or canvas.mode_preview or getattr(window, "content_invalid", False)
            or getattr(window, "draft_error", "") or getattr(window, "font_requests", None)
            or getattr(window, "font_token", None)):
        return
    ids = set(canvas.selected_ids())
    if not ids or set(values)-GEOMETRY_KEYS:
        return
    if hasattr(window, "template"):
        before, after = window.template.to_dict(), window.template.to_dict()
        page = after["pages"][window.page_index]
        objects = page["elements"]
        width, height = page["width_mm"], page["height_mm"]
    else:
        after = window.spec.to_dict()
        objects = [item["element"] for item in after["objects"]]
        width, height = canvas.page_width, canvas.page_height
    try:
        for element in objects:
            if element["id"] in ids:
                update = dict(values)
                if relative_rotation:
                    update["rotation_deg"] = (element.get("rotation_deg", 0)+update["rotation_deg"]) % 360
                element.update(update)
                if "rotation_deg" in values:
                    fit_rotated_position(element, width, height)
        if hasattr(window, "template"):
            Template.from_dict(after)
            window._commit(before, after, "Set selected object geometry", list(ids))
        else:
            if not window.commit(after, "Set selected object geometry", list(ids)):
                window.properties.restore_geometry([item.element for item in canvas.element_items if item.element.id in ids])
    except ValueError as exc:
        window.properties.restore_geometry([item.element for item in canvas.element_items if item.element.id in ids])
        (window._error if hasattr(window, "template") else window.error)(str(exc))


def install_layout_tools(window, menu):
    quick_menu = QMenu(window)
    canvas = window.canvas
    from .arrange import ArrangeDialog
    arrange_action=QAction(icon("layers"),"Arrange selected objects…",window)
    arrange_action.setProperty("designer_icon","layers")
    arrange_action.triggered.connect(lambda:ArrangeDialog(window).exec())
    window.actions["arrange_tools"]=arrange_action
    menu.addAction(arrange_action)
    quick_menu.addAction(arrange_action)
    if not hasattr(window,"template"):
        canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def context(position):
            popup=QMenu(canvas)
            popup.addAction(arrange_action)
            for key in ("rotate_cw","rotate_ccw","rotate_reset"):
                popup.addAction(window.actions[key])
            popup.exec(canvas.viewport().mapToGlobal(position))
        canvas.customContextMenuRequested.connect(context)
    for key, title, setter, checked in (
        ("rulers", "Millimetre rulers", canvas.set_rulers, True),
        ("snap_guides", "Snap to page and object edges / centres", canvas.set_snap_guides, True),
        ("measure", "Measure distance (mm)", canvas.set_measure, False),
    ):
        action = QAction(icon("line-tool"), title, window)
        action.setProperty("designer_icon", "line-tool")
        action.setCheckable(True)
        action.setChecked(checked)
        action.toggled.connect(setter)
        window.actions[key] = action
        menu.addAction(action)
        quick_menu.addAction(action)
    canvas.measurementChanged.connect(lambda distance, dx, dy: (
        window.message.setText(f"Distance {distance:.2f} mm · X {dx:.2f} mm · Y {dy:.2f} mm")
        if hasattr(window, "message") else window.statusBar().showMessage(
            f"Distance {distance:.2f} mm · X {dx:.2f} mm · Y {dy:.2f} mm")))
    canvas.set_rulers(True)
    for key, title, angle in (("rotate_cw", "Rotate selected 90° clockwise", 90),
                              ("rotate_ccw", "Rotate selected 90° counterclockwise", -90),
                              ("rotate_reset", "Reset selected rotation", 0)):
        action = QAction(icon("rotate-cw"), title, window)
        action.setProperty("designer_icon", "rotate-cw")
        action.triggered.connect(lambda checked=False, a=angle: edit_geometry(
            window, {"rotation_deg": a}, relative_rotation=a != 0))
        window.actions[key] = action
        menu.addAction(action)
        quick_menu.addAction(action)
    for key in ("grid", "snap"):
        if key in window.actions:
            quick_menu.addAction(window.actions[key])
    button = QToolButton(window)
    button.setIcon(icon("line-tool"))
    button.setText("Layout")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setToolTip("Rulers, alignment snapping, measuring and rotation. Hold Alt while dragging to bypass snapping.")
    button.setAccessibleName("Canvas layout tools")
    button.setMenu(quick_menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    toolbar = getattr(window, "project_toolbar", None) or window.layout_toolbar
    toolbar.addWidget(button)
    window.layout_tools_button = button
    window.properties.geometryEdited.connect(lambda values: edit_geometry(window, values))
