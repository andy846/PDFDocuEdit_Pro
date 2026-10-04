import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QPushButton

from composition.designer import recents
from composition.designer.home import RecentProbe
from composition.designer.project_host import DesignerProjectHost
from tests.composition.test_workspace import wait_until
from workflow.model import WorkflowSpec
from workflow.node_settings import StepDialog
from workflow.registry import EXTRA_KINDS, default_options


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def host(app,monkeypatch,tmp_path):
    settings=QSettings(str(tmp_path/"recent.ini"),QSettings.Format.IniFormat)
    monkeypatch.setattr(recents,"QSettings",lambda:settings)
    monkeypatch.setattr(RecentProbe,"start",lambda *args:None)
    host=DesignerProjectHost()
    host.resize(960,640)
    host.show()
    QApplication.processEvents()
    yield host
    host.shutdown()
    wait_until(lambda:not host.projects)
    host.close()
    host.deleteLater()
    QApplication.processEvents()


def test_home_cards_narrow_and_recent_cache_merges_without_filesystem_queries(host,monkeypatch):
    settings=recents.QSettings()
    settings.setValue("recent_projects",["C:/missing/old.pdcx"])
    settings.setValue("designer/recent_projects_v1",json.dumps([{"path":"C:/missing/run.pdflow","kind":"Workflow"}]))
    original_stat=Path.stat
    def forbidden(path,*args,**kwargs):
        if "missing" in str(path):
            raise AssertionError("Cached recent listing must not stat paths")
        return original_stat(path,*args,**kwargs)
    with monkeypatch.context() as cached:
        cached.setattr("pathlib.Path.stat",forbidden)
        assert len(recents.entries())==2
    host.start.refresh()
    assert host.start.recent.count()==2
    assert [host.start.grid.getItemPosition(i)[:2] for i in range(3)]==[(0,0),(1,0),(2,0)]
    names=[button.text() for button in host.start.findChildren(QPushButton)]
    assert "Create Letter Template" in names and "Create PDF Overlay" in names and "Create Visual Workflow" in names
    recents.remove("C:/missing/old.pdcx")
    assert len(recents.entries())==1


def test_repeatable_steps_insert_duplicate_reorder_undo_and_last_tab_home(host):
    w=host.new_mail_merge_workflow()
    assert w.spec.workflow_version==3
    w.select_node(w.spec.node("template").id)
    w.insert_step("clean_fields")
    first=w.spec.node("clean_fields")
    w.duplicate_node(first)
    assert len([n for n in w.spec.nodes if n.kind=="clean_fields"])==2
    last=w.spec.chain()[4]
    w.reorder_node(last,-1)
    assert w.spec.chain()[3].id==last.id
    w.undo.undo()
    assert w.spec.chain()[3].id==first.id
    w.remove_node(first)
    assert len(w.spec.chain())==8
    w.undo.undo()
    assert len(w.spec.chain())==9
    w.undo.setClean()
    host.close_project(w)
    wait_until(lambda:not host.projects)
    assert host.stack.currentWidget() is host.start


@pytest.mark.parametrize("kind",EXTRA_KINDS)
def test_human_readable_step_dialog_roundtrips_settings(host,kind):
    from workflow.model import WorkflowNode
    node=WorkflowNode(kind,params=default_options(kind))
    dialog=StepDialog(node,["Name","Account_No"],host)
    dialog.show()
    QApplication.processEvents()
    options=dialog.value()
    from workflow.registry import REGISTRY
    REGISTRY[kind].validate_options(options)
    assert dialog.width()<=960
    dialog.accept()
    assert dialog.result()==dialog.DialogCode.Accepted
    dialog.deleteLater()


def test_legacy_upgrade_saves_copy_without_changing_original(host,tmp_path,monkeypatch):
    from workflow.serializer import save_workflow
    original=tmp_path/"legacy.pdflow"
    save_workflow(WorkflowSpec.mail_merge(),original)
    old=original.read_bytes()
    w=host.new_mail_merge_workflow()
    w.apply_spec(WorkflowSpec.mail_merge().to_dict())
    w.project_path=original
    copy=tmp_path/"new-v3.pdflow"
    monkeypatch.setattr(QFileDialog,"getSaveFileName",lambda *args:(str(copy),""))
    w.ensure_v3(lambda:w.insert_step("clean_fields",after_id=w.spec.node("template").id))
    wait_until(lambda:not w.active_worker,timeout=30)
    assert original.read_bytes()==old
    assert w.spec.workflow_version==3
    assert copy.exists() and w.project_path==copy
    assert w.spec.node("clean_fields") is not None
    w.undo.setClean()


def test_open_split_output_selects_requested_file_and_respects_cancel(host,monkeypatch):
    w=host.new_mail_merge_workflow()
    result={"output_pdf":"first.pdf","output_files":[{"output_pdf":"first.pdf","records":2,"pages":4},
            {"output_pdf":"second.pdf","records":1,"pages":2}]}
    monkeypatch.setattr(QInputDialog,"getItem",lambda parent,title,label,items,*args:(items[1],True))
    assert w.choose_output_path(result)=="second.pdf"
    monkeypatch.setattr(QInputDialog,"getItem",lambda *args:("",False))
    assert w.choose_output_path(result)==""
