"""Responsive Designer landing page; projects remain owned by the tab host."""
import queue
import threading
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.icons import icon

from . import recents


class RecentProbe(QObject):
    checked=pyqtSignal(int,str,bool)

    def start(self,token,paths):
        jobs=queue.Queue()
        for path in paths:
            jobs.put(path)
        def work():
            while True:
                try:
                    path=jobs.get_nowait()
                except queue.Empty:
                    return
                try:
                    exists=Path(path).is_file()
                except OSError:
                    exists=False
                try:
                    self.checked.emit(token,path,exists)
                except RuntimeError:
                    return  # Home was closed while a disconnected path was being probed.
        for _ in range(min(4,len(paths))):
            threading.Thread(target=work,daemon=True,name="designer-recents").start()


class DesignerHome(QScrollArea):
    def __init__(self, host):
        super().__init__(host)
        self.host=host
        self.probe=RecentProbe(self)
        self.probe.checked.connect(self.checked_recent)
        self.recent_token=0
        self.setObjectName("designerHome")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setAcceptDrops(True)
        body=QWidget()
        self.setWidget(body)
        layout=QVBoxLayout(body)
        layout.setContentsMargins(28,24,28,24)
        layout.setSpacing(16)
        title=QLabel("Document Designer")
        title.setStyleSheet("font-size: 25px; font-weight: 600;")
        layout.addWidget(title)
        subtitle=QLabel("Design reusable letters, prepare finished PDFs and build production workflows.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.grid=QGridLayout()
        self.grid.setSpacing(12)
        layout.addLayout(self.grid)
        self.cards=[]
        for name,description,symbol,handler in (
            ("Letter Template","Design variable fields, sequences and barcodes on one or more template pages.","file-text",host.new_template),
            ("PDF Overlay","Add envelope sequences and inserter marks to finished customer PDFs.","layers",host.new_overlay),
            ("Visual Workflow","Connect data preparation, quality checks and production for reusable batch jobs.","settings",host.choose_workflow)):
            card=QFrame()
            card.setObjectName("designerSidePanel")
            card.setFrameShape(QFrame.Shape.StyledPanel)
            content=QVBoxLayout(card)
            heading=QLabel(name)
            heading.setStyleSheet("font-size: 16px; font-weight: 600;")
            content.addWidget(heading)
            text=QLabel(description)
            text.setWordWrap(True)
            content.addWidget(text)
            content.addStretch()
            action=QPushButton(icon(symbol),"Create "+name)
            action.setProperty("primary",True)
            action.setProperty("home_icon",symbol)
            action.clicked.connect(lambda checked=False,fn=handler:fn())
            content.addWidget(action)
            self.cards.append(card)
        row=QHBoxLayout()
        label=QLabel("QUICK START")
        row.addWidget(label)
        row.addStretch()
        open_button=QPushButton(icon("folder-open"),"Open project…")
        open_button.setProperty("home_icon","folder-open")
        open_button.clicked.connect(lambda:self.host.open_project())
        row.addWidget(open_button)
        layout.addLayout(row)
        self.presets=QWidget()
        presets=QVBoxLayout(self.presets)
        presets.setContentsMargins(0,0,0,0)
        for name,key in (("Data → Mail Merge","mail"),("PDF → Inserter Overlay","pdf"),("Clean → Validate → Output","clean")):
            button=QPushButton(name)
            button.clicked.connect(lambda checked=False,k=key:self.preset(k))
            presets.addWidget(button)
        layout.addWidget(self.presets)
        recent_row=QHBoxLayout()
        recent_row.addWidget(QLabel("RECENT PROJECTS"))
        recent_row.addStretch()
        remove=QPushButton("Remove from list")
        remove.clicked.connect(self.remove_recent)
        recent_row.addWidget(remove)
        layout.addLayout(recent_row)
        self.recent=QListWidget()
        self.recent.setMinimumHeight(120)
        self.recent.setMaximumHeight(240)
        self.recent.itemActivated.connect(lambda item:host.open_project(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.recent)
        hint=QLabel("Drop a .pdcx / .pdflow project to reopen it. Drop PDF or data files to choose how to use them.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.refresh()
        self.arrange()
        self.refresh_icons()

    def refresh_icons(self):
        for button in self.findChildren(QPushButton):
            symbol=button.property("home_icon")
            if symbol:
                color="#ffffff" if button.property("primary") else self.palette().text().color().name()
                button.setIcon(icon(symbol,color=color))

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange,QEvent.Type.StyleChange):
            self.refresh_icons()

    def refresh(self):
        self.recent_token+=1
        self.recent.clear()
        rows=recents.entries()
        for row in rows:
            item=QListWidgetItem(f"{row['kind']}  ·  {Path(row['path']).name}\n{row['path']}")
            item.setData(Qt.ItemDataRole.UserRole,row["path"])
            item.setToolTip(row["path"])
            self.recent.addItem(item)
        if not self.recent.count():
            item=QListWidgetItem("Your saved templates, overlays and workflows will appear here.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(item)
        if self.isVisible():
            self.probe.start(self.recent_token,[row["path"] for row in rows])

    def checked_recent(self,token,path,exists):
        if token!=self.recent_token:
            return
        for i in range(self.recent.count()):
            item=self.recent.item(i)
            if item.data(Qt.ItemDataRole.UserRole)==path:
                item.setToolTip(path+("" if exists else "\nUnavailable. Locate the project with Open project, or remove it from this list."))
                if not exists:
                    item.setText(item.text()+"\nUnavailable")

    def remove_recent(self):
        item=self.recent.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole):
            recents.remove(item.data(Qt.ItemDataRole.UserRole))
            self.refresh()

    def preset(self, key):
        if key=="pdf":
            return self.host.new_workflow()
        window=self.host.new_mail_merge_workflow()
        if key=="clean":
            from workflow.model import WorkflowNode
            spec=window.spec.insert_after(window.spec.node("template").id,
                WorkflowNode("clean_fields",params={"operations":[{"field":"Name","operation":"trim"}]}))
            spec=spec.insert_after(spec.node("clean_fields").id,
                WorkflowNode("validate_data",params={"checks":[{"field":"Name","check":"required"}]}))
            window.commit(spec.to_dict(),"Use data preparation preset")
            from workflow.chrome import auto_layout
            auto_layout(window)
        return window

    def arrange(self):
        columns=1 if self.host.width()<1080 else 3
        for i,card in enumerate(self.cards):
            self.grid.removeWidget(card)
            self.grid.addWidget(card,i//columns,i%columns)
        for column in range(3):
            self.grid.setColumnStretch(column,1 if column<columns else 0)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"cards"):
            self.arrange()

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self,event):
        for url in event.mimeData().urls():
            path=url.toLocalFile()
            suffix=Path(path).suffix.lower()
            if suffix in (".pdcx",".pdflow"):
                self.host.open_project(path)
            elif suffix in (".pdf",".csv",".txt",".tsv",".xlsx",".xls"):
                choices=["Letter template", "PDF workflow"] if suffix==".pdf" else ["Letter template", "Mail Merge workflow"]
                choice,ok=QInputDialog.getItem(self,"Use dropped file","How should this file be used?",choices,0,False)
                if not ok:
                    continue
                if choice=="PDF workflow":
                    window=self.host.new_workflow()
                    window.params(window.spec.node("input"),{"paths":[path]})
                elif choice=="Mail Merge workflow":
                    from workflow.batch import BatchJob
                    window=self.host.new_mail_merge_workflow()
                    window.add_job(job=BatchJob(data_path=path))
                else:
                    window=self.host.new_template()
                    if suffix==".pdf":
                        # Existing handoff imports every PDF page as a template.
                        window._worker({"task":"template_backgrounds","source":path,
                            "target":str(window.directory/"dropped-template")},
                            lambda result,w=window:w._commit(w.template.to_dict(),result["template"],"Import PDF template"))
                    else:
                        from .data_dialog import DataDialog
                        dialog=DataDialog(path,window.directory,window)
                        if dialog.exec():
                            window._start_import(dialog.config())
        event.acceptProposedAction()
