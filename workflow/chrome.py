"""Shared Build / Review / Run chrome without changing workflow execution semantics."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .model import LABELS
from .registry import EXTRA_KINDS


def install(window):
    w=window
    w.tabs.setObjectName("designerPanelTabs")
    for index,text in enumerate(("Build","Review","Run")):
        w.tabs.setTabText(index,text)
    w.layout_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    # File actions remain in the shared main menu. Keep the project toolbar compact.
    for key in ("new","open","save","fit","step"):
        w.layout_toolbar.removeAction(w.actions[key])
    w.actions["scan"].setText("Check && Preview")
    w.actions["scan"].setIconText("Check && Preview")
    w.actions["generate"].setText("Run workflow")
    w.actions["generate"].setIconText("Run workflow")
    w.add_step.hide()
    for action in w.layout_toolbar.actions():
        if w.layout_toolbar.widgetForAction(action) is w.add_step:
            w.layout_toolbar.removeAction(action)
    w.library=QWidget()
    w.library.setObjectName("designerSidePanel")
    layout=QVBoxLayout(w.library)
    layout.setContentsMargins(8,8,8,8)
    heading=QLabel("STEPS")
    layout.addWidget(heading)
    w.library_search=QLineEdit()
    w.library_search.setPlaceholderText("Find a step…")
    w.library_search.setClearButtonEnabled(True)
    w.library_search.textChanged.connect(w.toolbox.filter)
    layout.addWidget(w.library_search)
    w.toolbox.setParent(w.library)
    layout.addWidget(w.toolbox,1)
    tip=QLabel("Drag a step onto the canvas, or choose Add next step.")
    tip.setWordWrap(True)
    layout.addWidget(tip)
    w.splitter.insertWidget(0,w.library)
    w.library.setMaximumWidth(230)
    w.canvas.setAccessibleName("Visual workflow canvas")
    w.toolbox.itemDoubleClicked.disconnect()
    def choose_step(item):
        kind=item.data(Qt.ItemDataRole.UserRole)
        node=w.spec.node(kind)
        if kind in EXTRA_KINDS:
            w.ensure_v3(lambda:w.insert_step(kind))
        elif node:
            w.canvas.scene().clearSelection()
            w.canvas.nodes[node.id].setSelected(True)
            w.canvas.ensureVisible(w.canvas.nodes[node.id])
        else:
            w.add_node(kind,0,150)
    w.toolbox.itemDoubleClicked.connect(choose_step)
    footer=QWidget()
    row=QHBoxLayout(footer)
    row.setContentsMargins(0,0,0,0)
    def button(text,callback):
        control=QPushButton(text)
        control.setProperty("compact",True)
        control.clicked.connect(callback)
        row.addWidget(control)
        return control
    w.library_toggle=button("Steps",lambda:w.library.setVisible(not w.library.isVisible()))
    w.settings_toggle=button("Settings",lambda:w.inspector_scroll.setVisible(not w.inspector_scroll.isVisible()))
    w.next_step=QToolButton()
    w.next_step.setText("Add next step")
    w.next_step.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    w.next_menu=QMenu(w.next_step)
    w.next_menu.aboutToShow.connect(lambda:populate_next(w))
    w.next_step.setMenu(w.next_menu)
    row.addWidget(w.next_step)
    button("Auto Layout",lambda:auto_layout(w))
    row.addStretch()
    button("−",lambda:w.canvas.zoom(1/1.15))
    w.zoom_label=QLabel("100%")
    row.addWidget(w.zoom_label)
    w.canvas.zoomChanged.connect(lambda value:w.zoom_label.setText(f"{value:.0%}"))
    button("+",lambda:w.canvas.zoom(1.15))
    button("Fit",w.canvas.fit)
    button("Reset",w.canvas.reset_view)
    w.flow_page.layout().addWidget(footer)
    w.tabs.currentChanged.connect(lambda *_:context(w))
    context(w)


def populate_next(w):
    w.next_menu.clear()
    node=next((n for n in w.spec.nodes if n.id==w.selected),None)
    for kind in sorted(w.spec.allowed_next(node.kind) if node else []):
        target=w.spec.node(kind)
        if kind in EXTRA_KINDS:
            w.next_menu.addAction("Insert "+LABELS[kind],lambda checked=False,k=kind:w.ensure_v3(lambda:w.insert_step(k)))
            continue
        label=("Connect to " if target else "Add ")+LABELS[kind]
        def connect(checked=False,k=kind):
            source=next(n for n in w.spec.nodes if n.id==w.selected)
            if not w.spec.node(k):
                w.add_node(k,source.x+230,source.y)
            target=w.spec.node(k)
            if target:
                w.connect_nodes(source.id,target.id)
        w.next_menu.addAction(label,connect)
    if not w.next_menu.actions():
        act=w.next_menu.addAction("This is the final step")
        act.setEnabled(False)


def auto_layout(w):
    if not w.flush_settings():
        return
    raw=w.spec.to_dict()
    try:
        order=[n.id for n in w.spec.chain()]
    except ValueError:
        order=[n.id for n in w.spec.nodes]
    for node in raw["nodes"]:
        index=order.index(node["id"])
        node.update(x=(index%3)*230,y=(index//3)*150)
    if w.commit(raw,"Arrange workflow"):
        w.canvas.fit()


def context(w):
    index=w.tabs.currentIndex()
    for key in ("undo","redo"):
        w.actions[key].setVisible(index==0)
    w.actions["scan"].setVisible(index!=2)
    w.actions["generate"].setVisible(index!=0)
    w.actions["cancel"].setVisible(bool(w.active_worker))


def resize(w):
    band="narrow" if w.width()<1080 else "wide"
    if band!=getattr(w,"_workflow_band",None):
        w._workflow_band=band
        w.library.setVisible(band=="wide")
        left,right=(180,310) if band=="wide" else (0,280)
        w.splitter.setSizes([left,max(200,w.width()-left-right-20),right])
    w.inspector_scroll.setMinimumWidth(210 if band=="narrow" else 260)
    w.inspector_scroll.setMaximumWidth(360 if band=="wide" else 300)
