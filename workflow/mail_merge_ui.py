"""Reusable Mail Merge recipes and model-backed batch production in Designer tabs."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt, QTimer
from PyQt6.QtGui import QDesktopServices, QPixmap
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from composition.template.model import DataConfig

from .batch import BatchJob, BatchRun
from .model import LABELS, WorkflowRun, WorkflowSpec
from .workspace import WorkflowWindow


class JobsModel(QAbstractTableModel):
    columns=("Job","Template","Data / sheet","Mapping","Sequences","Output","Records","Pages","Status")

    def __init__(self,parent=None):
        super().__init__(parent)
        self.jobs=[]

    def rowCount(self,parent=None):
        return 0 if parent and parent.isValid() else len(self.jobs)

    def columnCount(self,parent=None):
        return 0 if parent and parent.isValid() else len(self.columns)

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:
            return self.columns[section]

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        job=self.jobs[index.row()]
        if role==Qt.ItemDataRole.UserRole:
            return job.id
        if role==Qt.ItemDataRole.ToolTipRole:
            return job.error or "\n".join([job.template_path,job.data_path,*job.warnings])
        if role==Qt.ItemDataRole.DisplayRole:
            values=(job.name,Path(job.template_path).name,Path(job.data_path).name+(" / "+job.data_options["sheet"] if job.data_options.get("sheet") else ""),
                job.mapping_profile or "Template / default",", ".join(f"{k}={v}" for k,v in job.sequence_starts.items()) or "Template starts",
                job.output_name,f"{job.input_records:,}" if job.input_records else "—",
                f"{job.expected_pages:,}" if job.expected_pages else "—",job.status)
            return values[index.column()]

    def update(self,jobs):
        self.beginResetModel()
        self.jobs=jobs
        self.endResetModel()


class JobDialog(QDialog):
    """Explicit pairing, with import options configured using the existing data dialog."""
    def __init__(self,window,job):
        super().__init__(window)
        self.window=window
        self.job=copy.deepcopy(job)
        self.setWindowTitle("Batch job · Template + Data")
        self.resize(620,460)
        outer=QVBoxLayout(self)
        form=QFormLayout()
        outer.addLayout(form)
        self.controls={}
        for key,title in (("name","Job name"),("template_path","Letter template"),("data_path","Data source"),("output_name","Output PDF")):
            edit=QLineEdit(getattr(job,key))
            self.controls[key]=edit
            if key in ("template_path","data_path"):
                row=QWidget()
                box=QHBoxLayout(row)
                box.setContentsMargins(0,0,0,0)
                box.addWidget(edit,1)
                browse=QPushButton("Browse…")
                browse.clicked.connect(lambda checked=False,k=key:self.browse(k))
                box.addWidget(browse)
                form.addRow(title,row)
            else:
                form.addRow(title,edit)
        self.mapping=QComboBox()
        self.mapping.addItem("Template / workflow default","")
        for name in window.spec.node("mapping").params.get("profiles",{}):
            self.mapping.addItem(name,name)
        if job.mapping_profile and self.mapping.findData(job.mapping_profile)<0:
            self.mapping.addItem(job.mapping_profile+" (missing)",job.mapping_profile)
        self.mapping.setCurrentIndex(self.mapping.findData(job.mapping_profile))
        form.addRow("Mapping profile",self.mapping)
        self.options=QLabel(self.options_text())
        self.options.setWordWrap(True)
        self.options.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.options)
        button=QPushButton("Import settings & field mapping…")
        button.clicked.connect(self.import_settings)
        outer.addWidget(button)
        self.starts=QLineEdit(", ".join(f"{k}={v}" for k,v in job.sequence_starts.items()))
        self.starts.setPlaceholderText("Leave blank to use template starts; e.g. Seq=1, Reference=1000")
        form.addRow("Sequence starts",self.starts)
        if job.sequence_fields:
            known=QLabel("Template sequences: "+", ".join(f"{s['name']} (start {s['start']})" for s in job.sequence_fields))
            known.setWordWrap(True)
            known.setTextFormat(Qt.TextFormat.PlainText)
            outer.addWidget(known)
        tip=QLabel("Layout, fonts and barcode definitions belong to the template. Each job uses independent sequences and produces its own PDF and reports.")
        tip.setWordWrap(True)
        outer.addWidget(tip)
        self.error=QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.error)
        outer.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def options_text(self):
        values=self.job.data_options
        return "Import: "+("Template/detected defaults" if not values else ", ".join(f"{k}: {v}" for k,v in values.items() if k!="mapping"))

    def browse(self,key):
        filter="Designer template (*.pdcx)" if key=="template_path" else "Data (*.csv *.txt *.tsv *.xlsx *.xls)"
        path,_=QFileDialog.getOpenFileName(self,"Choose "+key,"",filter)
        if path:
            self.controls[key].setText(path)

    def import_settings(self):
        from composition.designer.data_dialog import DataDialog
        path=self.controls["data_path"].text().strip()
        if not path:
            self.error.setText("Choose a data file first.")
            return
        options={**self.job.data_options,"path":path}
        initial=DataConfig(**options) if self.job.data_options else None
        dialog=DataDialog(path,self.window.directory,self,initial)
        if self.job.template_fields:
            required=QLabel("Required template fields: "+", ".join(self.job.template_fields))
            required.setWordWrap(True)
            required.setTextFormat(Qt.TextFormat.PlainText)
            dialog.layout().insertWidget(2,required)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.job.data_options=asdict(dialog.config())
            self.job.data_options.pop("path",None)
            # Per-job mapping overrides a workflow profile only when no profile is selected.
            self.mapping.setCurrentIndex(0)
            self.options.setText(self.options_text())

    def accept(self):
        try:
            for key,control in self.controls.items():
                setattr(self.job,key,control.text().strip())
            self.job.mapping_profile=self.mapping.currentData() or ""
            starts={}
            if self.starts.text().strip():
                for item in self.starts.text().split(","):
                    name,number=item.split("=",1)
                    starts[name.strip()]=int(number.strip())
            self.job.sequence_starts=starts
            self.job.validate()
            if not self.job.template_path:
                raise ValueError("Choose a letter template.")
        except (ValueError,TypeError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()


class MailMergeWorkflowWindow(WorkflowWindow):
    def __init__(self,*args,**kwargs):
        self.batch=BatchRun()
        self.batch_dirty=False
        self.batch_revision=0
        self.preview_generation=0
        super().__init__(*args,**kwargs)
        self._build_batch_ui()
        self.apply_spec(WorkflowSpec.mail_merge().upgraded().to_dict())
        self.actions["generate"].setText("Run Ready Jobs")
        self.actions["generate"].setIconText("Run Ready Jobs")
        self.setAcceptDrops(True)
        self.undo.setClean()
        self.lock()

    def _build_batch_ui(self):
        old=self.review_page
        self.tabs.removeTab(1)
        old.deleteLater()
        self.review_page=QWidget()
        layout=QVBoxLayout(self.review_page)
        layout.setContentsMargins(8,6,8,6)
        self.batch_summary=QLabel("Add template + data pairs, then Check & Preview.")
        self.batch_summary.setWordWrap(True)
        self.batch_summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.batch_summary)
        actions=QHBoxLayout()
        self.batch_buttons=[]
        def button(text,callback):
            b=QPushButton(text)
            b.setProperty("compact",True)
            b.clicked.connect(callback)
            actions.addWidget(b)
            self.batch_buttons.append(b)
            return b
        button("Add job…",self.add_job)
        button("Edit…",self.edit_job)
        more=QPushButton("More ▾")
        menu=QMenu(more)
        for text,fn in (("Duplicate selected",self.duplicate_job),("Remove selected",self.remove_jobs),
                        ("Move up",lambda:self.move_job(-1)),("Move down",lambda:self.move_job(1)),
                        ("Apply selected settings to other selected jobs",self.bulk_settings),
                        ("Edit letter template",self.edit_template),("Locate issue",self.locate_issue),
                        ("Save batch list…",self.save_batch_dialog),("Open batch list…",self.load_batch_dialog)):
            menu.addAction(text,fn)
        more.setMenu(menu)
        actions.addWidget(more)
        self.batch_buttons.append(more)
        actions.addStretch()
        self.job_filter=QComboBox()
        for label,value in (("All jobs",""),("Needs attention","attention"),("Ready","Ready"),("Completed","Completed")):
            self.job_filter.addItem(label,value)
        self.job_filter.currentIndexChanged.connect(self.filter_jobs)
        actions.addWidget(self.job_filter)
        layout.addLayout(actions)
        self.jobs_model=JobsModel(self)
        self.proxy=QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.jobs_model)
        self.proxy.setFilterKeyColumn(8)
        self.jobs_table=QTableView()
        self.jobs_table.setModel(self.proxy)
        self.jobs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_table.setAlternatingRowColors(True)
        self.jobs_table.setAccessibleName("Mail Merge batch jobs")
        self.jobs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.doubleClicked.connect(lambda *_:self.edit_job())
        self.jobs_table.selectionModel().selectionChanged.connect(lambda *_:self.selection_changed())
        self.jobs_table.setMinimumHeight(120)
        self.review_split=QSplitter(Qt.Orientation.Vertical)
        self.review_split.addWidget(self.jobs_table)
        preview=QWidget()
        preview_layout=QVBoxLayout(preview)
        preview_layout.setContentsMargins(0,0,0,0)
        nav=QHBoxLayout()
        self.preview_record=QSpinBox()
        self.preview_record.setPrefix("Record ")
        self.preview_record.setRange(1,1)
        self.preview_page=QSpinBox()
        self.preview_page.setPrefix("Page ")
        self.preview_page.setRange(1,1)
        self.preview_timer=QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(180)
        self.preview_timer.timeout.connect(self.preview_job)
        self.preview_record.valueChanged.connect(self.schedule_preview)
        self.preview_page.valueChanged.connect(self.schedule_preview)
        for text,fn in (("First",lambda:self.preview_record.setValue(1)),("Last",self.last_record)):
            b=QPushButton(text)
            b.setProperty("compact",True)
            b.clicked.connect(fn)
            nav.addWidget(b)
        nav.addWidget(self.preview_record)
        nav.addWidget(self.preview_page)
        preview_button=QPushButton("Preview")
        preview_button.clicked.connect(self.preview_job)
        nav.addWidget(preview_button)
        nav.addStretch()
        self.accept_button=QPushButton("Approve selected jobs")
        self.accept_button.clicked.connect(self.approve_selected)
        nav.addWidget(self.accept_button)
        preview_layout.addLayout(nav)
        self.job_detail=QLabel("Select a job to inspect its inputs, counts and findings.")
        self.job_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.job_detail.setWordWrap(True)
        preview_layout.addWidget(self.job_detail)
        self.preview_image=QLabel("Check the job, then preview a record.")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_scroll=QScrollArea()
        self.preview_scroll.setWidget(self.preview_image)
        self.preview_scroll.setWidgetResizable(False)
        preview_layout.addWidget(self.preview_scroll,1)
        self.review_split.addWidget(preview)
        self.review_split.setSizes([250,300])
        layout.addWidget(self.review_split,1)
        self.tabs.insertTab(1,self.review_page,"Review")
        self.run_header=QLabel("No batch has been run.")
        self.production_overview.hide()
        self.run_header.setWordWrap(True)
        self.run_header.setTextFormat(Qt.TextFormat.PlainText)
        self.production_page.layout().insertWidget(0,self.run_header)
        self.run_table=QTableView()
        self.run_table.setModel(self.jobs_model)
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.run_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.run_table.setAlternatingRowColors(True)
        self.run_table.horizontalHeader().setStretchLastSection(True)
        self.run_table.clicked.connect(lambda *_:self.run_detail())
        self.run_table.doubleClicked.connect(lambda *_:self.review_run_job())
        self.production_page.layout().insertWidget(1,self.run_table,1)
        self.production_summary.setMaximumHeight(160)
        resume=QHBoxLayout()
        retry=QPushButton("Retry Failed…")
        retry.clicked.connect(self.retry_failed)
        remaining=QPushButton("Run Remaining")
        remaining.clicked.connect(lambda:self.execute("output"))
        resume.addWidget(retry)
        resume.addWidget(remaining)
        resume.addStretch()
        self.production_page.layout().insertLayout(2,resume)
        self.batch_buttons.extend([retry,remaining])
        self.jobs_model.update(self.batch.jobs)

    def apply_spec(self,raw):
        if raw.get("project_kind")!="mail_merge_workflow":
            return super().apply_spec(raw)
        previous=getattr(self,"spec",None)
        spec=WorkflowSpec.from_dict(raw)
        changed=previous and previous.fingerprint()!=spec.fingerprint()
        self.spec=spec
        if changed:
            self.inspections.invalidate()
            self.run=WorkflowRun()
            for job in self.batch.jobs:
                if job.status!="Completed":
                    job.status="Needs review"
                    # Retain approval evidence; checking will compare effective per-job settings.
            self.preview_generation+=1
            self.message("Workflow changed. Check affected jobs before running." if self.batch.jobs
                         else "Add template + data pairs, then Check & Preview.")
        if self.selected not in [n.id for n in spec.nodes]:
            self.selected=spec.nodes[0].id
        self._draft_getter=None
        self.draft_error=""
        from .registry import EXTRA_KINDS
        self.toolbox.configure(tuple(dict.fromkeys(spec.kinds+EXTRA_KINDS)))
        self.canvas.summaries={"data":f"{len(self.batch.jobs)} batch job(s)","mapping":"Reusable field aliases",
            "template":"One template per job","sequences":"Independent per job","mail_review":"Check and approve",
            "compose":"Background generation","reports":"PDF + CSV + JSON"}
        self.canvas.display(spec,self.run.statuses,self.selected)
        self.select_node(self.selected)
        if hasattr(self,"jobs_model"):
            self.refresh_jobs()
        self.title()

    def _build_node_settings(self,identity):
        if getattr(self,"spec",None) is None or self.spec.project_kind!="mail_merge_workflow":
            return super()._build_node_settings(identity)
        self._draft_getter=None
        self.selected=identity
        node=next((n for n in self.spec.nodes if n.id==identity),None)
        if not node:
            return
        from .registry import EXTRA_KINDS
        if node.kind in EXTRA_KINDS:
            from .node_settings import install
            return install(self,node)
        self.inspector=QWidget()
        layout=QVBoxLayout(self.inspector)
        title=QLabel(LABELS[node.kind])
        font=title.font()
        font.setPointSizeF(12)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        descriptions={"data":"INPUT\nCSV / TXT / Excel, or template-generated records. Each batch row explicitly pairs a template with its data.",
            "mapping":"SETTINGS\nMap original column names to template fields. Missing required fields block that job. Unused columns are allowed.",
            "template":"SETTINGS\nLayouts, fonts, multi-page backgrounds and barcode definitions are edited in Document Designer.",
            "sequences":"SETTINGS\nEach job uses its template's sequence definitions. Override existing sequence starts in Edit Job; imported fields are never overwritten.",
            "mail_review":"OUTPUT\nCheck all pairs, inspect representative records and approve the jobs to run. Changes require checking again.",
            "compose":"SETTINGS\nGenerate one job at a time in an isolated background process. A failed job does not discard other jobs.",
            "reports":"OUTPUT\nEach job publishes a validated PDF with reconciliation, control CSV and JSON log. The batch also has a summary CSV and JSON record."}
        info=QLabel(descriptions[node.kind])
        info.setWordWrap(True)
        layout.addWidget(info)
        def button(text,fn):
            b=QPushButton(text)
            b.clicked.connect(fn)
            layout.addWidget(b)
        if node.kind=="data":
            button("Add template + data pair…",self.add_job)
            button("Open batch list",lambda:self.tabs.setCurrentWidget(self.review_page))
        elif node.kind=="mapping":
            profiles=node.params.get("profiles",{})
            selected=QComboBox()
            selected.addItem("Use each template's mapping","")
            for name in profiles:
                selected.addItem(name,name)
            selected.setCurrentIndex(max(0,selected.findData(node.params.get("default_profile",""))))
            layout.addWidget(selected)
            self.watch_settings(node,lambda:{**node.params,"default_profile":selected.currentData()},[selected])
            button("Create / update from selected job…",self.create_mapping)
        elif node.kind=="template":
            button("Edit template in Designer…",self.edit_template)
            button("Choose template per job…",self.edit_job)
        elif node.kind=="sequences":
            button("Set selected job sequence starts…",self.edit_job)
        elif node.kind=="mail_review":
            button("Check & Preview",self.check_jobs)
            button("Open Review",lambda:self.tabs.setCurrentWidget(self.review_page))
        elif node.kind=="compose":
            fallback=QCheckBox("Automatic missing-glyph repair with report")
            fallback.setChecked(node.params.get("auto_repair",True))
            layout.addWidget(fallback)
            self.watch_settings(node,lambda:{"auto_repair":fallback.isChecked()},[fallback])
        elif node.kind=="reports":
            form=QFormLayout()
            folder=QLineEdit(node.params.get("directory",""))
            form.addRow("Batch output folder",folder)
            layout.addLayout(form)
            self.watch_settings(node,lambda:{"directory":folder.text().strip()},[folder])
            def browse():
                path=QFileDialog.getExistingDirectory(self,"Batch output folder")
                if path:
                    folder.setText(path)
            button("Browse…",browse)
        button("Apply settings",self.flush_settings)
        button("Add / connect next step",lambda:self.next_step.showMenu())
        layout.addStretch()
        self.inspector_scroll.setWidget(self.inspector)
        self.inspector.setEnabled(not bool(self.active_worker))

    def selected_jobs(self):
        if not hasattr(self,"jobs_table"):
            return []
        indices=self.jobs_table.selectionModel().selectedRows()
        ids={i.data(Qt.ItemDataRole.UserRole) for i in indices}
        return [j for j in self.batch.jobs if j.id in ids]

    def refresh_jobs(self):
        if self.inspections.pane:
            self.inspections.pane.sync_jobs()
        selected=[j.id for j in self.selected_jobs()]
        self.jobs_model.update(self.batch.jobs)
        for row,job in enumerate(self.batch.jobs):
            if job.id in selected:
                index=self.proxy.mapFromSource(self.jobs_model.index(row,0))
                if index.isValid():
                    from PyQt6.QtCore import QItemSelectionModel
                    self.jobs_table.selectionModel().select(index,QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        counts={status:sum(j.status==status for j in self.batch.jobs) for status in ("Ready","Needs review","Blocked","Completed","Failed","Cancelled")}
        self.batch_summary.setText(f"{len(self.batch.jobs)} jobs · "+" · ".join(f"{count} {status.lower()}" for status,count in counts.items() if count))
        self.run_header.setText(f"Batch {self.batch.batch_id} · {self.batch.status}\n"+self.batch_summary.text())
        self.canvas.summaries["data"]=f"{len(self.batch.jobs)} batch job(s)"
        self.canvas.display(self.spec,self.run.statuses,self.selected)
        self.title()

    def filter_jobs(self):
        value=self.job_filter.currentData()
        self.proxy.setFilterRegularExpression("Blocked|Failed|Needs review|Cancelled" if value=="attention" else value)

    def changed_jobs(self):
        self.inspections.invalidate()
        self.batch_dirty=True
        self.batch_revision+=1
        self.preview_generation+=1
        self.preview_image.clear()
        self.preview_image.setText("Check the changed job before previewing.")
        self.refresh_jobs()
        self.properties.edited.emit()

    def add_job(self,checked=False,job=None):
        if self.active_worker:
            return
        job=job or BatchJob(name=f"Letter job {len(self.batch.jobs)+1}",output_name=f"letters-{len(self.batch.jobs)+1}.pdf")
        dialog=JobDialog(self,job)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.batch.jobs.append(dialog.job)
            self.changed_jobs()
            self.tabs.setCurrentWidget(self.review_page)

    def edit_job(self):
        jobs=([self.inspections.job()] if self.tabs.currentWidget() is self.flow_page and self.inspections.job()
              else self.selected_jobs())
        if self.active_worker or not jobs:
            self.message("Select a batch job in Review first.")
            return
        original=jobs[0]
        dialog=JobDialog(self,original)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            updated=dialog.job
            if any(getattr(updated,k)!=getattr(original,k) for k in ("template_path","data_path","data_options","mapping_profile","sequence_starts","output_name")):
                updated.status="Needs review"
                updated.approved=False
                updated.prepared_template={}
            self.batch.jobs[self.batch.jobs.index(original)]=updated
            self.changed_jobs()

    def duplicate_job(self):
        for original in self.selected_jobs():
            job=BatchJob(name=original.name+" copy",template_path=original.template_path,data_path=original.data_path,
                data_options=copy.deepcopy(original.data_options),mapping_profile=original.mapping_profile,
                sequence_starts=copy.deepcopy(original.sequence_starts),output_name=Path(original.output_name).stem+"-"+uuid.uuid4().hex[:4]+".pdf")
            self.batch.jobs.append(job)
        self.changed_jobs()

    def remove_jobs(self):
        ids={j.id for j in self.selected_jobs()}
        self.batch.jobs=[j for j in self.batch.jobs if j.id not in ids]
        self.changed_jobs()

    def move_job(self,offset):
        selected=self.selected_jobs()
        if not selected:
            return
        index=self.batch.jobs.index(selected[0])
        target=index+offset
        if 0<=target<len(self.batch.jobs):
            self.batch.jobs[index],self.batch.jobs[target]=self.batch.jobs[target],self.batch.jobs[index]
            self.changed_jobs()

    def bulk_settings(self):
        jobs=self.selected_jobs()
        if len(jobs)<2:
            self.message("Select a source job followed by the jobs to receive its settings.")
            return
        source=jobs[0]
        if QMessageBox.question(self,"Apply job settings",f"Copy template, import settings, mapping and sequence starts from '{source.name}' to {len(jobs)-1} selected jobs? Data files and output names stay as listed.")!=QMessageBox.StandardButton.Yes:
            return
        for job in jobs[1:]:
            for key in ("template_path","data_options","mapping_profile","sequence_starts"):
                setattr(job,key,copy.deepcopy(getattr(source,key)))
            job.approved=False
            job.status="Needs review"
            job.prepared_template={}
        self.changed_jobs()

    def create_mapping(self):
        if not self.flush_settings():
            return
        selected=self.selected_jobs()
        if not selected or not selected[0].data_path:
            self.message("Select a job with a data file in Review first.")
            return
        from composition.designer.data_dialog import DataDialog
        job=selected[0]
        options={**job.data_options,"path":job.data_path}
        dialog=DataDialog(job.data_path,self.directory,self,DataConfig(**options) if job.data_options else None)
        if job.template_fields:
            required=QLabel("Required template fields: "+", ".join(job.template_fields))
            required.setWordWrap(True)
            required.setTextFormat(Qt.TextFormat.PlainText)
            dialog.layout().insertWidget(2,required)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            return
        name,ok=QInputDialog.getText(self,"Mapping profile","Profile name")
        name=name.strip()
        if not ok or not name or len(name)>100:
            return
        node=self.spec.node("mapping")
        profiles=copy.deepcopy(node.params.get("profiles",{}))
        profiles[name]=dialog.config().mapping
        if self.params(node,{**node.params,"profiles":profiles}):
            job.data_options={k:v for k,v in asdict(dialog.config()).items() if k not in ("path","mapping")}
            job.mapping_profile=name
            self.changed_jobs()

    def check_jobs(self):
        if self.active_worker or not self.flush_settings():
            return
        if not self.batch.jobs:
            self.tabs.setCurrentWidget(self.review_page)
            self.message("Add at least one template + data pair.")
            return
        if not self.templates_saved():
            return
        for node in self.spec.nodes:
            self.run.statuses[node.id]="Pending"
        def ready(result):
            self.batch=BatchRun.from_dict(result["batch"])
            for node in self.spec.nodes:
                self.run.statuses[node.id]="Needs review" if node.kind=="mail_review" else "Completed" if node.kind in ("data","mapping","template","sequences") else "Pending"
                from .registry import EXTRA_KINDS
                if node.kind in EXTRA_KINDS:
                    findings=[s for j in self.batch.jobs for s in j.data_summary.get("steps",[]) if s.get("node_id")==node.id]
                    self.run.statuses[node.id]="Failed" if any(s.get("errors") for s in findings) else "Completed" if findings else "Pending"
            self.batch_dirty=True
            self.refresh_jobs()
            self.tabs.setCurrentWidget(self.review_page)
            self.message("Checking cancelled. Unfinished jobs require checking again." if self.batch.status=="Cancelled"
                         else "Check findings, preview records, then approve the jobs to run.")
        self.request({"operation":"batch_check","spec":self.spec.to_dict(),"batch":self.batch.to_dict(),"directory":str(self.directory)},ready)

    def templates_saved(self):
        if not self.project_host:
            return True
        paths={self.project_host.identity(j.template_path) for j in self.batch.jobs if j.template_path}
        for project in self.project_host.projects:
            if project is self or not project.project_path or self.project_host.identity(project.project_path) not in paths:
                continue
            if self.project_host.is_busy(project) or project.properties.apply() is False or not project.undo.isClean() or getattr(project,"content_invalid",False):
                self.message("Save the open letter template and finish its tasks before checking/running this workflow.")
                return False
        return True

    def selection_changed(self):
        self.preview_generation+=1
        self.preview_image.clear()
        jobs=self.selected_jobs()
        if not jobs:
            return
        job=jobs[0]
        self.preview_record.setMaximum(max(1,job.input_records))
        self.preview_page.setMaximum(max(1,len(job.prepared_template.get("pages",[])) or job.pages_per_record))
        detail=f"{job.name} · {job.status}\n{job.input_records:,} records × {job.pages_per_record} pages = {job.expected_pages:,} expected pages"
        if job.data_summary:
            detail+=f"\nSource {job.data_summary['input']:,} · Kept {job.data_summary['retained']:,} · Excluded {job.data_summary['excluded']:,}"
        detail+="\n"+(job.error or "\n".join(job.warnings) or "Primary fonts, rules and barcode layout come from the template.")
        if job.template_fields:
            detail+="\nTemplate fields: "+", ".join(job.template_fields)
        self.job_detail.setText(detail)
        from .registry import EXTRA_KINDS
        selected=next((n for n in self.spec.nodes if n.id==self.selected),None)
        if selected and selected.kind in EXTRA_KINDS:
            self.select_node(selected.id)
        self.accept_button.setEnabled(not self.active_worker and any(j.status in ("Needs review","Ready") and j.prepared_template for j in jobs))
        self.schedule_preview()

    def last_record(self):
        self.preview_record.setValue(self.preview_record.maximum())

    def schedule_preview(self,*_):
        self.preview_generation+=1
        jobs=self.selected_jobs()
        if not self.active_worker and jobs and jobs[0].prepared_template and jobs[0].status in ("Ready","Needs review"):
            self.preview_timer.start()
        else:
            self.preview_timer.stop()

    def preview_job(self):
        self.preview_timer.stop()
        selected=self.selected_jobs()
        if self.active_worker or not selected:
            return
        job=selected[0]
        if not job.prepared_template or job.status not in ("Ready","Needs review"):
            self.message("Check the job before previewing.")
            return
        self.preview_generation+=1
        generation=self.preview_generation
        target=self.directory/(uuid.uuid4().hex+".png")
        def ready(result):
            if generation!=self.preview_generation:
                target.unlink(missing_ok=True)
                return
            pixmap=QPixmap(result["image"])
            self.preview_image.setPixmap(pixmap)
            self.preview_image.resize(pixmap.size())
            target.unlink(missing_ok=True)
            self.message(f"Preview · {job.name} · Record {result['record']} · Page {self.preview_page.value()}")
        self.request({"operation":"batch_preview","spec":self.spec.to_dict(),"batch":self.batch.to_dict(),"job_id":job.id,
            "record":self.preview_record.value(),"page":self.preview_page.value(),"target":str(target)},ready,preview=True)

    def approve_selected(self):
        from .batch import approve
        jobs=self.selected_jobs()
        approve(self.batch,[j.id for j in jobs])
        self.batch_dirty=True
        self.refresh_jobs()
        self.message("Selected checked jobs approved. Use Run Ready Jobs to start production.")

    def execute(self,until):
        if self.spec.project_kind!="mail_merge_workflow":
            return super().execute(until)
        if until not in ("output","reports","compose"):
            self.check_jobs()
            return
        if self.active_worker or not self.flush_settings() or not self.templates_saved():
            return
        ready=[j for j in self.batch.jobs if j.status=="Ready" and j.approved]
        if not ready:
            self.tabs.setCurrentWidget(self.review_page)
            self.message("Check and approve the batch jobs before running.")
            return
        output=self.spec.node("reports").params.get("directory","")
        if not output:
            output=QFileDialog.getExistingDirectory(self,"Batch output folder")
            if not output:
                return
            if not self.params(self.spec.node("reports"),{"directory":output}):
                return
        counts=sum(j.input_records for j in ready),sum(j.expected_pages for j in ready)
        if QMessageBox.question(self,"Run Ready Jobs",f"Generate {len(ready)} approved jobs?\nRecords: {counts[0]:,}\nExpected pages: {counts[1]:,}\nOutput: {output}\nOther jobs remain in the list.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:
            return
        def finished(result):
            self.batch=BatchRun.from_dict(result["batch"])
            for kind in ("compose","reports"):
                self.run.statuses[self.spec.node(kind).id]="Completed" if self.batch.status=="Completed" else "Needs review"
            self.batch_dirty=True
            self.refresh_jobs()
            self.production_summary.setPlainText(f"{self.batch.status}\nReports: {self.batch.report_dir}")
            self.message(self.batch.status)
        self.tabs.setCurrentWidget(self.production_page)
        self.run.statuses[self.spec.node("compose").id]="Running"
        self.request({"operation":"batch_run","spec":self.spec.to_dict(),"batch":self.batch.to_dict(),
            "approved":[j.id for j in ready],"output_dir":output},finished)

    def update_progress(self,current,total,message):
        super().update_progress(current,total,message)
        if hasattr(self,"run_header"):
            self.run_header.setText(message)

    def batch_state(self,state):
        current={j.id:j for j in self.batch.jobs}
        for raw in state.get("jobs",[]):
            job=current.get(raw["id"])
            if job:
                for key in ("status","stage","error","result","warnings","approved"):
                    setattr(job,key,raw[key])
        self.batch.status=state.get("status",self.batch.status)
        self.refresh_jobs()

    def run_detail(self):
        rows=self.run_table.selectionModel().selectedRows()
        if not rows:
            return
        job=self.batch.jobs[rows[0].row()]
        self.production_summary.setPlainText("\n".join([f"{job.name} · {job.status}",job.error,
            f"PDF: {job.result.get('output_pdf','')}",
            *([f"PostScript: {job.result['output_ps']}"] if job.result.get('output_ps') else []),
            f"Reports: {job.result.get('report_dir','')}",*job.warnings]))

    def review_run_job(self):
        rows=self.run_table.selectionModel().selectedRows()
        if rows:
            source=self.jobs_model.index(rows[0].row(),0)
            index=self.proxy.mapFromSource(source)
            if not index.isValid():
                self.job_filter.setCurrentIndex(0)
                index=self.proxy.mapFromSource(source)
            self.jobs_table.selectRow(index.row())
            self.tabs.setCurrentWidget(self.review_page)
            self.jobs_table.scrollTo(index)

    def retry_failed(self):
        if any(j.status in ("Failed","Cancelled","Blocked") for j in self.batch.jobs):
            self.check_jobs()
            self.message("Rechecking unfinished jobs. Completed outputs are preserved; approve checked jobs before retrying.")
        else:
            self.message("There are no failed jobs to retry.")

    def output_job(self):
        rows=self.run_table.selectionModel().selectedRows()
        return self.batch.jobs[rows[0].row()] if rows else next((j for j in self.batch.jobs if j.status=="Completed"),None)

    def open_output(self):
        job=self.output_job()
        if job and self.project_host:
            path=self.choose_output_path(job.result)
            if path:
                self.project_host.open_pdf(path)

    def show_reports(self):
        from PyQt6.QtCore import QUrl
        job=self.output_job()
        path=job.result.get("report_dir") if job else self.batch.report_dir
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def edit_template(self):
        if not self.project_host:
            self.message("Open this workflow in Document Designer to edit its templates.")
            return
        jobs=([self.inspections.job()] if self.tabs.currentWidget() is self.flow_page and self.inspections.job()
              else self.selected_jobs() or self.batch.jobs)
        if not jobs:
            self.tabs.setCurrentWidget(self.review_page)
            self.message("Add a template + data pair before editing a letter template.")
            return
        job=jobs[0]
        if len(jobs)>1:
            labels=[f"{i+1} · {j.name} — {Path(j.template_path).name or 'No template assigned'}"
                    for i,j in enumerate(jobs)]
            label,ok=QInputDialog.getItem(self,"Edit letter template","Choose a job's template",labels,0,False)
            if not ok:
                return
            job=jobs[labels.index(label)]
        if not job.template_path:
            self.tabs.setCurrentWidget(self.review_page)
            self.message(f"Assign a letter template to '{job.name}' using Edit Job first.")
            return
        return self.project_host.open_project(job.template_path)

    def locate_issue(self):
        jobs=self.selected_jobs()
        if not jobs:
            return
        job=jobs[0]
        kind="mapping" if "field" in job.error.lower() else "data" if job.stage=="Import data" else "template"
        self.select_node(self.spec.node(kind).id)
        self.tabs.setCurrentWidget(self.flow_page)
        self.inspector_scroll.show()
        self.message(job.error or "Check the selected job settings.")

    def lock(self,*args):
        super().lock(*args)
        if hasattr(self,"jobs_table"):
            busy=bool(self.active_worker or self.close_pending)
            for button in self.batch_buttons:
                button.setEnabled(not busy)
            self.accept_button.setEnabled(not busy and bool(self.selected_jobs()))
            self.job_filter.setEnabled(not busy)
            self.run_table.setEnabled(True)

    def title(self,*args):
        super().title(*args)
        if self.batch_dirty and " *" not in self.windowTitle():
            self.setWindowTitle(self.windowTitle().replace(" — Workflow"," * — Workflow"))

    def save_batch_dialog(self):
        path,_=QFileDialog.getSaveFileName(self,"Save batch list","","Batch record (*.json)")
        if path:
            self.request({"operation":"batch_save","batch":self.batch.to_dict(),"path":path},lambda result:self.message("Batch list saved: "+result["path"]))

    def load_batch_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,"Open batch list","","Batch record (*.json)")
        if path:
            self.request({"operation":"batch_load","path":path},self.batch_loaded)

    def batch_loaded(self,result):
        self.batch=BatchRun.from_dict(result["batch"])
        self.changed_jobs()
        self.tabs.setCurrentWidget(self.review_page)
        self.message("Batch list restored. Check inputs before resuming; nothing started automatically.")

    def save_project(self,*args,after=None,**kwargs):
        if self.active_worker or not self.flush_settings():
            return False
        path=kwargs.get("path") or (str(self.project_path) if self.project_path and not kwargs.get("save_as") else "")
        if not path:
            path,_=QFileDialog.getSaveFileName(self,"Save workflow","","Workflow (*.pdflow)")
        if not path:
            return False
        if self.project_host and not self.project_host.allow_save_path(self,path):
            return False
        revision=self.batch_revision
        def saved(result):
            self.project_path=Path(result["path"])
            self.undo.setClean()
            if revision==self.batch_revision:
                self.batch_dirty=False
            self.title()
            self.activityChanged.emit()
            if after:
                QTimer.singleShot(0,after)
        return self.request({"operation":"batch_project_save","spec":self.spec.to_dict(),"batch":self.batch.to_dict(),"path":path},saved)

    def load_path(self,path):
        def loaded(result):
            self.apply_spec(result["spec"])
            self.project_path=Path(path)
            self.undo.clear()
            self.undo.setClean()
            record=self.project_path.with_suffix(".batch.json")
            if record.is_file():
                def restored(result):
                    self.batch=BatchRun.from_dict(result["batch"])
                    self.batch_dirty=False
                    self.refresh_jobs()
                self.request({"operation":"batch_load","path":str(record)},restored)
            self.title()
            self.canvas.fit()
        self.request({"operation":"load","path":str(path)},loaded)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.active_worker:
            event.acceptProposedAction()

    def dropEvent(self,event):
        if self.active_worker:
            return
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        for path in paths:
            suffix=Path(path).suffix.lower()
            if suffix not in (".pdcx",".csv",".txt",".tsv",".xlsx",".xls"):
                continue
            job=BatchJob(name=Path(path).stem,output_name=Path(path).stem+".pdf",
                template_path=path if suffix==".pdcx" else "",data_path=path if suffix!=".pdcx" else "")
            self.add_job(job=job)
        event.acceptProposedAction()

    def closeEvent(self,event):
        self.preview_timer.stop()
        if not self.embedded and not self._close_approved and not self.close_pending and self.batch_dirty:
            if QMessageBox.question(self,"Unsaved batch list","Discard the unsaved batch changes?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        super().closeEvent(event)
