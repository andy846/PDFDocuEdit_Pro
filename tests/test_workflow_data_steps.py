import json
import sqlite3
from pathlib import Path

import fitz
import pytest

from composition.production.generator import JobCancelled
from tests.test_mail_merge_workflow import pair, recipe
from tests.test_workflow_core import configured, fixture_pdf
from workflow.batch import BatchRun, approve, execute_batch, prepare
from workflow.engine import execute
from workflow.extraction import ExtractionStore
from workflow.model import WorkflowNode, WorkflowRun, WorkflowSpec
from workflow.pipeline import split_names, summary
from workflow.registry import default_options
from workflow.serializer import load_workflow, save_workflow
from workflow.transforms import assert_valid, snapshot, transform


def rows(tmp_path):
    return snapshot(iter([(2,{"Name":"  alice\nCHAN ","Id":"0007","Amount":"10","Type":"GS"}),
                          (3,{"Name":"Bob","Id":"0008","Amount":"2","Type":"IS"}),
                          (4,{"Name":"Zed","Id":"0007","Amount":"","Type":"GS"})]),
                    ["Name","Id","Amount","Type"],tmp_path/"in.sqlite")


def insert(spec,after,kind,params):
    return spec.insert_after(spec.node(after).id,WorkflowNode(kind,params=params))


def test_clean_create_preserve_original_values_and_zeros(tmp_path):
    source=rows(tmp_path)
    clean=transform(source,tmp_path/"clean.sqlite","clean_fields",{"operations":[
        {"field":"Name","operation":"trim"},{"field":"Name","operation":"join_lines"}]})
    created=transform(clean,tmp_path/"created.sqlite","create_fields",{"fields":[
        {"field":"Ref","operation":"concat","sources":["Type","Id"],"separator":"-"},
        {"field":"Suffix","operation":"last","sources":["Id"],"length":2}]})
    assert created.record(1)["Ref"]=="GS-0007"
    assert created.record(1)["Suffix"]=="07"
    assert created.record(1)["Name"]=="alice CHAN"
    assert source.record(1)["Name"].startswith("  ")
    with sqlite3.connect(created.path) as db:
        assert json.loads(db.execute("SELECT value FROM originals WHERE source_id=2").fetchone()[0])["Name"].startswith("  ")
    with pytest.raises(ValueError,match="already exists"):
        transform(source,tmp_path/"bad.sqlite","create_fields",{"fields":[{"field":"Id","operation":"constant","value":"x"}]})


def test_numeric_sort_filter_stable_identity_and_reconciliation(tmp_path):
    source=rows(tmp_path)
    sorted_rows=transform(source,tmp_path/"sort.sqlite","sort_records",{"keys":[{"field":"Amount","type":"number","descending":True}]})
    assert [sid for _,_,sid in sorted_rows.rows()]==[2,3,4]
    filtered=transform(sorted_rows,tmp_path/"filter.sqlite","filter_records",{"mode":"all","conditions":[
        {"field":"Type","operator":"eq","data_type":"text","value":"GS"}]},node_id="filter1")
    assert [sid for _,_,sid in filtered.rows()]==[2,4]
    assert summary(filtered,3)["excluded"]==1
    assert filtered.metadata["steps"][-1]["input"]==3


def test_validation_reports_both_duplicate_rows_and_blocks_without_deleting(tmp_path):
    checked=transform(rows(tmp_path),tmp_path/"checked.sqlite","validate_data",{"checks":[{"field":"Id","check":"unique"}]})
    assert checked.count==3
    with sqlite3.connect(checked.path) as db:
        assert {r[0] for r in db.execute("SELECT source_id FROM findings")}=={2,4}
    assert checked.metadata["steps"][0]["issues"]==2
    with pytest.raises(ValueError,match="Duplicate"):
        assert_valid(checked)


def test_warning_validation_and_cancel_preserve_source(tmp_path):
    source=rows(tmp_path)
    checked=transform(source,tmp_path/"checked.sqlite","validate_data",{"checks":[{"field":"Amount","check":"required","severity":"warning"}]})
    assert_valid(checked)
    assert summary(checked,3)["warnings"]==1
    with pytest.raises(JobCancelled):
        transform(source,tmp_path/"cancel.sqlite","clean_fields",default_options("clean_fields"),is_cancelled=lambda:True)
    assert not (tmp_path/"cancel.sqlite").exists()
    assert source.count==3


def test_v3_repeatable_nodes_typed_reordering_and_copy_serialization(tmp_path):
    legacy=WorkflowSpec.mail_merge()
    spec=insert(legacy.upgraded(),"template","clean_fields",default_options("clean_fields"))
    spec=spec.insert_after(spec.node("clean_fields").id,WorkflowNode("clean_fields",params=default_options("clean_fields")))
    assert len(spec.chain())==9
    path=save_workflow(spec,tmp_path/"v3.pdflow")
    assert load_workflow(path).to_dict()==spec.to_dict()
    assert legacy.workflow_version==2 and len(legacy.chain())==7
    order=[n.id for n in spec.chain()]
    index=order.index(spec.node("template").id)
    order[index],order[-2]=order[-2],order[index]
    with pytest.raises(ValueError):
        spec.reorder(order)
    pdf=WorkflowSpec.default().upgraded()
    with pytest.raises(ValueError):
        insert(pdf,"extract","filter_records",default_options("filter_records"))


def test_split_sanitization_collisions_block_before_production(tmp_path):
    source=snapshot([(1,{"Kind":"A/B"}),(2,{"Kind":"A\\B"})],["Kind"],tmp_path/"source.sqlite")
    split=transform(source,tmp_path/"split.sqlite","split_output",{"method":"field","field":"Kind"})
    with pytest.raises(ValueError,match="collision"):
        split_names(split,"letters.pdf")


def test_mail_merge_data_steps_split_preserve_customer_sequence_across_files(tmp_path):
    job=pair(tmp_path,records=4)
    spec=recipe([job]).upgraded()
    spec=insert(spec,"template","sort_records",{"keys":[{"field":"Name","type":"text","descending":True}]})
    spec=insert(spec,"sort_records","running_sequence",default_options("running_sequence"))
    spec=insert(spec,"running_sequence","split_output",{"method":"count","count":2})
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"scratch")
    assert job.status=="Needs review",job.error
    assert job.data_summary["retained"]==4
    assert job.data_summary["steps"][0]["samples"][0]["source_id"]==5
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Completed",job.error
    assert len(job.result["output_files"])==2
    for index,item in enumerate(job.result["output_files"]):
        with fitz.open(item["output_pdf"]) as doc:
            assert doc.page_count==4
            assert f"{index*2+1:04}" in doc[0].get_text()
    assert not list(Path(run.report_dir).glob("*/letters.pdf"))


def test_mail_merge_zero_selection_publishes_report_without_empty_pdf(tmp_path):
    job=pair(tmp_path)
    spec=insert(recipe([job]).upgraded(),"template","filter_records",{"mode":"all","conditions":[
        {"field":"Name","operator":"eq","data_type":"text","value":"not present"}]})
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"scratch")
    assert job.input_records==0 and job.status=="Needs review",job.error
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Completed",job.error
    assert job.result["generated_files"]==0 and job.result["excluded_records"]==2
    assert not list(Path(run.report_dir).rglob("*.pdf"))


def test_pdf_filter_preserves_original_boundaries_and_whole_envelopes(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=insert(configured(source,tmp_path/"out").upgraded(),"group","filter_records",{"mode":"all","conditions":[
        {"field":"Account_No","operator":"eq","data_type":"text","value":"00002"}]})
    run=execute(spec,WorkflowRun(),tmp_path/"scratch")
    assert not run.error,run.error
    assert run.groups==[[1,3],[4,6]]
    assert run.data_summary["retained"]==1 and run.data_summary["excluded"]==1
    assert Path(run.data_summary["exclusions_report"]).is_file()
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    run=execute(spec,run,tmp_path/"scratch",until="output")
    assert not run.error,run.error
    assert run.groups==[[1,3],[4,6]]
    with fitz.open(run.output["output_pdf"]) as doc:
        assert doc.page_count==3
        assert "00002" in doc[0].get_text()
    assert run.output["excluded_envelopes"]==1


def test_pdf_page_clean_derived_group_field_and_variable_envelope_split(tmp_path):
    from composition.template.model import MM_TO_PT
    source=tmp_path/"source.pdf"
    with fitz.open() as pdf:
        for envelope,count in enumerate((2,3,1),1):
            for _ in range(count):
                page=pdf.new_page(width=210*MM_TO_PT,height=297*MM_TO_PT)
                page.insert_text((60,65),f"Account: {envelope:05}")
        pdf.save(source)
    spec=configured(source,tmp_path/"out").upgraded()
    spec=insert(spec,"extract","create_fields",{"fields":[{"field":"DerivedId","operation":"concat","sources":["Account_No"]}]})
    spec.node("group").params={"method":"field","field":"DerivedId"}
    spec=insert(spec,"group","sort_records",{"keys":[{"field":"DerivedId","type":"text","descending":True}]})
    spec=insert(spec,"sort_records","split_output",{"method":"count","count":1})
    run=execute(spec,WorkflowRun(),tmp_path/"scratch")
    assert not run.error,run.error
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    run=execute(spec,run,tmp_path/"scratch",until="output")
    assert not run.error,run.error
    assert run.groups==[[1,2],[3,5],[6,6]]
    assert len(run.output["output_files"])==3
    assert run.output["generated_files"]==3
    report=Path(run.output["report_dir"])
    assert json.loads((report/"job.json").read_text(encoding="utf-8"))["generated_files"]==3
    assert json.loads((report/"original-boundaries.json").read_text(encoding="utf-8"))["groups"]==run.groups
    for item,expected,count in zip(run.output["output_files"],["00003","00002","00001"],[1,3,2],strict=True):
        with fitz.open(item["output_pdf"]) as doc:
            assert doc.page_count==count
            assert expected in doc[0].get_text()


def test_disk_sort_ten_thousand_preserves_stable_order_and_missing_values(tmp_path):
    source=snapshot(((i,{"Key":str(i%17),"Id":f"{i:06}"}) for i in range(1,10001)),["Key","Id"],tmp_path/"large.sqlite")
    sorted_rows=transform(source,tmp_path/"sorted.sqlite","sort_records",{"keys":[{"field":"Key","type":"number"}]})
    assert sorted_rows.count==10000
    assert sorted_rows.record(1)["Id"]=="000017"
    assert sorted_rows.source_id(2)==34
    assert len(sorted_rows.metadata["steps"][0]["samples"])==8


def test_page_sequence_is_not_flattened_and_split_does_not_reset_it(tmp_path):
    from composition.template.model import Element
    from composition.template.serializer import load_project, save_project
    job=pair(tmp_path,records=2)
    template=load_project(job.template_path)
    for page in template.pages:
        page.elements.append(Element(value="PAGESEQ {{WorkflowSeq}}",y_mm=35,width_mm=150,height_mm=12))
    save_project(template,job.template_path)
    spec=insert(recipe([job]).upgraded(),"template","running_sequence",{**default_options("running_sequence"),"scope":"page"})
    spec=insert(spec,"running_sequence","split_output",{"method":"count","count":1})
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"scratch")
    assert job.status=="Needs review",job.error
    assert job.data_summary["steps"][0]["kind"]=="running_sequence"
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Completed",job.error
    for item,numbers in zip(job.result["output_files"],[("000001","000002"),("000003","000004")],strict=True):
        with fitz.open(item["output_pdf"]) as pdf:
            assert numbers[0] in pdf[0].get_text()
            assert numbers[1] in pdf[1].get_text()


def test_overlay_designer_samples_use_sorted_filtered_production_view(tmp_path):
    from composition.overlay.serializer import load_project
    from composition.pdf_source.planner import EnvelopePlan
    from workflow.pdf_pipeline import ProductionValues
    from workflow.worker import dispatch
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=insert(configured(source,tmp_path/"out").upgraded(),"group","sort_records",{"keys":[{"field":"Account_No","type":"text","descending":True}]})
    spec=insert(spec,"sort_records","running_sequence",default_options("running_sequence"))
    run=execute(spec,WorkflowRun(),tmp_path/"scratch")
    assert not run.error,run.error
    result=dispatch({"operation":"make_overlay","spec":spec.to_dict(),"workflow_run":run.__dict__,
        "source":run.source,"groups":run.groups,"directory":str(tmp_path/"scratch"),"path":str(tmp_path/"overlay.pdcx")},None,None)
    project=load_project(result["path"])
    plan=EnvelopePlan(project.source.pages,project.settings)
    with ProductionValues(result["external_data"],run.database,project) as values:
        first=values(plan.page(1,1))
        assert first["Envelope_Account_No"]==first["Page_Account_No"]=="00002"
        assert first["WorkflowSeq"]=="000001"
    with fitz.open(project.source.path) as pdf:
        assert "00002" in pdf[0].get_text()
    assert run.groups==[[1,3],[4,6]]
    execute(spec,run,tmp_path/"scratch")
    with ProductionValues(result["external_data"],run.database,project) as values:
        assert values(plan.page(1,1))["WorkflowSeq"]=="000001"


def test_repeated_step_run_stops_at_requested_identity(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=insert(configured(source,tmp_path/"out").upgraded(),"extract","clean_fields",
                {"operations":[{"field":"Account_No","operation":"trim"}]})
    first=spec.node("clean_fields")
    spec=spec.insert_after(first.id,WorkflowNode("clean_fields",params={"operations":[{"field":"Missing","operation":"trim"}]}))
    run=execute(spec,WorkflowRun(),tmp_path/"scratch",until=first.id)
    assert not run.error,run.error
    assert run.statuses[first.id]=="Completed" and not run.groups
    run=execute(spec,run,tmp_path/"scratch")
    assert "Missing fields: Missing" in run.error


@pytest.mark.parametrize("value",[{"steps":["bad"]},{"retained":"many"},{"steps":[{"node_id":"x","kind":"clean_fields","samples":[{"source_id":1,"before":[]}]}]}])
def test_corrupt_workflow_findings_rejected_before_ui(value):
    from workflow.batch import BatchJob
    with pytest.raises(ValueError,match="Invalid workflow"):
        BatchJob(data_summary=value).validate()
