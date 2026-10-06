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
    QInputDialog,
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

from composition.media.model import FAMILIES, PS_FAMILIES, ROLES, MediaSpec, PrinterProfile, default_media
from composition.media.ticket import HEADERS
from core.io_atomic import atomic_output

from .process import Worker


class MediaDialog(QDialog):
    def __init__(self,media,context=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Print Media · Stocks, PostScript and job tickets")
        self.resize(890,620)
        self.context=copy.deepcopy(context)
        self.worker=None
        self.closing=False
        self.checked=None
        self.options=None
        self.start=1
        self.total=0
        self.rule_mode=None
        self.rule_drafts={}
        self.profile_families={}
        self.profile_backend=None
        self.directory=Path(tempfile.mkdtemp(prefix="media-preview-"))
        self.initial=copy.deepcopy(media or default_media())
        if not media and context and context.get("kind")=="template":
            # Paper choices belong to the operator, not the first three page numbers.
            self.initial.update(mode="template",assignments={})
        root=QVBoxLayout(self)
        self.enabled=QCheckBox("Enable Media Assignment and selected production output")
        entry=QHBoxLayout()
        entry.addWidget(self.enabled,1)
        self.library_button=QPushButton("Profile library…")
        self.library_button.setToolTip("Browse saved setups by device, or import media / printer profile files.")
        self.library_button.clicked.connect(self.open_library)
        entry.addWidget(self.library_button)
        root.addLayout(entry)
        note=QLabel("Assign logical Stocks to pages, then choose PDF + JDF or PDF + PostScript in Printer profile. Save a profile for each environment; verify paper selection with a test print.")
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
        self.duplex.setToolTip("A sheet has one Stock: pages 1/2 share it, then pages 3/4. The number of Stocks is unrestricted.")
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
        add.clicked.connect(self.add_rule)
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
        self.sheet_button=QPushButton("Assign Stocks by duplex sheet…")
        self.sheet_button.setToolTip("For a fixed template, assign one Stock to each front/back pair without editing both pages separately.")
        self.sheet_button.clicked.connect(self.assign_sheets)
        rules.addWidget(self.sheet_button)
        role_note=QLabel("One or more Stocks can be used. Duplex example: pages 1/2 → Stock A, pages 3/4 → Stock B. SINGLE is a one-page letter; FIRST / LAST apply to longer letters. Blank backs inherit the front's Stock.")
        role_note.setWordWrap(True)
        rules.addWidget(role_note)
        printer=page("Printer profile")
        form=QFormLayout()
        self.output_format=QComboBox()
        self.output_format.addItem("PDF + Canon offline JDF","canon_prismasync")
        self.output_format.addItem("PDF + PostScript (no separate job ticket)","postscript")
        form.addRow("Production output",self.output_format)
        self.profile_name=QLineEdit()
        self.profile_name.setPlaceholderText("e.g. Production room A")
        form.addRow("Profile name",self.profile_name)
        self.family=QComboBox()
        for key,label in (FAMILIES|PS_FAMILIES).items():
            self.family.addItem(label,key)
        self.controller=QLineEdit()
        form.addRow("Device / controller family",self.family)
        form.addRow("Controller/version notes",self.controller)
        form.addRow("Device validation",QLabel("Pending · offline review only"))
        self.selection_mode=QComboBox()
        self.selection_mode.addItem("Paper attributes (MediaType / colour)","attributes")
        self.selection_mode.addItem("Paper source position (MediaPosition)","tray")
        form.addRow("PS paper selection",self.selection_mode)
        self.tumble=QCheckBox("Duplex short-edge binding (Tumble)")
        form.addRow(self.tumble)
        self.emit_weight=QCheckBox("Include Stock weight in attribute matching")
        form.addRow(self.emit_weight)
        self.resolution=QComboBox()
        for dpi in (300,600,1200):
            self.resolution.addItem(f"{dpi} dpi",dpi)
        form.addRow("PS flattening resolution",self.resolution)
        printer.addLayout(form)
        self.printer_hint=QLabel()
        self.printer_hint.setWordWrap(True)
        printer.addWidget(self.printer_hint)
        self.mappings=self.table(["Stock ID","Media Catalog name","Media Catalog ID (optional)","PS MediaType","PS MediaColor (optional)","PS MediaPosition"])
        self.mappings.setColumnWidth(0,120)
        self.mappings.setColumnWidth(1,240)
        printer.addWidget(self.mappings,1)
        sync=QPushButton("Synchronise Stock rows with printer mappings")
        sync.clicked.connect(self.sync_stocks)
        printer.addWidget(sync)
        self.profile_actions=QWidget()
        files=QHBoxLayout(self.profile_actions)
        files.setContentsMargins(0,0,0,0)
        self.profile_buttons=[]
        for label,callback in (("Save media profile…",lambda:self.save_profile(False)),("Load media profile…",lambda:self.load_profile(False)),
                               ("Save printer profile…",lambda:self.save_profile(True)),("Load printer profile…",lambda:self.load_profile(True))):
            button=QPushButton(label)
            button.clicked.connect(callback)
            files.addWidget(button)
            self.profile_buttons.append(button)
        root.addWidget(self.profile_actions)
        self.profile_actions.setVisible(False)
        self.tabs.currentChanged.connect(lambda index:self.profile_actions.setVisible(index==2))
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
        self.proof_button=QPushButton("Export paper-selection test PS…")
        self.proof_button.setToolTip("One sheet per Stock, using these profile settings. No customer data; print to verify paper sources.")
        self.proof_button.clicked.connect(self.export_paper_test)
        preview.addWidget(self.proof_button)
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
        for widget in (self.mode,self.policy,self.family,self.fallback,self.output_format,self.selection_mode,self.resolution):
            widget.currentIndexChanged.connect(self.invalidate)
        self.output_format.currentIndexChanged.connect(self.printer_controls)
        self.selection_mode.currentIndexChanged.connect(self.printer_controls)
        self.fallback.editTextChanged.connect(self.invalidate)
        self.controller.textChanged.connect(self.invalidate)
        self.profile_name.textChanged.connect(self.invalidate)
        self.tumble.toggled.connect(self.invalidate)
        self.emit_weight.toggled.connect(self.invalidate)
        self.enabled.toggled.connect(self.invalidate)
        self.duplex.toggled.connect(self.invalidate)
        self.printer_controls()
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

    def rule_keys(self,mode):
        if mode=="role":
            return list(ROLES)
        if mode=="template":
            return [p["id"] for p in self.context.get("project",{}).get("pages",[])] if self.context else []
        return [str(i) for i in range(1,101)]

    def add_rule(self):
        mode=self.mode.currentData()
        used={row[0] for row in self.rows(self.assignments)}
        available=[key for key in self.rule_keys(mode) if key not in used]
        if not available:
            self.error.setText("All pages / roles already have a rule. Edit or remove an existing rule.")
            return
        key=available[0]
        if mode in ("template","role") and len(available)>1:
            names={p["id"]:f"{i+1} · {p.get('name','Page')}" for i,p in enumerate(self.context.get("project",{}).get("pages",[]))} if self.context else {}
            labels=[names.get(value,value) for value in available]
            label,ok=QInputDialog.getItem(self,"Add paper rule","Page / role",labels,0,False)
            if not ok:
                return
            key=available[labels.index(label)]
        self.append(self.assignments,[key,""])
        self.label_template_pages()
        self.assignments.setCurrentCell(self.assignments.rowCount()-1,1)
        self.invalidate()

    def assign_selected(self):
        for row in {i.row() for i in self.assignments.selectedIndexes()}:
            self.assignments.setItem(row,1,QTableWidgetItem(self.batch_stock.currentText()))

    def sync_stocks(self):
        ids=[r[0] for r in self.rows(self.stocks) if r[0]]
        current={r[0]:r for r in self.rows(self.mappings)}
        self.mappings.setRowCount(0)
        for key in ids:
            self.append(self.mappings,current.get(key,[key,key,"","","",""]))
        for box in (self.fallback,self.batch_stock):
            text=box.currentText()
            box.clear()
            box.addItems([""]+ids)
            box.setCurrentText(text)
        self.invalidate()

    def fill(self,raw):
        spec=MediaSpec.from_dict(raw)
        self.rule_mode=spec.mode
        self.rule_drafts={}
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
        rows=dict(spec.assignments)
        if self.context and self.context.get("kind")=="template" and spec.mode in ("template","page"):
            pages=self.context["project"]["pages"]
            keys=[p["id"] if spec.mode=="template" else str(i+1) for i,p in enumerate(pages)]
            rows={**{key:spec.assignments.get(key,"") for key in keys},
                  **{key:value for key,value in spec.assignments.items() if key not in keys}}
        for key,value in rows.items():
            self.append(self.assignments,[key,value])
        self.label_template_pages()
        self.fill_printer(spec.printer_profile)
        self.sync_stocks()
        self.fallback.setCurrentText(spec.fallback_stock)

    def fill_printer(self,raw):
        profile=PrinterProfile.from_dict(raw)
        self.ticket_limit=profile.max_ticket_bytes
        self.profile_families[profile.backend]=profile.family
        self.output_format.blockSignals(True)
        self.output_format.setCurrentIndex(self.output_format.findData(profile.backend))
        self.output_format.blockSignals(False)
        self.profile_name.setText(profile.profile_name)
        self.selection_mode.setCurrentIndex(self.selection_mode.findData(profile.selection_mode))
        self.tumble.setChecked(profile.tumble)
        self.emit_weight.setChecked(profile.emit_media_weight)
        self.resolution.setCurrentIndex(self.resolution.findData(profile.resolution_dpi))
        self.printer_controls()
        self.family.setCurrentIndex(self.family.findData(profile.family))
        self.controller.setText(profile.controller_version)
        self.mappings.setRowCount(0)
        for key,value in profile.mappings.items():
            self.append(self.mappings,[key,value.get("name",""),value.get("catalog_id",""),
                                      value.get("media_type",""),value.get("media_color",""),
                                      "" if value.get("media_position") is None else value["media_position"]])

    def printer_controls(self,*_):
        backend=self.output_format.currentData()
        ps=backend=="postscript"
        tray=self.selection_mode.currentData()=="tray"
        family=self.family.currentData()
        if self.profile_backend!=backend:
            if self.profile_backend and family:
                self.profile_families[self.profile_backend]=family
            family=self.profile_families.get(backend,"generic" if ps else "vp6000")
            self.profile_backend=backend
        options=FAMILIES|PS_FAMILIES if ps else FAMILIES
        if [self.family.itemData(i) for i in range(self.family.count())]!=list(options):
            self.family.clear()
            for key,label in options.items():
                self.family.addItem(label,key)
            self.family.setCurrentIndex(self.family.findData(family) if family in options else 0)
        elif family in options:
            self.family.setCurrentIndex(self.family.findData(family))
        for control in (self.selection_mode,self.tumble,self.resolution):
            control.setEnabled(ps)
        self.emit_weight.setEnabled(ps and not tray)
        for col in (1,2):
            self.mappings.setColumnHidden(col,ps)
        self.mappings.setColumnHidden(3,not ps or tray)
        self.mappings.setColumnHidden(4,not ps or tray)
        self.mappings.setColumnHidden(5,not ps or not tray)
        self.printer_hint.setText(
            "MediaPosition is the controller's paper-source number; 0 is valid. It may differ from the tray label. Page size is always requested; type/colour/weight are not forced."
            if ps and tray else
            "Enter an explicit MediaType for each Stock and optional colour. Different letterheads need distinguishable requests. These are PS attributes, not automatically Media Catalog names."
            if ps else "Map each Stock to the exact Canon Media Catalog name / ID. This backend produces an offline JDF package.")
        self.proof_button.setVisible(ps)
        self.navigation()

    def reset_rules(self):
        old_mode=self.rule_mode
        rows=self.rows(self.assignments)
        if old_mode:
            self.rule_drafts[old_mode]=copy.deepcopy(rows)
        self.assignments.setRowCount(0)
        mode=self.mode.currentData()
        pages=self.context.get("project",{}).get("pages",[]) if self.context else []
        if mode in self.rule_drafts:
            rows=copy.deepcopy(self.rule_drafts[mode])
        elif pages and {old_mode,mode}=={"page","template"}:
            mapping={str(i+1):p["id"] for i,p in enumerate(pages)}
            if mode=="page":
                mapping={value:key for key,value in mapping.items()}
            # Conversion is explicit in the selected mode; other mode drafts remain intact.
            rows=[[mapping[key],stock] for key,stock in rows if key in mapping]
        else:
            keys=ROLES if mode=="role" else [p["id"] for p in pages] if mode=="template" else [str(i+1) for i in range(len(pages) or 3)]
            rows=[[key,""] for key in keys]
        for row in rows:
            self.append(self.assignments,row)
        self.rule_mode=mode
        self.label_template_pages()
        self.invalidate()

    def label_template_pages(self):
        if self.mode.currentData()=="role":
            for row in range(self.assignments.rowCount()):
                item=self.assignments.item(row,0)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return
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

    def create_sheet_dialog(self):
        from .media_sheet_dialog import DuplexSheetDialog
        if (not self.context or self.context.get("kind")!="template" or
                self.mode.currentData() not in ("template","page") or not self.duplex.isChecked()):
            raise ValueError("Choose Duplex and template / logical page rules for a fixed template first.")
        return DuplexSheetDialog(self.context["project"]["pages"],self.rows(self.stocks),
                                 dict(self.rows(self.assignments)),self.fallback.currentText().strip(),
                                 self.mode.currentData(),self)

    def assign_sheets(self):
        if self.worker:
            return
        try:
            dialog=self.create_sheet_dialog()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        try:
            if dialog.exec()!=QDialog.DialogCode.Accepted:
                return
            rows=dict(self.rows(self.assignments))
            rows.update(dialog.assignments)
            self.assignments.setRowCount(0)
            for key,stock in rows.items():
                self.append(self.assignments,[key,stock])
            self.label_template_pages()
            self.invalidate()
            self.error.setText("Front/back Stock pairs updated. Check & Preview before applying.")
        finally:
            dialog.deleteLater()

    def read_printer(self):
        rows=self.rows(self.mappings)
        if len({r[0] for r in rows})!=len(rows):
            raise ValueError("Duplicate Stock in Catalog mappings.")
        ps=self.output_format.currentData()=="postscript"
        mappings={}
        for r in rows:
            item={"name":r[1],"catalog_id":r[2]}
            if ps:
                if r[5] and (not r[5].isascii() or not r[5].isdigit()):
                    raise ValueError("MediaPosition must be a whole paper-source number; leave blank if unknown.")
                item.update(media_type=r[3],media_color=r[4],media_position=int(r[5]) if r[5] else None)
            mappings[r[0]]=item
        profile=PrinterProfile(profile_version=2 if ps else 1,backend=self.output_format.currentData(),
                               family=self.family.currentData(),controller_version=self.controller.text(),
                               mappings=mappings,max_ticket_bytes=self.ticket_limit,profile_name=self.profile_name.text().strip(),
                               selection_mode=self.selection_mode.currentData(),tumble=self.tumble.isChecked(),
                               resolution_dpi=self.resolution.currentData(),emit_media_weight=self.emit_weight.isChecked())
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
        self.navigation()

    def navigation(self):
        busy=self.worker is not None
        self.library_button.setEnabled(not busy)
        self.profile_actions.setEnabled(not busy)
        self.preview_button.setEnabled(not busy and self.context is not None)
        self.sheet_button.setEnabled(not busy and self.duplex.isChecked() and bool(self.context)
                                     and self.context.get("kind")=="template"
                                     and self.mode.currentData() in ("template","page"))
        self.previous.setEnabled(not busy and self.checked is not None and self.start>1)
        self.next.setEnabled(not busy and self.checked is not None and self.start+199<self.total)
        self.cancel.setEnabled(busy)
        self.locate.setEnabled(not busy and self.checked is not None and self.preview_table.currentRow()>=0)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not busy)
        self.proof_button.setEnabled(not busy and self.output_format.currentData()=="postscript")

    def export_paper_test(self):
        if self.worker:
            return
        try:
            media=self.value()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        path,_=QFileDialog.getSaveFileName(self,"Export paper-selection test","paper-test.ps","PostScript (*.ps)")
        if not path:
            return
        self.worker=Worker(self.directory,{"task":"media_paper_test","media":media,"target":path},self)
        self.worker.resultReady.connect(lambda result:self.error.setText("Paper test saved: "+result["path"]+". Print it to check actual Stock / tray selection."))
        self.worker.failed.connect(lambda message:self.error.setText(message))
        self.worker.ended.connect(self.ended)
        self.error.setText("Generating and validating paper-selection test…")
        self.navigation()

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

    def open_library(self):
        if self.worker:
            return
        from .profile_library_dialog import ProfileLibraryDialog
        dialog=ProfileLibraryDialog(self.profile_directory(),self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            try:
                self.apply_library_profile(dialog.selected_profile)
            except (ValueError,TypeError,KeyError) as exc:
                self.error.setText(str(exc))

    def apply_library_profile(self,raw):
        from composition.media.profile_library import validate_profile
        if self.worker:
            raise ValueError("Wait for the current media task before loading a profile.")
        profile=validate_profile(raw)
        settings=profile["settings"]
        if profile["kind"]=="media":
            if settings["mode"]=="template":
                pages=self.context.get("project",{}).get("pages",[]) if self.context and self.context.get("kind")=="template" else []
                ids={page["id"] for page in pages}
                if not ids or set(settings["assignments"])-ids:
                    raise ValueError("This profile uses other template page identities. Load it in the matching template, or save logical page rules for reuse.")
                if self.mode.findData("template")<0:
                    self.mode.addItem("Template page identity","template")
            self.fill(settings)
        else:
            self.fill_printer(settings)
            self.sync_stocks()
        self.invalidate()
        self.tabs.setCurrentIndex(1 if profile["kind"]=="media" else 2)
        self.error.setText("Profile loaded as a draft. Review rules and mappings, then Check & Preview. Device validation: Pending.")

    def save_profile(self,printer):
        try:
            value=self.read_printer() if printer else self.value()
            path,_=QFileDialog.getSaveFileName(self,"Save printer profile" if printer else "Save media profile",str(self.profile_directory()/('printer.json' if printer else 'media.json')),"JSON (*.json)")
            if path:
                with atomic_output(Path(path)) as temp:
                    version=2 if (value if printer else value["printer_profile"]).get("backend")=="postscript" else 1
                    temp.write_text(json.dumps({"kind":"printer" if printer else "media","profile_version":version,"settings":value},indent=2),encoding="utf-8")
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
            if raw.get("profile_version") not in (1,2) or raw.get("kind")!=("printer" if printer else "media"):
                raise ValueError("Incorrect profile type / version.")
            self.apply_library_profile(raw)
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
