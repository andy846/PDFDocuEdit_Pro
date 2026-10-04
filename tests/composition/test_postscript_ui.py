"""Profile editing, paper test worker and production result discoverability."""
import copy
import json

import pytest
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QFileDialog, QTableWidgetItem

from composition.designer.media_dialog import MediaDialog
from composition.designer.workspace import CompositionWindow
from composition.engine.assets import asset_root
from styles.components import global_style
from styles.theme import apply_theme
from tests.composition.test_postscript import model, ps_media
from tests.composition.test_workspace import close_window, wait_until


@pytest.fixture(scope="module")
def app(qt_application):
    return qt_application


@pytest.mark.parametrize("mode",["attributes","tray"])
def test_ps_profile_json_roundtrip_and_switch_retains_in_dialog_mappings(app,tmp_path,monkeypatch,mode):
    media=ps_media(mode)
    template=model(media)
    dialog=MediaDialog(media,{"kind":"template","project":template.to_dict(),"records":2})
    try:
        dialog.show()
        assert dialog.output_format.currentData()=="postscript"
        assert dialog.read_printer()==media["printer_profile"]
        dialog.profile_name.setText("Second production room")
        dialog.tumble.setChecked(True)
        dialog.resolution.setCurrentIndex(dialog.resolution.findData(1200))
        column=5 if mode=="tray" else 3
        assert not dialog.mappings.isColumnHidden(column)
        dialog.mappings.setItem(0,column,QTableWidgetItem("11" if mode=="tray" else "Custom letterhead"))
        draft=copy.deepcopy(dialog.read_printer())
        target=tmp_path/"printer.json"
        monkeypatch.setattr(dialog,"profile_directory",lambda:tmp_path)
        monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *args:(str(target),""))
        dialog.save_profile(True)
        assert json.loads(target.read_text())["profile_version"]==2
        dialog.profile_name.setText("Changed")
        dialog.selection_mode.setCurrentIndex(dialog.selection_mode.findData("tray" if mode=="attributes" else "attributes"))
        monkeypatch.setattr(QFileDialog,"getOpenFileName",lambda *args:(str(target),""))
        dialog.load_profile(True)
        assert dialog.read_printer()==draft
        dialog.output_format.setCurrentIndex(dialog.output_format.findData("canon_prismasync"))
        assert dialog.read_printer()["profile_version"]==1
        dialog.output_format.setCurrentIndex(dialog.output_format.findData("postscript"))
        assert dialog.read_printer()==draft
        dialog.scan(1)
        wait_until(lambda:dialog.worker is None)
        assert dialog.checked==dialog.value()
        dialog.accept()
        assert dialog.options["printer_profile"]==draft
    finally:
        dialog.reject()


def test_switch_to_ps_requires_explicit_mapping_and_zero_tray_survives(app):
    from composition.media.model import default_media
    from composition.media.planner import build_print_plan
    from composition.template.model import CompositionError

    media=default_media()
    template=model(media)
    dialog=MediaDialog(media,{"kind":"template","project":template.to_dict(),"records":1})
    try:
        dialog.output_format.setCurrentIndex(dialog.output_format.findData("postscript"))
        assert dialog.family.currentData()=="generic"
        template.media=dialog.value()
        with pytest.raises(CompositionError,match="MediaType"):
            build_print_plan(template,1)
        dialog.selection_mode.setCurrentIndex(dialog.selection_mode.findData("tray"))
        for row in range(3):
            dialog.mappings.setItem(row,5,QTableWidgetItem(str(row)))
        assert dialog.read_printer()["mappings"]["LH_A"]["media_position"]==0
        template.media=dialog.value()
        assert build_print_plan(template,1).output_pages==3
    finally:
        dialog.reject()


def test_paper_test_runs_in_worker_and_leaves_project_draft_unchanged(app,tmp_path,monkeypatch):
    media=ps_media("tray",duplex=True)
    dialog=MediaDialog(media)
    try:
        dialog.show()
        target=tmp_path/"paper-proof.ps"
        monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *args:(str(target),""))
        before=dialog.value()
        dialog.proof_button.click()
        assert dialog.worker is not None and not dialog.proof_button.isEnabled()
        app.processEvents()
        assert dialog.isVisible()
        wait_until(lambda:dialog.worker is None,timeout=30)
        assert target.is_file(),dialog.error.text()
        assert "Paper test saved" in dialog.error.text()
        assert dialog.value()==before and dialog.options is None
    finally:
        dialog.reject()


@pytest.mark.parametrize("theme",["dark","light"])
def test_ps_profile_controls_and_mapping_fit_narrow_dialog(app,theme):
    palette,font,style=app.palette(),app.font(),app.styleSheet()
    font_id=QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    app.setFont(QFont("Noto Sans",9))
    apply_theme(app,theme)
    app.setStyleSheet(global_style())
    dialog=MediaDialog(ps_media())
    try:
        dialog.resize(960,640)
        dialog.show()
        dialog.tabs.setCurrentIndex(2)
        app.processEvents()
        assert dialog.width()<=960
        for button in dialog.profile_buttons:
            assert button.isVisible()
            assert button.mapTo(dialog,button.rect().bottomRight()).y()<dialog.height()
        scroll=dialog.tabs.widget(2)
        assert scroll.horizontalScrollBar().maximum()==0
        for control in (dialog.output_format,dialog.profile_name,dialog.selection_mode,dialog.resolution,dialog.mappings):
            scroll.ensureWidgetVisible(control,0,0)
            app.processEvents()
            assert control.mapTo(dialog,control.rect().topLeft()).x()>=0
            assert control.mapTo(dialog,control.rect().topRight()).x()<dialog.width()
        dialog.selection_mode.setCurrentIndex(dialog.selection_mode.findData("tray"))
        assert not dialog.mappings.isColumnHidden(5)
        assert dialog.mappings.isColumnHidden(3)
    finally:
        dialog.reject()
        app.setStyleSheet(style)
        app.setPalette(palette)
        app.setFont(font)
        QFontDatabase.removeApplicationFont(font_id)


def test_designer_result_shows_ps_and_no_jdf_instruction(app,tmp_path,monkeypatch):
    monkeypatch.setattr(CompositionWindow,"_load_windows_fonts",lambda self:None)
    monkeypatch.setattr(CompositionWindow,"_render_preview",lambda self:None)
    window=CompositionWindow()
    try:
        from composition.production.generator import generate
        from composition.production.model import ProductionJob
        result=generate(ProductionJob(model(ps_media(),1).to_dict(),"",str(tmp_path)))
        assert result.status=="completed",result.error
        window._production_ready(result.to_dict())
        text=window.production_summary.toPlainText()
        assert result.output_ps in text and "default_ticket.jdf" not in text
    finally:
        close_window(window)
