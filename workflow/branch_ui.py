"""Bounded Mail Merge graph workspace; production is always explicitly approved."""
from __future__ import annotations

import copy
import json
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QAbstractTableModel, QEvent, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QPixmap, QUndoStack
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from composition.designer.process import Worker
from composition.template.model import ConditionGroup, DataConfig, RuleCondition
from ui.icons import icon

from .branch_canvas import BranchCanvas
from .branch_graph import COMMON, add_route, edge
from .model import LABELS, WorkflowNode, WorkflowSpec
from .node_presentation import description, settings_summary
from .registry import DATA_KINDS, default_options
from .workspace import ProjectProperties, WorkflowEdit


class EvidenceModel(QAbstractTableModel):
    """Plain value model: never creates per-record widgets or loads all record data."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.records=[]
        self.columns=[]

    def rowCount(self,parent=None):
        return 0 if parent and parent.isValid() else len(self.records)

    def columnCount(self,parent=None):
        return len(self.columns)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row=self.records[index.row()]
        if role==Qt.ItemDataRole.UserRole:
            return row
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            key=self.columns[index.column()]
            return str(row.get("value",{}).get(key,row.get(key,"")))

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal:
            return self.columns[section].replace("_"," ").title()

    def update(self,records,columns):
        self.beginResetModel()
        self.records,self.columns=records,columns
        self.endResetModel()


def table(parent):
    view=QTableView(parent)
    model=EvidenceModel(view)
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.horizontalHeader().setStretchLastSection(True)
    view.setAlternatingRowColors(True)
    return view,model


class RouteDialog(QDialog):
    def __init__(self,route,fields,parent=None):
        super().__init__(parent)
        from composition.designer.rules_dialog import ConditionEditor
        self.setWindowTitle("Template route · Exclusive condition")
        self.resize(740,460)
        layout=QVBoxLayout(self)
        form=QFormLayout()
        self.name=QLineEdit(route.get("name","New letters"))
        self.name.setMaxLength(100)
        form.addRow("Route name",self.name)
        self.fallback=QCheckBox("Explicit fallback · only when no condition matches")
        self.fallback.setChecked(route.get("fallback",False))
        form.addRow(self.fallback)
        layout.addLayout(form)
        options=route.get("condition",{})
        group=ConditionGroup(options.get("mode","all"),[RuleCondition(**c) for c in options.get("conditions",[])])
        self.conditions=ConditionEditor("Route matching records",fields,group if group.conditions else None,self)
        self.conditions.setChecked(True)
        self.conditions.setEnabled(not self.fallback.isChecked())
        self.fallback.toggled.connect(lambda checked:self.conditions.setEnabled(not checked))
        layout.addWidget(self.conditions,1)
        warning=QLabel("More than one matching route sends the record to Exceptions. Conditions do not use first-match priority.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.error=QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            if not self.name.text().strip():
                raise ValueError("Enter a route name.")
            self.options={"name":self.name.text().strip(),"fallback":self.fallback.isChecked()}
            if not self.options["fallback"]:
                self.options["condition"]=asdict(self.conditions.read_group())
                from .transforms import condition
                condition(self.options["condition"])
        except (ValueError,TypeError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()


class BranchWorkflowWindow(QMainWindow):
    activityChanged=pyqtSignal()
    projectClosed=pyqtSignal()
    is_workflow=True

    def __init__(self,parent=None,*,embedded=False,project_host=None):
        super().__init__(parent,Qt.WindowType.Widget if embedded else Qt.WindowType.Window)
        self.embedded,self.project_host=embedded,project_host
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,embedded)
        self.spec=WorkflowSpec.branched_mail_merge()
        self.project_path=None
        self.temp=tempfile.TemporaryDirectory(prefix="vw-")
        self.directory=Path(self.temp.name)
        self.run={}
        self.workers=[]
        self.active_worker=None
        self.close_pending=False
        self._close_approved=False
        self.draft_error=""
        self.node_drafts={}
        self.selected=self.spec.nodes[0].id
        self.properties=ProjectProperties(self)
        self.undo=QUndoStack(self)
        self.actions={}
        self.offset=0
        self.evidence_token=0
        self.current_evidence={}
        self.setup_chrome()
        self.setup_build()
        self.setup_review()
        self.setup_production()
        self.progress=QProgressBar()
        self.progress.setMaximumHeight(16)
        self.statusBar().addPermanentWidget(self.progress)
        self.progress.hide()
        self.undo.indexChanged.connect(self.title)
        self.undo.canUndoChanged.connect(self.lock)
        self.undo.canRedoChanged.connect(self.lock)
        self.refresh_graph()
        self.select_node(self.selected)
        self.undo.setClean()
        self.resize(1280,800)
        QTimer.singleShot(0,self.start_view)

    def setup_chrome(self):
        toolbar=QToolBar("Visual Workflow")
        toolbar.setObjectName("designerMainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        file=self.menuBar().addMenu("&Workflow")
        edit=self.menuBar().addMenu("&Edit")
        def action(key,label,callback,shortcut="",symbol="file-text",bar=True):
            act=QAction(icon(symbol),label,self)
            act.setProperty("workflow_icon",symbol)
            act.triggered.connect(callback)
            act.setShortcut(shortcut)
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.actions[key]=act
            file.addAction(act)
            if bar:
                toolbar.addAction(act)
        action("new","New workflow",self.new_project,"Ctrl+N")
        action("open","Open…",self.open_project,"Ctrl+O","folder-open")
        action("save","Save",self.save_project,"Ctrl+S","save")
        action("save_as","Save as…",lambda:self.save_project(save_as=True),"Ctrl+Shift+S",bar=False)
        action("close","Close workflow",self.close,"Ctrl+W",bar=False)
        for key,shortcut in (("undo","Ctrl+Z"),("redo","Ctrl+Shift+Z")):
            act=self.undo.createUndoAction(self,"Undo") if key=="undo" else self.undo.createRedoAction(self,"Redo")
            act.setShortcut(shortcut)
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.actions[key]=act
            edit.addAction(act)
        action("fit","Fit flow",lambda:self.canvas.fit(),symbol="monitor")
        action("step","Check to step",self.check_selected,symbol="search")
        action("scan","Check & Preview",self.check_all,symbol="scan")
        action("generate","Run approved",self.generate,"Ctrl+Shift+G","printer")
        action("cancel","Cancel",self.cancel_job,symbol="x")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for key in ("scan","generate"):
            toolbar.widgetForAction(self.actions[key]).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.tabs=QTabWidget()
        self.tabs.setObjectName("designerPanelTabs")
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

    def setup_build(self):
        self.build_page=QWidget()
        layout=QVBoxLayout(self.build_page)
        layout.setContentsMargins(6,6,6,6)
        header=QHBoxLayout()
        label=QLabel("CONDITIONAL MAIL MERGE")
        header.addWidget(label)
        header.addStretch()
        add=QToolButton()
        add.setText("Add data step")
        add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(add)
        for kind in DATA_KINDS:
            menu.addAction(LABELS[kind],lambda checked=False,k=kind:self.add_step(k))
        add.setMenu(menu)
        header.addWidget(add)
        self.add_step_button=add
        self.route_button=QPushButton("+ Template route")
        self.route_button.clicked.connect(self.add_route)
        header.addWidget(self.route_button)
        layout.addLayout(header)
        self.splitter=QSplitter()
        self.steps=QListWidget()
        self.steps.setMinimumWidth(120)
        self.steps.currentRowChanged.connect(self.step_selected)
        self.canvas=BranchCanvas()
        self.canvas.nodeSelected.connect(self.select_node)
        self.canvas.positionChanged.connect(self.move_node)
        self.canvas.nodeCommand.connect(self.node_command)
        self.canvas.message.connect(self.message)
        self.details=QTabWidget()
        self.settings_scroll=QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setMinimumWidth(220)
        settings=QWidget()
        settings_layout=QVBoxLayout(settings)
        settings_layout.setContentsMargins(4,4,4,4)
        settings_layout.addWidget(self.settings_scroll,1)
        self.draft_label=QLabel()
        self.draft_label.setWordWrap(True)
        self.draft_label.setTextFormat(Qt.TextFormat.PlainText)
        settings_layout.addWidget(self.draft_label)
        row=QHBoxLayout()
        self.apply_button=QPushButton("Apply settings")
        self.apply_button.clicked.connect(self.flush_settings)
        self.revert_button=QPushButton("Revert draft")
        self.revert_button.clicked.connect(self.revert_draft)
        row.addWidget(self.apply_button)
        row.addWidget(self.revert_button)
        settings_layout.addLayout(row)
        self.details.addTab(settings,"Settings")
        self.input_page=self.evidence_page("input")
        self.output_page=self.evidence_page("output")
        self.issue_page=self.evidence_page("issues")
        self.details.addTab(self.input_page,"Input")
        self.details.addTab(self.output_page,"Output")
        self.details.addTab(self.issue_page,"Issues")
        self.details.currentChanged.connect(lambda *_:self.load_evidence(reset=True))
        for widget in (self.steps,self.canvas,self.details):
            self.splitter.addWidget(widget)
        self.splitter.setSizes([170,650,360])
        self.compact=QTabWidget()
        self.compact.hide()
        layout.addWidget(self.splitter,1)
        layout.addWidget(self.compact,1)
        self.tabs.addTab(self.build_page,"Build")

    def evidence_page(self,view):
        page=QWidget()
        layout=QVBoxLayout(page)
        layout.setContentsMargins(4,4,4,4)
        source=QComboBox()
        source.setMinimumContentsLength(8)
        source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        source.addItem("All sources","")
        layout.addWidget(source)
        search=QLineEdit()
        search.setPlaceholderText("Search record, sequence or content")
        layout.addWidget(search)
        check=QPushButton("Check to this step")
        check.clicked.connect(self.check_selected)
        layout.addWidget(check)
        grid,model=table(page)
        layout.addWidget(grid,1)
        nav=QHBoxLayout()
        previous=QPushButton("◀")
        following=QPushButton("▶")
        count=QLabel("Check a step to inspect results")
        count.setWordWrap(True)
        previous.clicked.connect(lambda:self.page_results(-50))
        following.clicked.connect(lambda:self.page_results(50))
        nav.addWidget(previous)
        nav.addWidget(count,1)
        nav.addWidget(following)
        layout.addLayout(nav)
        locate=QPushButton("Locate selected issue" if view=="issues" else "Inspect selected record")
        locate.clicked.connect(lambda:self.locate_evidence(page))
        layout.addWidget(locate)
        page.controls=dict(source=source,search=search,grid=grid,model=model,count=count,view=view,
                           previous=previous,following=following,check=check)
        search.returnPressed.connect(lambda:self.load_evidence(reset=True))
        source.currentIndexChanged.connect(lambda:self.load_evidence(reset=True))
        return page

    def setup_review(self):
        self.review_page=QWidget()
        layout=QVBoxLayout(self.review_page)
        self.summary=QLabel("Add data files, configure routes and choose a saved letter template for each route.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.jobs_view,self.jobs_model=table(self.review_page)
        layout.addWidget(self.jobs_view,1)
        self.jobs_view.doubleClicked.connect(lambda *_:self.preview_job())
        self.acknowledge=QCheckBox("Accept partial production")
        layout.addWidget(self.acknowledge)
        explanation=QLabel("Confirm only after reviewing exceptions and blocked items. Normal records may print; exceptions retain their sequence numbers and are listed in the report.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.preview_record=QSpinBox()
        self.preview_record.setRange(1,100000000)
        self.preview_page=QSpinBox()
        self.preview_page.setRange(1,1000)
        row=QHBoxLayout()
        row.addWidget(QLabel("Branch record"))
        row.addWidget(self.preview_record)
        row.addWidget(QLabel("Template page"))
        row.addWidget(self.preview_page)
        layout.addLayout(row)
        row=QHBoxLayout()
        for text,callback in (("Preview record",self.preview_job),("Review exceptions",self.review_exceptions),
                              ("Approve selected",lambda:self.approve(False)),("Approve all checked",lambda:self.approve(True))):
            button=QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs.addTab(self.review_page,"Review && approve")

    def setup_production(self):
        self.production_page=QWidget()
        layout=QVBoxLayout(self.production_page)
        self.production_summary=QLabel("Production runs only explicitly approved branches. Completed outputs are retained on recheck.")
        self.production_summary.setWordWrap(True)
        self.production_summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.production_summary)
        self.production_view,self.production_model=table(self.production_page)
        layout.addWidget(self.production_view,1)
        row=QHBoxLayout()
        for text,callback in (("Run approved branches…",self.generate),("Open selected PDF",self.open_output),("Open reports",self.show_reports)):
            button=QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs.addTab(self.production_page,"Production")

    def message(self,text):
        self.statusBar().showMessage(text)

    def error(self,text):
        self.message(str(text))
        QMessageBox.warning(self,"Visual Workflow",str(text))

    def title(self,*_):
        self.setWindowTitle((self.project_path.name if self.project_path else self.spec.name)+
                            (" *" if not self.undo.isClean() or self.draft_error else "")+" · Visual Workflow")
        self.activityChanged.emit()

    def edit(self,new,label):
        if self.active_worker:
            return False
        try:
            new.validate()
        except ValueError as exc:
            self.error(str(exc))
            return False
        self.undo.push(WorkflowEdit(self,self.spec.to_dict(),new.to_dict(),label))
        return True

    def apply_spec(self,value):
        new=WorkflowSpec.from_dict(value)
        def settings(spec):
            return {"nodes":[(n.id,n.kind,n.params) for n in spec.nodes],"edges":spec.edges}
        changed=settings(new)!=settings(self.spec)
        self.spec=new
        self.evidence_token+=1
        # Keep completed results for a safe recheck; none remain approved after edits.
        if changed:
            for job in self.run.get("jobs",[]):
                job["approved"]=False
                if job["status"]=="Ready":
                    job["status"]="Needs review"
            self.run["stale"]=True
        self.clear_drafts()
        if not any(n.id==self.selected for n in self.spec.nodes):
            self.selected=self.spec.nodes[0].id
        self.refresh_graph()
        self.select_node(self.selected)
        self.refresh_results()
        self.title()

    def refresh_graph(self):
        self.steps.blockSignals(True)
        self.steps.clear()
        try:
            plan=self.spec.execution_plan(self.spec.node("route").id)
        except ValueError:
            plan=None
        ordered=[*plan.common,plan.route] if plan else self.spec.nodes[:]
        if plan:
            for route in self.spec.node("route").params["routes"]:
                ordered.extend(plan.branches.get(route["id"],[]))
            ordered.extend(n for n in self.spec.nodes if n.kind in ("exceptions","collect"))
        route_names={n.id:r["name"] for r in self.spec.node("route").params["routes"]
                     for n in (plan.branches.get(r["id"],[]) if plan else [])}
        for node in ordered:
            self.steps.addItem((route_names[node.id]+" · " if node.id in route_names else "")+LABELS[node.kind])
            item=self.steps.item(self.steps.count()-1)
            item.setData(Qt.ItemDataRole.UserRole,node.id)
            item.setToolTip(description(node.kind))
            if node.id==self.selected:
                self.steps.setCurrentRow(self.steps.count()-1)
        self.steps.blockSignals(False)
        summaries={}
        route=self.spec.node("route")
        summaries[self.spec.node("for_each").id]=f"{len(self.spec.node('for_each').params.get('items',[]))} data file(s)"
        summaries[route.id]=f"{len(route.params['routes'])} exclusive route(s)"
        summaries[self.spec.node("batch_sequence").id]="Across all files · reserves exceptions"
        for identity,path in plan.branches.items() if plan else []:
            name=next(r["name"] for r in route.params["routes"] if r["id"]==identity)
            for node in path:
                summaries[node.id]=name+(" · "+Path(node.params.get("path","")).name if node.kind=="template" else "")
        self.canvas.summaries=summaries
        self.canvas.display(self.spec,{},self.selected)

    def step_selected(self,index):
        item=self.steps.item(index)
        if item:
            identity=item.data(Qt.ItemDataRole.UserRole)
            self.select_node(identity)
            self.canvas.ensureVisible(self.canvas.nodes[identity])

    def fields(self):
        return list(dict.fromkeys([self.spec.node("batch_sequence").params.get("name","WorkflowSeq"),
                                  *self.current_evidence.get("fields",[]),
                                  *(k for r in self.current_evidence.get("rows",[]) for k in r.get("value",{}))]))

    def select_node(self,identity):
        node=next((n for n in self.spec.nodes if n.id==identity),None)
        if not node:
            return
        self.selected=identity
        self.offset=0
        self.evidence_token+=1
        old=self.settings_scroll.takeWidget()
        if old:
            old.hide()
            old.setParent(self)
        entry=self.node_drafts.get(identity)
        if entry is None:
            entry=self.build_settings(node)
            self.node_drafts[identity]=entry
        self.settings_scroll.setWidget(entry["widget"])
        entry["widget"].show()
        self.update_draft_status()
        self.steps.blockSignals(True)
        for i in range(self.steps.count()):
            if self.steps.item(i).data(Qt.ItemDataRole.UserRole)==identity:
                self.steps.setCurrentRow(i)
        self.steps.blockSignals(False)
        self.canvas.scene().blockSignals(True)
        for item in self.canvas.nodes.values():
            item.setSelected(item.node.id==identity)
        self.canvas.scene().blockSignals(False)
        self.load_evidence(reset=True)

    def build_settings(self,node):
        widget=QWidget()
        layout=QVBoxLayout(widget)
        heading=QLabel(LABELS[node.kind])
        font=heading.font()
        font.setBold(True)
        font.setPointSizeF(11)
        heading.setFont(font)
        layout.addWidget(heading)
        text=QLabel(description(node.kind))
        text.setWordWrap(True)
        layout.addWidget(text)
        def getter():
            return copy.deepcopy(node.params)
        if node.kind=="for_each":
            self.source_table,self.source_model=table(widget)
            self.source_model.update([{**item,"file":Path(item["path"]).name} for item in node.params.get("items",[])],["file","path"])
            self.source_table.setMinimumHeight(160)
            layout.addWidget(self.source_table)
            for label,callback in (("Add data files…",self.add_sources),("Add folder snapshot…",self.add_folder),
                                   ("Import settings / mapping…",self.configure_source),("Move up",lambda:self.move_source(-1)),
                                   ("Move down",lambda:self.move_source(1)),("Remove selected files",self.remove_sources)):
                button=QPushButton(label)
                button.clicked.connect(callback)
                layout.addWidget(button)
            note=QLabel("File order determines the shared sequence. A folder is captured once; this is not a watch folder.")
            note.setWordWrap(True)
            layout.addWidget(note)
        elif node.kind=="mapping":
            pairs=QTableWidget(0,2)
            pairs.setHorizontalHeaderLabels(["Original field","Merge field alias"])
            pairs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            pairs.setMinimumHeight(180)
            layout.addWidget(pairs)
            def add_pair(key="",value=""):
                if pairs.rowCount()>=100:
                    return
                row=pairs.rowCount()
                pairs.insertRow(row)
                pairs.setItem(row,0,QTableWidgetItem(key))
                pairs.setItem(row,1,QTableWidgetItem(value))
            for key,value in node.params.get("aliases",{}).items():
                add_pair(key,value)
            button=QPushButton("+ Alias")
            button.clicked.connect(lambda:add_pair())
            layout.addWidget(button)
            remove=QPushButton("Remove alias")
            remove.clicked.connect(lambda:pairs.removeRow(pairs.currentRow()))
            layout.addWidget(remove)
            def aliases():
                values={}
                for row in range(pairs.rowCount()):
                    key=pairs.item(row,0).text().strip() if pairs.item(row,0) else ""
                    value=pairs.item(row,1).text().strip() if pairs.item(row,1) else ""
                    if not key or not value or key in values:
                        raise ValueError("Aliases need unique original fields and nonempty names.")
                    values[key]=value
                from .transforms import _field
                for value in values.values():
                    _field(value)
                return {"aliases":values}
            getter=aliases
            pairs.itemChanged.connect(lambda *_:self.draft_changed())
        elif node.kind in DATA_KINDS or node.kind=="batch_sequence":
            from .node_settings import StepDialog
            proxy=copy.deepcopy(node)
            if node.kind=="batch_sequence":
                proxy.kind="running_sequence"
            editor=StepDialog(proxy,self.fields(),widget,embedded=True)
            if node.kind=="batch_sequence":
                editor.controls["scope"].setEnabled(False)
            layout.addWidget(editor)
            getter=editor.value
            editor.edited.connect(self.draft_changed)
        elif node.kind=="route":
            for route in node.params["routes"]:
                row=QHBoxLayout()
                button=QPushButton(route["name"]+(" · fallback" if route.get("fallback") else " · conditions"))
                button.clicked.connect(lambda checked=False,r=route:self.edit_route(r))
                row.addWidget(button,1)
                remove=QPushButton("Remove")
                remove.setEnabled(len(node.params["routes"])>1)
                remove.clicked.connect(lambda checked=False,r=route:self.remove_route(r["id"]))
                row.addWidget(remove)
                layout.addLayout(row)
            button=QPushButton("+ Template route")
            button.clicked.connect(self.add_route)
            layout.addWidget(button)
            warning=QLabel("No match → Exceptions, unless an explicit fallback exists. Multiple matches always require review.")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        elif node.kind=="template":
            path=QLineEdit(node.params.get("path",""))
            path.setPlaceholderText("Saved letter template (.pdcx)")
            layout.addWidget(path)
            browse=QPushButton("Choose template…")
            browse.clicked.connect(lambda:self.choose_template(path))
            layout.addWidget(browse)
            edit=QPushButton("Edit template in Designer")
            edit.clicked.connect(lambda:self.edit_template(path.text()))
            layout.addWidget(edit)
            media=QPushButton("Configure print media…")
            media.clicked.connect(lambda:self.configure_media(node.id))
            layout.addWidget(media)
            def getter():
                return {"path":path.text().strip()}
            path.textChanged.connect(self.draft_changed)
        elif node.kind=="media_assignment":
            info=QLabel(settings_summary(node,"Print media settings"))
            info.setWordWrap(True)
            layout.addWidget(info)
            button=QPushButton("Stocks / printer profile…")
            button.clicked.connect(lambda:self.configure_media(node.id))
            layout.addWidget(button)
        elif node.kind=="compose":
            repair=QCheckBox("Automatic glyph repair")
            repair.setChecked(node.params.get("auto_repair",True))
            layout.addWidget(repair)
            def getter():
                return {**node.params,"auto_repair":repair.isChecked()}
            repair.toggled.connect(self.draft_changed)
        else:
            note=QLabel({"exceptions":"Review records that have invalid data, no route or multiple matches. Exceptions reserve their sequence numbers.",
                        "mail_review":"Check the entire graph, preview a record and approve this branch on Review & approve.",
                        "reports":"A job log, branch summary and record reconciliation are produced for every production run.",
                        "collect":"Collects job statuses and reports. It does not merge PDFs or renumber records."}.get(node.kind,""))
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addStretch()
        return {"widget":widget,"getter":getter,"original":copy.deepcopy(node.params)}

    def choose_template(self,edit):
        path,_=QFileDialog.getOpenFileName(self,"Choose letter template","","Designer template (*.pdcx)")
        if path:
            edit.setText(path)

    def edit_template(self,path):
        if not path or not self.flush_settings():
            self.message("Choose and apply a saved template first.")
            return
        if self.project_host:
            self.project_host.open_project(path)
        else:
            self.error("Open this workflow within Document Designer to edit its template.")

    def draft_changed(self,*_):
        self.run["stale"]=True
        for job in self.run.get("jobs",[]):
            job["approved"]=False
        self.update_draft_status()
        self.properties.edited.emit()
        self.title()

    def pending_spec(self):
        result=copy.deepcopy(self.spec)
        for node in result.nodes:
            if node.id in self.node_drafts:
                try:
                    node.params=self.node_drafts[node.id]["getter"]()
                    result.validate()
                except (ValueError,TypeError) as exc:
                    raise ValueError(LABELS[node.kind]+": "+str(exc)) from exc
        result.validate()
        return result

    def update_draft_status(self):
        try:
            changed=self.pending_spec().to_dict()!=self.spec.to_dict()
            self.draft_error="Unapplied settings" if changed else ""
            self.draft_label.setText("Draft retained. Apply before checking or saving." if changed else "")
        except (ValueError,TypeError) as exc:
            self.draft_error=str(exc)
            self.draft_label.setText(self.draft_error)
        self.lock()

    def flush_settings(self,*_,**__):
        if self.active_worker:
            return False
        try:
            new=self.pending_spec()
        except (ValueError,TypeError) as exc:
            self.draft_error=str(exc)
            self.error(str(exc))
            return False
        if new.to_dict()!=self.spec.to_dict():
            return self.edit(new,"Apply node settings")
        self.draft_error=""
        return True

    def clear_drafts(self):
        self.settings_scroll.takeWidget()
        for entry in self.node_drafts.values():
            entry["widget"].hide()
            entry["widget"].deleteLater()
        self.node_drafts.clear()
        self.draft_error=""

    def revert_draft(self):
        old=self.node_drafts.pop(self.selected,None)
        if old:
            self.settings_scroll.takeWidget()
            old["widget"].deleteLater()
        self.select_node(self.selected)

    def selected_sources(self):
        return sorted({i.row() for i in self.source_table.selectionModel().selectedRows()})

    def add_sources(self):
        paths,_=QFileDialog.getOpenFileNames(self,"Add data files","","Data (*.csv *.txt *.tsv *.xlsx *.xlsm)")
        self.append_sources(paths)

    def append_sources(self,paths):
        if not paths or not self.flush_settings():
            return
        new=copy.deepcopy(self.spec)
        items=new.node("for_each").params.setdefault("items",[])
        existing={str(Path(i["path"]).resolve()).casefold() for i in items}
        for path in paths:
            key=str(Path(path).resolve()).casefold()
            if key not in existing:
                items.append({"id":uuid.uuid4().hex,"path":str(Path(path).resolve()),"options":{}})
                existing.add(key)
        self.edit(new,"Add data files")

    def add_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Capture data folder")
        if folder:
            self.request({"operation":"branch_folder","folder":folder},lambda r:self.append_sources(r["paths"]))

    def remove_sources(self):
        selected=self.selected_sources()
        new=copy.deepcopy(self.spec)
        items=new.node("for_each").params["items"]
        new.node("for_each").params["items"]=[item for i,item in enumerate(items) if i not in selected]
        self.edit(new,"Remove data files")

    def move_source(self,delta):
        selected=self.selected_sources()
        if len(selected)!=1:
            return
        new=copy.deepcopy(self.spec)
        items=new.node("for_each").params["items"]
        index=selected[0]
        target=index+delta
        if 0<=target<len(items):
            items[index],items[target]=items[target],items[index]
            self.edit(new,"Reorder data files")
            self.source_table.selectRow(target)

    def configure_source(self):
        selected=self.selected_sources()
        if len(selected)!=1:
            self.message("Select one source to configure its encoding, delimiter, worksheet and mapping.")
            return
        from composition.designer.data_dialog import DataDialog
        new=copy.deepcopy(self.spec)
        item=new.node("for_each").params["items"][selected[0]]
        dialog=DataDialog(item["path"],self.directory,self,
                          DataConfig(path=item["path"],**item["options"]) if item.get("options") else None)
        if dialog.exec():
            item["options"]=asdict(dialog.config())
            item["options"].pop("path",None)
            self.edit(new,"Configure data source")

    def edit_route(self,route):
        if not self.flush_settings():
            return
        dialog=RouteDialog(route,self.fields(),self)
        if dialog.exec():
            new=copy.deepcopy(self.spec)
            target=next(r for r in new.node("route").params["routes"] if r["id"]==route["id"])
            target.clear()
            target.update(id=route["id"],**dialog.options)
            self.edit(new,"Edit template route")

    def add_route(self):
        if not self.flush_settings():
            return
        dialog=RouteDialog({},self.fields(),self)
        if dialog.exec():
            try:
                self.edit(add_route(self.spec,dialog.options["name"],dialog.options.get("condition"),dialog.options["fallback"]),"Add template route")
                self.arrange_graph()
            except ValueError as exc:
                self.error(str(exc))

    def remove_route(self,identity):
        if not self.flush_settings():
            return
        new=copy.deepcopy(self.spec)
        route=new.node("route")
        if len(route.params["routes"])<=1:
            return
        removed={n.id for n in new.execution_plan(route.id).branches[identity]}
        route.params["routes"]=[r for r in route.params["routes"] if r["id"]!=identity]
        new.nodes=[n for n in new.nodes if n.id not in removed]
        new.edges=[e for e in new.edges if e["source"] not in removed and e["target"] not in removed]
        self.edit(new,"Remove template route")

    def add_step(self,kind):
        if not self.flush_settings():
            return
        new=copy.deepcopy(self.spec)
        predecessor=next((n for n in new.nodes if n.id==self.selected),None)
        if predecessor.kind not in ("for_each",*COMMON) or predecessor.kind=="batch_sequence":
            predecessor=next(n for n in new.nodes if any(e["source"]==n.id and e["target"]==new.node("batch_sequence").id for e in new.edges))
        connection=next(e for e in new.edges if e["source"]==predecessor.id)
        node=WorkflowNode(kind,params=default_options(kind))
        new.nodes.append(node)
        new.edges.remove(connection)
        new.edges.extend((edge(predecessor.id,node.id),edge(node.id,connection["target"])))
        self.selected=node.id
        self.edit(new,"Add data preparation step")
        self.arrange_graph()

    def node_command(self,identity,command):
        node=next(n for n in self.spec.nodes if n.id==identity)
        if command!="remove" or node.kind not in DATA_KINDS:
            self.message("Shared routing and production steps are required. Data preparation steps can be removed.")
            return
        if not self.flush_settings():
            return
        new=copy.deepcopy(self.spec)
        before=next(e for e in new.edges if e["target"]==identity)
        after=next(e for e in new.edges if e["source"]==identity)
        new.edges=[e for e in new.edges if e["source"]!=identity and e["target"]!=identity]
        new.edges.append(edge(before["source"],after["target"]))
        new.nodes=[n for n in new.nodes if n.id!=identity]
        self.edit(new,"Remove data step")

    def arrange_graph(self):
        new=copy.deepcopy(self.spec)
        plan=new.execution_plan(new.node("route").id)
        for i,node in enumerate([*plan.common,plan.route]):
            node.x=i*230
            node.y=0
        x=(len(plan.common)+1)*230
        for row,route in enumerate(plan.route.params["routes"]):
            for col,node in enumerate(plan.branches[route["id"]]):
                node.x=x+col*230
                node.y=row*150
        new.node("exceptions").x=x
        new.node("exceptions").y=len(plan.branches)*150
        new.node("collect").x=x+1150
        new.node("collect").y=150
        self.edit(new,"Arrange branch graph")

    def start_view(self):
        from PyQt6.QtCore import QPointF
        self.canvas.resetTransform()
        self.canvas.scale(.75,.75)
        self.canvas.centerOn(self.canvas.nodes[self.spec.nodes[0].id].pos()+QPointF(350,120))

    def move_node(self,identity,x,y):
        if not self.flush_settings():
            return
        new=copy.deepcopy(self.spec)
        node=next(n for n in new.nodes if n.id==identity)
        node.x,node.y=x,y
        self.edit(new,"Move workflow step")

    def branch_id(self,node_id=None):
        identity=node_id or self.selected
        try:
            plan=self.spec.execution_plan(self.spec.node("route").id)
        except ValueError:
            return ""
        return next((key for key,path in plan.branches.items() if any(n.id==identity for n in path)),
                    "exceptions" if self.spec.node("exceptions").id==identity else "")

    def configure_media(self,identity):
        if not self.flush_settings():
            return
        branch=self.branch_id(identity)
        path=self.spec.execution_plan(self.spec.node("route").id).branches[branch]
        template=path[0]
        def ready(result):
            from composition.designer.media_dialog import MediaDialog
            media=next((n for n in path if n.kind=="media_assignment"),None)
            dialog=MediaDialog(media.params if media else result["template"].get("media",{}),
                               {"kind":"template","project":result["template"],"records":1},self)
            if dialog.exec():
                new=copy.deepcopy(self.spec)
                if media:
                    next(n for n in new.nodes if n.id==media.id).params=dialog.options
                else:
                    n=WorkflowNode("media_assignment",params=dialog.options,x=template.x+200,y=template.y+110)
                    connection=next(e for e in new.edges if e["source"]==template.id)
                    new.edges.remove(connection)
                    new.nodes.append(n)
                    new.edges.extend((edge(template.id,n.id),edge(n.id,connection["target"])))
                self.edit(new,"Configure branch print media")
        self.request({"operation":"branch_template","path":template.params.get("path","")},ready)

    def check_selected(self):
        self.check(self.selected)

    def check_all(self):
        self.check(None)

    def check(self,target):
        if not self.flush_settings() or not self.templates_saved():
            return
        try:
            self.spec.execution_plan(target)
        except ValueError as exc:
            self.error(str(exc))
            return
        def ready(result):
            self.run=result["run"]
            self.refresh_results()
            if not target:
                self.tabs.setCurrentWidget(self.review_page)
            else:
                self.details.setCurrentWidget(self.output_page)
                self.load_evidence(reset=True)
        self.request({"operation":"branch_check","node_id":target},ready)

    def refresh_results(self):
        entries=self.run.get("jobs",[])
        source_names={s["id"]:Path(s["path"]).name for s in self.run.get("sources",[])}
        values=[{**j,"source":source_names.get(j["source_id"],j["source_id"])} for j in entries]
        columns=["source","branch_name","records","status","error"]
        self.jobs_model.update(values,columns)
        self.production_model.update(values,columns)
        self.summary.setText(f"{self.run.get('status','Not checked')}{' · OUTDATED — recheck required' if self.run.get('stale') else ''}\n"
                             f"Input {self.run.get('input',0):,} = excluded {self.run.get('excluded',0):,} + candidates {self.run.get('candidates',0):,}\n"
                             f"Candidates = routed {self.run.get('routed',0):,} + exceptions {self.run.get('exceptions',0):,}"+
                             "\n"+"\n".join(f"Blocked source: {Path(s['path']).name} · {s['error']}" for s in self.run.get("sources",[]) if s["status"]=="Blocked"))
        self.production_summary.setText(self.summary.text()+f"\nPublished {self.run.get('published_records',0):,} · "
                                       f"Unpublished {self.run.get('unpublished_records',self.run.get('routed',0)):,}\n"+self.run.get("report_dir",""))
        for page in (self.input_page,self.output_page,self.issue_page):
            combo=page.controls["source"]
            previous=combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All sources","")
            for source in self.run.get("sources",[]):
                combo.addItem(Path(source["path"]).name,source["id"])
            combo.setCurrentIndex(max(0,combo.findData(previous)))
            combo.blockSignals(False)
        inspections={}
        if self.run and not self.run.get("stale"):
            for stage in self.run.get("stages",[]):
                target=inspections.setdefault(stage["node_id"],dict(status="Checked",input_count=0,output_count=0,output_scope="record"))
                target["input_count"]+=stage["input"]
                target["output_count"]+=stage["output"]
            inspections[self.spec.node("route").id]=dict(status="Needs review",input_count=self.run.get("candidates",0),output_count=self.run.get("routed",0),output_scope="record")
            inspections[self.spec.node("exceptions").id]=dict(status="Needs review" if self.run.get("exceptions") else "Checked",input_count=self.run.get("exceptions",0),output_count=self.run.get("exceptions",0),output_scope="record")
            plan=self.spec.execution_plan(self.spec.node("route").id)
            for key,path in plan.branches.items():
                jobs=[j for j in entries if j["branch_id"]==key]
                statuses={j["status"] for j in jobs}
                status="Completed" if statuses<={"Completed","No records"} else "Blocked" if "Blocked" in statuses else "Needs review"
                for node in path:
                    inspections[node.id]=dict(status=status,input_count=sum(j["records"] for j in jobs),output_count=sum(j["records"] for j in jobs),output_scope="record")
        self.canvas.inspections=inspections
        self.canvas.display(self.spec,{},self.selected)
        self.load_evidence(reset=True)
        self.lock()

    def evidence_controls(self):
        page=self.details.currentWidget()
        return page.controls if hasattr(page,"controls") else None

    def load_evidence(self,*,reset=False):
        controls=self.evidence_controls()
        if not controls:
            return
        if reset:
            self.offset=0
        if not self.run.get("directory") or self.run.get("stale"):
            controls["model"].update([],[])
            controls["count"].setText("Recheck required" if self.run.get("stale") else "Check this step first")
            return
        self.evidence_token+=1
        token=self.evidence_token
        selected=self.selected
        def ready(result):
            if token!=self.evidence_token or selected!=self.selected:
                return
            self.current_evidence=result
            rows=result.get("rows",[])
            fields=list(dict.fromkeys(k for row in rows for k in row.get("value",{})))
            base=["source_id","source_record","sequence","disposition"] if controls["view"]!="issues" else ["source_id","source_record","sequence","field","reason"]
            controls["model"].update(rows,[*base,*fields])
            total=result["total"]
            controls["count"].setText(f"{self.offset+1 if total else 0}–{min(self.offset+50,total)} / {total:,}")
            controls["previous"].setEnabled(self.offset>0)
            controls["following"].setEnabled(self.offset+50<total)
        self.request({"operation":"branch_rows","node_id":self.selected,"source_id":controls["source"].currentData() or "",
                      "branch_id":self.branch_id(),"view":controls["view"],"offset":self.offset,"search":controls["search"].text()},ready,preview=True)

    def page_results(self,delta):
        self.offset=max(0,self.offset+delta)
        self.load_evidence()

    def locate_evidence(self,page):
        controls=page.controls
        index=controls["grid"].currentIndex()
        row=controls["model"].data(index,Qt.ItemDataRole.UserRole) if index.isValid() else None
        if not row:
            return
        node_id=row.get("node_id")
        if node_id:
            self.select_node(node_id)
            self.details.setCurrentIndex(0)
        text=QLabel(json.dumps(row,ensure_ascii=False,indent=2))
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dialog=QDialog(self)
        dialog.setWindowTitle("Source record evidence")
        dialog.resize(600,480)
        layout=QVBoxLayout(dialog)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(text)
        layout.addWidget(scroll)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def selected_jobs(self,view=None):
        view=view or self.jobs_view
        return [view.model().records[index.row()] for index in view.selectionModel().selectedRows()]

    def review_exceptions(self):
        self.select_node(self.spec.node("exceptions").id)
        self.tabs.setCurrentWidget(self.build_page)
        self.details.setCurrentWidget(self.issue_page)
        if self.compact.isVisible():
            self.compact.setCurrentWidget(self.details)

    def approve(self,all_checked):
        if not self.templates_saved():
            return
        if self.draft_error or self.run.get("stale"):
            self.error("Apply edits and check the entire workflow before approval.")
            return
        jobs=self.run.get("jobs",[]) if all_checked else self.selected_jobs()
        identities=[j["id"] for j in jobs if j["status"] in ("Needs review","Ready")]
        if not identities:
            self.message("Select a checked branch to approve.")
            return
        self.request({"operation":"branch_approve","identities":identities,"acknowledge":self.acknowledge.isChecked()},self.receive_run)

    def receive_run(self,result):
        self.run=result["run"]
        self.refresh_results()

    def generate(self):
        if not self.templates_saved():
            return
        if self.draft_error or self.run.get("stale") or not any(j["approved"] and j["status"]=="Ready" for j in self.run.get("jobs",[])):
            self.error("Check, review and explicitly approve the branches before production.")
            return
        output=QFileDialog.getExistingDirectory(self,"Production output folder")
        if output:
            self.tabs.setCurrentWidget(self.production_page)
            self.request({"operation":"branch_run","output_dir":output},self.receive_run)

    def preview_job(self):
        if self.run.get("stale") or self.draft_error or not self.templates_saved():
            self.message("Apply edits, save open templates and recheck before previewing.")
            return
        jobs=self.selected_jobs()
        if len(jobs)!=1 or not jobs[0].get("batch"):
            self.message("Select one checked source/template branch to preview.")
            return
        target=self.directory/(uuid.uuid4().hex+".png")
        def ready(result):
            dialog=QDialog(self)
            dialog.setWindowTitle("Checked branch preview · not production output")
            dialog.resize(720,740)
            layout=QVBoxLayout(dialog)
            scroll=QScrollArea()
            label=QLabel()
            label.setPixmap(QPixmap(result["image"]))
            scroll.setWidget(label)
            layout.addWidget(scroll)
            target.unlink(missing_ok=True)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.exec()
        self.request({"operation":"branch_preview","job_id":jobs[0]["id"],"record":self.preview_record.value(),
                      "page":self.preview_page.value(),"target":str(target)},ready)

    def templates_saved(self):
        if not self.project_host:
            return True
        paths={self.project_host.identity(n.params["path"]) for n in self.spec.nodes if n.kind=="template" and n.params.get("path")}
        for project in self.project_host.projects:
            if project is self or not project.project_path or self.project_host.identity(project.project_path) not in paths:
                continue
            if (self.project_host.is_busy(project) or project.properties.apply() is False or not project.undo.isClean()
                    or getattr(project,"content_invalid",False)):
                self.message("Save the open letter template and finish its tasks before checking/running this workflow.")
                return False
        return True

    def open_output(self):
        jobs=self.selected_jobs(self.production_view)
        if len(jobs)==1:
            result=jobs[0].get("batch",{}).get("jobs",[{}])[0].get("result",{})
            if result.get("output_pdf") and self.project_host:
                self.project_host.open_production_output(self,result)

    def show_reports(self):
        if self.run.get("report_dir"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.run["report_dir"]))

    def request(self,request,callback,*,preview=False):
        if self.close_pending or (self.active_worker and not preview):
            return None
        if preview:
            old=getattr(self,"evidence_worker",None)
            if old and not sip.isdeleted(old) and old.running:
                old.superseded=True
                old.stop_preview()
        worker=Worker(self.directory,{"task":"workflow","spec":self.spec.to_dict(),"directory":str(self.directory),"run":self.run,**request},self)
        self.workers.append(worker)
        if preview:
            self.evidence_worker=worker
        else:
            self.active_worker=worker
        results=[]
        errors=[]
        worker.resultReady.connect(results.append)
        worker.failed.connect(errors.append)
        worker.progress.connect(lambda done,total,text:(self.progress.setRange(0,total),self.progress.setValue(done),self.message(text)))
        worker.stateChanged.connect(self.worker_state)
        def ended():
            if worker in self.workers:
                self.workers.remove(worker)
            if worker is self.active_worker:
                self.active_worker=None
            if worker is getattr(self,"evidence_worker",None):
                self.evidence_worker=None
            if not self.close_pending and not getattr(worker,"superseded",False):
                if results:
                    callback(results[0])
                elif errors:
                    if preview:
                        self.message(errors[0])
                    else:
                        self.error(errors[0])
            self.lock()
            if self.close_pending and not self.workers:
                QTimer.singleShot(0,self.close)
        worker.ended.connect(ended)
        self.lock()
        return worker

    def worker_state(self,state):
        entry=state.get("branch_job")
        if entry:
            for index,job in enumerate(self.run.get("jobs",[])):
                if job["id"]==entry["id"]:
                    self.run["jobs"][index]=entry
            self.refresh_results()
        if state.get("branch_source"):
            self.message("Checked "+Path(state["branch_source"]["path"]).name)

    def lock(self,*_):
        if not hasattr(self,"canvas"):
            return
        busy=bool(self.active_worker or self.close_pending)
        for key,action in self.actions.items():
            enabled=not busy
            if key=="cancel":
                enabled=bool(self.active_worker)
            elif key in ("undo","redo"):
                enabled=not busy and not self.draft_error and (self.undo.canUndo() if key=="undo" else self.undo.canRedo())
            elif key=="fit":
                enabled=True
            action.setEnabled(enabled)
        self.actions["cancel"].setVisible(bool(self.active_worker))
        self.canvas.set_editable(not busy)
        self.settings_scroll.setEnabled(not busy)
        self.apply_button.setEnabled(not busy)
        self.revert_button.setEnabled(not busy)
        self.route_button.setEnabled(not busy)
        self.add_step_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        for page in (getattr(self,"input_page",None),getattr(self,"output_page",None),getattr(self,"issue_page",None)):
            if page:
                page.controls["check"].setEnabled(not busy)
        self.activityChanged.emit()

    def cancel_job(self):
        if self.active_worker:
            self.active_worker.cancel()
            self.message("Cancellation requested. Completed outputs remain available.")

    def new_project(self):
        if self.project_host:
            self.project_host.new_branch_workflow()

    def open_project(self,checked=False,path=None):
        if self.project_host:
            self.project_host.open_project(path)

    def load_path(self,path):
        def ready(result):
            self.run={}
            self.apply_spec(result["spec"])
            self.project_path=Path(path)
            self.undo.clear()
            self.undo.setClean()
            self.title()
            self.start_view()
        self.request({"operation":"load","path":str(path)},ready)

    def save_project(self,checked=False,*,save_as=False,path=None,after=None):
        if not self.flush_settings():
            return False
        path=path or (str(self.project_path) if self.project_path and not save_as else "")
        if not path:
            path,_=QFileDialog.getSaveFileName(self,"Save conditional workflow","","Workflow (*.pdflow)")
        if not path or (self.project_host and not self.project_host.allow_save_path(self,path)):
            return False
        def ready(result):
            self.project_path=Path(result["path"])
            self.undo.setClean()
            self.title()
            if after:
                QTimer.singleShot(0,after)
        return self.request({"operation":"save","path":path},ready)

    def closeEvent(self,event):
        if self.embedded and not self._close_approved and not self.close_pending:
            event.ignore()
            QTimer.singleShot(0,lambda:self.project_host.close_project(self))
            return
        if not self.close_pending:
            if not self._close_approved and not self.active_worker and not self.flush_settings():
                event.ignore()
                return
            if not self._close_approved and not self.undo.isClean():
                answer=QMessageBox.question(self,"Unsaved workflow","Discard this workflow?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self.close_pending=True
            for worker in self.workers:
                worker.cancel()
        if self.workers:
            event.ignore()
            return
        self.temp.cleanup()
        event.accept()
        self.projectClosed.emit()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,"compact"):
            return
        narrow=self.width()<1100
        if narrow and self.compact.isHidden():
            self.wide_sizes=self.splitter.sizes()
            for title,widget in (("Steps",self.steps),("Canvas",self.canvas),("Details",self.details)):
                self.compact.addTab(widget,title)
            self.compact.setCurrentWidget(self.canvas)
            self.splitter.hide()
            self.compact.show()
        elif not narrow and not self.compact.isHidden():
            for widget in (self.steps,self.canvas,self.details):
                self.splitter.addWidget(widget)
            self.splitter.setSizes(getattr(self,"wide_sizes",[170,650,360]))
            self.compact.hide()
            self.splitter.show()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange,QEvent.Type.StyleChange):
            for act in getattr(self,"actions",{}).values():
                symbol=act.property("workflow_icon")
                if symbol:
                    act.setIcon(icon(symbol,color=self.palette().text().color().name()))
