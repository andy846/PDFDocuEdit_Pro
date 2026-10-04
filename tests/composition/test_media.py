"""Physical-sheet reconciliation, unchanged content, tickets and workflow handoff."""
import copy
import csv
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
import pytest

from composition.data.sequences import sequence_record
from composition.engine.renderer import render_preview
from composition.media.model import MediaSpec, default_media
from composition.media.planner import PrintPlan, build_print_plan, overlay_plan
from composition.media.ticket import NS, export_print_package, validate_ticket
from composition.overlay.generator import generate as overlay_generate
from composition.overlay.model import OverlayJob
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.production.generator import JobCancelled, generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, Element, PageSpec, SequenceSpec, Template
from composition.template.serializer import load_project, save_project
from composition.worker import dispatch
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.test_mail_merge_workflow import pair, recipe
from tests.test_workflow_core import configured, fixture_pdf
from workflow.batch import BatchRun, approve, execute_batch, prepare
from workflow.engine import execute
from workflow.extraction import ExtractionStore
from workflow.model import WorkflowNode, WorkflowRun, WorkflowSpec
from workflow.registry import default_options


def template(count=3,duplex=False,policy="block"):
    media=default_media()
    media.update(duplex=duplex,blank_policy=policy)
    return Template(pages=[PageSpec(name=f"Page {i+1}",elements=[Element(value=f"Letter page {i+1}: {{{{PageSeq}}}}",width_mm=150)]) for i in range(3)],
        record_mode="generated",generated_count=count,sequences=[SequenceSpec(name="PageSeq",scope="page",padding=3)],media=media)


def csv_rows(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def test_three_stocks_300_letters_and_100000_records_are_lazy():
    model=template(300)
    plan=build_print_plan(model,300)
    assert (plan.output_pages,plan.sheets,plan.inserted_blanks)==(900,900,0)
    assert plan.stock_sheets=={"LH_A":300,"LH_B":300,"LH_C":300}
    assert plan.output_page(900).envelope==300
    assert plan.output_page(900).logical_page==3
    large=build_print_plan(model,100000)
    assert large.output_pages==300000 and not large.output_starts
    assert len(large.patterns)==1 and len(large.patterns[3])==3


def test_dynamic_roles_and_sheet_conflicts():
    raw=default_media()
    raw.update(mode="role",assignments={"SINGLE":"LH_A","FIRST":"LH_A","CONTINUATION":"LH_B","LAST":"LH_C"})
    base=EnvelopePlan(8,EnvelopeSettings(pages_per_envelope=1,groups=[[1,1],[2,3],[4,8]]))
    plan=PrintPlan(base,raw)
    assert [p.fields()["PageRole"] for p in plan.pages()]==["SINGLE","FIRST","LAST","FIRST","CONTINUATION","CONTINUATION","CONTINUATION","LAST"]
    assert plan.stock_sheets=={"LH_A":3,"LH_B":3,"LH_C":2}
    raw.update(duplex=True)
    with pytest.raises(CompositionError,match="Media conflict"):
        PrintPlan(base,raw)
    raw.update(blank_policy="insert")
    plan=PrintPlan(base,raw)
    assert plan.output_pages==14 and plan.inserted_blanks==6
    for first in range(1,plan.output_pages+1,2):
        front,back=plan.output_page(first),plan.output_page(first+1)
        assert (front.stock,front.envelope)==(back.stock,back.envelope)


def test_duplex_same_stock_and_confirmed_blank_sequence():
    model=template(2,True)
    with pytest.raises(CompositionError,match="logical pages 1 and 2"):
        build_print_plan(model,2)
    model.media["blank_policy"]="insert"
    plan=build_print_plan(model,2)
    assert plan.output_pages==12 and plan.sheets==6
    assert [p.logical_page for p in plan.pages()]==[1,None,2,None,3,None]*2
    assert [sequence_record(model,{},2,i)["PageSeq"] for i in range(3)]==["007","009","011"]
    model.media["assignments"]={"1":"LH_A","2":"LH_A","3":"LH_A"}
    plan=build_print_plan(model,2)
    assert plan.output_pages==8 and plan.inserted_blanks==2
    assert sequence_record(model,{},2,2)["PageSeq"]=="007"


@pytest.mark.parametrize("change",[{"stocks":[]},{"assignments":{"1":"missing"}},{"duplex":1},{"media_version":2},
                                   {"stocks":[{"id":"X","name":"X","width_mm":float('nan'),"height_mm":297,"weight_gsm":80}]}])
def test_invalid_declarative_media_is_blocked(change):
    raw=default_media()
    raw.update(change)
    with pytest.raises(CompositionError):
        MediaSpec.from_dict(raw)


def test_unassigned_size_mapping_and_template_ids():
    model=template()
    model.media["assignments"].pop("3")
    with pytest.raises(CompositionError,match="no assigned Stock"):
        build_print_plan(model,1)
    model.media["fallback_stock"]="LH_C"
    assert build_print_plan(model,1).page(1,3).reason=="Explicit fallback"
    model.media["printer_profile"]["mappings"]["LH_C"]={}
    with pytest.raises(CompositionError,match="Catalog mapping"):
        build_print_plan(model,1)
    model.media=default_media()
    model.media.update(mode="template",assignments={p.id:"LH_A" for p in model.pages})
    assert build_print_plan(model,1).stock_sheets=={"LH_A":3}
    model.pages[1].width_mm=148
    with pytest.raises(CompositionError,match="size differs"):
        build_print_plan(model,1)


def test_zero_based_jdf_full_coverage_and_device_pending(tmp_path):
    plan=build_print_plan(template(300),300)
    summary=export_print_package(tmp_path,plan)
    assert summary["device_validation"]=="pending" and summary["sheets"]==900
    data=(tmp_path/"default_ticket.jdf").read_bytes()
    validate_ticket(data,900)
    root=ET.fromstring(data)
    parts=list(root.iter("{"+NS+"}DigitalPrintingParams"))[1:]
    assert any(part.attrib["RunIndex"].split()[0]=="0" for part in parts)
    rows=csv_rows(tmp_path/"media-plan.csv")
    assert rows[0]["File page"]=="1" and rows[-1]["File page"]=="900"
    assert set(row["Stock"] for row in rows)=={"LH_A","LH_B","LH_C"}
    broken=data.replace(b'RunIndex="0 ',b'RunIndex="1 ',1)
    with pytest.raises(CompositionError,match="overlap|omit"):
        validate_ticket(broken,900)
    assert "tray" in (tmp_path/"SUBMISSION.txt").read_text().lower()


@pytest.mark.parametrize("duplex,policy,pages",[(False,"block",9),(True,"insert",18)])
def test_generation_matches_preview_and_reports(tmp_path,duplex,policy,pages):
    model=template(3,duplex,policy)
    before=copy.deepcopy(model.to_dict())
    result=generate(ProductionJob(model.to_dict(),"",str(tmp_path)))
    assert result.status=="completed",result.error
    assert result.generated_pages==pages and result.successful_records==3
    assert model.to_dict()==before
    folder=Path(result.report_dir)
    assert (folder/"default_ticket.jdf").is_file()
    assert result.media_summary["stock_sheets"]=={"LH_A":3,"LH_B":3,"LH_C":3}
    with fitz.open(result.output_pdf) as pdf:
        assert "Letter page 1: 001" in pdf[0].get_text()
        assert f"Letter page 1: {'007' if duplex else '004'}" in pdf[6 if duplex else 3].get_text()
        if duplex:
            assert all(not pdf[i].get_text() for i in range(1,pages,2))
        with fitz.open(stream=render_preview(model,{},ordinal=2,page_index=1),filetype="pdf") as preview:
            index=8 if duplex else 4
            assert pdf[index].get_pixmap().samples==preview[0].get_pixmap().samples
    log=json.loads((folder/"job.json").read_text())
    assert log["page_mapping"]["type"]=="media_print_plan"
    validate_ticket((folder/"default_ticket.jdf").read_bytes(),pages)


def test_media_failure_and_cancel_publish_diagnostics_only(tmp_path):
    result=generate(ProductionJob(template(3,True).to_dict(),"",str(tmp_path)))
    assert result.status=="failed" and "Media conflict" in result.error
    assert result.successful_records==result.generated_files==0
    assert Path(result.report_dir,"job.json").exists()
    cancelled=generate(ProductionJob(template().to_dict(),"",str(tmp_path)),is_cancelled=lambda:True)
    assert cancelled.status=="cancelled"
    assert not list(tmp_path.rglob("*.pdf")) and not list(tmp_path.rglob("*.jdf"))
    with pytest.raises(JobCancelled):
        build_print_plan(template(),2,is_cancelled=lambda:True)


def test_overlay_barcode_scope_and_print_page_counts_follow_media(tmp_path):
    spec=sample_spec(tmp_path)
    spec.media=default_media()
    spec.media.update(duplex=True,blank_policy="insert")
    plan=overlay_plan(spec)
    assert plan.page(1,3).fields()["LetterPage"]=="2"
    assert plan.page(1,3).fields()["PrintPageCount"]=="6"
    result=overlay_generate(OverlayJob(spec.to_dict(),str(tmp_path/"out")))
    assert result.status=="completed",result.error
    assert result.generated_pages==12 and result.decoded_barcodes==6 and result.inserted_blanks==6
    rows=csv_rows(Path(result.report_dir)/"barcodes.csv")
    assert [r["Output page"] for r in rows]==["1","3","5","7","9","11"]
    with fitz.open(spec.source.path) as source,fitz.open(result.output_pdf) as output:
        for index in range(6):
            assert source[index].get_pixmap(clip=fitz.Rect(0,180,595,842)).samples==output[index*2].get_pixmap(clip=fitz.Rect(0,180,595,842)).samples
    spec.media["blank_policy"]="block"
    failure=overlay_generate(OverlayJob(spec.to_dict(),str(tmp_path/"out")))
    assert failure.status=="failed" and "Media conflict" in failure.error
    assert Path(failure.report_dir,"job.json").exists()


def test_versions_keep_legacy_media_disabled_and_reject_downgrade(tmp_path):
    original=template()
    raw=original.to_dict()
    raw.update(template_version=9,media={})
    migrated=Template.from_dict(raw)
    assert not migrated.media
    path=save_project(original,tmp_path/"media.pdcx")
    assert load_project(path).media==original.media
    raw["media"]=default_media()
    with pytest.raises(CompositionError,match="version"):
        Template.from_dict(raw)
    legacy=WorkflowSpec.mail_merge()
    with pytest.raises(CompositionError):
        legacy.upgraded().insert_after(legacy.node("template").id,WorkflowNode("media_assignment",params=default_media())).validate()
    spec=legacy.upgraded(4).insert_after(legacy.node("template").id,WorkflowNode("media_assignment",params=default_media()))
    assert WorkflowSpec.from_dict(spec.to_dict()).workflow_version==4
    with pytest.raises(CompositionError,match="before"):
        spec.insert_after(spec.node("media_assignment").id,WorkflowNode("sort_records",params=default_options("sort_records")))


def test_template_media_without_workflow_node_and_split_packages(tmp_path):
    job=pair(tmp_path,pages=3,records=3)
    model=load_project(job.template_path)
    model.media=default_media()
    model.media.update(duplex=True,blank_policy="insert")
    save_project(model,job.template_path)
    spec=recipe([job])
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
    assert job.status=="Needs review",job.error
    assert job.expected_pages==18
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"normal")
    assert job.status=="Completed",job.error
    job=pair(tmp_path,"SPLIT",pages=3,records=3)
    spec=recipe([job]).upgraded(4)
    spec=spec.insert_after(spec.node("template").id,WorkflowNode("media_assignment",params=model.media))
    spec=spec.insert_after(spec.node("media_assignment").id,WorkflowNode("running_sequence",params={**default_options("running_sequence"),"scope":"page"}))
    spec=spec.insert_after(spec.node("running_sequence").id,WorkflowNode("split_output",params={"method":"count","count":1}))
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"split-check")
    assert job.status=="Needs review",job.error
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"split")
    assert job.status=="Completed",job.error
    files=job.result["output_files"]
    assert len(files)==3 and all(f["pages"]==6 for f in files)
    for index,item in enumerate(files):
        folder=Path(item["output_pdf"]).parent
        validate_ticket((folder/"default_ticket.jdf").read_bytes(),6)
        assert (folder/"job.json").is_file()
        rows=csv_rows(folder/"media-plan.csv")
        assert rows[0]["File page"]=="1" and rows[-1]["File page"]=="6"
        assert rows[0]["Global output page"]==str(index*6+1)


def test_pdf_workflow_media_to_offline_output(tmp_path):
    spec=configured(fixture_pdf(tmp_path/"source.pdf"),tmp_path/"output").upgraded(4)
    media=default_media()
    media.update(duplex=True,blank_policy="insert")
    spec=spec.insert_after(spec.node("review").id,WorkflowNode("media_assignment",params=media))
    run=execute(spec,WorkflowRun(),tmp_path/"scratch",until="review")
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    result=execute(spec,run,tmp_path/"scratch",until="output")
    assert result.output["status"]=="completed",result.error
    assert result.output["generated_pages"]==12
    folder=Path(result.output["report_dir"])
    validate_ticket((folder/"default_ticket.jdf").read_bytes(),12)


def test_background_preview_is_bounded_and_uses_physical_pages():
    model=template(100000,True,"insert")
    result=dispatch({"task":"media_preview","context":{"kind":"template","project":model.to_dict(),"records":100000},
                     "media":model.media,"start":599801})
    assert result["pages"]==600000 and len(result["rows"])==200
    assert result["rows"][-1][0]==600000 and result["rows"][-1][5]=="BLANK"


def test_split_ticket_size_limit_is_per_output_not_global(tmp_path):
    job=pair(tmp_path,"LIMIT",pages=3,records=300)
    model=load_project(job.template_path)
    model.media=default_media()
    model.media["printer_profile"]["max_ticket_bytes"]=4096
    save_project(model,job.template_path)
    plan=build_print_plan(model,300)
    unsplit=tmp_path/"unsplit"
    unsplit.mkdir()
    with pytest.raises(CompositionError,match="size limit"):
        export_print_package(unsplit,plan)
    spec=recipe([job]).upgraded(4)
    spec=spec.insert_after(spec.node("template").id,WorkflowNode("split_output",params={"method":"count","count":100}))
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
    assert job.status=="Needs review",job.error
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"split")
    assert job.status=="Completed",job.error
    for item in job.result["output_files"]:
        ticket=Path(item["output_pdf"]).parent/"default_ticket.jdf"
        assert ticket.stat().st_size<=4096
        validate_ticket(ticket.read_bytes(),300)
