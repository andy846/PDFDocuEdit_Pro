"""Human-readable settings for executable data steps, with shared validation."""
from dataclasses import asdict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from composition.template.model import ConditionGroup, RuleCondition

from .registry import DATA_KINDS, REGISTRY


class StepDialog(QDialog):
    edited=pyqtSignal()

    def __init__(self,node,fields,parent=None,*,embedded=False):
        super().__init__(parent)
        self.embedded=embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.node=node
        self.fields=fields
        self.setWindowTitle(REGISTRY[node.kind].label)
        self.resize(780,560)
        root=QVBoxLayout(self)
        description=QLabel(REGISTRY[node.kind].description)
        description.setWordWrap(True)
        root.addWidget(description)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        body=QWidget()
        self.content=QVBoxLayout(body)
        scroll.setWidget(body)
        root.addWidget(scroll,1)
        self.rows=[]
        self.controls={}
        if node.kind=="filter_records":
            from composition.designer.rules_dialog import ConditionEditor
            group=ConditionGroup(node.params.get("mode","all"),[RuleCondition(**c) for c in node.params["conditions"]])
            self.conditions=ConditionEditor("Keep matching records / whole envelopes",fields,group,self)
            self.conditions.setChecked(True)
            self.content.addWidget(self.conditions)
        elif node.kind in DATA_KINDS:
            key={"clean_fields":"operations","create_fields":"fields","sort_records":"keys","validate_data":"checks"}[node.kind]
            self.items_key=key
            for values in node.params[key]:
                self.add_row(values)
            add=QPushButton("+ Add another operation")
            add.clicked.connect(lambda:self.add_row())
            self.content.addWidget(add)
        else:
            form=QFormLayout()
            self.content.addLayout(form)
            if node.kind=="running_sequence":
                for key,label in (("name","Field name"),("start","Start"),("step","Increment"),("padding","Digit padding"),
                                  ("prefix","Prefix"),("suffix","Suffix")):
                    control=QLineEdit(str(node.params.get(key,"")))
                    form.addRow(label,control)
                    self.controls[key]=control
                scope=QComboBox()
                for label,value in (("Per record / envelope","record"),("Per output page","page")):
                    scope.addItem(label,value)
                scope.setCurrentIndex(max(0,scope.findData(node.params.get("scope","record"))))
                self.controls["scope"]=scope
                form.addRow("Scope",scope)
            else:
                method=QComboBox()
                method.addItem("Whole records / envelopes per file","count")
                method.addItem("Field value","field")
                method.setCurrentIndex(max(0,method.findData(node.params.get("method","count"))))
                count=QSpinBox()
                count.setRange(1,1000000)
                count.setValue(node.params.get("count",1000))
                field=self.field_control(node.params.get("field",fields[0] if fields else "Name"))
                self.controls.update(method=method,count=count,field=field)
                for label,widget in (("Split by",method),("Quantity",count),("Field",field)):
                    form.addRow(label,widget)
                def update():
                    field.setEnabled(method.currentData()=="field")
                    count.setEnabled(method.currentData()=="count")
                method.currentIndexChanged.connect(update)
                update()
        self.content.addStretch()
        self.error=QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if embedded:
            buttons.hide()
            self.connect_edits(self)

    def connect_edits(self,root):
        for control in root.findChildren(QWidget):
            if control.property("workflow_edit_connected"):
                continue
            signal=(control.textChanged if isinstance(control,QLineEdit) else control.currentTextChanged
                    if isinstance(control,QComboBox) else control.toggled if isinstance(control,QCheckBox)
                    else control.valueChanged if isinstance(control,QSpinBox) else None)
            if signal is not None:
                signal.connect(self.edited)
                control.setProperty("workflow_edit_connected",True)

    def field_control(self,value):
        control=QComboBox()
        control.setEditable(True)
        control.addItems(self.fields)
        control.setCurrentText(value)
        control.setMinimumContentsLength(10)
        return control

    def add_row(self,values=None):
        if len(self.rows)>=100:
            return
        values=dict(values or {"field":self.fields[0] if self.fields else "Name"})
        box=QWidget()
        form=QFormLayout(box)
        controls={"field":self.field_control(values["field"])}
        form.addRow("Field",controls["field"])
        specs={
            "clean_fields":(("operation","Operation",("trim","join_lines","remove_prefix","upper","lower","replace")),
                            ("value","Prefix / literal search",None),("replacement","Replacement",None)),
            "create_fields":(("operation","Operation",("constant","concat","pad","first","last")),
                             ("sources","Source fields (comma separated)",None),("value","Constant text",None),
                             ("separator","Join separator",None),("length","Length / padding",None),
                             ("overwrite","Explicitly overwrite existing field",False)),
            "sort_records":(("type","Comparison",("text","number")),("descending","Descending",False)),
            "validate_data":(("check","Check",("required","length","number","unique")),
                             ("min","Minimum length",None),("max","Maximum length",None),
                             ("severity","On finding",("error","warning"))),
        }
        for key,label,choices in specs[self.node.kind]:
            value=values.get(key,{"length":6,"min":0,"max":10000}.get(key,""))
            if choices is False:
                control=QCheckBox()
                control.setChecked(bool(value))
            elif choices:
                control=QComboBox()
                control.addItems(choices)
                control.setCurrentText(value if value in choices else choices[0])
            else:
                control=QLineEdit(", ".join(value) if isinstance(value,list) else str(value))
            controls[key]=control
            form.addRow(label,control)
        remove=QPushButton("Remove this operation")
        def discard():
            self.rows.remove(controls)
            box.deleteLater()
            self.edited.emit()
        remove.clicked.connect(discard)
        form.addRow(remove)
        self.rows.append(controls)
        self.content.insertWidget(max(0,self.content.count()-1),box)
        if getattr(self,"embedded",False):
            self.connect_edits(box)
            self.edited.emit()

    def value(self):
        if self.node.kind=="filter_records":
            group=self.conditions.read_group()
            if group is None:
                raise ValueError("Enable the filter's matching conditions.")
            return asdict(group)
        if self.node.kind in DATA_KINDS:
            result=[]
            for controls in self.rows:
                row={}
                for key,widget in controls.items():
                    value=(widget.isChecked() if isinstance(widget,QCheckBox) else widget.currentText()
                           if isinstance(widget,QComboBox) else widget.text())
                    if key in ("length","min","max"):
                        value=int(value)
                    elif key=="sources":
                        value=[v.strip() for v in value.split(",") if v.strip()]
                    row[key]=value
                result.append(row)
            return {self.items_key:result}
        values={key:widget.currentData() if isinstance(widget,QComboBox) and key!="field" else
                widget.currentText() if isinstance(widget,QComboBox) else widget.value() if isinstance(widget,QSpinBox)
                else widget.text() for key,widget in self.controls.items()}
        if self.node.kind=="running_sequence":
            for key in ("start","step","padding"):
                values[key]=int(values[key])
        elif values["method"]=="field":
            values.pop("count")
        else:
            values.pop("field")
        return values

    def accept(self):
        try:
            self.options=self.value()
            REGISTRY[self.node.kind].validate_options(self.options)
        except (ValueError,TypeError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()


def install(window,node):
    window.inspector=QWidget()
    layout=QVBoxLayout(window.inspector)
    heading=QLabel(REGISTRY[node.kind].label)
    heading.setStyleSheet("font-size:16px;font-weight:600;")
    layout.addWidget(heading)
    description=QLabel(REGISTRY[node.kind].description)
    description.setWordWrap(True)
    layout.addWidget(description)
    def settings_text():
        if node.kind=="media_assignment":
            printer=node.params.get("printer_profile",{})
            backend="PDF + PostScript" if printer.get("backend")=="postscript" else "PDF + JDF"
            return (f"{node.params.get('mode','page')} rules · {len(node.params.get('stocks',[]))} Stocks\n"
                    f"{'Duplex' if node.params.get('duplex') else 'Simplex'} · blank policy: {node.params.get('blank_policy','block')}\n"
                    f"{backend} · {printer.get('profile_name') or 'Unnamed profile'}\nDevice validation pending")
        if node.kind in DATA_KINDS:
            key={"clean_fields":"operations","create_fields":"fields","filter_records":"conditions",
                 "sort_records":"keys","validate_data":"checks"}[node.kind]
            return "\n".join(" · ".join(str(v) for v in item.values()) for item in node.params.get(key,[]))
        if node.kind=="running_sequence":
            return f"{node.params.get('name')} · start {node.params.get('start',1)} · increment {node.params.get('step',1)}\n{node.params.get('scope','record')} scope · {node.params.get('padding',0)} digits"
        return (f"Field: {node.params.get('field','')}" if node.params.get('method')=='field' else
                f"{node.params.get('count',1000):,} complete records / envelopes per file")
    details=QLabel(settings_text())
    details.setWordWrap(True)
    details.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(details)
    summaries=[]
    jobs=window.selected_jobs() if hasattr(window,"selected_jobs") else []
    for job in jobs[:1]:
        summaries=job.data_summary.get("steps",[])
    if not jobs:
        summaries=getattr(window.run,"data_steps",[])
    summary=next((s for s in reversed(summaries) if s.get("node_id")==node.id),None)
    fields=[]
    checked=window.inspections.current(node.id)
    if checked:
        fields=checked.get("fields",[])
    if not fields and jobs and jobs[0].data_summary:
        fields=jobs[0].data_summary.get("fields",[])
    if not fields and window.spec.node("extract"):
        fields=[r["name"] for r in window.spec.node("extract").params.get("regions",[]) if "name" in r]
    def configure():
        if not window.flush_settings() or window.active_worker:
            return
        if node.kind=="media_assignment":
            from composition.designer.media_dialog import MediaDialog
            context=None
            if jobs and jobs[0].prepared_template and jobs[0].input_records:
                context={"kind":"template","project":jobs[0].prepared_template,"records":jobs[0].input_records}
            elif window.run.groups and window.run.source:
                context={"kind":"workflow_pdf","source":window.run.source,"groups":window.run.groups,
                         "data_set":window.run.data_set}
            dialog=MediaDialog(node.params,context,window)
        else:
            dialog=StepDialog(node,fields,window)
        if dialog.exec():
            window.params(node,dialog.options)
    button=QPushButton("Configure step…")
    button.setProperty("primary",True)
    button.clicked.connect(configure)
    if node.kind in DATA_KINDS or node.kind in ("running_sequence","split_output"):
        editor=StepDialog(node,fields,window.inspector,embedded=True)
        layout.addWidget(editor)
        window.watch_settings(node,editor.value,[])
        def edited():
            from .drafts import update_error
            if window._draft_node==node.id:
                window.node_drafts.pop(node.id,None)
                update_error(window)
                window.title()
                window.properties.edited.emit()
        editor.edited.connect(edited)
    else:
        layout.addWidget(button)
    report_summary=jobs[0].data_summary if jobs else getattr(window.run,"data_summary",{})
    if node.kind=="media_assignment" and report_summary.get("media"):
        media=report_summary["media"]
        text=QLabel(f"{media['pages']:,} final pages · {media['sheets']:,} sheets · {media['inserted_blanks']:,} blank backs\n"+
                   " · ".join(f"{k}: {v:,}" for k,v in media["stock_sheets"].items()))
        text.setWordWrap(True)
        layout.addWidget(text)
    if summary and summary.get("scope")=="page":
        report_summary=summary
    if report_summary:
        for key,label in (("findings_report","Open validation findings"),("exclusions_report","Open excluded records")):
            path=report_summary.get(key)
            if path:
                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices
                button=QPushButton(label)
                button.clicked.connect(lambda checked=False,p=path:QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
                layout.addWidget(button)
    if summary:
        label=QLabel(f"Input {summary['input']:,} · Kept {summary['retained']:,}\nExcluded {summary['excluded']:,} · Issues {summary['issues']:,}")
        label.setWordWrap(True)
        layout.addWidget(label)
        preview=QTableWidget(0,3)
        preview.setHorizontalHeaderLabels(["Source","Before","After / reason"])
        preview.setMinimumHeight(200)
        preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for sample in summary.get("samples",[]):
            row=preview.rowCount()
            preview.insertRow(row)
            for col,value in enumerate((sample["source_id"],sample.get("before",{}),sample.get("after",{}))):
                text=str(value) if col==0 else "\n".join(f"{k}: {v}" for k,v in value.items())
                if col==2 and not sample.get("retained",True):
                    text="EXCLUDED: "+sample.get("reason","")+"\n"+text
                item=QTableWidgetItem(text)
                item.setToolTip(text)
                preview.setItem(row,col,item)
        preview.resizeRowsToContents()
        layout.addWidget(preview)
    else:
        text=QLabel("Check & Preview once to inspect this step's source identities, counts and before/after examples.")
        text.setWordWrap(True)
        layout.addWidget(text)
    for label,callback in (("Duplicate step",lambda:window.duplicate_node(node)),("Move earlier",lambda:window.reorder_node(node,-1)),
                           ("Move later",lambda:window.reorder_node(node,1)),("Remove step",lambda:window.remove_node(node))):
        if label=="Duplicate step" and not REGISTRY[node.kind].repeatable:
            continue
        button=QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
    layout.addStretch()
    window.inspector_scroll.setWidget(window.inspector)
    window.inspector.setEnabled(not bool(window.active_worker))
