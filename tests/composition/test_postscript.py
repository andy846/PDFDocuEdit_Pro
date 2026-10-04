"""Declarative PS profiles, actual conversion and production publication checks."""
import copy
import csv
import json
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest

from composition.media.model import PrinterProfile, default_media
from composition.media.planner import build_print_plan
from composition.media.postscript import (
    _run,
    export_paper_test,
    ghostscript_executable,
    program_dsc,
    ps_string,
    selection_request,
)
from composition.overlay.generator import generate as overlay_generate
from composition.overlay.model import OverlayJob
from composition.production.generator import JobCancelled, generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, Element, FontSpec, PageSpec, Template
from composition.template.serializer import load_project, save_project
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.test_mail_merge_workflow import pair, recipe
from workflow.batch import BatchRun, approve, execute_batch, prepare
from workflow.model import WorkflowNode


def ps_media(mode="attributes", *, duplex=False):
    media=default_media()
    media.update(duplex=duplex,blank_policy="insert" if duplex else "block")
    media["printer_profile"]=asdict(PrinterProfile(profile_version=2,backend="postscript",family="generic",
        profile_name="Test environment",selection_mode=mode,mappings={s["id"]:{"name":"","catalog_id":"","media_type":s["id"],"media_color":"white",
         "media_position":i} for i,s in enumerate(media["stocks"])}))
    return media


def rows(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def model(media, count=2):
    return Template(record_mode="generated",generated_count=count,media=media,
        pages=[PageSpec(elements=[Element(value=f"Letter page {i+1}")]) for i in range(3)])


def test_legacy_profile_and_v2_project_roundtrip(tmp_path):
    legacy={"profile_version":1,"backend":"canon_prismasync","family":"vp6000",
            "mappings":{"LH_A":{"name":"Paper A","catalog_id":""}}}
    assert PrinterProfile.from_dict(legacy).backend=="canon_prismasync"
    template=model(ps_media("tray"))
    path=save_project(template,tmp_path/"letter.pdcx")
    assert load_project(path).media==template.media


@pytest.mark.parametrize("key,value",[("profile_version",True),("profile_version",1),("selection_mode","exec"),
    ("resolution_dpi",0),("tumble",1),("validation","verified"),("commands","quit")])
def test_invalid_profile_does_not_accept_executable_options(key,value):
    raw=ps_media()["printer_profile"]
    raw[key]=value
    with pytest.raises(CompositionError):
        PrinterProfile.from_dict(raw)


@pytest.mark.parametrize("position",[-1,True,"0",1.5,10000])
def test_invalid_tray_number(position):
    raw=ps_media("tray")["printer_profile"]
    raw["mappings"]["LH_A"]["media_position"]=position
    with pytest.raises(CompositionError):
        PrinterProfile.from_dict(raw)


@pytest.mark.parametrize("mode",["attributes","tray"])
def test_missing_and_indistinguishable_stock_requests_block_preflight(mode):
    media=ps_media(mode)
    media["printer_profile"]["mappings"]["LH_A"]={}
    with pytest.raises(CompositionError,match="configure"):
        build_print_plan(model(media),2)
    media=ps_media(mode)
    media["printer_profile"]["mappings"]["LH_B"]=copy.deepcopy(media["printer_profile"]["mappings"]["LH_A"])
    with pytest.raises(CompositionError,match="identical"):
        build_print_plan(model(media),2)


def test_zero_tray_is_valid_and_strings_are_literals():
    media=ps_media("tray")
    request=selection_request(PrinterProfile.from_dict(media["printer_profile"]),media["stocks"][0])
    assert request["MediaPosition"]==0 and request["MediaWeight"] is None
    assert ps_string("田()\\")==r"(\347\224\260\050\051\134)"


@pytest.mark.parametrize("mode",["attributes","tray"])
@pytest.mark.parametrize("duplex",[False,True])
def test_actual_ps_production_page_mapping_and_duplex(mode,duplex,tmp_path):
    template=model(ps_media(mode,duplex=duplex))
    result=generate(ProductionJob(template.to_dict(),"",str(tmp_path)))
    assert result.status=="completed",result.error
    folder=Path(result.report_dir)
    ps=Path(result.output_ps)
    assert ps.is_file() and not (folder/"default_ticket.jdf").exists()
    assert result.generated_pages==(12 if duplex else 6)
    assert result.media_summary["postscript_pages"]==result.generated_pages
    assert json.loads((folder/"job.json").read_text())["output_ps"]==str(ps)
    audit=rows(folder/"postscript-pages.csv")
    assert [r["Stock"] for r in audit]==(["LH_A","LH_A","LH_B","LH_B","LH_C","LH_C"]*2 if duplex else ["LH_A","LH_B","LH_C"]*2)
    assert sum(r["Selection programmed"]=="True" for r in audit)==6
    requests=[json.loads(r["Request JSON"]) for r in audit if r["Selection programmed"]=="True"]
    assert requests[0]["Duplex"] is duplex
    assert [r["MediaPosition"] for r in requests]==[0,1,2]*2 if mode=="tray" else [r["MediaType"] for r in requests]==["LH_A","LH_B","LH_C"]*2
    with fitz.open(result.output_pdf) as document:
        assert "Letter page 1" in document[0].get_text()
    assert not list(folder.glob(".postscript-*"))


def test_ps_interpretation_keeps_chinese_and_barcode_visuals(tmp_path):
    from composition.overlay.qc import check_mark

    template=model(ps_media(),count=1)
    template.pages[0].elements=[Element(value="田 中文 ABC",font=FontSpec(family="Noto Sans CJK HK"),width_mm=120,height_mm=20),
        Element(type="i25",value="000100",x_mm=20,y_mm=80,width_mm=80,height_mm=20)]
    result=generate(ProductionJob(template.to_dict(),"",str(tmp_path)))
    assert result.status=="completed",result.error
    checked=tmp_path/"interpreted.pdf"
    _run(ghostscript_executable(),["-sDEVICE=pdfwrite",f"-sOutputFile={checked}","-f",result.output_ps],tmp_path,None)
    with fitz.open(result.output_pdf) as source,fitz.open(checked) as target:
        # Compare visual ink, not PS text extraction metadata (CMaps may change).
        clip=fitz.Rect(20*72/25.4,20*72/25.4,140*72/25.4,40*72/25.4)
        a=source[0].get_pixmap(clip=clip,colorspace=fitz.csGRAY).samples
        b=target[0].get_pixmap(clip=clip,colorspace=fitz.csGRAY).samples
        assert len(a)==len(b)
        assert sum(abs(x-y) for x,y in zip(a,b,strict=True))/len(a)<3
        assert check_mark(target[0],{"object":"test","symbology":"i25","payload":"000100",
                                    "rect":[20*72/25.4,80*72/25.4,100*72/25.4,100*72/25.4]})


def test_overlay_ps_and_paper_proof_literal_escape(tmp_path):
    spec=sample_spec(tmp_path)
    spec.media=ps_media("tray")
    result=overlay_generate(OverlayJob(spec.to_dict(),str(tmp_path/"output")))
    assert result.status=="completed",result.error
    assert Path(result.output_ps).is_file() and result.media_summary["postscript_pages"]==6
    media=ps_media()
    media["printer_profile"]["mappings"]["LH_A"]["media_type"]=") quit ("
    proof=export_paper_test(tmp_path/"paper-test.ps",media)
    assert proof["pages"]==3 and Path(proof["path"]).is_file()
    assert not list(tmp_path.glob(".paper-test-*"))


def test_split_ps_is_rebased_and_has_one_output_per_package(tmp_path):
    job=pair(tmp_path,pages=3,records=2)
    template=load_project(job.template_path)
    template.media=ps_media("tray",duplex=True)
    save_project(template,job.template_path)
    spec=recipe([job]).upgraded(4)
    spec=spec.insert_after(spec.node("template").id,WorkflowNode("split_output",params={"method":"count","count":1}))
    run=prepare(spec,BatchRun(jobs=[job]),tmp_path/"check")
    assert job.status=="Needs review",job.error
    approve(run,[job.id])
    execute_batch(spec,run,tmp_path/"split")
    assert job.status=="Completed",job.error
    assert len(job.result["output_files"])==2
    assert job.result["output_ps"]==job.result["output_files"][0]["output_ps"]
    for index,item in enumerate(job.result["output_files"]):
        folder=Path(item["output_pdf"]).parent
        assert Path(item["output_ps"]).is_file() and not (folder/"default_ticket.jdf").exists()
        audit=rows(folder/"postscript-pages.csv")
        assert [r["File page"] for r in audit]==[str(i) for i in range(1,7)]
        mapping=rows(folder/"media-plan.csv")
        assert mapping[0]["Global output page"]==str(index*6+1)


def test_late_cancel_does_not_publish_completed_ps(tmp_path):
    template=model(ps_media(),count=1)
    cancelled=False
    def reports(*args):
        nonlocal cancelled
        cancelled=True
    result=generate(ProductionJob(template.to_dict(),"",str(tmp_path)),additional_reports=reports,is_cancelled=lambda:cancelled)
    assert result.status=="cancelled" and not result.output_ps and not result.output_pdf
    folder=Path(result.report_dir)
    assert not list(folder.glob("*.ps")) and not list(folder.glob("*.pdf"))
    assert not (folder/"postscript-report.json").exists()
    assert json.loads((folder/"media-summary.json").read_text())["postscript_validation"]=="not_published"


def test_converter_cancel_terminates_its_process(tmp_path,monkeypatch):
    import subprocess

    import composition.media.postscript as module

    created=[]
    popen=subprocess.Popen
    def spawn(*args,**kwargs):
        process=popen(*args,**kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(module.subprocess,"Popen",spawn)
    checks=0
    def cancel():
        nonlocal checks
        checks+=1
        return checks>=3
    with pytest.raises(JobCancelled):
        _run(ghostscript_executable(),["-sDEVICE=nullpage","-c","{} loop"],tmp_path,cancel)
    assert created and created[0].poll() is not None


def test_dsc_mismatch_blocks_ps(tmp_path):
    raw=tmp_path/"bad.ps"
    raw.write_bytes(b"%!PS-Adobe-3.0\n%%EndProlog\n%%Page: 1 1\n%%BeginPageSetup\n%%Page: 3 3\n")
    media=ps_media()
    with pytest.raises(CompositionError,match="order"):
        program_dsc(raw,tmp_path/"output.ps",[[1,1,1,1,1,"SINGLE",1,"Front","LH_A",""]],media,1,tmp_path/"audit.csv")


@pytest.mark.parametrize("failure",["missing_converter","conversion_failure"])
def test_converter_failure_never_publishes_production(tmp_path,monkeypatch,failure):
    import composition.media.postscript as module

    def fail(*args,**kwargs):
        raise CompositionError("Unavailable converter" if failure=="missing_converter" else "Conversion failure")
    monkeypatch.setattr(module,"ghostscript_executable" if failure=="missing_converter" else "_run",fail)
    result=generate(ProductionJob(model(ps_media()).to_dict(),"",str(tmp_path)))
    assert result.status=="failed" and not result.output_ps and not result.output_pdf
    assert not list(Path(result.report_dir).glob("*.ps"))
    assert not list(Path(result.report_dir).glob("*.pdf"))
    assert not list(tmp_path.glob(".composition-*"))
    if failure=="missing_converter":
        assert result.processed_records==0


def test_output_folder_percent_pattern_is_not_converter_numbering(tmp_path):
    result=generate(ProductionJob(model(ps_media(),1).to_dict(),"",str(tmp_path/"Room %03d")))
    assert result.status=="completed",result.error
    assert Path(result.output_ps).is_file()
    assert Path(result.output_ps).is_relative_to(tmp_path/"Room %03d")
