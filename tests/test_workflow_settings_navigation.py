from types import SimpleNamespace

from tests.test_mail_merge_workflow import pair, recipe
from workflow.batch import BatchRun, prepare


def test_issue_route_uses_effective_media_source():
    from workflow.settings_navigation import issue_target
    spec=SimpleNamespace(node=lambda _:None)
    binding={"files":["letter.pdcx"],"data_summary":{"media_source":"workflow","media_node_id":"media-B"}}
    context={"kind":"template","identity":"job-A","binding":binding}
    assert issue_target(spec,context,{"action":"media"})==("node","media-B")
    binding["data_summary"]["media_source"]="project"
    assert issue_target(spec,context,{"action":"media"})==("project","letter.pdcx")
    assert issue_target(spec,context,{"action":"object","object_id":"text-A"})==("project","letter.pdcx")
    assert issue_target(spec,context,{"action":"data","field":"Name"})==("data","job-A")


def test_changed_source_invalidates_only_unfinished_job(tmp_path):
    from workflow.source_state import changed_files, invalidate_batch, observe_files
    first=pair(tmp_path,"First")
    second=pair(tmp_path,"Second")
    batch=prepare(recipe([first,second]),BatchRun(jobs=[first,second]),tmp_path/"work")
    before=observe_files([first.data_path,second.data_path])
    first.approved=True
    second.status="Completed"
    second.approved=True
    from pathlib import Path
    Path(first.data_path).write_text("Customer\nChanged customer\n",encoding="utf-8")
    changes=changed_files(before)
    assert changes==[first.data_path]
    assert invalidate_batch(batch,changes)==[first.id]
    assert first.status=="Needs review" and not first.approved
    assert first.data_summary["stale"]
    assert second.status=="Completed" and second.approved
    assert first.prepared_template


def test_output_picker_has_dedicated_remembered_directory(qt_application,tmp_path,monkeypatch):
    from PyQt6.QtCore import QSettings

    from composition.designer.output_location import choose_output_directory
    settings=QSettings(str(tmp_path/"preferences.ini"),QSettings.Format.IniFormat)
    settings.setValue("last_directory",str(tmp_path/"media_profiles"))
    selected=tmp_path/"Deliverables"
    selected.mkdir()
    starts=[]
    def choose(parent,title,directory):
        starts.append(directory)
        return str(selected)
    monkeypatch.setattr("composition.designer.output_location.QFileDialog.getExistingDirectory",choose)
    assert choose_output_directory(None,settings=settings)==str(selected)
    assert starts[0]!=str(tmp_path/"media_profiles")
    assert choose_output_directory(None,settings=settings)==str(selected)
    assert starts[1]==str(selected)
    monkeypatch.setattr("composition.designer.output_location.QFileDialog.getExistingDirectory",lambda *_:"")
    assert choose_output_directory(None,settings=settings)==""
    assert settings.value("production/output_directory")==str(selected)


def test_source_watch_checks_in_worker_and_blocks_stale_acceptance(qt_application,tmp_path):
    from pathlib import Path

    from tests.composition.test_workspace import wait_until
    from workflow.batch import approve
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    w=MailMergeWorkflowWindow()
    w.show()
    try:
        job=pair(tmp_path,"Watch")
        spec=recipe([job])
        w.apply_spec(spec.to_dict())
        w.batch=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
        approve(w.batch,[job.id])
        w.refresh_jobs()
        Path(job.data_path).write_text("Customer\nChanged\n",encoding="utf-8")
        w.source_watch.check()
        wait_until(lambda:not w.workers,timeout=20)
        assert job.status=="Needs review" and not job.approved
        assert job.data_summary["stale"]
        approve(w.batch,[job.id])
        assert not job.approved
        assert "changed" in w.feedback.text().lower()
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)


def test_branch_source_change_invalidates_shared_sequence_jobs(qt_application,tmp_path):
    from pathlib import Path

    from tests.composition.test_workspace import wait_until
    from tests.test_workflow_branch_engine import fixture
    from workflow.branch_engine import approve_routes, prepare_routes
    from workflow.branch_ui import BranchWorkflowWindow
    w=BranchWorkflowWindow()
    try:
        spec=fixture(tmp_path)
        w.apply_spec(spec.to_dict())
        w.run=prepare_routes(spec,tmp_path/"check")
        approve_routes(spec,w.run,[j["id"] for j in w.run["jobs"]])
        first=spec.node("for_each").params["items"][0]["path"]
        Path(first).write_text("Name,Scheme\nChanged,A\n",encoding="utf-8")
        w.source_watch.invalidate([first])
        assert w.run["stale"]
        assert all(not j["approved"] for j in w.run["jobs"])
        assert all(j["status"]=="Needs review" for j in w.run["jobs"])
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)


def test_review_media_override_returns_to_its_branch_node(qt_application):
    from PyQt6.QtWidgets import QTabWidget, QWidget

    from workflow.settings_navigation import edit_review_issue
    node=SimpleNamespace(id="media-second")
    tabs=QTabWidget()
    build=QWidget()
    review=QWidget()
    tabs.addTab(build,"Build")
    tabs.addTab(review,"Review")
    selected=[]
    window=SimpleNamespace(spec=SimpleNamespace(nodes=[node],node=lambda _:node),tabs=tabs,build_page=build,
        review_page=review,project_host=None,settings_scroll=QWidget(),select_node=selected.append,message=lambda _:None)
    context={"binding":{"data_summary":{"media_source":"workflow","media_node_id":node.id},"files":["template.pdcx"]}}
    tabs.setCurrentWidget(review)
    edit_review_issue(window,context,{"action":"media"})
    assert tabs.currentWidget() is build
    assert selected==[node.id]


def test_invalid_saved_source_metadata_rejected_before_ui():
    import pytest

    from workflow.batch import BatchJob
    with pytest.raises(ValueError,match="source observation"):
        BatchJob(data_summary={"source_observations":{"source.pdf":[]}}).validate()
    with pytest.raises(ValueError,match="print counts"):
        BatchJob(data_summary={"print_plan":{"sheets":"many"}}).validate()
