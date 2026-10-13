from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QFileDialog, QMessageBox

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from core.settings import SettingsManager
from core.viewer import PDFViewer
from tests.composition.test_workspace import wait_until
from tests.test_workflow_core import configured, fixture_pdf
from workflow.model import WorkflowRun
from workflow.regions_ui import RegionEditor
from workflow.workspace import WorkflowWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def standalone(app):
    window=WorkflowWindow()
    window.show()
    QApplication.processEvents()
    yield window
    window._close_approved=True
    window.close()
    wait_until(lambda:not window.workers)
    QApplication.processEvents()


@pytest.fixture
def integrated(app,monkeypatch,tmp_path):
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION","1")
    monkeypatch.setattr("core.viewer.SettingsManager",lambda:SettingsManager(tmp_path/"settings.json"))
    monkeypatch.setattr(CompositionWindow,"_load_windows_fonts",lambda self:None)
    monkeypatch.setattr(CompositionWindow,"_render_preview",lambda self:None)
    monkeypatch.setattr(OverlayWindow,"load_fonts",lambda self:None)
    root=PDFViewer()
    root.resize(960,640)
    root.show()
    controller=root._mode_controller
    host=controller.ensure_host(create_default=False)
    controller.request_mode("designer")
    yield root,host
    for project in host.projects:
        project.undo.setClean()
        project.draft_error=""
    monkeypatch.setattr(root,"_confirm_discard_changes",lambda:True)
    monkeypatch.setattr(host,"confirm_all",lambda:True)
    root.close()
    wait_until(lambda:not root.isVisible(),timeout=30)
    root.deleteLater()
    QApplication.processEvents()


def test_canvas_connections_undo_and_positions_preserve_review(standalone):
    w=standalone
    original=w.spec.to_dict()
    w.run=WorkflowRun(accepted=True)
    first=w.spec.nodes[0]
    w.move_node(first.id,100,150)
    assert w.run.accepted
    assert w.undo.canUndo()
    w.undo.undo()
    assert w.spec.to_dict()==original
    # Invalid connections give a reason without corrupting the graph.
    w.connect_nodes(first.id,w.spec.node("output").id)
    assert w.spec.to_dict()==original
    assert "cannot connect" in w.feedback.text()
    w.remove_node(w.spec.node("overlay"))
    assert len(w.spec.chain())==5


def test_worker_review_production_and_portable_save(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"output").to_dict())
    heartbeat=[]
    from PyQt6.QtCore import QTimer
    timer=QTimer(w)
    timer.setInterval(10)
    timer.timeout.connect(lambda:heartbeat.append(True))
    timer.start()
    w.execute("review")
    wait_until(lambda:w.active_worker is None and w.run.database and w.results.rowCount()>0,timeout=30)
    assert w.run.groups==[[1,3],[4,6]]
    assert w.results.item(0,3).text()=="00001"
    assert heartbeat
    w.accept_review()
    wait_until(lambda:w.active_worker is None and w.run.accepted)
    w.execute("output")
    from tests.composition.review_helpers import confirm_review
    confirm_review(w)
    wait_until(lambda:w.active_worker is None and bool(w.run.output),timeout=30)
    assert w.run.output["status"]=="completed",w.run.error
    target=tmp_path/"saved.pdflow"
    w.save_project(path=str(target))
    wait_until(lambda:w.active_worker is None and target.exists(),timeout=30)
    assert w.undo.isClean()
    timer.stop()


def test_visual_region_edit_does_not_reload_background_and_undo(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"out")
    dialog=RegionEditor(w,str(source),spec.node("extract").params)
    dialog.show()
    wait_until(lambda:dialog.last_image is not None and not w.workers,timeout=30)
    image=dialog.last_image
    pixmaps=[item for item in dialog.view.scene().items() if hasattr(item,"pixmap")]
    assert pixmaps and pixmaps[0].pixmap().height()>1500
    dialog.region[0].setValue(21)
    dialog.save_controls()
    wait_until(lambda:not w.workers and not dialog.timer.isActive(),timeout=30)
    assert dialog.last_image==image
    assert dialog.undo.canUndo()
    dialog.undo.undo()
    assert dialog.regions[0]["x_mm"]==20
    dialog.reject()


def test_workspace_mode_and_duplicate_project_shortcut_routing(integrated,tmp_path,monkeypatch):
    root,host=integrated
    w=host.new_workflow()
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.undo.resetClean()
    target=tmp_path/"project.pdflow"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a,**k:(str(target),""))
    root.activateWindow()
    root.raise_()
    QTest.qWait(250)
    w.canvas.setFocus()
    QTest.keyClick(w,Qt.Key.Key_S,Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda:target.exists() and w.active_worker is None,timeout=30)
    assert host.open_project(target) is w
    assert len(host.projects)==1
    before=w.spec.to_dict()
    root._mode_controller.request_mode("pdf")
    QApplication.processEvents()
    root._mode_controller.request_mode("designer")
    QApplication.processEvents()
    assert host.current_project is w and w.spec.to_dict()==before
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k:QMessageBox.StandardButton.Cancel)
    w.move_node(w.spec.nodes[0].id,12,34)
    assert not host.close_project(w)
    assert w in host.projects
    w.undo.setClean()


@pytest.mark.parametrize("theme",["light","dark"])
def test_narrow_layout_graph_and_inspector_remain_visible(integrated,theme):
    root,host=integrated
    root._apply_theme(theme)
    w=host.new_workflow()
    QApplication.processEvents()
    assert w.canvas.width()>180
    assert w.inspector_scroll.width()>=200
    assert not w.toolbox.isVisible()
    assert w.actions["scan"].isEnabled()
    w.undo.setClean()


def test_cancel_and_mode_switch_keeps_worker_owned(integrated,tmp_path):
    root,host=integrated
    w=host.new_workflow()
    source=fixture_pdf(tmp_path/"source.pdf",300)
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.execute("review")
    worker=w.active_worker
    root._mode_controller.request_mode("pdf")
    QApplication.processEvents()
    assert w.active_worker is worker
    w.cancel_job()
    wait_until(lambda:not w.workers,timeout=30)
    assert not w.run.output
    root._mode_controller.request_mode("designer")
    assert host.current_project is w
    w.undo.setClean()


def test_real_canvas_drag_and_ports_keep_a_valid_graph(standalone):
    w=standalone
    w.canvas.fit()
    original=w.spec.nodes[0].x
    item=w.canvas.nodes[w.spec.nodes[0].id]
    start=w.canvas.mapFromScene(item.pos()+QPointF(60,22))
    QTest.mousePress(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(w.canvas.viewport(),start+QPoint(35,25),delay=20)
    QTest.mouseRelease(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=start+QPoint(35,25))
    assert w.spec.nodes[0].x!=original
    assert w.spec.chain()
    w.add_node("merge",900,0)
    w.canvas.fit()
    def port(kind,output):
        node=w.spec.node(kind)
        item=w.canvas.nodes[node.id]
        return w.canvas.mapFromScene(item.pos()+QPointF(174 if output else 0,38))
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=port("input",True))
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=port("merge",False))
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=port("merge",True))
    QTest.mouseClick(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=port("extract",False))
    assert [node.kind for node in w.spec.chain()][:3]==["input","merge","extract"]


def test_double_click_connection_removes_it_and_undo_restores_it(standalone):
    w = standalone
    w.canvas.fit()
    edge = w.canvas.edges[0]
    connection = [edge.a, edge.b]
    # Pick the middle of the curve, away from the node and its ports.
    point = w.canvas.mapFromScene(edge.path().pointAtPercent(.5))
    QTest.mouseDClick(w.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()
    assert connection not in w.spec.edges
    w.undo.undo()
    QApplication.processEvents()
    assert connection in w.spec.edges


def test_dragging_another_node_applies_pending_inspector_settings(standalone, tmp_path):
    from PyQt6.QtWidgets import QLineEdit

    w = standalone
    w.select_node(w.spec.node("output").id)
    folder = w.inspector.findChild(QLineEdit)
    folder.setText(str(tmp_path / "new-output"))
    assert w.draft_error
    w.canvas.fit()
    node = w.spec.node("group")
    item = w.canvas.nodes[node.id]
    start = w.canvas.mapFromScene(item.pos() + QPointF(70, 20))
    QTest.mousePress(w.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(w.canvas.viewport(), start + QPoint(35, 25), delay=20)
    QTest.mouseRelease(w.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(35, 25))
    QApplication.processEvents()
    assert w.spec.node("output").params["directory"] == str(tmp_path / "new-output")
    assert w.spec.node("group").x != node.x
    assert w.selected == node.id
    assert w.canvas.nodes[node.id].isSelected()


def test_click_fourth_node_after_editing_grouping(standalone):
    from PyQt6.QtWidgets import QSpinBox

    w = standalone
    w.canvas.fit()
    fourth = w.spec.nodes[3].id
    for count in range(2, 17):
        group = w.canvas.nodes[w.spec.node("group").id]
        point = w.canvas.mapFromScene(group.pos() + QPointF(70, 20))
        QTest.mouseClick(w.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
        w.inspector.findChild(QSpinBox).setValue(count)
        item = w.canvas.nodes[fourth]
        point = w.canvas.mapFromScene(item.pos() + QPointF(70, 20))
        QTest.mouseClick(w.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QApplication.processEvents()
        assert w.spec.node("group").params["pages"] == count
        assert w.selected == fourth
        assert w.canvas.nodes[fourth].isSelected()
    w.undo.undo()
    assert w.spec.node("group").params["pages"] == 15


def test_designer_overlay_preview_and_unsaved_generation_guard(integrated,tmp_path,monkeypatch):
    root,host=integrated
    w=host.new_workflow()
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    # Add the optional overlay to the reviewed linear workflow.
    w.add_node("overlay",200,200)
    w.connect_nodes(w.spec.node("review").id,w.spec.node("overlay").id)
    w.connect_nodes(w.spec.node("overlay").id,w.spec.node("output").id)
    w.execute("review")
    wait_until(lambda:not w.workers and bool(w.run.groups),timeout=30)
    path=tmp_path/"production-overlay.pdcx"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a,**k:(str(path),""))
    w.edit_overlay()
    wait_until(lambda:len(host.projects)==2 and host.current_project.spec is not None,timeout=30)
    project=host.current_project
    wait_until(lambda:not project.active_worker)
    assert "Envelope_Account_No" in [project.fields.item(i).text() for i in range(project.fields.count())]
    assert not project.actions["generate"].isEnabled()
    project.add_object("text",field="Envelope_Account_No",x=20,y=60)
    wait_until(lambda:project.preview_status.text()=="Preview ready",timeout=30)
    host.tabs.setCurrentWidget(w)
    w.execute("output")
    assert w.active_worker is None
    assert "Save or repair" in w.feedback.text()
    assert not w.run.output
    w.undo.setClean()
    project.undo.setClean()


def test_inspector_settings_survive_selection_and_save(standalone,tmp_path):
    from PyQt6.QtWidgets import QLineEdit, QSpinBox
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.select_node(w.spec.node("output").id)
    folder=w.inspector.findChild(QLineEdit)
    folder.setText(str(tmp_path/"new-output"))
    assert w.draft_error and "*" in w.windowTitle()
    w.select_node(w.spec.node("group").id)
    assert w.spec.node("output").params["directory"]==str(tmp_path/"new-output")
    method=w.inspector.findChildren(QComboBox)[0]
    method.setCurrentIndex(method.findData("fixed"))
    pages=w.inspector.findChild(QSpinBox)
    pages.setValue(3)
    target=tmp_path/"settings.pdflow"
    w.save_project(path=str(target))
    wait_until(lambda:not w.workers and target.exists(),timeout=30)
    from workflow.serializer import load_workflow
    assert load_workflow(target).node("group").params["pages"]==3
    assert not w.draft_error and w.undo.isClean()


def test_multiple_sources_insert_merge_and_compact_add_step(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"first.pdf")
    second=fixture_pdf(tmp_path/"second.pdf")
    w.remove_node(w.spec.node("overlay"))
    w.undo.clear()
    w.params(w.spec.node("input"),{"paths":[str(source),str(second)]})
    assert [n.kind for n in w.spec.chain()][:3]==["input","merge","extract"]
    w.undo.undo()
    assert not w.spec.node("merge") and not w.spec.node("input").params["paths"]
    w.resize(960,640)
    QApplication.processEvents()
    # Optional steps moved into the contextual canvas control to free toolbar space.
    assert w.next_step.isVisible()
    w.add_optional("overlay")
    assert [n.kind for n in w.spec.chain()][-2:]==["overlay","output"]
    w.canvas.pending=w.spec.node("input").id
    QTest.keyClick(w.canvas,Qt.Key.Key_Escape)
    assert w.canvas.pending is None


def test_review_correction_cannot_target_old_page_fields(standalone,tmp_path,monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.execute("review")
    wait_until(lambda:not w.workers and w.results.rowCount()>0,timeout=30)
    w.results.selectRow(0)
    w.page.blockSignals(True)
    w.page.setValue(4)
    w.page.blockSignals(False)
    def unexpected(*args,**kwargs):
        raise AssertionError("A correction dialog was offered for stale page data")
    monkeypatch.setattr(QInputDialog,"getMultiLineText",unexpected)
    w.correct()
    assert "finish loading" in w.feedback.text()
    w.review()
    wait_until(lambda:not w.workers and w.results.item(0,3).text()=="00002")
    w.results.selectRow(0)
    monkeypatch.setattr(QInputDialog,"getMultiLineText",lambda *a,**k:("00009",True))
    monkeypatch.setattr(QInputDialog,"getText",lambda *a,**k:("Verified page four",True))
    w.correct()
    wait_until(lambda:not w.workers and w.results.item(0,3).text()=="00009")
    from workflow.extraction import ExtractionStore
    with ExtractionStore(w.run.database) as store:
        assert store.values(1)["Account_No"]=="00001"
        assert store.values(4)["Account_No"]=="00009"


def test_failed_boundary_edit_keeps_last_successful_grouping(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.execute("review")
    wait_until(lambda:not w.workers and bool(w.run.groups),timeout=30)
    previous=w.run.groups.copy()
    w.change_groups([[1,2],[4,6]])
    assert w.run.groups==previous
    wait_until(lambda:not w.workers)
    assert w.run.groups==previous and w.groups_model.groups==previous
    assert "cover" in w.feedback.text()


def test_region_editor_small_pdf_and_invalid_draft_remain_visible(standalone,tmp_path):
    import fitz

    from composition.template.model import MM_TO_PT
    w=standalone
    source=tmp_path/"small.pdf"
    with fitz.open() as pdf:
        page=pdf.new_page(width=60*MM_TO_PT,height=40*MM_TO_PT)
        page.insert_text((10,30),"Small PDF")
        pdf.save(source)
    dialog=RegionEditor(w,str(source),{})
    dialog.show()
    wait_until(lambda:dialog.last_image is not None and not w.workers and not dialog.timer.isActive(),timeout=30)
    assert dialog.regions[0]["page_width_mm"]==pytest.approx(60)
    assert dialog.regions[0]["x_mm"]+dialog.regions[0]["width_mm"]<=60.01
    image=dialog.last_image
    dialog.name.setText("invalid name")
    dialog.save_controls()
    dialog.zoom(1.2)
    wait_until(lambda:not w.workers and not dialog.timer.isActive(),timeout=30)
    assert dialog.last_image and dialog.last_image!=image
    assert dialog.view.scene().items() and "name" in dialog.sample.text().lower()
    dialog.name.setText("Repaired_Field")
    dialog.save_controls()
    dialog.use_page_size()
    dialog.accept()
    assert dialog.result()==dialog.DialogCode.Accepted


def test_undo_buttons_do_not_enable_empty_history(standalone):
    w=standalone
    w.lock()
    assert not w.actions["undo"].isEnabled() and not w.actions["redo"].isEnabled()
    w.move_node(w.spec.node("input").id,42,43)
    assert w.actions["undo"].isEnabled() and not w.actions["redo"].isEnabled()
    w.undo.undo()
    w.lock()
    assert not w.actions["undo"].isEnabled() and w.actions["redo"].isEnabled()


def test_merge_page_drafts_follow_the_selected_source(standalone,tmp_path):
    from PyQt6.QtWidgets import QLineEdit
    w=standalone
    first=fixture_pdf(tmp_path/"first.pdf")
    second=fixture_pdf(tmp_path/"second.pdf")
    w.params(w.spec.node("input"),{"paths":[str(first),str(second)]})
    w.select_node(w.spec.node("merge").id)
    pages=w.inspector.findChild(QLineEdit)
    pages.setText("1,3")
    combo=w.inspector.findChild(QComboBox)
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert w.spec.node("merge").params["pages"][str(first)]=="1,3"
    assert w.inspector.findChild(QComboBox).currentText()==str(second)
    w.inspector.findChild(QLineEdit).setText("Even")
    w.select_node(w.spec.node("input").id)
    assert w.spec.node("merge").params["pages"][str(second)]=="Even"


def test_reopening_workflow_overlay_syncs_grouping_without_losing_design(integrated,tmp_path,monkeypatch):
    root,host=integrated
    w=host.new_workflow()
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.add_optional("overlay")
    w.execute("review")
    wait_until(lambda:not w.workers and bool(w.run.groups),timeout=30)
    path=tmp_path/"overlay.pdcx"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *a,**k:(str(path),""))
    w.edit_overlay()
    wait_until(lambda:len(host.projects)==2 and host.current_project.spec is not None,timeout=30)
    project=host.current_project
    wait_until(lambda:not project.active_worker)
    project.add_object("text",field="Envelope_Account_No",x=20,y=60)
    original=project.spec.to_dict()["objects"]
    # Current project content is retained even when the synchronisation changes grouping.
    host.tabs.setCurrentWidget(w)
    w.change_groups([[1,2],[3,3],[4,6]])
    wait_until(lambda:not w.workers and len(w.run.groups)==3)
    w.edit_overlay()
    wait_until(lambda:not w.workers and project.spec.settings.groups==w.run.groups,timeout=30)
    assert project.spec.to_dict()["objects"]==original
    assert project.workflow_database==w.run.database and not project.undo.isClean()
    wait_until(lambda:project.preview_status.text()=="Preview ready",timeout=30)
    w.undo.setClean()
    project.undo.setClean()


def test_region_sidebar_controls_are_reachable_in_a_short_window(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    dialog=RegionEditor(w,str(source),configured(source,tmp_path/"out").node("extract").params)
    dialog.resize(960,640)
    dialog.show()
    wait_until(lambda:dialog.last_image is not None and not w.workers,timeout=30)
    assert dialog.name.width()>=150
    for control in (dialog.region[3],dialog.maximum,dialog.join):
        dialog.inspector.ensureWidgetVisible(control)
        QApplication.processEvents()
        point=control.mapTo(dialog.inspector.viewport(),control.rect().center())
        assert dialog.inspector.viewport().rect().contains(point)
    dialog.reject()


def test_review_navigation_keeps_current_envelope_selected(standalone,tmp_path):
    w=standalone
    source=fixture_pdf(tmp_path/"source.pdf")
    w.apply_spec(configured(source,tmp_path/"out").to_dict())
    w.execute("review")
    wait_until(lambda:not w.workers and w.results.rowCount()>0,timeout=30)
    w.page.setValue(4)
    wait_until(lambda:not w.workers and w.results.item(0,3).text()=="00002")
    assert w.group_table.currentIndex().row()==1
    w.merge_previous()
    wait_until(lambda:not w.workers and w.run.groups==[[1,6]])
    assert w.group_table.currentIndex().row()==0
