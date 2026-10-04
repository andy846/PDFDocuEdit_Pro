from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from composition.designer.project_host import DesignerProjectHost
from tests.composition.test_workspace import wait_until
from tests.test_mail_merge_workflow import pair, recipe
from workflow.mail_merge_ui import MailMergeWorkflowWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w=MailMergeWorkflowWindow()
    w.show()
    QApplication.processEvents()
    yield w
    w._close_approved=True
    w.close()
    wait_until(lambda:not w.workers)
    QApplication.processEvents()


def test_check_preview_approve_generate_save_reopen(window,tmp_path,monkeypatch):
    w=window
    job=pair(tmp_path)
    spec=recipe([job])
    spec.node("reports").params={"directory":str(tmp_path/"output")}
    w.apply_spec(spec.to_dict())
    w.batch.jobs=[job]
    w.refresh_jobs()
    w.check_jobs()
    wait_until(lambda:w.active_worker is None,timeout=30)
    assert w.batch.jobs[0].status=="Needs review",w.feedback.text()
    w.jobs_table.selectRow(0)
    w.preview_record.setValue(2)
    w.preview_page.setValue(2)
    w.preview_job()
    wait_until(lambda:not w.workers,timeout=30)
    assert w.preview_image.pixmap() is not None and not w.preview_image.pixmap().isNull(),w.feedback.text()
    w.preview_record.setValue(1)
    wait_until(lambda:not w.preview_timer.isActive() and not w.workers,timeout=30)
    assert "Record 1" in w.feedback.text()
    w.approve_selected()
    assert w.batch.jobs[0].status=="Ready"
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:QMessageBox.StandardButton.Yes)
    w.execute("output")
    wait_until(lambda:w.active_worker is None,timeout=30)
    assert w.batch.status=="Completed",w.feedback.text()
    assert Path(w.batch.jobs[0].result["output_pdf"]).is_file()
    target=tmp_path/"production.pdflow"
    w.save_project(path=str(target))
    wait_until(lambda:w.active_worker is None,timeout=30)
    assert target.is_file() and target.with_suffix(".batch.json").is_file(),w.feedback.text()
    assert not w.batch_dirty
    w.load_path(target)
    wait_until(lambda:w.active_worker is None,timeout=30)
    assert w.batch.jobs[0].status=="Completed"
    assert not w.batch.jobs[0].approved


def test_canvas_cards_survive_changes_navigation_and_checkbox_drafts(window):
    w=window
    node=w.spec.node("compose")
    original=w.canvas.nodes[node.id]
    w.select_node(node.id)
    from PyQt6.QtWidgets import QCheckBox
    check=w.inspector.findChild(QCheckBox)
    check.setChecked(False)
    assert w.flush_settings()
    assert w.spec.node("compose").params["auto_repair"] is False
    assert w.canvas.nodes[node.id] is original
    w.canvas.zoom(.8)
    zoom=w.canvas.transform().m11()
    for _ in range(10):
        for step in w.spec.nodes:
            w.select_node(step.id)
            QApplication.processEvents()
    assert w.canvas.transform().m11()==zoom
    w.canvas.setFocus()
    QTest.keyClick(w.canvas,Qt.Key.Key_Right)
    assert w.canvas.scene().selectedItems()


def test_narrow_layout_filters_and_pair_dedup_in_host(app,tmp_path,monkeypatch):
    from workflow.serializer import save_workflow
    host=DesignerProjectHost()
    host.resize(960,640)
    host.show()
    path=save_workflow(recipe([]),tmp_path/"mail.pdflow")
    w=host.open_project(path)
    wait_until(lambda:w.active_worker is None,timeout=30)
    assert isinstance(w,MailMergeWorkflowWindow)
    assert host.open_project(path) is w
    assert [w.tabs.tabText(i) for i in range(3)]==["Build","Review","Run"]
    assert w.canvas.width()>180
    assert not w.library.isVisible()
    assert w.inspector_scroll.isVisible()
    jobs=[pair(tmp_path,"GS"),pair(tmp_path,"IS")]
    jobs[0].status="Blocked"
    w.batch.jobs=jobs
    w.changed_jobs()
    w.job_filter.setCurrentIndex(1)
    assert w.proxy.rowCount()==1
    assert w.jobs_model.rowCount()==2
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:QMessageBox.StandardButton.Cancel)
    assert not host.close_project(w)
    assert w.batch_dirty
    w._close_approved=True
    w.close()
    wait_until(lambda:not host.projects)
    host.close()


def test_port_rejection_preserves_connection_and_next_step_is_compatible(window):
    w=window
    w.canvas.fit()
    def point(kind,output):
        item=w.canvas.nodes[w.spec.node(kind).id]
        return w.canvas.mapFromScene(item.pos()+QPointF(174 if output else 0,38))
    original=w.spec.edges[:]
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=point("data",True))
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=point("compose",False))
    assert w.spec.edges==original
    assert "cannot connect" in w.feedback.text()
    w.select_node(w.spec.node("data").id)
    from workflow.chrome import populate_next
    populate_next(w)
    choices=[a.text() for a in w.next_menu.actions()]
    assert "Connect to Field Mapping" in choices
    assert "Insert Clean Fields" in choices
    assert "Connect to Compose" not in choices


@pytest.mark.parametrize("theme",["light","dark"])
def test_theme_narrow_panels_and_footer_are_inside_workspace(window,theme):
    from styles.theme import apply_theme
    apply_theme(QApplication.instance(),theme)
    w=window
    w.resize(960,640)
    QApplication.processEvents()
    assert w.width()==960
    assert w.canvas.width()>=400
    assert 210<=w.inspector_scroll.width()<=300
    for index in range(3):
        w.tabs.setCurrentIndex(index)
        QApplication.processEvents()
        assert w.tabs.geometry().bottom()<=w.centralWidget().height()
    w.tabs.setCurrentIndex(0)
    w.settings_toggle.click()
    assert not w.inspector_scroll.isVisible()
    w.settings_toggle.click()
    assert w.inspector_scroll.isVisible()
    w.library_toggle.click()
    assert w.library.isVisible()
    w.library_search.setText("Compose")
    assert sum(not w.toolbox.item(i).isHidden() for i in range(w.toolbox.count()))==1


def test_designer_project_creates_paired_workflow_and_dirty_template_blocks_run(app,tmp_path,monkeypatch):
    from composition.designer.workspace import CompositionWindow
    from composition.template.serializer import load_project
    monkeypatch.setattr(CompositionWindow,"_load_windows_fonts",lambda self:None)
    monkeypatch.setattr(CompositionWindow,"_render_preview",lambda self:None)
    host=DesignerProjectHost()
    host.show()
    job=pair(tmp_path)
    project=host.new_template()
    project._apply_template(load_project(job.template_path).to_dict())
    project.project_path=Path(job.template_path)
    project.undo.setClean()
    w=host.workflow_from_project(project)
    assert w is host.current_project
    assert w.batch.jobs[0].template_path==job.template_path
    project.undo.resetClean()
    assert not w.templates_saved()
    assert "Save the open letter template" in w.feedback.text()
    for tab in host.projects[:]:
        tab._close_approved=True
        tab.close()
    wait_until(lambda:not host.projects)
    host.close()
