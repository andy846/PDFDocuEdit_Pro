"""Headless checks never publish or approve, and inspect full disk-backed inputs."""
import copy
import importlib
from pathlib import Path

import pytest

from tests.test_mail_merge_workflow import pair, recipe
from tests.test_workflow_core import configured, fixture_pdf
from workflow.inspection import inspect_step, inspection_preview, inspection_rows, inspection_value
from workflow.model import WorkflowNode, WorkflowSpec
from workflow.registry import default_options
from workflow.worker import dispatch


def block_generation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An inspection must never call production generation")
    modules = [importlib.import_module(name) for name in (
        "composition.production.generator", "composition.overlay.generator", "workflow.batch", "workflow.engine", "workflow.pdf_pipeline")]
    for module in modules:
        monkeypatch.setattr(module, "generate", forbidden)


def test_partial_connected_prefix_and_disconnected_target():
    spec = WorkflowSpec.mail_merge().upgraded()
    spec.edges = spec.edges[:1]
    assert [n.kind for n in spec.execution_prefix(spec.node("mapping").id)] == ["data", "mapping"]
    with pytest.raises(ValueError, match="Connect"):
        spec.execution_prefix(spec.node("compose").id)
    with pytest.raises(ValueError):
        spec.chain()


def test_mail_compose_reports_checks_full_input_without_publishing_or_approval(tmp_path, monkeypatch):
    block_generation(monkeypatch)
    job = pair(tmp_path, records=4)
    spec = recipe([job]).upgraded()
    spec.node("reports").params = {"directory": str(tmp_path / "output")}
    before = copy.deepcopy(job)
    result = inspect_step(spec, spec.node("reports").id, tmp_path / "checks", job=job)
    assert result["result"]["status"] == "Checked", result["result"]["error"]
    assert result["result"]["plan"]["pages"] == 8
    assert result["result"]["plan"]["checked_records"] == 4
    assert job == before and not job.approved
    assert not (tmp_path / "output").exists()
    preview = inspection_preview(tmp_path / "checks", result["result"]["run_id"], spec.node("reports").id,
                                 spec, tmp_path / "checks" / "preview.png", job=job, record=4, page=2)
    assert Path(preview["image"]).is_file()
    assert not list((tmp_path / "checks").rglob("*.ps"))


def test_full_sort_paged_before_after_and_stable_identity(tmp_path):
    job = pair(tmp_path, records=125)
    spec = recipe([job]).upgraded()
    clean = WorkflowNode("clean_fields", params={"operations": [{"field": "Name", "operation": "upper"}]})
    sort = WorkflowNode("sort_records", params={"keys": [{"field": "Name", "type": "text", "descending": True}]})
    spec = spec.insert_after(spec.node("mapping").id, clean).insert_after(clean.id, sort)
    result = inspect_step(spec, sort.id, tmp_path / "checks", job=job)
    assert result["result"]["status"] == "Checked", result["result"]["error"]
    assert result["steps"][clean.id]["output_count"] == 125
    page = inspection_rows(tmp_path / "checks", result["result"]["run_id"], sort.id, spec, job=job)
    assert page["total"] == 125 and len(page["rows"]) == 50
    assert page["rows"][0]["values"]["Name"] == "PERSON 99"
    assert page["rows"][0]["source_id"] == 101
    assert page["rows"][0]["before"]["Name"] == "PERSON 99"
    third = inspection_rows(tmp_path / "checks", result["result"]["run_id"], sort.id, spec, job=job, offset=100)
    assert len(third["rows"]) == 25
    clipped = inspection_rows(tmp_path / "checks", result["result"]["run_id"], sort.id, spec, job=job, offset=10000)
    assert clipped["offset"] == 100 and len(clipped["rows"]) == 25
    clean_page = inspection_rows(tmp_path / "checks", result["result"]["run_id"], clean.id, spec, job=job)
    assert clean_page["rows"][0]["before"]["Name"] == "Person 0"


def test_unique_validation_checks_beyond_first_page_and_attributes_issues(tmp_path):
    job = pair(tmp_path, records=130)
    data = Path(job.data_path)
    data.write_text("Customer\n" + "\n".join(["Duplicate", *[f"Name {i}" for i in range(128)], "Duplicate"]) + "\n")
    spec = recipe([job]).upgraded()
    validate = WorkflowNode("validate_data", params={"checks": [{"field": "Name", "check": "unique", "severity": "error"}]})
    spec = spec.insert_after(spec.node("mapping").id, validate)
    result = inspect_step(spec, validate.id, tmp_path / "checks", job=job)
    assert result["result"]["status"] == "Needs review"
    assert result["result"]["output_count"] == 130
    issues = inspection_rows(tmp_path / "checks", result["result"]["run_id"], validate.id, spec, job=job, view="issues")
    assert issues["total"] == 2
    assert {r["source_id"] for r in issues["rows"]} == {2, 131}
    assert {r["node_id"] for r in issues["rows"]} == {validate.id}


def test_source_change_and_configuration_change_invalidate_cached_rows(tmp_path):
    job = pair(tmp_path)
    spec = recipe([job]).upgraded()
    target = spec.node("mapping").id
    result = inspect_step(spec, target, tmp_path / "checks", job=job)
    repeated = inspect_step(spec, target, tmp_path / "checks", job=job)
    assert repeated["cached"] and repeated["result"]["run_id"] == result["result"]["run_id"]
    Path(job.data_path).write_text("Customer\nChanged\n")
    with pytest.raises(ValueError, match="out of date"):
        inspection_rows(tmp_path / "checks", result["result"]["run_id"], target, spec, job=job)
    changed = inspect_step(spec, target, tmp_path / "checks", job=job)
    assert not changed["cached"] and changed["result"]["output_count"] == 1
    spec.node("mapping").params["profiles"][job.mapping_profile] = {"Customer": "OtherName"}
    with pytest.raises(ValueError, match="out of date"):
        inspection_rows(tmp_path / "checks", changed["result"]["run_id"], target, spec, job=job)


def test_cache_for_upstream_step_does_not_restore_stale_downstream_results(tmp_path):
    job=pair(tmp_path)
    spec=recipe([job]).upgraded()
    spec.node("reports").params={"directory":str(tmp_path/"out")}
    complete=inspect_step(spec,spec.node("reports").id,tmp_path/"checks",job=job)
    assert complete["result"]["status"]=="Checked"
    spec.node("compose").params={"auto_repair":False}
    prefix=inspect_step(spec,spec.node("mapping").id,tmp_path/"checks",job=job)
    assert prefix["cached"]
    assert set(prefix["steps"])=={spec.node("data").id,spec.node("mapping").id}


def test_field_reader_covers_extra_columns_long_values_and_exact_source_lookup(tmp_path):
    job = pair(tmp_path,records=125)
    columns = ["Customer",*[f"Extra_{i}" for i in range(16)]]
    value = "Long " + "x" * 900
    Path(job.data_path).write_text(",".join(columns)+"\n"+"\n".join(",".join([f"Person {i}",*[value]*16]) for i in range(125))+"\n")
    spec = recipe([job]).upgraded()
    node=WorkflowNode("clean_fields",params={"operations":[{"field":"Extra_15","operation":"upper"}]})
    spec=spec.insert_after(spec.node("mapping").id,node)
    checked=inspect_step(spec,node.id,tmp_path/"checks",job=job)["result"]
    assert checked["status"]=="Checked",checked["error"]
    field=inspection_value(tmp_path/"checks",checked["run_id"],node.id,spec,job=job,record=125,field_name="Extra_15")
    assert field["before"]==value and field["value"]==value.upper() and not field["truncated"]
    exact=inspection_rows(tmp_path/"checks",checked["run_id"],node.id,spec,job=job,source_id=126)
    assert exact["total"]==1 and exact["rows"][0]["ordinal"]==125


def test_failure_after_sort_maps_record_ordinal_to_source_identity(tmp_path,monkeypatch):
    from composition.template.model import CompositionError
    job=pair(tmp_path,records=3)
    spec=recipe([job]).upgraded()
    node=WorkflowNode("sort_records",params={"keys":[{"field":"Name","type":"text","descending":True}]})
    spec=spec.insert_after(spec.node("mapping").id,node)
    def fail(*args,**kwargs):
        raise CompositionError("Record 2, object sample_text, field Name: Missing glyph")
    monkeypatch.setattr("composition.engine.renderer.Renderer.prepare_fonts",fail)
    result=inspect_step(spec,spec.node("compose").id,tmp_path/"checks",job=job)
    failed=result["result"]
    assert failed["status"]=="Failed"
    issues=inspection_rows(tmp_path/"checks",failed["run_id"],failed["node_id"],spec,job=job,view="issues")
    assert issues["rows"][0]["source_id"]==3
    assert issues["rows"][0]["field"]=="Name"
    earlier=inspection_rows(tmp_path/"checks",failed["run_id"],node.id,spec,job=job,view="issues")
    assert earlier["total"]==0


def test_compose_inspection_checks_barcode_payload_beyond_first_page(tmp_path):
    from composition.template.model import Element
    from composition.template.serializer import load_project, save_project
    job=pair(tmp_path,records=100)
    Path(job.data_path).write_text("Customer\n"+"\n".join(["000000"]*99+["invalid"])+"\n")
    template=load_project(job.template_path)
    template.pages[0].elements.append(Element(type="i25",value="{{Name}}",width_mm=80,height_mm=20))
    save_project(template,job.template_path)
    spec=recipe([job]).upgraded()
    result=inspect_step(spec,spec.node("compose").id,tmp_path/"checks",job=job)["result"]
    assert result["status"]=="Failed" and "I25 accepts digits" in result["error"]
    rows=inspection_rows(tmp_path/"checks",result["run_id"],result["node_id"],spec,job=job,view="issues")
    assert rows["rows"][0]["source_id"]==101


def test_pdf_group_output_keeps_original_source_trace_and_no_production(tmp_path, monkeypatch):
    block_generation(monkeypatch)
    source = fixture_pdf(tmp_path / "source.pdf")
    spec = configured(source, tmp_path / "output").upgraded()
    result = inspect_step(spec, spec.node("output").id, tmp_path / "checks")
    assert result["result"]["status"] == "Checked", result["result"]["error"]
    assert result["result"]["plan"]["pages"] == 6
    groups = inspection_rows(tmp_path / "checks", result["result"]["run_id"], spec.node("group").id, spec)
    assert groups["total"] == 2
    assert groups["rows"][1]["trace"]["source_page"] == 4
    assert groups["rows"][1]["trace"]["source_file"] == str(source.resolve())
    assert not (tmp_path / "output").exists()


def test_page_transforms_feed_grouping_and_repeated_steps_have_separate_data(tmp_path):
    source = fixture_pdf(tmp_path / "source.pdf")
    spec = configured(source, tmp_path / "output").upgraded()
    first = WorkflowNode("clean_fields", params=default_options("clean_fields", "Account_No"))
    second = WorkflowNode("clean_fields", params={"operations": [{"field": "Account_No", "operation": "replace", "value": "000", "replacement": "X"}]})
    spec = spec.insert_after(spec.node("extract").id, first).insert_after(first.id, second)
    result = inspect_step(spec, spec.node("group").id, tmp_path / "checks")
    # The values still feed grouping, but X01 violates the original digits rule.
    assert result["result"]["status"] == "Needs review", result["result"]["error"]
    one = inspection_rows(tmp_path / "checks", result["result"]["run_id"], first.id, spec)
    two = inspection_rows(tmp_path / "checks", result["result"]["run_id"], second.id, spec)
    assert one["rows"][0]["values"]["Account_No"] == "00001"
    assert two["rows"][0]["values"]["Account_No"] == "X01"


def test_partial_data_workflow_accepts_import_options_without_a_template(tmp_path):
    from workflow.batch import BatchJob
    source = tmp_path / "tab.txt"
    source.write_text("skip this row\nName\tAmount\nAnn\t10\n")
    job = BatchJob(data_path=str(source), data_options={"delimiter": "\t", "header_row": 2})
    spec = WorkflowSpec.mail_merge().upgraded()
    spec.edges = []
    result = inspect_step(spec, spec.node("data").id, tmp_path / "checks", job=job)
    assert result["result"]["status"] == "Checked", result["result"]["error"]
    assert result["result"]["fields"] == ["Name", "Amount"]


def test_worker_inspection_dispatch_and_cancel_preserve_completed_steps(tmp_path):
    job = pair(tmp_path, records=200)
    spec = recipe([job]).upgraded()
    cancelled = [False]
    def state(event):
        if event["inspection"]["node_id"] == spec.node("mapping").id:
            cancelled[0] = True
    result = dispatch({"operation": "inspect_step", "spec": spec.to_dict(), "job": job.__dict__,
                       "node_id": spec.node("compose").id, "directory": str(tmp_path / "checks")},
                      lambda *_: None, lambda: cancelled[0], state)
    assert result["steps"][spec.node("data").id]["status"] == "Checked"
    assert result["result"]["status"] == "Cancelled"
    assert not job.approved


def test_version_four_media_review_runs_shared_pipeline(tmp_path,monkeypatch):
    from dataclasses import asdict

    from composition.media.model import default_media
    from workflow import pdf_pipeline
    from workflow.engine import execute
    from workflow.model import WorkflowRun
    spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"output").upgraded(4)
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("media_assignment",params=default_media()))
    run=execute(spec,WorkflowRun(),tmp_path/"scratch",until="review")
    assert not run.error,run.error
    called=[]
    original=pdf_pipeline.prepare_mailpieces
    def prepare(*args,**kwargs):
        called.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(pdf_pipeline,"prepare_mailpieces",prepare)
    result=dispatch({"operation":"review","action":"accept","workflow":spec.to_dict(),"workflow_run":asdict(run),
                     "database":run.database,"groups":run.groups,"page":1,"directory":str(tmp_path/"scratch")},
                    lambda *_:None,lambda:False)
    assert called and result["accepted"] and result["data_set"]


@pytest.mark.parametrize("run_id", ["../escape", "bad", "", 1])
def test_inspection_reader_rejects_invalid_identity(tmp_path, run_id):
    spec = WorkflowSpec.default()
    with pytest.raises(ValueError, match="identity"):
        inspection_rows(tmp_path, run_id, spec.node("input").id, spec)
