import pytest

from composition.template.serializer import load_project, save_project
from tests.test_mail_merge_workflow import pair, recipe
from workflow.batch import BatchRun, prepare


def test_duplex_without_media_batch_matches_physical_plan(tmp_path):
    job = pair(tmp_path, 'Duplex', pages=3, records=2)
    template = load_project(job.template_path)
    template.media = {'duplex': True}
    save_project(template, job.template_path)
    checked = prepare(recipe([job]), BatchRun(jobs=[job]), tmp_path / 'check').jobs[0]
    assert checked.expected_pages == 8
    assert checked.pages_per_record == 4
    assert checked.data_summary["print_plan"]["logical_pages_per_record"] == 3
    assert checked.data_summary['print_plan']['sheets'] == 4
    assert checked.data_summary['print_plan']['inserted_blank_backs'] == 2


def test_media_sources_preserve_legacy_and_strip_metadata():
    from workflow.media_settings import media_options, resolve_media_settings
    project = {'duplex': True}
    legacy = {'enabled': False, 'duplex': False}
    assert resolve_media_settings(project, legacy).source == 'workflow'
    assert resolve_media_settings(project, legacy).media == legacy
    inherited = {**legacy, 'settings_source': 'project'}
    result = resolve_media_settings(project, inherited)
    assert result.source == 'project' and result.media == project
    assert 'settings_source' not in media_options(inherited)
    result.media['duplex'] = False
    assert project['duplex'] is True
    with pytest.raises(ValueError):
        resolve_media_settings(project, {'settings_source': 'guess'})


def test_new_media_node_inherits_and_roundtrips():
    from workflow.media_settings import resolve_media_settings
    from workflow.registry import REGISTRY, default_options
    options = default_options('media_assignment')
    assert options['settings_source'] == 'project'
    REGISTRY['media_assignment'].validate_options(options)
    assert resolve_media_settings({'duplex': True}, options).media['duplex']


@pytest.mark.parametrize("source,expected",[("project",8),("workflow",6),(None,6)])
def test_batch_media_source_used_by_inspection_review_and_generation(tmp_path, source, expected):
    import fitz

    from tests.production_approval import execute_batch
    from workflow.batch import approve
    from workflow.inspection import inspect_step
    from workflow.model import WorkflowNode
    from workflow.production_review import prepare_contexts
    job=pair(tmp_path,"SamePlan",pages=3,records=2)
    template=load_project(job.template_path)
    template.media={"duplex":True}
    save_project(template,job.template_path)
    options={"duplex":False}
    if source:
        options["settings_source"]=source
    spec=recipe([job]).upgraded(4)
    spec=spec.insert_after(spec.node("template").id,WorkflowNode("media_assignment",params=options))
    assert spec.from_dict(spec.to_dict()).to_dict()==spec.to_dict()
    check=inspect_step(spec,spec.node("compose").id,tmp_path/"inspect",job=job)
    assert check["result"]["status"]=="Checked",check["result"]["error"]
    assert check["result"]["plan"]["pages"]==expected
    assert not (tmp_path/"out").exists()
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
    assert job.expected_pages==expected,job.error
    approve(run,[job.id])
    context=prepare_contexts({"review_kind":"batch","spec":spec.to_dict(),"batch":run.to_dict(),"output_dir":str(tmp_path/"out")})["contexts"][0]
    assert context["binding"]["data_summary"]["media_source"]==(source or "workflow")
    assert "settings_source" not in context["job"]["template"]["media"]
    result=execute_batch(spec,run,tmp_path/"out")
    assert result.status=="Completed",job.error
    with fitz.open(job.result["output_pdf"]) as pdf:
        assert len(pdf)==expected


def test_explicit_media_inspection_does_not_load_downstream_overlay(tmp_path):
    from tests.test_workflow_core import configured, fixture_pdf
    from workflow.inspection import inspect_step
    from workflow.model import WorkflowNode
    spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"out").upgraded(4)
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("overlay",params={"path":str(tmp_path/"not-yet-saved.pdcx")}))
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("media_assignment",params={"duplex":True,"settings_source":"workflow"}))
    checked=inspect_step(spec,spec.node("media_assignment").id,tmp_path/"check")
    assert checked["result"]["status"]=="Checked",checked["result"]["error"]
    assert checked["result"]["plan"]["pages"]==8


def test_check_data_prefix_does_not_require_downstream_overlay(tmp_path):
    from tests.test_workflow_core import configured, fixture_pdf
    from workflow.engine import execute
    from workflow.model import WorkflowNode, WorkflowRun
    from workflow.registry import default_options
    spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"out").upgraded(4)
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("overlay",params={"path":str(tmp_path/"not-yet-saved.pdcx")}))
    spec=spec.insert_after(spec.node("group").id,WorkflowNode("clean_fields",params=default_options("clean_fields","Account_No")))
    target=spec.node("clean_fields")
    run=execute(spec,WorkflowRun(),tmp_path/"check",until=target.id)
    assert not run.error,run.error
    assert run.statuses[target.id]=="Completed"
