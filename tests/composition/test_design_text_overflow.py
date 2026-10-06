"""Oversized design labels must not blank the canvas or weaken production checks."""
import math
import os
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageChops
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest

from composition.designer.workspace import CompositionWindow
from composition.engine.assets import asset_root
from composition.engine.renderer import render_preview
from composition.template.geometry import element_bounds
from composition.template.model import MM_TO_PT, CompositionError, Element, Template
from composition.worker import dispatch
from styles.components import global_style
from tests.composition.test_workspace import close_window, wait_until

FIELD="Customer_Reference_Number_For_Print_Production"


@pytest.mark.parametrize("width,height",[(10,8),(.1,8),(15,.1)])
@pytest.mark.parametrize("angle",[0,45,90])
def test_design_overflow_clips_only_the_object_and_reports_it(tmp_path,width,height,angle):
    background=tmp_path/"background.pdf"
    with fitz.open() as pdf:
        page=pdf.new_page(width=210*MM_TO_PT,height=297*MM_TO_PT)
        page.insert_text((30,30),"STATIC LETTERHEAD")
        pdf.save(background)
    small=Element(value="{{"+FIELD+"}}",x_mm=60,y_mm=50,width_mm=width,height_mm=height,rotation_deg=angle)
    other=Element(value="Other object stays visible",y_mm=100,width_mm=100)
    model=Template(background=str(background),elements=[small,other])
    issues=[]
    raw=render_preview(model,{FIELD:"{{"+FIELD+"}}"},design=True,page_index=0,layout_details=issues)
    assert len(issues)==1 and issues[0]["object"]==small.id and issues[0]["fields"]==[FIELD]
    assert small.value=="{{"+FIELD+"}}"  # Only the raster is clipped, never the template.
    reference=render_preview(Template(background=str(background),elements=[other]),{},design=True,page_index=0)
    with fitz.open(stream=raw,filetype="pdf") as actual,fitz.open(stream=reference,filetype="pdf") as expected:
        assert "STATIC LETTERHEAD" in actual[0].get_text()
        assert "Other object stays visible" in actual[0].get_text()
        def raster(pdf):
            pix=pdf[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            return Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
        diff=ImageChops.difference(raster(actual),raster(expected))
        bounds=element_bounds(small)
        # Outside the rotated box, not a single pixel may change (including later objects).
        rectangle=(math.floor(bounds[0]*MM_TO_PT*2)-2,math.floor(bounds[1]*MM_TO_PT*2)-2,
                   math.ceil(bounds[2]*MM_TO_PT*2)+2,math.ceil(bounds[3]*MM_TO_PT*2)+2)
        diff.paste((0,0,0),rectangle)
        assert diff.getbbox() is None


def test_record_preview_remains_strict_but_short_data_can_fit_long_field_name():
    model=Template(elements=[Element(value="{{"+FIELD+"}}",width_mm=10,height_mm=8)])
    issues=[]
    render_preview(model,{FIELD:"{{"+FIELD+"}}"},design=True,layout_details=issues)
    assert issues
    issues=[]
    raw=render_preview(model,{FIELD:"A"},layout_details=issues)
    assert not issues
    with fitz.open(stream=raw,filetype="pdf") as pdf:
        assert "A" in pdf[0].get_text()
    with pytest.raises(CompositionError,match="overflows"):
        render_preview(model,{FIELD:"Customer reference "*10})
    model.elements[0].width_mm=.1
    with pytest.raises(CompositionError,match="narrower than a character"):
        render_preview(model,{FIELD:"A"})


def test_worker_returns_current_canvas_image_and_layout_issue(tmp_path):
    model=Template(elements=[Element(value="{{"+FIELD+"}}",width_mm=10,height_mm=8)])
    result=dispatch({"task":"preview","template":model.to_dict(),"design":True,
                     "target":str(tmp_path/"design.pdf"),"page":0})
    assert result["layout_issues"][0]["object"]==model.elements[0].id
    with Image.open(result["image"]) as image:
        assert image.width>500


def test_resize_merge_field_keeps_canvas_editable_and_recovers_with_undo(qt_application,monkeypatch):
    monkeypatch.setattr(CompositionWindow,"_load_windows_fonts",lambda self:None)
    font_id=QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    window=CompositionWindow()
    window.setFont(QFont("Noto Sans",9))
    window.setStyleSheet(global_style())
    ticks=[]
    timer=QTimer()
    timer.timeout.connect(lambda:ticks.append(True))
    timer.start(10)
    try:
        window.resize(960,640)
        window.show()
        window.add_field(FIELD,30,30)
        def settled():
            return window.canvas.preview_item is not None and window.preview_worker is None and not window.preview_timer.isActive()
        wait_until(settled)
        item=window.canvas.element_items[0]
        selected=item.element.id
        original_width=item.element.width_mm
        preview=window.canvas.preview_item
        window.canvas.set_zoom(1.5)
        window.canvas.ensureVisible(item)
        transform=window.canvas.transform()
        window._property_edit({"width_mm":10,"height_mm":8})
        assert window.canvas.preview_item is preview
        wait_until(lambda:settled() and bool(window.preview_layout_issues))
        assert window.canvas.preview_item is preview and window.canvas.element_items[0] is item
        assert window.canvas.selected_ids()==[selected] and window.canvas.transform()==transform
        assert item.layout_issue and FIELD in item.toolTip()
        assert ticks and "clipped" in window.preview_state.text()
        if target := os.environ.get("DESIGN_OVERFLOW_UI_ARTIFACT_DIR"):
            path=Path(target)
            path.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(path/"clipped-merge-field.png"))
        window.preview_review.click()
        assert window.canvas.selected_ids()==[selected] and not window.properties_scroll.isHidden()
        QTest.keyClick(window.canvas,Qt.Key.Key_Right)
        wait_until(settled)
        assert window.page.elements[0].x_mm==30.5
        window.undo.undo()  # Move
        window.undo.undo()  # Resize
        wait_until(lambda:settled() and not window.preview_layout_issues)
        assert window.page.elements[0].width_mm==original_width
        assert not item.layout_issue and window.canvas.preview_item is preview
        window.undo.redo()
        wait_until(lambda:settled() and bool(window.preview_layout_issues))
        assert window.canvas.preview_item is preview
        window._property_edit({"width_mm":80,"height_mm":15})
        wait_until(lambda:settled() and not window.preview_layout_issues)
        assert not item.layout_issue and window.preview_review.isHidden()
    finally:
        timer.stop()
        close_window(window)
        QFontDatabase.removeApplicationFont(font_id)
