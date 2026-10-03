"""Large PDF region editor: crisp background stays in place while boxes are edited."""
from __future__ import annotations

import copy

from PyQt6 import sip
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPen, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from composition.designer.mailpiece_region import RegionView

from .extraction import ExtractionSpec, Region


class RegionChange(QUndoCommand):
    def __init__(self,dialog,before,after,label):
        super().__init__(label)
        self.dialog,self.before,self.after=dialog,copy.deepcopy(before),copy.deepcopy(after)

    def undo(self):
        self.dialog.apply_regions(self.before)

    def redo(self):
        self.dialog.apply_regions(self.after)


class RegionCanvas(RegionView):
    def __init__(self,dialog):
        super().__init__(dialog)
        self.move_start=None
        self.setAccessibleName("PDF visual extraction regions")

    def mousePressEvent(self,event):
        self.move_start=None
        if event.button()==Qt.MouseButton.LeftButton and self.dragMode()!=self.DragMode.ScrollHandDrag:
            point=self.mapToScene(event.pos())
            for index,region in enumerate(self.dialog.regions):
                rect=QRectF(region["x_mm"],region["y_mm"],region["width_mm"],region["height_mm"])
                if rect.contains(point):
                    self.dialog.list.setCurrentRow(index)
                    break
        if (event.button()==Qt.MouseButton.LeftButton and self.region_item and not self.loading
                and self.dragMode()!=self.DragMode.ScrollHandDrag):
            p=self.mapToScene(event.pos())
            rect=self.region_item.rect()
            if rect.contains(p):
                self.move_start=(p,QRectF(rect),abs(p.x()-rect.right())<3 and abs(p.y()-rect.bottom())<3)
                self.dialog.before_drag=copy.deepcopy(self.dialog.regions)
                event.accept()
                return
        self.dialog.before_drag=copy.deepcopy(self.dialog.regions)
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.move_start:
            p,rect,resize=self.move_start
            delta=self.mapToScene(event.pos())-p
            updated=QRectF(rect)
            if resize:
                updated.setWidth(max(.5,min(rect.width()+delta.x(),self.sceneRect().right()-rect.left())))
                updated.setHeight(max(.5,min(rect.height()+delta.y(),self.sceneRect().bottom()-rect.top())))
            else:
                updated.moveLeft(max(0,min(rect.left()+delta.x(),self.sceneRect().right()-rect.width())))
                updated.moveTop(max(0,min(rect.top()+delta.y(),self.sceneRect().bottom()-rect.height())))
            self.region_item.setRect(updated)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def wheelEvent(self,event):
        super().wheelEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.dialog.schedule(True)

    def mouseReleaseEvent(self,event):
        if self.move_start:
            self.move_start=None
            rect=self.region_item.rect()
            self.dialog.set_coords(rect.x(),rect.y(),rect.width(),rect.height())
            self.dialog.invalidate()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class RegionEditor(QDialog):
    def __init__(self,host,source,spec,page=1):
        super().__init__(host)
        self.host,self.source=host,source
        self.setWindowTitle("Visual Extraction Regions")
        self.resize(1180,780)
        self.regions=copy.deepcopy(spec.get("regions",[]))
        self.original_empty=not self.regions
        if not self.regions:
            from dataclasses import asdict
            self.regions=[asdict(Region())]
        self.current=0
        self.geometry=(210,297)
        self.before_drag=None
        self.loading_controls=False
        self.last_image=None
        self.token=0
        self.closed=False
        self.undo=QUndoStack(self)
        outer=QVBoxLayout(self)
        top=QHBoxLayout()
        self.page=QSpinBox()
        self.page.setRange(1,1000000)
        self.page.setValue(page)
        self.page.setPrefix("Page ")
        self.page.valueChanged.connect(lambda *_:self.schedule(True))
        top.addWidget(self.page)
        for text,handler in (("Fit page",lambda:self.view.fit_page()),("Zoom +",lambda:self.zoom(1.2)),("Zoom −",lambda:self.zoom(1/1.2)),
                              ("Undo",self.undo.undo),("Redo",self.undo.redo)):
            button=QPushButton(text)
            button.clicked.connect(handler)
            top.addWidget(button)
        top.addStretch()
        outer.addLayout(top)
        splitter=QSplitter()
        self.view=RegionCanvas(self)
        splitter.addWidget(self.view)
        inspector=QWidget()
        right=QVBoxLayout(inspector)
        self.list=QListWidget()
        self.list.setMaximumHeight(145)
        self.list.currentRowChanged.connect(self.select)
        right.addWidget(self.list)
        tools=QHBoxLayout()
        for text,fn in (("Add",self.add),("Duplicate",self.duplicate),("Delete",self.delete)):
            button=QPushButton(text)
            button.clicked.connect(fn)
            tools.addWidget(button)
        right.addLayout(tools)
        content=QWidget()
        form=QFormLayout(content)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name=QLineEdit()
        self.name.editingFinished.connect(self.save_controls)
        form.addRow("Field name",self.name)
        self.region=[]
        for label in ("X (mm)","Y (mm)","Width (mm)","Height (mm)"):
            spin=QDoubleSpinBox()
            spin.setRange(0,2000)
            spin.setDecimals(2)
            spin.setSingleStep(.5)
            spin.editingFinished.connect(self.save_controls)
            self.region.append(spin)
            form.addRow(label,spin)
        self.whole=QCheckBox()
        self.whole.setChecked(False)
        self.scope=QComboBox()
        for label,value in (("All pages","all"),("First page of each envelope","first"),("Specific page role","role")):
            self.scope.addItem(label,value)
        self.role=QSpinBox()
        self.role.setRange(1,100)
        self.policy=QComboBox()
        self.policy.addItems(["Take first applicable page","Verify all applicable pages agree"])
        self.format=QComboBox()
        self.format.addItems(["text","digits","decimal"])
        self.required=QCheckBox("Required value")
        self.trim=QCheckBox("Trim outer whitespace")
        self.join=QCheckBox("Join lines with spaces")
        self.label=QLineEdit()
        self.minimum,self.maximum=QSpinBox(),QSpinBox()
        for spin in (self.minimum,self.maximum):
            spin.setRange(0,100000)
        for label,control in (("Apply to",self.scope),("Page role",self.role),("Envelope value",self.policy),
                              ("Format",self.format),("Remove leading label",self.label),("Minimum length",self.minimum),
                              ("Maximum length",self.maximum),("",self.required),("",self.trim),("",self.join)):
            form.addRow(label,control)
            if isinstance(control,QComboBox):
                control.currentIndexChanged.connect(self.save_controls)
            elif isinstance(control,QCheckBox):
                control.toggled.connect(self.save_controls)
            else:
                control.editingFinished.connect(self.save_controls)
        for control in (self.scope,self.policy,self.format):
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            control.setMinimumContentsLength(8)
            control.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            control.setToolTip(control.currentText())
            control.currentTextChanged.connect(control.setToolTip)
        scroll=QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        right.addWidget(scroll,1)
        self.sample=QLabel()
        self.sample.setTextFormat(Qt.TextFormat.PlainText)
        self.sample.setWordWrap(True)
        self.sample.setMaximumHeight(110)
        right.addWidget(self.sample)
        self.hint=QLabel("Drag inside a box to move; drag its bottom-right corner to resize. Drag outside to redraw. Ctrl+wheel zooms; Space pans.")
        self.hint.setWordWrap(True)
        right.addWidget(self.hint)
        self.inspector=inspector
        splitter.addWidget(inspector)
        splitter.setSizes([790,330])
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter,1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self.preview)
        self.raster_needed=True
        self.apply_regions(self.regions)
        self.undo.setClean()
        self.schedule(True)

    def zoom(self,factor):
        self.view.fit_mode=False
        self.view.scale(factor,factor)
        self.schedule(True)

    def set_coords(self,*coords):
        for spin,value in zip(self.region,coords,strict=True):
            spin.setValue(value)

    def apply_regions(self,regions):
        self.regions=copy.deepcopy(regions)
        self.current=max(0,min(self.current,len(self.regions)-1))
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([r["name"] for r in self.regions])
        self.list.setCurrentRow(self.current)
        self.list.blockSignals(False)
        self.select(self.current)

    def select(self,index):
        if not 0<=index<len(self.regions):
            return
        self.current=index
        r=self.regions[index]
        self.loading_controls=True
        self.name.setText(r["name"])
        self.set_coords(*[r[k] for k in ("x_mm","y_mm","width_mm","height_mm")])
        self.scope.setCurrentIndex(self.scope.findData(r["scope"]))
        self.role.setValue(r["role"])
        self.policy.setCurrentIndex(int(r["envelope_value"]=="consistent"))
        self.format.setCurrentText(r["format"])
        self.required.setChecked(r["required"])
        self.trim.setChecked(r["trim"])
        self.join.setChecked(r["join_lines"])
        self.label.setText(r["remove_label"])
        self.minimum.setValue(r["min_length"])
        self.maximum.setValue(r["max_length"])
        self.loading_controls=False
        self.view.update_region()
        self.other_boxes()
        self.schedule()

    def other_boxes(self):
        for item in list(self.view.scene().items()):
            if item.data(0)=="other_region":
                self.view.scene().removeItem(item)
        for i,r in enumerate(self.regions):
            if i==self.current:
                continue
            pen=QPen(QColor("#448ecc"),1)
            pen.setCosmetic(True)
            item=self.view.scene().addRect(QRectF(r["x_mm"],r["y_mm"],r["width_mm"],r["height_mm"]),pen)
            item.setData(0,"other_region")

    def save_controls(self,*_):
        if self.loading_controls or not self.regions:
            return
        before=copy.deepcopy(self.regions)
        r=self.regions[self.current]
        r.update(name=self.name.text().strip(),scope=self.scope.currentData(),role=self.role.value(),
                 envelope_value="consistent" if self.policy.currentIndex() else "first",format=self.format.currentText(),
                 required=self.required.isChecked(),trim=self.trim.isChecked(),join_lines=self.join.isChecked(),
                 remove_label=self.label.text(),min_length=self.minimum.value(),max_length=self.maximum.value())
        for key,control in zip(("x_mm","y_mm","width_mm","height_mm"),self.region,strict=True):
            r[key]=control.value()
        self.push(before,"Edit extraction region")

    def invalidate(self):
        before=self.before_drag or copy.deepcopy(self.regions)
        self.before_drag=None
        r=self.regions[self.current]
        r.update(dict(zip(("x_mm","y_mm","width_mm","height_mm"),[s.value() for s in self.region],strict=True)))
        r["page_width_mm"],r["page_height_mm"]=self.geometry
        self.push(before,"Move / resize extraction region")

    def push(self,before,label):
        after=copy.deepcopy(self.regions)
        if before!=after:
            self.undo.push(RegionChange(self,before,after,label))

    def add(self):
        from dataclasses import asdict
        before=copy.deepcopy(self.regions)
        number=len(self.regions)+1
        name="Field_"+str(number)
        while name in [r["name"] for r in self.regions]:
            number+=1
            name="Field_"+str(number)
        self.regions.append(asdict(Region(name=name,page_width_mm=self.geometry[0],page_height_mm=self.geometry[1])))
        self.current=len(self.regions)-1
        self.push(before,"Add extraction region")

    def duplicate(self):
        before=copy.deepcopy(self.regions)
        r=copy.deepcopy(self.regions[self.current])
        r["name"]+="_copy"
        while r["name"] in [v["name"] for v in self.regions]:
            r["name"]+="_copy"
        self.regions.append(r)
        self.current=len(self.regions)-1
        self.push(before,"Duplicate extraction region")

    def delete(self):
        if len(self.regions)==1:
            self.sample.setText("Keep at least one extraction region.")
            return
        before=copy.deepcopy(self.regions)
        self.regions.pop(self.current)
        self.push(before,"Delete extraction region")

    def schedule(self,raster=False):
        self.raster_needed|=raster
        self.token+=1
        self.timer.start()

    def preview(self):
        token=self.token
        raster=self.raster_needed or self.last_image is None
        self.raster_needed=False
        try:
            ExtractionSpec.from_dict({"regions":self.regions,"version":1})
        except ValueError as exc:
            self.sample.setText(str(exc))
            return
        def ready(result):
            if sip.isdeleted(self) or self.closed or token!=self.token:
                return
            self.geometry=(result["width_mm"],result["height_mm"])
            self.page.blockSignals(True)
            self.page.setMaximum(result["pages"])
            self.page.blockSignals(False)
            if self.original_empty:
                self.original_empty=False
                for r in self.regions:
                    r["page_width_mm"],r["page_height_mm"]=self.geometry
            if raster:
                self.last_image=result["image"]
                self.view.load(result["image"],{"width_pt":self.geometry[0]*72/25.4,"height_pt":self.geometry[1]*72/25.4})
                self.other_boxes()
            cell=result["cells"][self.current]
            self.sample.setText("Value: "+cell["value"]+"\n"+(cell["issue"] or "Region extracted successfully"))
        self.host.request({"operation":"preview","source":self.source,"page":self.page.value(),
                           "target":str(self.host.directory/f"region-{token}.png"),"raster":raster,
                           "scale":max(2,self.view.transform().m11()*self.devicePixelRatioF()/(72/25.4)),
                           "extraction":{"regions":self.regions,"version":1}},ready,preview=True)

    def accept(self):
        self.save_controls()
        try:
            ExtractionSpec.from_dict({"regions":self.regions,"version":1})
        except ValueError as exc:
            self.sample.setText(str(exc))
            return
        self.closed=True
        self.timer.stop()
        super().accept()

    def reject(self):
        self.closed=True
        self.timer.stop()
        super().reject()
