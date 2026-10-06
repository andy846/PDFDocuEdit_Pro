"""Shared Build / Review / Run chrome without changing workflow execution semantics."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .model import LABELS
from .node_presentation import CATEGORIES
from .registry import EXTRA_KINDS


def install(window):
    w=window
    w.tabs.setObjectName("designerPanelTabs")
    for index,text in enumerate(("Build","Review","Run")):
        w.tabs.setTabText(index,text)
    w.layout_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    # Keep Save visible in every project, with file commands also in the shared menu.
    for key in ("new","open","fit","step"):
        w.layout_toolbar.removeAction(w.actions[key])
    w.layout_toolbar.widgetForAction(w.actions["save"]).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    w.actions["save"].setToolTip("Save workflow (Ctrl+S)")
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
    w.library_category=QComboBox()
    w.library_category.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    w.library_category.setMinimumContentsLength(10)
    w.library_category.addItem("All categories","")
    for category in CATEGORIES:
        w.library_category.addItem(category,category)
    def filter_category():
        w.toolbox.category_name=w.library_category.currentData()
        w.toolbox.filter(w.library_search.text())
    w.library_category.currentIndexChanged.connect(filter_category)
    layout.addWidget(w.library_category)
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
            w.insert_step(kind)
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
        control=QToolButton()
        control.setText(text)
        control.setProperty("compact",True)
        control.clicked.connect(callback)
        row.addWidget(control)
        return control
    w.panel_preferences={"library":None,"details":True}
    w.panel_sizes={}
    w.library_toggle=button("Steps",lambda:toggle_panel(w,"library"))
    w.settings_toggle=button("Settings",lambda:toggle_panel(w,"details"))
    w.panel_view=QComboBox()
    w.panel_view.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    w.panel_view.setMinimumContentsLength(8)
    w.panel_view.setAccessibleName("Workflow panel layout")
    for name,value in (("Split view","split"),("Steps","steps"),("Canvas","canvas"),("Details","details")):
        w.panel_view.addItem(name,value)
    w.panel_view.setToolTip("Use one full-width panel on a small screen")
    w.panel_view.currentIndexChanged.connect(lambda *_:layout_panels(w))
    row.addWidget(w.panel_view)
    w.splitter.splitterMoved.connect(lambda *_:remember_sizes(w))
    w.next_step=QToolButton()
    w.next_step.setText("Add next step")
    w.next_step.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    w.next_menu=QMenu(w.next_step)
    w.next_menu.aboutToShow.connect(lambda:populate_next(w))
    w.next_step.setMenu(w.next_menu)
    row.addWidget(w.next_step)
    view=QToolButton()
    view.setText("View")
    view.setProperty("compact",True)
    view.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu=QMenu(view)
    w.auto_layout_action=menu.addAction("Auto Layout",lambda:auto_layout(w))
    menu.addAction("Fit",w.canvas.fit)
    menu.addAction("Reset",w.canvas.reset_view)
    view.setMenu(menu)
    row.addWidget(view)
    row.addStretch()
    button("−",lambda:w.canvas.zoom(1/1.15))
    w.zoom_label=QLabel("100%")
    row.addWidget(w.zoom_label)
    w.canvas.zoomChanged.connect(lambda value:w.zoom_label.setText(f"{value:.0%}"))
    button("+",lambda:w.canvas.zoom(1.15))
    w.flow_page.layout().addWidget(footer)
    w.tabs.currentChanged.connect(lambda *_:context(w))
    context(w)


def populate_next(w):
    w.next_menu.clear()
    node=next((n for n in w.spec.nodes if n.id==w.selected),None)
    unavailable=w.next_menu.addMenu("Why other steps are unavailable")
    unavailable.setToolTipsVisible(True)
    for kind in sorted(k for k in w.spec.kinds if k not in ("input","data")):
        reason=""
        if node is None:
            reason="Select a source step first."
        elif kind not in w.spec.allowed_next(node.kind):
            reason=f"{LABELS[kind]} cannot use the output of {LABELS[node.kind]} at this position."
        elif w.spec.workflow_version>=3:
            try:
                from .model import WorkflowNode
                from .registry import default_options, validate_chain
                if kind in EXTRA_KINDS:
                    prefix=w.spec.execution_prefix(node.id)
                    validate_chain([*prefix,WorkflowNode(kind,params=default_options(kind))],w.spec.project_kind)
                    w.spec.insert_after(node.id,WorkflowNode(kind,params=default_options(kind)))
                else:
                    target=w.spec.node(kind)
                    if target and any(b==target.id and a!=node.id for a,b in w.spec.edges):
                        raise ValueError("This step already has an incoming connection; disconnect it first.")
            except ValueError as exc:
                reason=str(exc)
        if reason:
            action=unavailable.addAction(LABELS[kind]+" — "+reason)
            action.setEnabled(False)
            action.setToolTip(reason)
            continue
        target=w.spec.node(kind)
        if kind in EXTRA_KINDS:
            w.next_menu.addAction("Insert "+LABELS[kind],lambda checked=False,k=kind:w.insert_step(k))
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
    if len(w.next_menu.actions())==1:
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
        if getattr(w,"_workflow_band",None):
            remember_sizes(w)
        w._workflow_band=band
        layout_panels(w)
    apply_panel_limits(w)


def remember_sizes(w):
    if w.panel_view.currentData()=="split" and getattr(w,"_workflow_band",None):
        sizes=w.splitter.sizes()
        if sizes[1]>0:
            w.panel_sizes[w._workflow_band]=sizes


def toggle_panel(w,panel):
    widget=w.library if panel=="library" else w.inspector_scroll
    w.panel_preferences[panel]=not widget.isVisible()
    if w.panel_view.currentData()!="split":
        w.panel_view.setCurrentIndex(0)
    layout_panels(w)


def apply_panel_limits(w):
    band=getattr(w,"_workflow_band","wide")
    single=w.panel_view.currentData()!="split"
    w.library.setMaximumWidth(16777215 if single else 230)
    w.inspector_scroll.setMinimumWidth(210 if band=="narrow" else 260)
    w.inspector_scroll.setMaximumWidth(16777215 if single else 360 if band=="wide" else 300)


def layout_panels(w):
    mode=w.panel_view.currentData()
    band=getattr(w,"_workflow_band","wide")
    left=w.panel_preferences["library"]
    left=band=="wide" if left is None else left
    right=w.panel_preferences["details"]
    w.library.setVisible(mode=="steps" or mode=="split" and left)
    w.canvas.setVisible(mode in ("split","canvas"))
    w.inspector_scroll.setVisible(mode=="details" or mode=="split" and right)
    apply_panel_limits(w)
    if mode=="split":
        a,b=(180,310) if band=="wide" else (180,280)
        a=a if left else 0
        b=b if right else 0
        sizes=w.panel_sizes.get(band,[a,max(200,w.width()-a-b-20),b])
        w.splitter.setSizes([sizes[0] or a if left else 0,sizes[1],sizes[2] or b if right else 0])
    else:
        w.splitter.setSizes([w.width() if mode=="steps" else 0,w.width() if mode=="canvas" else 0,w.width() if mode=="details" else 0])
