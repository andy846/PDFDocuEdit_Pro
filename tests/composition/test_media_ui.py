import copy
import json
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QTableWidgetItem

from composition.designer.media_dialog import MediaDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.project_host import DesignerProjectHost
from composition.media.model import default_media
from tests.composition.test_media import template
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_workspace import wait_until


@pytest.fixture(scope="module")
def app(qt_application):
    return qt_application


def test_media_dialog_batch_assign_roundtrip_profile_and_narrow_layout(app,tmp_path,monkeypatch):
    model=template()
    dialog=MediaDialog(model.media,{"kind":"template","project":model.to_dict(),"records":300})
    try:
        dialog.resize(860,540)
        dialog.show()
        QApplication.processEvents()
        assert dialog.width()<=960 and dialog.buttons.geometry().bottom()<dialog.height()
        dialog.tabs.setCurrentIndex(1)
        dialog.assignments.selectAll()
        dialog.batch_stock.setCurrentText("LH_A")
        dialog.assign_selected()
        assert set(dialog.value()["assignments"].values())=={"LH_A"}
        profile=tmp_path/"media.json"
        monkeypatch.setattr(dialog,"profile_directory",lambda:tmp_path)
        monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a:(str(profile),""))
        dialog.save_profile(False)
        saved=json.loads(profile.read_text())
        assert saved["profile_version"]==1 and "Customer" not in profile.read_text()
        dialog.assignments.setItem(0,1,QTableWidgetItem("LH_B"))
        monkeypatch.setattr(QFileDialog,"getOpenFileName",lambda *a:(str(profile),""))
        dialog.load_profile(False)
        assert dialog.value()["assignments"]["1"]=="LH_A"
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert dialog.checked==dialog.value() and dialog.preview_table.rowCount()==200
        assert "900" in dialog.summary.text()
        dialog.scan(201)
        wait_until(lambda:dialog.worker is None)
        assert dialog.preview_table.item(0,0).text()=="201"
        dialog.accept()
        assert dialog.result()==dialog.DialogCode.Accepted and not dialog.directory.exists()
    finally:
        dialog.reject()


def test_template_page_names_and_missing_stock_can_be_repaired(app):
    model=template()
    dialog=MediaDialog({}, {"kind":"template","project":model.to_dict(),"records":2})
    try:
        assert dialog.mode.currentData()=="template"
        assert "Page 1" in dialog.assignments.item(0,0).text()
        assert model.pages[0].id in dialog.value()["assignments"]
        dialog.assignments.setItem(1,1,QTableWidgetItem("LH_C"))
        dialog.duplex.setChecked(True)
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert not dialog.checked and "Media conflict" in dialog.error.text()
        dialog.duplex.setChecked(False)
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert dialog.checked and dialog.total==6
    finally:
        dialog.reject()


def test_overlay_invalid_media_stays_editable_and_blocks_generation(app,tmp_path):
    w=OverlayWindow()
    spec=sample_spec(tmp_path)
    spec.media=default_media()
    spec.media.update(duplex=True)
    try:
        w.show()
        w.apply_spec(spec.to_dict())
        wait_until(lambda:not w.font_token)
        assert w.media_error and "Media needs repair" in w.source_summary.text()
        assert not w.actions["generate"].isEnabled()
        assert w.actions["media"].isEnabled()
        repaired=copy.deepcopy(spec.to_dict())
        repaired["media"]["assignments"]={"1":"LH_A","2":"LH_A","3":"LH_A"}
        w.commit(repaired,"Repair media")
        assert not w.media_error and w.actions["generate"].isEnabled()
        w.undo.undo()
        assert w.media_error and not w.actions["generate"].isEnabled()
    finally:
        w.draft_error=""
        w.undo.setClean()
        w.close()
        wait_until(lambda:not w.workers)


def test_media_workflow_insertion_upgrades_once_and_undo(app):
    host=DesignerProjectHost()
    w=host.new_mail_merge_workflow()
    try:
        w.select_node(w.spec.node("template").id)
        w.insert_step("media_assignment")
        assert w.spec.workflow_version==4 and w.spec.node("media_assignment")
        assert any("Stock" in label.text() for label in w.inspector.findChildren(QLabel))
        w.undo.undo()
        assert not w.spec.node("media_assignment")
        w.undo.redo()
        assert w.spec.node("media_assignment")
    finally:
        w.undo.setClean()
        host.close_project(w)
        wait_until(lambda:not host.projects)
        host.close()


def test_duplicate_reorder_delete_keep_template_stock_identity(app):
    from composition.designer.workspace import CompositionWindow
    from composition.media.planner import build_print_plan
    from tests.composition.test_workspace import close_window
    w=CompositionWindow()
    model=template()
    model.media.update(mode="template",assignments={p.id:"LH_"+"ABC"[i] for i,p in enumerate(model.pages)})
    try:
        w._apply_template(model.to_dict())
        w.select_template_page(0)
        w.add_template_page(duplicate=True)
        copied=w.active_page_id
        assert w.template.media["assignments"][copied]=="LH_A"
        w.move_template_page(1)
        assert build_print_plan(w.template,1).page(1,3).stock=="LH_A"
        w.delete_template_page()
        assert copied not in w.template.media["assignments"]
        w.undo.undo()
        assert w.template.media["assignments"][copied]=="LH_A"
        dialog=MediaDialog(w.template.media,{"kind":"template","project":w.template.to_dict(),"records":2},w)
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        dialog.preview_table.setCurrentCell(1,0)
        dialog.locate_page()
        assert w.page_index==1
        assert dialog.options is None  # Navigation does not apply pending media settings.
        dialog.reject()
    finally:
        close_window(w)


@pytest.mark.parametrize("theme",["dark","light"])
def test_media_tabs_with_application_theme_at_960x640(app,theme):
    from PyQt6.QtGui import QFont, QFontDatabase

    from composition.engine.assets import asset_root
    from styles.components import global_style
    from styles.theme import apply_theme
    palette,style,font=app.palette(),app.styleSheet(),app.font()
    font_id=QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    app.setFont(QFont("Noto Sans",9))
    apply_theme(app,theme)
    app.setStyleSheet(global_style())
    model=template()
    dialog=MediaDialog(model.media,{"kind":"template","project":model.to_dict(),"records":1000})
    try:
        dialog.resize(960,640)
        dialog.show()
        app.processEvents()
        for index in range(4):
            dialog.tabs.setCurrentIndex(index)
            app.processEvents()
            assert dialog.width()==960
            assert dialog.buttons.geometry().bottom()<640
            assert dialog.tabs.currentWidget().viewport().height()>250
            target=os.environ.get("MEDIA_UI_ARTIFACT_DIR")
            if target:
                path=Path(target)
                path.mkdir(parents=True,exist_ok=True)
                dialog.grab().save(str(path/f"media-{theme}-{os.environ.get('QT_SCALE_FACTOR','1')}-tab{index}.png"))
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert dialog.checked and "3,000" in dialog.summary.text()
    finally:
        dialog.reject()
        app.setPalette(palette)
        app.setStyleSheet(style)
        app.setFont(font)
        QFontDatabase.removeApplicationFont(font_id)
