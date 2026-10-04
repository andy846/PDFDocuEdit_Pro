"""Stock/catalog editing and bounded background physical-page previews."""
import copy
import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import (
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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from composition.media.model import FAMILIES, ROLES, MediaSpec, PrinterProfile, default_media
from composition.media.ticket import HEADERS
from core.io_atomic import atomic_output

from .process import Worker


class MediaDialog(QDialog):
    def __init__(self,media,context=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Print Media · Stocks, page rules and Canon ticket")
        self.resize(890,620)
        self.context=copy.deepcopy(context)
        self.worker=None
        self.closing=False
        self.checked=None
        self.options=None
        self.start=1
        self.total=0
        self.directory=Path(tempfile.mkdtemp(prefix="media-preview-"))
        self.initial=copy.deepcopy(media or default_media())
        if not media and context and context.get("kind")=="template":
            pages=context["project"]["pages"]
            self.initial.update(mode="template",assignments={p["id"]:"LH_"+"ABC"[i] for i,p in enumerate(pages[:3])})
        root=QVBoxLayout(self)
        self.enabled=QCheckBox("Enable Media Assignment and export PDF + offline JDF package")
        root.addWidget(self.enabled)
        note=QLabel("Stock identifies paper, not a tray. Map the catalog on your DFE. All Canon reference profiles require device validation and a proof print.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.tabs=QTabWidget()
        root.addWidget(self.tabs,1)
        def page(title):
            scroll=QScrollArea()
            scroll.setWidgetResizable(True)
            body=QWidget()
            layout=QVBoxLayout(body)
            scroll.setWidget(body)
            self.tabs.addTab(scroll,title)
            return layout
        stocks=page("Stocks")
        self.stocks=self.table(["Stock ID","Display name","Width mm","Height mm","Weight gsm","Preprinted"])
        stocks.addWidget(self.stocks,1)
        row=QHBoxLayout()
        for label,callback in (("Add stock",self.add_stock),("Remove selected stocks",lambda:self.remove_rows(self.stocks))):
            button=QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        stocks.addLayout(row)
        rules=page("Page rules")
        form=QFormLayout()
        self.mode=QComboBox()
        self.mode.addItem("Logical page number","page")
        self.mode.addItem("Page role: single / first / continuation / last","role")
        if context and context.get("kind")=="template" or self.initial.get("mode")=="template":
            self.mode.addItem("Template page identity","template")
        form.addRow("Assign by",self.mode)
        self.fallback=QComboBox()
        self.fallback.setEditable(True)
        form.addRow("Fallback Stock",self.fallback)
        self.fallback.setToolTip("Leave empty to block pages without a matching rule.")
        self.duplex=QCheckBox("Duplex: two sides of the same physical sheet")
        form.addRow(self.duplex)
        self.policy=QComboBox()
        self.policy.addItem("Block different Stocks on one sheet","block")
        self.policy.addItem("Insert blank backs at Stock changes","insert")
        form.addRow("Stock conflict",self.policy)
        rules.addLayout(form)
        self.assignments=self.table(["Template page / logical page / role","Stock ID"])
        self.assignments.setColumnWidth(0,330)
        rules.addWidget(self.assignments,1)
        rule_buttons=QHBoxLayout()
        add=QPushButton("Add rule")
        add.clicked.connect(lambda:self.append(self.assignments,[str(self.assignments.rowCount()+1),""]))
        rule_buttons.addWidget(add)
        remove=QPushButton("Remove selected rules")
        remove.clicked.connect(lambda:self.remove_rows(self.assignments))
        rule_buttons.addWidget(remove)
        self.batch_stock=QComboBox()
        self.batch_stock.setEditable(True)
        rule_buttons.addWidget(self.batch_stock)
        assign=QPushButton("Assign selected pages")
        assign.clicked.connect(self.assign_selected)
        rule_buttons.addWidget(assign)
        rules.addLayout(rule_buttons)
        role_note=QLabel("SINGLE is a one-page letter; FIRST / LAST apply to longer letters. Duplex pads odd letter endings. Blank backs inherit the front's Stock; logical template pages keep their identity.")
        role_note.setWordWrap(True)
        rules.addWidget(role_note)
        printer=page("Canon profile")
        form=QFormLayout()
        self.family=QComboBox()
        for key,label in FAMILIES.items():
            self.family.addItem(label,key)
        self.controller=QLineEdit()
        form.addRow("Reference device family",self.family)
        form.addRow("Controller/version notes",self.controller)
        form.addRow("Device validation",QLabel("Pending · offline review only"))
        printer.addLayout(form)
        self.mappings=self.table(["Stock ID","Media Catalog name","Media Catalog ID (optional)"])
        self.mappings.setColumnWidth(0,120)
        self.mappings.setColumnWidth(1,240)
        printer.addWidget(self.mappings,1)
        sync=QPushButton("Synchronise Stock rows with Catalog mappings")
        sync.clicked.connect(self.sync_stocks)
        printer.addWidget(sync)
        files=QHBoxLayout()
        for label,callback in (("Save media profile…",lambda:self.save_profile(False)),("Load media profile…",lambda:self.load_profile(False)),
                               ("Save printer profile…",lambda:self.save_profile(True)),("Load printer profile…",lambda:self.load_profile(True))):
            button=QPushButton(label)
            button.clicked.connect(callback)
            files.addWidget(button)
        printer.addLayout(files)
        preview=page("Media preview")
        self.summary=QLabel("Preview calculates final pages, front/back pairing and physical sheets per Stock. No PDF is generated.")
        self.summary.setWordWrap(True)
        preview.addWidget(self.summary)
        self.preview_table=self.table(HEADERS)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_rows=[]
        self.preview_table.cellDoubleClicked.connect(lambda *_:self.locate_page())
        preview.addWidget(self.preview_table,1)
        navigation=QHBoxLayout()
        self.preview_button=QPushButton("Check & Preview")
        self.preview_button.setProperty("primary",True)
        self.preview_button.clicked.connect(lambda:self.scan(1))
        navigation.addWidget(self.preview_button)
        self.previous=QPushButton("Previous 200")
        self.previous.clicked.connect(lambda:self.scan(max(1,self.start-200)))
        navigation.addWidget(self.previous)
        self.next=QPushButton("Next 200")
        self.next.clicked.connect(lambda:self.scan(self.start+200))
        navigation.addWidget(self.next)
        self.cancel=QPushButton("Cancel preview")
        self.cancel.clicked.connect(lambda:self.worker.cancel() if self.worker else None)
        navigation.addWidget(self.cancel)
        self.locate=QPushButton("Show source / template page")
        self.locate.clicked.connect(self.locate_page)
        self.preview_table.itemSelectionChanged.connect(self.navigation)
        host=self.parent()
        self.locate.setVisible(bool(host and (hasattr(host,"select_template_page") or hasattr(host,"print_page") or hasattr(host,"preview_record"))))
        navigation.addWidget(self.locate)
        preview.addLayout(navigation)
        self.error=QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.error)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.fill(self.initial)
        self.mode.currentIndexChanged.connect(self.reset_rules)
        self.stocks.itemChanged.connect(lambda *_:self.invalidate())
        self.assignments.itemChanged.connect(lambda *_:self.invalidate())
        self.mappings.itemChanged.connect(lambda *_:self.invalidate())
        for widget in (self.mode,self.policy,self.family,self.fallback):
            widget.currentIndexChanged.connect(self.invalidate)
        self.fallback.editTextChanged.connect(self.invalidate)
        self.controller.textChanged.connect(self.invalidate)
        self.enabled.toggled.connect(self.invalidate)
        self.duplex.toggled.connect(self.invalidate)
        self.navigation()
        self.error.setText("Check & Preview to review the physical pages before applying." if self.context else
                           "Save rules, then select and check a job to review the physical pages.")

    @staticmethod
    def table(headers):
        table=QTableWidget(0,len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setMinimumHeight(140)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def append(table,values):
        if table.rowCount()>=1000:
            return
        row=table.rowCount()
        table.insertRow(row)
        for col,value in enumerate(values):
            item=QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            table.setItem(row,col,item)

    @staticmethod
    def rows(table):
        return [[(table.item(r,c).data(Qt.ItemDataRole.UserRole) or table.item(r,c).text().strip()) if table.item(r,c) else "" for c in range(table.columnCount())]
                for r in range(table.rowCount())]

    def remove_rows(self,table):
        for row in sorted({i.row() for i in table.selectedIndexes()},reverse=True):
            table.removeRow(row)
        self.invalidate()

    def add_stock(self):
        self.append(self.stocks,["STOCK_"+str(self.stocks.rowCount()+1),"Paper",210,297,80,"false"])
        self.invalidate()

    def assign_selected(self):
        for row in {i.row() for i in self.assignments.selectedIndexes()}:
            self.assignments.setItem(row,1,QTableWidgetItem(self.batch_stock.currentText()))

    def sync_stocks(self):
        ids=[r[0] for r in self.rows(self.stocks) if r[0]]
        current={r[0]:r for r in self.rows(self.mappings)}
        self.mappings.setRowCount(0)
        for key in ids:
            self.append(self.mappings,current.get(key,[key,key,""]))
        for box in (self.fallback,self.batch_stock):
            text=box.currentText()
            box.clear()
            box.addItems([""]+ids)
            box.setCurrentText(text)
        self.invalidate()

    def fill(self,raw):
        spec=MediaSpec.from_dict(raw)
        self.enabled.setChecked(spec.enabled)
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(max(0,self.mode.findData(spec.mode)))
        self.mode.blockSignals(False)
        self.duplex.setChecked(spec.duplex)
        self.policy.setCurrentIndex(self.policy.findData(spec.blank_policy))
        self.stocks.setRowCount(0)
        for s in spec.stocks:
            self.append(self.stocks,[s["id"],s["name"],s["width_mm"],s["height_mm"],s["weight_gsm"],str(s.get("preprinted",False)).lower()])
        self.assignments.setRowCount(0)
        for key,value in spec.assignments.items():
            self.append(self.assignments,[key,value])
        self.label_template_pages()
        self.fill_printer(spec.printer_profile)
        self.sync_stocks()
        self.fallback.setCurrentText(spec.fallback_stock)

    def fill_printer(self,raw):
        profile=PrinterProfile.from_dict(raw)
        self.ticket_limit=profile.max_ticket_bytes
        self.family.setCurrentIndex(self.family.findData(profile.family))
        self.controller.setText(profile.controller_version)
        self.mappings.setRowCount(0)
        for key,value in profile.mappings.items():
            self.append(self.mappings,[key,value.get("name",""),value.get("catalog_id","")])

    def reset_rules(self):
        self.assignments.setRowCount(0)
        mode=self.mode.currentData()
        pages=self.context.get("project",{}).get("pages",[]) if self.context else []
        keys=ROLES if mode=="role" else [p["id"] for p in pages] if mode=="template" else [str(i+1) for i in range(len(pages) or 3)]
        for key in keys:
            self.append(self.assignments,[key,""])
        self.label_template_pages()
        self.invalidate()

    def label_template_pages(self):
        if self.mode.currentData()!="template" or not self.context:
            return
        names={p["id"]:f"{i+1} · {p.get('name','Page')}" for i,p in enumerate(self.context.get("project",{}).get("pages",[]))}
        for row in range(self.assignments.rowCount()):
            item=self.assignments.item(row,0)
            key=item.data(Qt.ItemDataRole.UserRole) or item.text()
            item.setData(Qt.ItemDataRole.UserRole,key)
            item.setText(names.get(key,"Missing template page: "+key))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip("Stable template page ID: "+key)

    def read_printer(self):
        rows=self.rows(self.mappings)
        if len({r[0] for r in rows})!=len(rows):
            raise ValueError("Duplicate Stock in Catalog mappings.")
        profile=PrinterProfile(family=self.family.currentData(),controller_version=self.controller.text(),
                               mappings={r[0]:{"name":r[1],"catalog_id":r[2]} for r in rows},max_ticket_bytes=self.ticket_limit)
        from dataclasses import asdict
        return asdict(PrinterProfile.from_dict(asdict(profile)))

    def value(self):
        stocks=[]
        for r in self.rows(self.stocks):
            if r[5].lower() not in ("true","false"):
                raise ValueError("Preprinted must be true or false.")
            stocks.append(dict(id=r[0],name=r[1],width_mm=float(r[2]),height_mm=float(r[3]),weight_gsm=float(r[4]),preprinted=r[5].lower()=="true"))
        rows=[r for r in self.rows(self.assignments) if r[1]]
        if len({r[0] for r in rows})!=len(rows):
            raise ValueError("Each page / role can have only one Stock rule.")
        spec=MediaSpec(enabled=self.enabled.isChecked(),mode=self.mode.currentData(),stocks=stocks,
                       assignments=dict(rows),fallback_stock=self.fallback.currentText().strip(),duplex=self.duplex.isChecked(),
                       blank_policy=self.policy.currentData(),printer_profile=self.read_printer())
        return MediaSpec.from_dict(spec.to_dict()).to_dict()

    def invalidate(self,*_):
        self.checked=None
        self.error.setText("Settings changed. Check & Preview before applying." if self.context else
                           "Rules can be saved; check against a selected job before production.")

    def navigation(self):
        busy=self.worker is not None
        self.preview_button.setEnabled(not busy and self.context is not None)
        self.previous.setEnabled(not busy and self.checked is not None and self.start>1)
        self.next.setEnabled(not busy and self.checked is not None and self.start+199<self.total)
        self.cancel.setEnabled(busy)
        self.locate.setEnabled(not busy and self.checked is not None and self.preview_table.currentRow()>=0)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not busy)

    def scan(self,start):
        if self.worker or not self.context:
            return
        try:
            media=self.value()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.tabs.setCurrentIndex(3)
        self.start=start
        self.checked=None
        self.error.setText("Checking physical page plan…")
        self.worker=Worker(self.directory,{"task":"media_preview","context":self.context,"media":media,"start":start},self)
        self.worker.resultReady.connect(lambda result:self.ready(result,media))
        self.worker.failed.connect(lambda message:self.error.setText(message))
        self.worker.ended.connect(self.ended)
        self.navigation()

    def ready(self,result,media):
        try:
            unchanged=self.value()==media
        except ValueError:
            unchanged=False
        if not unchanged:
            self.error.setText("Settings changed during preview; check again.")
            return
        self.checked=copy.deepcopy(media)
        self.total=result["pages"]
        self.preview_rows=result["rows"]
        self.preview_table.setRowCount(0)
        for row in result["rows"]:
            self.append(self.preview_table,row)
        if self.preview_rows:
            self.preview_table.setCurrentCell(0,0)
        if result.get("disabled"):
            self.summary.setText("Media Assignment disabled: normal PDF output.")
        else:
            stocks=" · ".join(f"{key}: {value:,} sheets" for key,value in result["stock_sheets"].items())
            self.summary.setText(f"{result['pages']:,} final pages · {result['sheets']:,} sheets · {result['inserted_blanks']:,} blank backs\n{stocks}\nShowing pages {self.start}–{min(self.start+199,self.total)}. Device validation pending.")
        self.error.setText("Configuration checked. Review the physical page plan before applying.")

    def locate_page(self):
        row=self.preview_table.currentRow()
        if self.worker or not self.checked or not 0<=row<len(self.preview_rows):
            return
        _,_,record,source,logical,*_=self.preview_rows[row]
        host=self.parent()
        if not logical:
            self.error.setText("Inserted blank back: no source or template page.")
        elif host and hasattr(host,"select_template_page"):
            host.select_template_page(int(logical)-1)
            host.tabs.setCurrentIndex(0)
            self.error.setText("Template page selected in Designer. Move this dialog aside to inspect it; settings remain a draft.")
        elif host and hasattr(host,"print_page") and host.spec:
            from composition.media.planner import preview_plan
            plan=preview_plan(host.spec)
            host.envelope.setValue(record)
            for index in range(1,plan.settings_for(record).output_pages_per_envelope+1):
                if plan.page(record,index).source_page==source:
                    host.print_page.setValue(index)
                    break
            host.tabs.setCurrentIndex(0)
            self.error.setText("Source page selected in Overlay. Move this dialog aside to inspect it; settings remain a draft.")
        elif host and hasattr(host,"preview_record"):
            host.preview_record.setValue(record)
            host.preview_page.setValue(int(logical))
            host.schedule_preview()
            self.error.setText("Checked job preview selected. Current media settings remain a draft until applied.")

    def ended(self):
        self.worker=None
        self.navigation()
        if self.closing:
            self.reject()

    def profile_directory(self):
        path=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))/"composition"/"media_profiles"
        path.mkdir(parents=True,exist_ok=True)
        return path

    def save_profile(self,printer):
        try:
            value=self.read_printer() if printer else self.value()
            path,_=QFileDialog.getSaveFileName(self,"Save reference profile",str(self.profile_directory()/('printer.json' if printer else 'media.json')),"JSON (*.json)")
            if path:
                with atomic_output(Path(path)) as temp:
                    temp.write_text(json.dumps({"kind":"printer" if printer else "media","profile_version":1,"settings":value},indent=2),encoding="utf-8")
        except (ValueError,OSError) as exc:
            self.error.setText(str(exc))

    def load_profile(self,printer):
        path,_=QFileDialog.getOpenFileName(self,"Load reference profile",str(self.profile_directory()),"JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size>1024*1024:
                raise ValueError("Profile exceeds 1 MB.")
            raw=json.loads(Path(path).read_text(encoding="utf-8"))
            if raw.get("profile_version")!=1 or raw.get("kind")!=("printer" if printer else "media"):
                raise ValueError("Incorrect profile type / version.")
            self.fill_printer(raw["settings"]) if printer else self.fill(raw["settings"])
            self.invalidate()
        except (ValueError,OSError,KeyError,TypeError,AttributeError) as exc:
            self.error.setText(str(exc))

    def accept(self):
        if self.worker:
            return
        try:
            options=self.value()
            if options["enabled"] and self.context and self.checked!=options:
                self.scan(1)
                return
            if options["enabled"] and options["duplex"] and options["blank_policy"]=="insert" and (
                    not self.initial.get("enabled") or self.initial.get("blank_policy")!="insert" or not self.initial.get("duplex")):
                if QMessageBox.question(self,"Confirm blank backs","Insert blank backs at Stock changes and odd letter endings? This changes final output page numbers, page sequences and barcode values.")!=QMessageBox.StandardButton.Yes:
                    return
            self.options=options
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()
        self.cleanup()

    def cleanup(self):
        if self.directory.exists():
            for path in self.directory.iterdir():
                path.unlink(missing_ok=True)
            self.directory.rmdir()

    def reject(self):
        if self.worker:
            self.closing=True
            self.worker.cancel()
            self.error.setText("Cancelling preview before closing…")
            return
        self.cleanup()
        super().reject()

    def closeEvent(self,event):
        if self.worker:
            event.ignore()
        else:
            event.accept()
        self.reject()
