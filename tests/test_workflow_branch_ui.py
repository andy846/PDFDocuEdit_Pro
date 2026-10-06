"""Focused v5 Qt workspace and real subprocess integration checks."""
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QLineEdit

from tests.composition.test_workspace import wait_until
from tests.test_workflow_branch_engine import fixture
from workflow.branch_ui import BranchWorkflowWindow, RouteDialog


@pytest.fixture
def window(qt_application,monkeypatch):
    w=BranchWorkflowWindow()
    errors=[]
    monkeypatch.setattr(w,"error",lambda text:errors.append(str(text)))
    w.test_errors=errors
    w.show()
    yield w
    w._close_approved=True
    w.close()
    wait_until(lambda:not w.workers)


def test_drafts_retained_invalid_then_undo_and_layout(window):
    from workflow.node_settings import StepDialog
    seq=window.spec.node("batch_sequence")
    window.select_node(seq.id)
    editor=window.settings_scroll.widget().findChild(StepDialog)
    editor.controls["start"].setText("bad")
    window.select_node(window.spec.node("route").id)
    assert not window.flush_settings()
    window.select_node(seq.id)
    assert window.settings_scroll.widget().findChild(StepDialog) is editor
    assert editor.controls["start"].text()=="bad"
    editor.controls["start"].setText("42")
    assert window.flush_settings()
    assert window.spec.node("batch_sequence").params["start"]==42
    window.undo.undo()
    assert window.spec.node("batch_sequence").params["start"]==1
    window.resize(960,640)
    wait_until(lambda:window.compact.isVisible())
    assert window.compact.count()==3
    window.compact.setCurrentWidget(window.details)
    assert window.apply_button.isVisible()
    window.resize(1280,800)
    wait_until(lambda:not window.compact.isVisible())
    assert window.splitter.count()==3


def test_route_dialog_named_ports_remove_and_incremental_canvas(window,tmp_path):
    model=fixture(tmp_path)
    window.apply_spec(model.to_dict())
    route=window.spec.node("route")
    item=window.canvas.nodes[route.id]
    assert [p[1] for p in item.ports()]==["A","B","Exceptions"]
    window.refresh_graph()
    assert window.canvas.nodes[route.id] is item
    dialog=RouteDialog(route.params["routes"][0],["Scheme"],window)
    dialog.accept()
    assert dialog.options["condition"]["conditions"][0]["field"]=="Scheme"
    window.remove_route(route.params["routes"][1]["id"])
    assert len(window.spec.execution_plan().branches)==1
    window.undo.undo()
    assert len(window.spec.execution_plan().branches)==2
    assert len(window.canvas.edges)==len(window.spec.edges)


def test_actual_check_pages_approval_preview_and_save_reopen(window,tmp_path):
    window.apply_spec(fixture(tmp_path,records=60).to_dict())
    window.check_all()
    wait_until(lambda:not window.active_worker,timeout=60)
    assert not window.test_errors,window.test_errors
    assert window.run["routed"]==180
    assert all(j["status"]=="Needs review" for j in window.run["jobs"])
    assert not any(j["approved"] for j in window.run["jobs"])
    window.select_node(window.spec.node("route").id)
    window.details.setCurrentWidget(window.output_page)
    wait_until(lambda:not window.workers,timeout=40)
    controls=window.output_page.controls
    assert controls["model"].rowCount()==50
    window.page_results(50)
    wait_until(lambda:not window.workers,timeout=40)
    assert controls["model"].records[0]["source_record"]==51
    window.approve(True)
    wait_until(lambda:not window.workers,timeout=40)
    assert all(j["approved"] for j in window.run["jobs"])
    path=tmp_path/"recipe.pdflow"
    window.save_project(path=str(path))
    wait_until(lambda:not window.workers,timeout=40)
    assert path.is_file() and window.undo.isClean()
    window.load_path(path)
    wait_until(lambda:not window.workers,timeout=40)
    assert window.spec.workflow_version==5 and not window.run.get("jobs")
    assert all(Path(n.params["path"]).is_file() for n in window.spec.nodes if n.kind=="template")


def test_template_draft_survives_switch_and_busy_browsing(window,tmp_path):
    from types import SimpleNamespace
    window.apply_spec(fixture(tmp_path).to_dict())
    template=window.spec.node("template")
    window.select_node(template.id)
    edit=window.settings_scroll.widget().findChild(QLineEdit)
    edit.setText("new-template.pdcx")
    window.select_node(window.spec.node("route").id)
    window.select_node(template.id)
    assert window.settings_scroll.widget().findChild(QLineEdit) is edit
    assert edit.text()=="new-template.pdcx"
    window.active_worker=SimpleNamespace()
    window.lock()
    try:
        assert window.canvas.isEnabled() and not window.canvas.editable
        window.canvas.nodes[window.spec.node("route").id].setSelected(True)
        window.canvas.zoom(1.1)
        assert not window.settings_scroll.isEnabled()
        assert window.canvas.nodes[template.id].flags() & window.canvas.nodes[template.id].GraphicsItemFlag.ItemIsSelectable
    finally:
        window.active_worker=None
        window.lock()


def test_host_embeds_v5_reopens_without_duplicate_tabs(qt_application,tmp_path):
    from composition.designer.project_host import DesignerProjectHost
    from workflow.serializer import save_workflow
    host=DesignerProjectHost()
    host.resize(960,640)
    host.show()
    path=save_workflow(fixture(tmp_path),tmp_path/"conditional.pdflow")
    project=host.open_project(path)
    try:
        assert isinstance(project,BranchWorkflowWindow)
        wait_until(lambda:not project.workers,timeout=40)
        assert host.current_project is project and not project.menuBar().isVisible()
        assert host.open_project(path) is project and len(host.projects)==1
        project.undo.setClean()
        host.close_project(project)
        wait_until(lambda:not host.projects)
        assert host.stack.currentWidget() is host.start
    finally:
        for project in host.projects[:]:
            project._close_approved=True
            project.close()
            wait_until(lambda p=project:not p.workers)
        host.close()


def test_unsaved_open_designer_template_blocks_check_and_production(window,tmp_path):
    from types import SimpleNamespace

    from PyQt6.QtGui import QUndoStack
    window.apply_spec(fixture(tmp_path).to_dict())
    dirty=QUndoStack(window)
    dirty.resetClean()
    project=SimpleNamespace(project_path=Path(window.spec.node("template").params["path"]),
                            undo=dirty,properties=SimpleNamespace(apply=lambda:True))
    window.project_host=SimpleNamespace(projects=[project],identity=lambda path:str(Path(path).resolve()).casefold(),
                                       is_busy=lambda project:False)
    assert not window.templates_saved()
    window.check_all()
    assert not window.active_worker and "Save the open letter template" in window.statusBar().currentMessage()
    dirty.setClean()
    assert window.templates_saved()
    window.project_host=None
