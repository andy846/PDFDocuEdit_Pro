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


def test_partial_cached_print_plan_and_branch_observations_rejected(tmp_path):
    import pytest

    from workflow.batch import BatchJob
    with pytest.raises(ValueError,match="print counts"):
        BatchJob(data_summary={"print_plan":{"output_pages":4}}).validate()


def test_invalid_cached_branch_source_metadata_rejected(tmp_path):
    import pytest

    from tests.test_workflow_branch_engine import fixture
    from workflow.branch_engine import prepare_routes, validate_branch_run
    run=prepare_routes(fixture(tmp_path),tmp_path/"check")
    run["source_observations"]={"file.csv":[]}
    with pytest.raises(ValueError):
        validate_branch_run(run)


def test_pdf_check_observes_optional_overlay_without_loading_it(tmp_path):
    from tests.test_workflow_core import configured, fixture_pdf
    from workflow.engine import execute
    from workflow.model import WorkflowNode, WorkflowRun
    spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"out")
    missing=str(tmp_path/"draft-overlay.pdcx")
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("overlay",params={"path":missing}))
    run=execute(spec,WorkflowRun(),tmp_path/"check",until="review")
    assert not run.error,run.error
    assert missing in run.data_summary["source_observations"]


def test_pdf_review_navigation_cannot_restore_stale_acceptance(qt_application,tmp_path):
    from tests.composition.test_workspace import wait_until
    from tests.test_workflow_core import configured, fixture_pdf
    from workflow.engine import execute
    from workflow.extraction import ExtractionStore
    from workflow.model import WorkflowRun
    from workflow.workspace import WorkflowWindow
    w=WorkflowWindow()
    try:
        spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"out")
        w.apply_spec(spec.to_dict())
        w.run=execute(spec,WorkflowRun(),tmp_path/"check")
        with ExtractionStore(w.run.database) as store:
            store.accept()
        w.run.accepted=True
        w.source_watch.invalidate([str(tmp_path/"source.pdf")])
        assert not w.run.accepted and w.run.data_summary["stale"]
        w.review()
        wait_until(lambda:not w.workers,timeout=20)
        assert not w.run.accepted
        assert w.run.data_summary["stale"]
        assert w.run.statuses[w.spec.node("review").id]=="Needs review"
        w.review(action="accept")
        wait_until(lambda:not w.workers,timeout=20)
        assert not w.run.accepted
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)


def test_unapplied_designer_batch_draft_invalidates_job(qt_application,tmp_path):
    from types import SimpleNamespace

    from tests.composition.test_workspace import wait_until
    from workflow.batch import approve
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    w=MailMergeWorkflowWindow()
    try:
        job=pair(tmp_path,"Draft")
        spec=recipe([job])
        w.apply_spec(spec.to_dict())
        w.batch=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
        approve(w.batch,[job.id])
        project=SimpleNamespace(project_path=job.template_path,undo=SimpleNamespace(isClean=lambda:True),
            properties=SimpleNamespace(has_batch_draft=lambda:True))
        w.project_host=SimpleNamespace(projects=[project])
        w.source_watch.open_changes()
        assert not job.approved
        assert job.data_summary["stale"]
    finally:
        w.project_host=None
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)


def test_inspection_only_sources_are_observed(qt_application,tmp_path):
    from tests.composition.test_workspace import wait_until
    from workflow.inspection import inspect_step
    from workflow.mail_merge_ui import MailMergeWorkflowWindow
    w=MailMergeWorkflowWindow()
    try:
        job=pair(tmp_path,"Inspection")
        spec=recipe([job]).upgraded(4)
        w.apply_spec(spec.to_dict())
        w.batch.jobs=[job]
        target=spec.node("template").id
        checked=inspect_step(spec,target,w.directory,job=job)
        result=checked["result"]
        assert result["status"]=="Checked",result["error"]
        w.inspections.results[(job.id,target)]=result
        assert job.template_path in w.source_watch.observations()
    finally:
        w._close_approved=True
        w.close()
        wait_until(lambda:not w.workers)
