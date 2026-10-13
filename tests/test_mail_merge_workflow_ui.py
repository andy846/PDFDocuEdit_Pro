from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton

from composition.designer.project_host import DesignerProjectHost
from tests.composition.test_workspace import wait_until
from tests.test_mail_merge_workflow import pair, recipe
from workflow.mail_merge_ui import MailMergeWorkflowWindow


@pytest.fixture(scope="module")
def app(qt_application):
    return qt_application


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
    from tests.composition.review_helpers import confirm_review
    confirm_review(w)
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


def test_first_output_folder_preserves_data_approval_but_requires_production_review(window,tmp_path,monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    from workflow.batch import BatchRun, approve, prepare
    w = window
    job = pair(tmp_path, "Folder")
    spec = recipe([job])
    w.apply_spec(spec.to_dict())
    w.batch = prepare(spec, BatchRun(jobs=[job]), w.directory)
    approve(w.batch, [job.id])
    w.refresh_jobs()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path / "out"))
    w.execute("output")
    wait_until(lambda: bool(w.production_review.contexts) and len(w.production_review.results) == 1 and not w.active_worker)
    assert w.batch.jobs[0].approved and w.batch.jobs[0].status == "Ready"
    assert w.production_review.results[0]["status"] == "checked"
    assert not (tmp_path / "out").exists()


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


def template_opener(window,monkeypatch):
    from types import SimpleNamespace

    opened=[]
    monkeypatch.setattr(window,"project_host",SimpleNamespace(open_project=opened.append,projects=[]))
    return opened


def test_edit_template_button_opens_only_job_without_review_selection(window,tmp_path,monkeypatch):
    job=pair(tmp_path)
    window.batch.jobs=[job]
    window.refresh_jobs()
    assert not window.selected_jobs()
    opened=template_opener(window,monkeypatch)
    window.select_node(window.spec.node("template").id)
    button=next(b for b in window.inspector.findChildren(QPushButton) if b.text()=="Edit in Template Designer…")
    button.click()
    assert opened==[job.template_path]
    assert window.batch.jobs==[job]


def test_edit_template_uses_selected_job_in_multiple_job_batch(window,tmp_path,monkeypatch):
    jobs=[pair(tmp_path,"GS"),pair(tmp_path,"IS")]
    window.batch.jobs=jobs
    window.refresh_jobs()
    window.jobs_table.selectRow(1)
    opened=template_opener(window,monkeypatch)
    monkeypatch.setattr(QInputDialog,"getItem",lambda *args:pytest.fail("A single selected job needs no picker"))
    window.edit_template()
    assert opened==[jobs[1].template_path]


def test_edit_template_picker_is_unambiguous_and_cancel_preserves_workflow(window,tmp_path,monkeypatch):
    jobs=[pair(tmp_path,"GS"),pair(tmp_path,"IS")]
    # Different jobs may have the same display name and template filename.
    for job in jobs:
        job.name="Letter"
        job.template_path="same.pdcx"
    window.batch.jobs=jobs
    window.refresh_jobs()
    window.jobs_table.clearSelection()
    opened=template_opener(window,monkeypatch)
    snapshot=window.spec.to_dict()
    selection=window.canvas.scene().selectedItems()
    def cancel(*args):
        assert len(set(args[3]))==2
        assert args[5] is False
        return "",False
    monkeypatch.setattr(QInputDialog,"getItem",cancel)
    window.edit_template()
    assert not opened and window.spec.to_dict()==snapshot
    assert window.canvas.scene().selectedItems()==selection
    jobs[1].template_path="chosen.pdcx"
    monkeypatch.setattr(QInputDialog,"getItem",lambda *args:(args[3][1],True))
    window.edit_template()
    assert opened==["chosen.pdcx"]


@pytest.mark.parametrize("has_job",[False,True])
def test_edit_template_missing_input_routes_to_review(window,monkeypatch,has_job):
    from workflow.batch import BatchJob

    window.batch.jobs=[BatchJob(name="Unassigned")] if has_job else []
    window.refresh_jobs()
    opened=template_opener(window,monkeypatch)
    window.tabs.setCurrentWidget(window.flow_page)
    window.edit_template()
    assert not opened and window.tabs.currentWidget() is window.review_page
    assert "Edit Job" in window.feedback.text() if has_job else "Add a template + data pair" in window.feedback.text()


def test_edit_template_in_host_focuses_existing_template_and_preserves_draft(app,tmp_path,monkeypatch):
    from composition.designer.workspace import CompositionWindow

    monkeypatch.setattr(CompositionWindow,"_load_windows_fonts",lambda self:None)
    monkeypatch.setattr(CompositionWindow,"_render_preview",lambda self:None)
    host=DesignerProjectHost()
    host.show()
    try:
        job=pair(tmp_path)
        project=host.open_project(job.template_path)
        project.add_element("text","Keep this unsaved edit")
        snapshot=project.template.to_dict()
        undo_index=project.undo.index()
        workflow=host.new_mail_merge_workflow()
        workflow.batch.jobs=[job]
        workflow.refresh_jobs()
        assert not workflow.selected_jobs()
        assert workflow.edit_template() is project
        assert host.current_project is project and len(host.projects)==2
        assert project.template.to_dict()==snapshot and project.undo.index()==undo_index
        assert not project.undo.isClean()
    finally:
        for tab in host.projects[:]:
            tab._close_approved=True
            tab.close()
        wait_until(lambda:not host.projects)
        host.close()
