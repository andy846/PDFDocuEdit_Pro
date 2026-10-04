from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from composition.template.model import Element, PageSpec, SequenceSpec, Template
from composition.template.serializer import save_project
from workflow.batch import BatchJob, BatchRun, approve, execute_batch, load_record, prepare, save_record
from workflow.model import WorkflowSpec
from workflow.serializer import load_workflow, save_workflow
from workflow.worker import dispatch


def pair(tmp_path,name="GS",pages=2,records=2,header="Customer"):
    template=Template(name=name,pages=[PageSpec(name=f"Page {i+1}",elements=[
        Element(value="{{Name}} / {{Seq}}",width_mm=150,height_mm=15)]) for i in range(pages)],
        sequences=[SequenceSpec(name="Seq",start=1,padding=4)])
    target=save_project(template,tmp_path/(name+".pdcx"))
    data=tmp_path/(name+".csv")
    data.write_text(header+"\n"+"\n".join(f"Person {i}" for i in range(records))+"\n",encoding="utf-8")
    job=BatchJob(name=name,template_path=str(target),data_path=str(data),output_name=name+".pdf",mapping_profile=name)
    return job


def recipe(jobs):
    spec=WorkflowSpec.mail_merge()
    spec.node("mapping").params={"profiles":{j.mapping_profile:{"Customer":"Name"} for j in jobs}}
    return spec


def test_recipe_v2_and_legacy_are_separate_and_do_not_embed_batch_data(tmp_path):
    spec=WorkflowSpec.mail_merge()
    assert len(spec.chain())==7
    assert spec.workflow_version==2
    path=save_workflow(spec,tmp_path/"letters.pdflow")
    assert load_workflow(path).to_dict()==spec.to_dict()
    assert "jobs" not in json.loads(Path(path).read_text())
    legacy=WorkflowSpec.default()
    assert legacy.workflow_version==1
    assert len(WorkflowSpec.from_dict(legacy.to_dict()).chain())==6
    raw=spec.to_dict()
    raw["edges"].append([spec.nodes[0].id,spec.nodes[-1].id])
    with pytest.raises(ValueError):
        WorkflowSpec.from_dict(raw)


def test_multitemplate_mapping_sequences_reconciliation_and_retry(tmp_path):
    first=pair(tmp_path,"GS",pages=2,records=3)
    second=pair(tmp_path,"IS",pages=3,records=2,header="Member")
    second.sequence_starts={"Seq":51}
    spec=recipe([first,second])
    spec.node("mapping").params["profiles"]["IS"]={"Member":"Name"}
    run=prepare(spec,BatchRun(jobs=[first,second]),tmp_path/"scratch")
    assert [j.status for j in run.jobs]==["Needs review"]*2
    assert [j.expected_pages for j in run.jobs]==[6,6]
    approve(run,[j.id for j in run.jobs])
    result=execute_batch(spec,run,tmp_path/"out")
    assert result.status=="Completed",[(j.error,j.status) for j in result.jobs]
    assert all(j.status=="Completed" for j in run.jobs)
    for job,pages,seq in [(first,6,"0001"),(second,6,"0051")]:
        pdf=Path(job.result["output_pdf"])
        assert pdf.name==job.output_name
        with fitz.open(pdf) as document:
            assert document.page_count==pages
            assert seq in document[0].get_text()
        log=json.loads((pdf.parent/"job.json").read_text(encoding="utf-8"))
        assert log["input_records"]==log["successful_records"]
    paths=[j.result["output_pdf"] for j in run.jobs]
    prepare(spec,run,tmp_path/"scratch")
    execute_batch(spec,run,tmp_path/"out")
    assert [j.result["output_pdf"] for j in run.jobs]==paths
    assert (Path(run.report_dir)/"batch-summary.csv").is_file()


def test_blocked_item_does_not_discard_good_job_and_mapping_profiles_isolated(tmp_path):
    first=pair(tmp_path,"Good")
    bad=pair(tmp_path,"Bad")
    bad.sequence_starts={"NotConfigured":3}
    spec=recipe([first,bad])
    run=prepare(spec,BatchRun(jobs=[first,bad]),tmp_path/"scratch")
    assert first.status=="Needs review"
    assert bad.status=="Blocked" and "Unknown sequence" in bad.error
    approve(run,[first.id])
    spec.node("mapping").params["profiles"]["Unused"]={"Unrelated":"Value"}
    result=execute_batch(spec,run,tmp_path/"out")
    assert first.status=="Completed"
    assert result.status=="Partial / needs attention"


def test_source_change_after_approval_requires_review_and_snapshot_preview_is_fixed(tmp_path):
    job=pair(tmp_path)
    spec=recipe([job])
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"scratch")
    approve(run,[job.id])
    Path(job.data_path).write_text("Customer\nChanged\n",encoding="utf-8")
    preview=dispatch({"operation":"batch_preview","spec":spec.to_dict(),"batch":run.to_dict(),
        "job_id":job.id,"record":1,"page":2,"target":str(tmp_path/"preview.png")},None,None)
    assert Path(preview["image"]).is_file()
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Needs review" and not job.result
    assert not list((tmp_path/"out").rglob("*.pdf"))


def test_cancel_preserves_ready_remaining_and_record_reopen_requires_check(tmp_path):
    jobs=[pair(tmp_path,name) for name in ("GS","IS")]
    spec=recipe(jobs)
    run=prepare(spec,BatchRun(jobs=jobs),tmp_path/"scratch")
    approve(run,[j.id for j in jobs])
    execute_batch(spec,run,tmp_path/"out",is_cancelled=lambda:True)
    assert run.status=="Cancelled"
    assert all(j.status=="Ready" for j in jobs)
    save_record(run,tmp_path/"list.json")
    restored=load_record(tmp_path/"list.json")
    assert all(not j.approved and j.status=="Needs review" and not j.prepared_template for j in restored.jobs)
    assert "Person 0" not in (tmp_path/"list.json").read_text()


@pytest.mark.parametrize("name",["../escape.pdf","CON.pdf","a/b.pdf","a?.pdf","letters.txt"])
def test_unsafe_output_is_rejected(name):
    with pytest.raises(ValueError):
        BatchJob(output_name=name).validate()


def test_duplicate_names_missing_fields_and_changed_output(tmp_path):
    first=pair(tmp_path,"GS")
    second=pair(tmp_path,"IS")
    second.output_name=first.output_name
    spec=recipe([first,second])
    run=prepare(spec,BatchRun(jobs=[first,second]),tmp_path/"scratch")
    assert all(j.status=="Blocked" and "Duplicate" in j.error for j in run.jobs)
    second.output_name="IS.pdf"
    spec.node("mapping").params["profiles"]["IS"]={"Customer":"Wrong"}
    prepare(spec,run,tmp_path/"scratch")
    assert "Missing mapped fields: Name" in second.error
    approve(run,[first.id])
    execute_batch(spec,run,tmp_path/"out")
    Path(first.result["output_pdf"]).unlink()
    prepare(spec,run,tmp_path/"scratch")
    assert first.status=="Needs review"


def test_acceptance_100_and_200_records_with_different_page_counts(tmp_path):
    jobs=[pair(tmp_path,"TwoPages",pages=2,records=100),pair(tmp_path,"ThreePages",pages=3,records=200)]
    spec=recipe(jobs)
    run=prepare(spec,BatchRun(jobs=jobs),tmp_path/"scratch")
    approve(run,[j.id for j in jobs])
    execute_batch(spec,run,tmp_path/"out")
    assert run.status=="Completed",[j.error for j in jobs]
    assert [j.result["generated_pages"] for j in jobs]==[200,600]
    assert [j.result["successful_records"] for j in jobs]==[100,200]


def test_excel_profile_preserves_zeros_and_real_render_error_continues(tmp_path):
    from openpyxl import Workbook
    jobs=[pair(tmp_path,"InvalidBarcode"),pair(tmp_path,"ExcelLetters")]
    bad_template=Template(elements=[Element(type="i25",value="{{Name}}",width_mm=80,height_mm=15)])
    save_project(bad_template,jobs[0].template_path)
    book=Workbook()
    book.active.title="Members"
    book.active.append(["Member"])
    book.active.append(["0000123"])
    source=tmp_path/"Members.xlsx"
    book.save(source)
    jobs[1].data_path=str(source)
    jobs[1].data_options={"sheet":"Members"}
    spec=recipe(jobs)
    spec.node("mapping").params["profiles"]["ExcelLetters"]={"Member":"Name"}
    run=prepare(spec,BatchRun(jobs=jobs),tmp_path/"scratch")
    approve(run,[j.id for j in jobs])
    states=[]
    execute_batch(spec,run,tmp_path/"out",on_state=states.append)
    assert jobs[0].status=="Failed" and jobs[0].result["failed_records"]>=1
    assert jobs[1].status=="Completed"
    with fitz.open(jobs[1].result["output_pdf"]) as pdf:
        assert "0000123" in pdf[0].get_text()
    assert any(s["jobs"] and s["jobs"][0]["status"]=="Running" for s in states)
    assert run.status=="Partial / needs attention"


def test_snapshot_tampering_and_output_directory_change(tmp_path):
    job=pair(tmp_path)
    spec=recipe([job])
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"scratch")
    approve(run,[job.id])
    spec.node("reports").params={"directory":str(tmp_path/"out")}
    # Choosing the output folder does not invalidate a checked template/data pair.
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Completed",job.error
    Path(job.data_path).write_text("Customer\nNew Person\n",encoding="utf-8")
    prepare(spec,run,tmp_path/"scratch")
    approve(run,[job.id])
    Path(job.record_store).write_bytes(b"changed")
    execute_batch(spec,run,tmp_path/"out")
    assert job.status=="Failed" and "snapshot changed" in job.error


@pytest.mark.parametrize("changes",[{"input_records":"many"},{"status":[]},{"warnings":"bad"},{"result":{"output_pdf":1}}])
def test_invalid_batch_records_are_rejected_before_ui(changes):
    raw=BatchRun(jobs=[BatchJob()]).to_dict()
    raw["jobs"][0].update(changes)
    with pytest.raises(ValueError):
        BatchRun.from_dict(raw)
