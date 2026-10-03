"""Embedded Workflow project: node canvas, bounded review and isolated workers."""
from __future__ import annotations

import copy
import tempfile
from dataclasses import asdict
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QAbstractTableModel, QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
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
from ui.icons import icon

from .canvas import NodeToolbox, WorkflowCanvas
from .model import KINDS, LABELS, WorkflowNode, WorkflowRun, WorkflowSpec


class ProjectProperties(QObject):
    edited=pyqtSignal()

    def apply(self):
        return self.parent().flush_settings()


class WorkflowEdit(QUndoCommand):
    def __init__(self,window,before,after,label):
        super().__init__(label)
        self.window,self.before,self.after=window,before,after

    def undo(self):
        self.window.apply_spec(self.before)

    def redo(self):
        self.window.apply_spec(self.after)


class GroupsModel(QAbstractTableModel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.groups=[]

    def rowCount(self,parent=None):
        return 0 if parent and parent.isValid() else len(self.groups)

    def columnCount(self,parent=None):
        return 3

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role==Qt.ItemDataRole.DisplayRole:
            start,end=self.groups[index.row()]
            return (str(index.row()+1),f"{start}–{end}",str(end-start+1))[index.column()]

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:
            return ("Envelope","Source pages","Count")[section]

    def update(self,groups):
        if self.groups==groups:
            return
        self.beginResetModel()
        self.groups=copy.deepcopy(groups)
        self.endResetModel()


class WorkflowWindow(QMainWindow):
    activityChanged=pyqtSignal()
    projectClosed=pyqtSignal()
    is_workflow=True

    def __init__(self,parent=None,*,embedded=False,project_host=None):
        super().__init__(parent,Qt.WindowType.Widget if embedded else Qt.WindowType.Window)
        self.embedded,self.project_host=embedded,project_host
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,embedded)
        self.resize(1280,820)
        self.spec=WorkflowSpec.default()
        self.run=WorkflowRun()
        self.project_path=None
        self.properties=ProjectProperties(self)
        self.temp=tempfile.TemporaryDirectory(prefix="pdf-workflow-")
        self.directory=Path(self.temp.name)
        self.workers=[]
        self.active_worker=None
        self.close_pending=False
        self._close_approved=False
        self.draft_error=""
        self._draft_getter=None
        self._flushing_settings=False
        self.selected=self.spec.nodes[0].id
        self.capture_active=False
        self.review_generation=0
        self.undo=QUndoStack(self)
        self.undo.cleanChanged.connect(self.title)
        self.undo.canUndoChanged.connect(self.lock)
        self.undo.canRedoChanged.connect(self.lock)
        self.actions={}
        file=self.menuBar().addMenu("&Workflow")
        edit=self.menuBar().addMenu("&Edit")
        toolbar=QToolBar("Workflow")
        self.layout_toolbar=toolbar
        toolbar.setObjectName("designerMainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        def action(key,label,callback,shortcut="",symbol="file-text",bar=True,menu=file):
            act=QAction(icon(symbol),label,self)
            act.setProperty("workflow_icon",symbol)
            act.triggered.connect(callback)
            act.setShortcut(shortcut)
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.actions[key]=act
            menu.addAction(act)
            if bar:
                toolbar.addAction(act)
            return act
        action("new","New workflow",self.new_project,"Ctrl+N")
        action("open","Open workflow…",self.open_project,"Ctrl+O","folder-open")
        action("save","Save",self.save_project,"Ctrl+S","save")
        action("save_as","Save as…",lambda:self.save_project(save_as=True),"Ctrl+Shift+S",bar=False)
        action("close","Close workflow",self.close,"Ctrl+W",bar=False)
        for key in ("undo","redo"):
            act=self.undo.createUndoAction(self,"Undo") if key=="undo" else self.undo.createRedoAction(self,"Redo")
            act.setShortcut("Ctrl+Z" if key=="undo" else "Ctrl+Shift+Z")
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            act.setIcon(icon(key))
            act.setProperty("workflow_icon",key)
            self.actions[key]=act
            edit.addAction(act)
            toolbar.addAction(act)
        action("fit","Fit flow",lambda:self.canvas.fit(),symbol="monitor")
        action("step","Run to selected step",self.run_selected,symbol="chevron-right")
        action("scan","Run to review",lambda:self.execute("review"),symbol="scan")
        action("generate","Generate production PDF",lambda:self.execute("output"),"Ctrl+Shift+G","printer")
        self.actions["scan"].setIconText("Scan and review")
        self.actions["generate"].setIconText("Generate PDF")
        action("cancel","Cancel task",self.cancel_job,symbol="x")
        self.add_step=QToolButton()
        self.add_step.setText("Add step")
        self.add_step.setToolTip("Insert an optional step and connect it automatically")
        self.add_step.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(self.add_step)
        for kind in ("merge","overlay"):
            menu.addAction(LABELS[kind],lambda checked=False,k=kind:self.add_optional(k))
        self.add_step.setMenu(menu)
        toolbar.addWidget(self.add_step)
        central=QWidget()
        root=QVBoxLayout(central)
        root.setContentsMargins(4,4,4,4)
        self.tabs=QTabWidget()
        self.tabs.setDocumentMode(True)
        self.flow_page=QWidget()
        flow_layout=QVBoxLayout(self.flow_page)
        flow_layout.setContentsMargins(0,0,0,0)
        self.splitter=QSplitter()
        self.toolbox=NodeToolbox()
        self.toolbox.setMaximumWidth(210)
        self.toolbox.itemDoubleClicked.connect(lambda item:self.add_node(KINDS[self.toolbox.row(item)],0,150))
        self.canvas=WorkflowCanvas()
        self.canvas.nodeSelected.connect(self.select_node)
        self.canvas.nodeDropped.connect(self.add_node)
        self.canvas.positionChanged.connect(self.move_node)
        self.canvas.connectionRequested.connect(self.connect_nodes)
        self.canvas.disconnectRequested.connect(self.disconnect_nodes)
        self.canvas.message.connect(self.message)
        self.inspector_scroll=QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setMinimumWidth(240)
        self.inspector=QWidget()
        self.inspector_scroll.setWidget(self.inspector)
        self.splitter.addWidget(self.toolbox)
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.inspector_scroll)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([160,750,340])
        flow_layout.addWidget(self.splitter,1)
        self.tabs.addTab(self.flow_page,"Workflow")
        self.review_page=QWidget()
        review_layout=QVBoxLayout(self.review_page)
        navigation=QHBoxLayout()
        self.page=QSpinBox()
        self.page.setPrefix("Source page ")
        self.page.setRange(1,1)
        self.page.valueChanged.connect(lambda *_:self.review())
        navigation.addWidget(self.page)
        for label,handler in (("View PDF region",self.edit_regions),("Correct value",self.correct),
                              ("Export CSV",self.export_csv),("Accept review",self.accept_review)):
            button=QPushButton(label)
            button.clicked.connect(handler)
            navigation.addWidget(button)
        navigation.addStretch()
        review_layout.addLayout(navigation)
        findings=QHBoxLayout()
        for label,action in (("Previous finding","previous_issue"),("Next finding","next_issue")):
            button=QPushButton(label)
            button.clicked.connect(lambda checked=False,key=action:self.review(action=key))
            findings.addWidget(button)
        findings.addStretch()
        review_layout.addLayout(findings)
        self.review_summary=QLabel("Run the workflow to review extracted fields and envelope boundaries.")
        self.review_summary.setWordWrap(True)
        self.review_summary.setTextFormat(Qt.TextFormat.PlainText)
        review_layout.addWidget(self.review_summary)
        review_split=QSplitter()
        group_panel=QWidget()
        gl=QVBoxLayout(group_panel)
        self.group_table=QTableView()
        self.groups_model=GroupsModel(self)
        self.group_table.setModel(self.groups_model)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.group_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.group_table.horizontalHeader().setStretchLastSection(True)
        self.group_table.clicked.connect(lambda index:self.page.setValue(self.run.groups[index.row()][0]))
        gl.addWidget(self.group_table,1)
        group_actions=QHBoxLayout()
        for label,handler in (("Merge previous",self.merge_previous),("Split at page…",self.split_group)):
            button=QPushButton(label)
            button.clicked.connect(handler)
            group_actions.addWidget(button)
        gl.addLayout(group_actions)
        review_split.addWidget(group_panel)
        self.results=QTableWidget(0,5)
        self.results.setHorizontalHeaderLabels(["Scope","Field","Raw text","Value","Issue"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.horizontalHeader().setStretchLastSection(True)
        review_split.addWidget(self.results)
        review_split.setSizes([270,850])
        review_layout.addWidget(review_split,1)
        self.tabs.addTab(self.review_page,"Review && Data")
        self.production_page=QWidget()
        pl=QVBoxLayout(self.production_page)
        self.production_summary=QPlainTextEdit()
        self.production_summary.setReadOnly(True)
        pl.addWidget(self.production_summary,1)
        output_actions=QHBoxLayout()
        for text,handler in (("Open output PDF",self.open_output),("Show reports",self.show_reports)):
            button=QPushButton(text)
            button.clicked.connect(handler)
            output_actions.addWidget(button)
        output_actions.addStretch()
        pl.addLayout(output_actions)
        self.tabs.addTab(self.production_page,"Production")
        root.addWidget(self.tabs,1)
        self.progress=QProgressBar()
        self.progress.setMaximumHeight(16)
        self.progress.hide()
        root.addWidget(self.progress)
        self.feedback=QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.feedback)
        self.setCentralWidget(central)
        self.statusBar().hide()
        self.apply_spec(self.spec.to_dict())
        self.lock()
        QTimer.singleShot(0,self.canvas.fit)

    def title(self,*_):
        name=self.project_path.name if self.project_path else self.spec.name
        self.setWindowTitle(name+(" *" if not self.undo.isClean() or self.draft_error else "")+" — Workflow")

    def message(self,text):
        self.feedback.setText(str(text))

    error=message

    def watch_settings(self,node,getter,controls):
        self.draft_error=""
        self._draft_node=node.id
        self._draft_getter=getter
        self._draft_initial=copy.deepcopy(getter())
        def changed(*_):
            if self._draft_getter is getter:
                self.draft_error="Unapplied workflow settings" if getter()!=self._draft_initial else ""
                self.title()
                self.properties.edited.emit()
                self.lock()
        for control in controls:
            signal=control.textChanged if isinstance(control,QLineEdit) else control.currentIndexChanged if isinstance(control,QComboBox) else control.valueChanged
            signal.connect(changed)

    def flush_settings(self):
        if self._flushing_settings or not self._draft_getter or not self.draft_error:
            return True
        if self.active_worker or self.capture_active:
            self.message("Wait for the current task before applying settings.")
            return False
        node=next((n for n in self.spec.nodes if n.id==self._draft_node),None)
        value=self._draft_getter()
        if node is None:
            return False
        self._flushing_settings=True
        try:
            return self.params(node,value)
        finally:
            self._flushing_settings=False

    def commit(self,after,label):
        if self.active_worker or self.capture_active:
            self.message("Wait for the current task before editing the workflow.")
            return False
        try:
            WorkflowSpec.from_dict(after)
        except ValueError as exc:
            self.error(exc)
            return False
        before=self.spec.to_dict()
        if before!=after:
            self.undo.push(WorkflowEdit(self,before,after,label))
        return True

    def apply_spec(self,raw):
        previous=self.spec if hasattr(self,"spec") else None
        self.spec=WorkflowSpec.from_dict(raw)
        if previous and previous.fingerprint()!=self.spec.fingerprint():
            upstream=("input","merge","extract","group")
            changed=any((previous.node(k).params if previous.node(k) else None)!=(self.spec.node(k).params if self.spec.node(k) else None) for k in upstream)
            if changed:
                self.review_generation+=1
                self.run=WorkflowRun()
                self.results.setRowCount(0)
                self.groups_model.update([])
            else:
                for n in self.spec.nodes:
                    if n.kind in ("overlay","output"):
                        self.run.statuses.pop(n.id,None)
                        self.run.signatures.pop(n.id,None)
                self.run.output={}
            self.production_summary.clear()
            self.message("Workflow changed. Downstream results will be rebuilt; review is required if input data changed.")
        if self.selected not in [n.id for n in self.spec.nodes]:
            self.selected=self.spec.nodes[0].id
        self._draft_getter=None
        self.draft_error=""
        self.canvas.display(self.spec,self.run.statuses,self.selected)
        self.select_node(self.selected)
        self.title()

    def select_node(self,identity):
        if not self.flush_settings():
            return
        self._draft_getter=None
        self.selected=identity
        node=next((n for n in self.spec.nodes if n.id==identity),None)
        if not node:
            return
        old=self.inspector_scroll.takeWidget()
        if old:
            old.deleteLater()
        self.inspector=QWidget()
        layout=QVBoxLayout(self.inspector)
        title=QLabel(LABELS[node.kind])
        title.setStyleSheet("font-size:16px;font-weight:600")
        layout.addWidget(title)
        self.inspector_scroll.setWidget(self.inspector)
        form=QFormLayout()
        layout.addLayout(form)
        def button(text,fn):
            b=QPushButton(text)
            b.clicked.connect(fn)
            layout.addWidget(b)
        if node.kind=="input":
            paths=node.params.get("paths",[])
            source_list=QListWidget()
            source_list.addItems(paths)
            for i,path in enumerate(paths):
                source_list.item(i).setToolTip(path)
            source_list.setMinimumHeight(90)
            layout.addWidget(source_list)
            button("Add PDFs…",self.add_sources)
            button("Add current workspace PDF",self.add_current_pdf)
            button("Remove selected source",lambda:self.remove_source(source_list.currentRow()))
            button("Locate selected source…",lambda:self.locate_source(source_list.currentRow()))
            for label,offset in (("Move source up",-1),("Move source down",1)):
                button(label,lambda checked=False,d=offset:self.reorder_source(source_list.currentRow(),d))
        elif node.kind=="merge":
            info=QLabel("Source order is set in PDF Input. Select source pages here (All / Odd / Even / 1,3,5–8).")
            info.setWordWrap(True)
            layout.addWidget(info)
            path=QComboBox()
            path.addItems(self.spec.node("input").params.get("paths",[]))
            pages=QLineEdit()
            def update():
                pages.setText(node.params.get("pages",{}).get(path.currentText(),"All"))
            def change_source(index):
                selected_path=path.itemText(index)
                if self.flush_settings():
                    self.select_node(node.id)
                    combo=self.inspector.findChild(QComboBox)
                    if combo:
                        combo.setCurrentText(selected_path)
                        edit=self.inspector.findChild(QLineEdit)
                        current=self.spec.node("merge")
                        edit.setText(current.params.get("pages",{}).get(selected_path,"All"))
                        self.watch_settings(current,lambda:{"pages":{**current.params.get("pages",{}),selected_path:edit.text()}},[edit])
            # The draft getter retains the previous source while the combo changes.
            path.activated.connect(change_source)
            update()
            form.addRow("Source",path)
            form.addRow("Pages",pages)
            source_path=path.currentText()
            self.watch_settings(node,lambda:{"pages":{**node.params.get("pages",{}),source_path:pages.text()}},[pages])
            button("Apply selection",self.flush_settings)
        elif node.kind=="extract":
            info=QLabel(f"{len(node.params.get('regions',[]))} named region(s). Uses PDF text layers; no automatic OCR.")
            info.setWordWrap(True)
            layout.addWidget(info)
            button("Edit visual extraction regions…",self.edit_regions)
        elif node.kind=="group":
            method=QComboBox()
            for label,key in (("Fixed pages per envelope","fixed"),("Extracted field changes","field"),("Printed page-number pattern","pattern")):
                method.addItem(label,key)
            method.setCurrentIndex(method.findData(node.params.get("method","fixed")))
            pages=QSpinBox()
            pages.setRange(1,100)
            pages.setValue(node.params.get("pages",1))
            field=QComboBox()
            extraction=self.spec.node("extract")
            field.addItem("Select extraction field…","")
            for region in extraction.params.get("regions",[]) if extraction else []:
                field.addItem(region["name"],region["name"])
            stored_field=node.params.get("field","")
            if stored_field and field.findData(stored_field)<0:
                field.addItem(stored_field+" (missing)",stored_field)
            field.setCurrentIndex(field.findData(stored_field))
            pattern=QLineEdit(node.params.get("pattern","Page {CURRENT} of {TOTAL}"))
            for label,control in (("Method",method),("Pages",pages),("Grouping field",field),("Pattern",pattern)):
                form.addRow(label,control)
            def availability():
                pages.setEnabled(method.currentData()=="fixed")
                field.setEnabled(method.currentData()=="field")
                pattern.setEnabled(method.currentData()=="pattern")
            method.currentIndexChanged.connect(availability)
            availability()
            self.watch_settings(node,lambda:{"method":method.currentData(),"pages":pages.value(),
                                            "field":field.currentData(),"pattern":pattern.text()},[method,pages,field,pattern])
            button("Apply grouping",self.flush_settings)
        elif node.kind=="review":
            info=QLabel("Review extracted values and envelope boundaries. Production waits for explicit acceptance and zero unresolved findings.")
            info.setWordWrap(True)
            layout.addWidget(info)
            button("Open review",lambda:self.tabs.setCurrentWidget(self.review_page))
        elif node.kind=="overlay":
            label=QLabel(node.params.get("path","") or "No overlay configured")
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
            button("Create / edit in Designer…",self.edit_overlay)
            button("Choose overlay project…",self.choose_overlay)
        elif node.kind=="output":
            folder=QLineEdit(node.params.get("directory",""))
            form.addRow("Output folder",folder)
            button("Browse…",lambda:self.choose_output(node))
            self.watch_settings(node,lambda:{"directory":folder.text().strip()},[folder])
            button("Apply folder",self.flush_settings)
            info=QLabel("A new job folder contains the validated PDF, extracted-data.csv, production reports and workflow.json.")
            info.setWordWrap(True)
            layout.addWidget(info)
        button("Connect to next…",lambda:self.connect_dialog(node))
        if node.kind in ("merge","overlay"):
            button("Remove optional step",lambda:self.remove_node(node))
        layout.addStretch()
        self.inspector.setEnabled(not bool(self.active_worker or self.capture_active))

    def params(self,node,value):
        after=self.spec.to_dict()
        next(n for n in after["nodes"] if n["id"]==node.id)["params"]=copy.deepcopy(value)
        if node.kind=="input" and len(value.get("paths",[]))>1 and not self.spec.node("merge"):
            merge=WorkflowNode("merge",x=max(n.x for n in self.spec.nodes)+215,y=0)
            after["nodes"].append(asdict(merge))
            edge=[node.id,self.spec.node("extract").id]
            if edge in after["edges"]:
                after["edges"].remove(edge)
                after["edges"].extend([[node.id,merge.id],[merge.id,edge[1]]])
        return self.commit(after,"Configure "+LABELS[node.kind])

    def add_optional(self,kind):
        if not self.flush_settings() or self.spec.node(kind):
            if self.spec.node(kind):
                self.select_node(self.spec.node(kind).id)
            return
        after=self.spec.to_dict()
        node=WorkflowNode(kind,x=max(n.x for n in self.spec.nodes)+215,y=150 if kind=="overlay" else 0)
        before,following=("input","extract") if kind=="merge" else ("review","output")
        a,b=self.spec.node(before).id,self.spec.node(following).id
        after["nodes"].append(asdict(node))
        if [a,b] in after["edges"]:
            after["edges"].remove([a,b])
            after["edges"].extend([[a,node.id],[node.id,b]])
        self.commit(after,"Insert "+LABELS[kind])
        self.select_node(node.id)

    def add_node(self,kind,x,y):
        if not self.flush_settings():
            return
        if self.spec.node(kind):
            self.message("This step already exists. Select it to change its settings.")
            return
        after=self.spec.to_dict()
        after["nodes"].append(asdict(WorkflowNode(kind,x=x,y=y)))
        self.commit(after,"Add workflow step")

    def remove_node(self,node):
        if not self.flush_settings():
            return
        after=self.spec.to_dict()
        previous=next((a for a,b in after["edges"] if b==node.id),None)
        following=next((b for a,b in after["edges"] if a==node.id),None)
        after["nodes"]=[n for n in after["nodes"] if n["id"]!=node.id]
        after["edges"]=[e for e in after["edges"] if node.id not in e]
        if previous and following:
            after["edges"].append([previous,following])
        self.commit(after,"Remove optional step")

    def move_node(self,identity,x,y):
        if not self.flush_settings():
            return
        after=self.spec.to_dict()
        node=next(n for n in after["nodes"] if n["id"]==identity)
        node.update(x=x,y=y)
        self.commit(after,"Move workflow node")

    def connect_nodes(self,a,b):
        if not self.flush_settings():
            return
        after=self.spec.to_dict()
        after["edges"]=[e for e in after["edges"] if e[0]!=a and e[1]!=b]
        after["edges"].append([a,b])
        self.commit(after,"Connect workflow steps")

    def disconnect_nodes(self,a,b):
        if not self.flush_settings():
            return
        after=self.spec.to_dict()
        after["edges"]=[e for e in after["edges"] if e!=[a,b]]
        self.commit(after,"Disconnect workflow steps")

    def connect_dialog(self,node):
        targets=[n for n in self.spec.nodes if n.id!=node.id]
        label,ok=QInputDialog.getItem(self,"Connect step","Next step",[LABELS[n.kind] for n in targets],0,False)
        if ok:
            self.connect_nodes(node.id,next(n.id for n in targets if LABELS[n.kind]==label))

    def add_sources(self):
        paths,_=QFileDialog.getOpenFileNames(self,"Add workflow sources","","PDF (*.pdf)")
        if paths:
            node=self.spec.node("input")
            values=list(dict.fromkeys([*node.params.get("paths",[]),*paths]))
            self.params(node,{"paths":values})

    def remove_source(self,index):
        node=self.spec.node("input")
        paths=list(node.params.get("paths",[]))
        if 0<=index<len(paths):
            paths.pop(index)
            self.params(node,{"paths":paths})

    def locate_source(self,index):
        node=self.spec.node("input")
        paths=list(node.params.get("paths",[]))
        if not 0<=index<len(paths):
            return
        path,_=QFileDialog.getOpenFileName(self,"Locate source PDF","","PDF (*.pdf)")
        if path:
            old=paths[index]
            paths[index]=path
            after=self.spec.to_dict()
            next(n for n in after["nodes"] if n["id"]==node.id)["params"]={"paths":paths}
            merge=self.spec.node("merge")
            if merge:
                params=next(n["params"] for n in after["nodes"] if n["id"]==merge.id)
                selections=params.get("pages",{})
                if old in selections:
                    selections[path]=selections.pop(old)
            self.commit(after,"Locate workflow source")

    def reorder_source(self,index,offset):
        node=self.spec.node("input")
        paths=list(node.params.get("paths",[]))
        other=index+offset
        if 0<=index<len(paths) and 0<=other<len(paths):
            paths[index],paths[other]=paths[other],paths[index]
            self.params(node,{"paths":paths})

    def add_current_pdf(self):
        if self.active_worker or not self.project_host or not self.project_host.handoff:
            return
        window=self.project_host.handoff.window
        session=window._session
        if not session or not session.engine.is_loaded() or window._tasks:
            self.error("Open a PDF and wait for its task to finish first.")
            return
        import uuid

        from ui.merge_workspace import capture_merge_source
        if session.form_draft and session.form_draft.changed:
            prompt=QMessageBox(self)
            prompt.setText("Apply the form draft before capturing this PDF?")
            apply=prompt.addButton("Apply",QMessageBox.ButtonRole.AcceptRole)
            ignore=prompt.addButton("Send without draft",QMessageBox.ButtonRole.ActionRole)
            prompt.addButton(QMessageBox.StandardButton.Cancel)
            prompt.exec()
            if prompt.clickedButton() is apply:
                window.workspace.set_current_session(session)
                if not window._apply_form_draft():
                    return
            elif prompt.clickedButton() is not ignore:
                return
        target=self.directory/("workspace-"+uuid.uuid4().hex+".pdf")
        identity=(session.engine.document_id,session.engine.revision)
        self.capture_active=True
        page=window._mode_controller.modes.pages["pdf"]
        enabled=page.isEnabled()
        page.setEnabled(False)
        self.lock()
        def ready(_result):
            self.capture_active=False
            node=self.spec.node("input")
            self.params(node,{"paths":[*node.params.get("paths",[]),str(target)]})
        def finished():
            self.capture_active=False
            page.setEnabled(enabled)
            self.lock()
        window._run_task("Capturing PDF for Workflow",capture_merge_source,session.engine,identity,target,
                         cancel_argument="is_cancelled",on_result=ready,on_finished=finished)

    def edit_regions(self):
        if self.active_worker or self.capture_active or not self.flush_settings():
            return
        source=self.run.source or next(iter(self.spec.node("input").params.get("paths",[])),"")
        if not source:
            self.message("Add a PDF source first.")
            return
        from .regions_ui import RegionEditor
        node=self.spec.node("extract")
        dialog=RegionEditor(self,source,node.params,self.page.value())
        self.region_dialog=dialog
        if dialog.exec():
            self.params(node,{"regions":dialog.regions,"version":1})
        self.region_dialog=None

    def run_selected(self):
        node=next(n for n in self.spec.nodes if n.id==self.selected)
        self.execute(node.kind)

    def execute(self,until):
        if self.active_worker or self.capture_active or not self.flush_settings():
            return
        try:
            self.spec.chain()
        except ValueError as exc:
            self.error(exc)
            return
        overlay=self.spec.node("overlay")
        if until in ("overlay","output") and overlay and overlay.params.get("path") and self.project_host:
            key=self.project_host.identity(overlay.params["path"])
            for project in self.project_host.projects:
                if project is self or not project.project_path or self.project_host.identity(project.project_path)!=key:
                    continue
                if self.project_host.is_busy(project):
                    self.message("Wait for the overlay project's task to finish before production.")
                    return
                project.properties.apply()
                if not project.undo.isClean() or getattr(project,"draft_error", ""):
                    self.message("Save or repair the open overlay project before running Workflow; production uses its saved version.")
                    return
        if until=="output":
            self.run.statuses.pop(self.spec.node("output").id,None)
            self.run.output={}
            self.production_summary.setPlainText("Production is running. The result will appear when the job finishes.")
        def ready(result):
            self.run=WorkflowRun(**result)
            self.canvas.display(self.spec,self.run.statuses,self.selected)
            self.message(self.run.error or ("Review and accept the results before production." if not self.run.accepted else "Workflow step completed."))
            self.groups_model.update(self.run.groups)
            if not self.run.database:
                self.results.setRowCount(0)
            if self.run.database:
                QTimer.singleShot(0,self.review)
                if not self.run.output:
                    self.tabs.setCurrentWidget(self.review_page)
            if self.run.output:
                self.production_summary.setPlainText(self.result_summary())
                self.tabs.setCurrentWidget(self.production_page)
        self.request({"operation":"run","spec":self.spec.to_dict(),"run":asdict(self.run),
                      "directory":str(self.directory),"until":until},ready)

    def request(self,request,callback,*,preview=False):
        if self.close_pending or (self.active_worker and not preview):
            return None
        worker=Worker(self.directory,{"task":"workflow",**request},self)
        self.workers.append(worker)
        if not preview:
            previous=getattr(self,"preview_worker",None)
            if previous and not sip.isdeleted(previous) and previous.running:
                previous.superseded=True
                previous.stop_preview()
            self.active_worker=worker
        else:
            previous=getattr(self,"preview_worker",None)
            if previous and not sip.isdeleted(previous) and previous.running:
                previous.superseded=True
                previous.stop_preview()
            self.preview_worker=worker
        delivered=[]
        failures=[]
        worker.resultReady.connect(delivered.append)
        worker.failed.connect(failures.append)
        if not preview:
            worker.progress.connect(self.update_progress)
        def ended():
            if worker in self.workers:
                self.workers.remove(worker)
            if worker is self.active_worker:
                self.active_worker=None
            if worker is getattr(self,"preview_worker",None):
                self.preview_worker=None
            if not self.close_pending and not getattr(worker,"superseded",False):
                if delivered:
                    callback(delivered[0])
                elif failures and not getattr(worker,"superseded",False):
                    if request.get("operation")=="run":
                        self.run.error=failures[0]
                        self.run.output={}
                        self.run.accepted=False
                        for identity,status in list(self.run.statuses.items()):
                            if status=="Running":
                                self.run.statuses[identity]="Cancelled" if getattr(worker,"cancel_requested",False) else "Failed"
                        self.canvas.display(self.spec,self.run.statuses,self.selected)
                        self.production_summary.setPlainText("Workflow failed: "+failures[0])
                    self.error(failures[0])
            if preview and request.get("operation")=="preview":
                target=Path(request["target"]).resolve()
                if target.is_relative_to(self.directory.resolve()):
                    target.unlink(missing_ok=True)
            self.lock()
            if self.close_pending and not self.workers:
                QTimer.singleShot(0,self.close)
        worker.ended.connect(ended)
        self.lock()
        return worker

    def update_progress(self,current,total,message):
        self.progress.setRange(0,total)
        self.progress.setValue(current)
        self.message(message)
        if message.startswith("Workflow: "):
            node=self.spec.node(message.split(": ",1)[1])
            if node:
                self.run.statuses[node.id]="Running"
                self.canvas.display(self.spec,self.run.statuses,self.selected)

    def lock(self,*_):
        if sip.isdeleted(self):
            return
        busy=bool(self.active_worker or self.capture_active or self.close_pending)
        for key,act in self.actions.items():
            enabled=not busy if key!="cancel" else bool(self.active_worker)
            if key in ("undo","redo"):
                enabled=enabled and not self.draft_error and (self.undo.canUndo() if key=="undo" else self.undo.canRedo())
            act.setEnabled(enabled)
        if hasattr(self,"add_step"):
            self.add_step.setEnabled(not busy)
        if not hasattr(self,"toolbox"):
            return
        self.toolbox.setEnabled(not busy)
        self.canvas.setEnabled(not busy)
        self.inspector.setEnabled(not busy)
        self.review_page.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.actions["cancel"].setVisible(bool(self.active_worker))
        self.activityChanged.emit()

    def cancel_job(self):
        if self.active_worker:
            self.active_worker.cancel_requested=True
            self.active_worker.cancel()
            self.message("Cancellation requested; waiting for a safe checkpoint.")

    def review(self,*,action="",after=None,**values):
        if not self.run.database or self.active_worker:
            return
        self.review_generation+=1
        generation=self.review_generation
        def ready(result):
            if generation!=self.review_generation:
                return
            self.run.accepted=result["accepted"]
            self.run.groups=result["groups"]
            self.groups_model.update(self.run.groups)
            self.page.blockSignals(True)
            self.page.setMaximum(result["pages"])
            self.page.setValue(result["page"])
            self.page.blockSignals(False)
            if result["envelope"]:
                self.group_table.selectRow(result["envelope"]-1)
            selected_row=self.results.currentRow()
            selected_field=(self.results.item(selected_row,0).text(),self.results.item(selected_row,1).text()) if selected_row>=0 else None
            self.results.setRowCount(0)
            for scope,rows in (("Page",result["cells"]),("Envelope",result["envelope_cells"])):
                for cell in rows:
                    row=self.results.rowCount()
                    self.results.insertRow(row)
                    for col,text in enumerate((scope,cell["field"],cell.get("raw",""),cell["value"],cell["issue"] if cell.get("applicable",1) else "Not applicable")):
                        item=QTableWidgetItem(str(text))
                        item.setToolTip(str(text))
                        item.setData(Qt.ItemDataRole.UserRole,result["page"])
                        self.results.setItem(row,col,item)
                    if selected_field==(scope,cell["field"]):
                        self.results.selectRow(row)
            self.review_summary.setText(f"{result['pages']:,} pages · {len(self.run.groups):,} envelopes · {result['issues']:,} unresolved findings · "
                                        +("Review accepted" if self.run.accepted else "Review required"))
            if self.spec.node("review"):
                self.run.statuses[self.spec.node("review").id]="Completed" if self.run.accepted else "Needs review"
            self.canvas.display(self.spec,self.run.statuses,self.selected)
            if after:
                after(result)
        self.request({"operation":"review","database":self.run.database,"groups":self.run.groups,
                      "page":self.page.value(),"action":action,**values},ready,preview=action in ("","next_issue","previous_issue"))

    def correct(self):
        row=self.results.currentRow()
        if row<0 or self.results.item(row,0).text()!="Page":
            self.message("Select a page field. Envelope values are rebuilt from source-page values.")
            return
        field=self.results.item(row,1).text()
        source_page=self.results.item(row,1).data(Qt.ItemDataRole.UserRole)
        if source_page!=self.page.value():
            self.message("Wait for the selected page's fields to finish loading before correcting a value.")
            return
        value,ok=QInputDialog.getMultiLineText(self,"Correct extracted value",field,self.results.item(row,3).text())
        if not ok:
            return
        reason,ok=QInputDialog.getText(self,"Correction reason","Explain the correction (retained in the report)")
        if ok and reason.strip():
            self.run.accepted=False
            self.run.output={}
            for kind in ("review","overlay","output"):
                if self.spec.node(kind):
                    self.run.statuses.pop(self.spec.node(kind).id,None)
            self.production_summary.setPlainText("Data changed; review again before generating a new production PDF.")
            self.review(action="correct",page=source_page,field=field,value=value,reason=reason)

    def accept_review(self):
        if not self.run.groups or self.run.statuses.get(self.spec.node("group").id)!="Completed":
            self.message("Complete grouping with Scan & review before accepting the results.")
            return
        self.review(action="accept")

    def export_csv(self):
        target,_=QFileDialog.getSaveFileName(self,"Export extracted data","","CSV (*.csv)")
        if target:
            target=Path(target).with_suffix(".csv")
            protected=[self.run.source,self.run.database,*self.spec.node("input").params.get("paths",[])]
            if target.resolve() in [Path(p).resolve() for p in protected if p]:
                self.message("Choose a report filename that does not replace a workflow source or database.")
                return
            self.review(action="export",target=str(target))

    def change_groups(self,groups):
        self.run.accepted=False
        self.run.output={}
        for kind in ("review","overlay","output"):
            if self.spec.node(kind):
                self.run.statuses.pop(self.spec.node(kind).id,None)
        self.production_summary.setPlainText("Envelope boundaries changed; review again before production.")
        self.review(action="groups",groups=groups)

    def merge_previous(self):
        index=self.group_table.currentIndex().row()
        if index>0:
            groups=copy.deepcopy(self.run.groups)
            groups[index-1][1]=groups.pop(index)[1]
            self.change_groups(groups)

    def split_group(self):
        index=self.group_table.currentIndex().row()
        if not 0<=index<len(self.run.groups):
            return
        start,end=self.run.groups[index]
        if start==end:
            self.message("A one-page envelope cannot be split.")
            return
        number,ok=QInputDialog.getInt(self,"Split envelope","First source page of new envelope",start+1,start+1,end)
        if ok:
            groups=copy.deepcopy(self.run.groups)
            groups[index:index+1]=[[start,number-1],[number,end]]
            self.change_groups(groups)

    def choose_overlay(self):
        path,_=QFileDialog.getOpenFileName(self,"Select overlay project","","Overlay project (*.pdcx)")
        if path:
            self.params(self.spec.node("overlay"),{"path":path})

    def edit_overlay(self):
        node=self.spec.node("overlay")
        if node.params.get("path"):
            if self.project_host:
                project=self.project_host.open_project(node.params["path"])
                if project and self.run.database:
                    self.bind_overlay(project)
            return
        if not self.run.groups or not self.run.source:
            self.message("Run to review first so Designer can use the current source and grouping.")
            return
        path,_=QFileDialog.getSaveFileName(self,"Save workflow overlay","","Overlay project (*.pdcx)")
        if not path:
            return
        target=Path(path).with_suffix(".pdcx")
        if self.project_host and any(p.project_path and self.project_host.identity(p.project_path)==self.project_host.identity(target) for p in self.project_host.projects):
            self.message("That overlay project is already open. Choose another filename or select it with Choose overlay project.")
            return
        def ready(result):
            # Worker is still finishing; apply after its cleanup boundary.
            def adopt():
                self.params(node,{"path":result["path"]})
                if self.project_host:
                    project=self.project_host.open_project(result["path"])
                    if project:
                        project.workflow_database=self.run.database
                        project.timer.start()
            QTimer.singleShot(0,adopt)
        self.request({"operation":"make_overlay","spec":self.spec.to_dict(),"groups":self.run.groups,
                      "source":self.run.source,"path":str(target)},ready)

    def bind_overlay(self,project):
        if sip.isdeleted(self) or sip.isdeleted(project) or self.close_pending or project.close_pending:
            return
        if project.active_worker:
            project.active_worker.ended.connect(lambda:QTimer.singleShot(0,lambda:self.bind_overlay(project)))
            return
        if not project.spec or not self.run.groups or not self.run.source:
            self.message("Run to review before synchronising the overlay preview.")
            return
        project.properties.apply()
        if project.draft_error or self.project_host.is_busy(project):
            self.message("Finish the overlay edit or task before updating its workflow source.")
            return
        if self.active_worker:
            return
        project.workflow_binding=True
        project.timer.stop()
        project.preview_generation+=1
        project.busy()
        def ready(result):
            if sip.isdeleted(project) or project.close_pending:
                return
            # The binding is an undoable project edit. Layout, fonts, sequence and
            # barcode choices are preserved; production still requires a saved project.
            project.workflow_database=self.run.database
            if project.commit(result["spec"],"Synchronise workflow source and envelopes"):
                project.schedule_preview()
                self.message("Designer now previews the current workflow source and envelope boundaries. Save the overlay if its source changed.")
        worker=self.request({"operation":"bind_overlay","spec":self.spec.to_dict(),"groups":self.run.groups,
                             "source":self.run.source,"path":str(project.project_path),"project":project.spec.to_dict()},ready)
        def release():
            if not sip.isdeleted(project):
                project.workflow_binding=False
                project.busy()
        if worker:
            worker.ended.connect(release)
        else:
            release()

    def choose_output(self,node):
        path=QFileDialog.getExistingDirectory(self,"Output folder")
        if path:
            self.params(node,{"directory":path})

    def result_summary(self):
        output=self.run.output
        return "\n".join(f"{key}: {output.get(key,'')}" for key in ("job_id","status","source_pages","input_envelopes",
                          "successful_envelopes","failed_envelopes","generated_pages","expected_barcodes",
                          "decoded_barcodes","output_pdf","report_dir","error"))

    def open_output(self):
        path=self.run.output.get("output_pdf")
        if path and self.project_host:
            self.project_host.open_pdf(path)

    def show_reports(self):
        path=self.run.output.get("report_dir")
        if path:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def new_project(self):
        if self.project_host:
            self.project_host.new_workflow()

    def open_project(self,checked=False,path=None):
        if self.project_host:
            self.project_host.open_project(path)

    def load_path(self,path):
        def ready(result):
            self.apply_spec(result["spec"])
            self.project_path=Path(path)
            self.undo.clear()
            self.undo.setClean()
            self.title()
            self.canvas.fit()
        self.request({"operation":"load","path":str(path)},ready)

    def save_project(self,checked=False,*,save_as=False,path=None,after=None):
        if self.active_worker or self.capture_active:
            self.error("Wait for the current task before saving.")
            return False
        if not self.flush_settings():
            return False
        path=path or (str(self.project_path) if self.project_path and not save_as else "")
        if not path:
            path,_=QFileDialog.getSaveFileName(self,"Save workflow","","Workflow (*.pdflow)")
        if not path:
            return False
        if self.project_host and not self.project_host.allow_save_path(self,path):
            return False
        def ready(result):
            self.project_path=Path(result["path"])
            self.undo.setClean()
            self.title()
            if after:
                QTimer.singleShot(0,after)
        return self.request({"operation":"save","spec":self.spec.to_dict(),"path":path},ready)

    def closeEvent(self,event):
        if self.capture_active:
            self.error("Finish capturing the workspace PDF before closing.")
            event.ignore()
            return
        if self.embedded and not self._close_approved and not self.close_pending:
            event.ignore()
            QTimer.singleShot(0,lambda:self.project_host.close_project(self))
            return
        if not self.close_pending:
            if not self.active_worker and not self._close_approved and not self.flush_settings():
                event.ignore()
                return
            if not self._close_approved and not self.undo.isClean():
                answer=QMessageBox.question(self,"Unsaved workflow","Discard this workflow?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
                if answer!=QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self.close_pending=True
            for worker in self.workers[:]:
                worker.cancel()
        if self.workers:
            event.ignore()
            return
        if self.project_host:
            for project in self.project_host.projects:
                if getattr(project,"workflow_database",None)==self.run.database:
                    project.workflow_database=""
        self.temp.cleanup()
        event.accept()
        self.projectClosed.emit()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange,QEvent.Type.StyleChange):
            from styles.theme import get_color
            for action in getattr(self,"actions",{}).values():
                symbol=action.property("workflow_icon")
                if symbol:
                    action.setIcon(icon(symbol,color=get_color("text_primary")))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"toolbox"):
            self.toolbox.setVisible(self.width()>=1080)
            self.inspector_scroll.setMinimumWidth(210 if self.width()<1080 else 260)
            for key in ("scan","generate"):
                button=self.layout_toolbar.widgetForAction(self.actions[key])
                if isinstance(button,QToolButton):
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if self.width()>=1080 else Qt.ToolButtonStyle.ToolButtonIconOnly)

