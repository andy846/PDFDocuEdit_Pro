from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import fitz
import pytest

from composition.overlay.model import BarcodeProfile, BarcodeToken, OverlayObject
from composition.overlay.serializer import load_project, save_project
from composition.production.generator import JobCancelled
from composition.template.model import MM_TO_PT, CompositionError, Element
from workflow.engine import execute
from workflow.extraction import ExtractionSpec, ExtractionStore, Region, extract_page, scan_pdf
from workflow.model import WorkflowNode, WorkflowRun, WorkflowSpec
from workflow.serializer import load_workflow, save_workflow
from workflow.worker import dispatch


def fixture_pdf(path,pages=6):
    with fitz.open() as doc:
        for number in range(pages):
            page=doc.new_page(width=210*MM_TO_PT,height=297*MM_TO_PT)
            page.insert_text((60,65),f"Account: {(number//3)+1:05}")
            page.insert_text((60,100),f"Page {number%3+1} of 3")
            page.insert_text((60,145),"田先生",fontname="china-s")
        doc.save(path)
    return path


def configured(path,output):
    spec=WorkflowSpec.default()
    spec.node("input").params={"paths":[str(path)]}
    spec.node("extract").params=ExtractionSpec([Region(y_mm=15,height_mm=12,remove_label="Account: ",format="digits",envelope_value="consistent")]).to_dict()
    spec.node("group").params={"method":"field","field":"Account_No"}
    overlay=spec.node("overlay")
    incoming=next(a for a,b in spec.edges if b==overlay.id)
    outgoing=next(b for a,b in spec.edges if a==overlay.id)
    spec.edges=[e for e in spec.edges if overlay.id not in e]+[[incoming,outgoing]]
    spec.nodes.remove(overlay)
    spec.node("output").params={"directory":str(output)}
    return spec


def test_extraction_unicode_zeros_raw_and_review(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    regions=[Region(y_mm=15,height_mm=12,remove_label="Account: ",format="digits"),
             Region(name="Name",y_mm=45,height_mm=12)]
    result=scan_pdf(source,ExtractionSpec(regions),tmp_path/"data.sqlite")
    with ExtractionStore(result.database) as store:
        assert store.values(1)=={"Account_No":"00001","Name":"田先生"}
        assert store.page(1)[0]["raw"].startswith("Account:")
        store.grouped([[1,3],[4,6]],ExtractionSpec(regions))
        store.accept()
        assert store.metadata()["accepted"]=="true"
        store.correct(1,"Account_No","00123","Operator verified the original")
        assert store.metadata()["accepted"]=="false"
        assert store.db.execute("SELECT old_value,new_value FROM edits").fetchone()[0]=="00001"


@pytest.mark.parametrize("rotation",[0,90,180,270])
def test_region_coordinates_rotation_crop_and_size_mismatch(tmp_path,rotation):
    path=fixture_pdf(tmp_path/"source.pdf",3)
    with fitz.open(path) as pdf:
        page=pdf[0]
        page.set_cropbox(fitz.Rect(20,30,page.rect.width-20,page.rect.height-30))
        page.set_rotation(rotation)
        found=page.search_for("00001")[0]*page.rotation_matrix
        found=found+(-1,-1,1,1)
        region=Region(name="Id",x_mm=found.x0/MM_TO_PT,y_mm=found.y0/MM_TO_PT,
                      width_mm=found.width/MM_TO_PT,height_mm=found.height/MM_TO_PT,
                      page_width_mm=page.rect.width/MM_TO_PT,page_height_mm=page.rect.height/MM_TO_PT)
        assert extract_page(page,region)[1]=="00001"
        region.page_width_mm+=10
        assert "size differs" in extract_page(page,region)[2]


def test_scopes_consistency_and_audited_corrections(tmp_path):
    path=fixture_pdf(tmp_path/"source.pdf")
    spec=ExtractionSpec([Region(y_mm=15,height_mm=12,remove_label="Account: ",envelope_value="consistent")])
    result=scan_pdf(path,spec,tmp_path/"data.sqlite")
    with ExtractionStore(result.database) as store:
        store.grouped([[1,6]],spec)
        assert store.issues()==1
        with pytest.raises(CompositionError,match="Resolve"):
            store.accept()
        spec.regions[0].scope="first"
        store.grouped([[1,6]],spec)
        assert store.issues()==0
        assert store.db.execute("SELECT SUM(applicable) FROM cells").fetchone()[0]==1


def test_graph_validation_and_canvas_positions_are_not_execution_settings():
    spec=WorkflowSpec.default()
    fingerprint=spec.fingerprint()
    spec.nodes[0].x+=300
    assert spec.fingerprint()==fingerprint
    assert len(spec.chain())==6
    raw=spec.to_dict()
    raw["edges"].append([spec.nodes[0].id,spec.nodes[-1].id])
    with pytest.raises(CompositionError):
        WorkflowSpec.from_dict(raw)
    raw=spec.to_dict()
    raw["nodes"][1]["params"]={"regions":[{"name":"__import__('os')"}]}
    with pytest.raises(CompositionError):
        ExtractionSpec.from_dict(raw["nodes"][1]["params"])


def test_end_to_end_review_gate_and_no_barcode_production(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run",until="output")
    assert not run.error
    assert run.groups==[[1,3],[4,6]]
    assert not run.output and not run.accepted
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    result=execute(spec,run,tmp_path/"run",until="output")
    assert not result.error,result.error
    assert result.output["status"]=="completed"
    assert result.output["expected_barcodes"]==0
    assert result.output["generated_pages"]==6
    assert (Path(result.output["report_dir"])/"extracted-data.csv").exists()
    assert json.loads((tmp_path/"run"/"run.json").read_text())["accepted"]
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest


def test_extracted_field_drives_real_barcode_and_preview(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    overlay_path=dispatch({"operation":"make_overlay","source":run.source,"groups":run.groups,
                           "spec":spec.to_dict(),"path":str(tmp_path/"overlay.pdcx")},None,None)["path"]
    project=load_project(overlay_path)
    project.objects=[OverlayObject(Element(type="code128",x_mm=20,y_mm=65,width_mm=90,height_mm=15),
                                   profile=BarcodeProfile(tokens=[BarcodeToken(value="Envelope_Account_No")]))]
    save_project(project,overlay_path)
    from workflow.model import WorkflowNode
    overlay=WorkflowNode("overlay",params={"path":overlay_path})
    spec.nodes.append(overlay)
    review=spec.node("review")
    output=spec.node("output")
    spec.edges.remove([review.id,output.id])
    spec.edges.extend([[review.id,overlay.id],[overlay.id,output.id]])
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    result=execute(spec,run,tmp_path/"run",until="output")
    assert not result.error,result.error
    assert result.output["decoded_barcodes"]==6
    csv=(Path(result.output["report_dir"])/"barcodes.csv").read_text(encoding="utf-8-sig")
    assert "00001" in csv and "00002" in csv


def test_source_change_invalidates_acceptance_and_output_folder_does_not_rescan(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    marker=Path(run.database).stat().st_mtime_ns
    spec.node("output").params["directory"]=str(tmp_path/"other")
    result=execute(spec,run,tmp_path/"run",until="review")
    assert result.accepted and Path(result.database).stat().st_mtime_ns==marker
    with fitz.open(source) as doc:
        doc[0].insert_text((50,200),"Changed")
        doc.saveIncr()
    result=execute(spec,result,tmp_path/"run",until="output")
    assert not result.error and not result.accepted and not result.output


def test_pattern_grouping_and_portable_save(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    spec.node("group").params={"method":"pattern","pattern":"Page {CURRENT} of {TOTAL}"}
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    assert run.groups==[[1,3],[4,6]],run.error
    target=save_workflow(spec,tmp_path/"bundle"/"project.pdflow")
    shutil.copytree(tmp_path/"bundle",tmp_path/"moved")
    source.unlink()
    reopened=load_workflow(tmp_path/"moved"/"project.pdflow")
    assert Path(reopened.node("input").params["paths"][0]).exists()
    assert Path(target).suffix==".pdflow"


def test_cancel_preserves_existing_database_and_reports_failing_page(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    original=source.read_bytes()
    with pytest.raises(CompositionError,match="overwrite"):
        scan_pdf(source,ExtractionSpec([Region()]),source)
    assert source.read_bytes()==original
    target=tmp_path/"data.sqlite"
    target.write_bytes(b"old output")
    calls=[0]
    def cancelled():
        calls[0]+=1
        return calls[0]>2
    with pytest.raises(JobCancelled):
        scan_pdf(source,ExtractionSpec([Region()]),target,is_cancelled=cancelled)
    assert target.read_bytes()==b"old output"
    assert not list(tmp_path.glob(".data-*"))
    spec=configured(source,tmp_path/"output")
    spec.node("extract").params["regions"][0]["y_mm"]=220
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    assert "grouping field" in run.error and not run.output
    assert run.statuses[spec.node("group").id]=="Failed"


def test_merge_selections_preserve_original_source_pages(tmp_path):
    first=fixture_pdf(tmp_path/"first.pdf",3)
    second=fixture_pdf(tmp_path/"second.pdf",3)
    spec=configured(first,tmp_path/"output")
    spec.node("input").params["paths"].append(str(second))
    merge=WorkflowNode("merge",params={"pages":{str(first):"1,3",str(second):"2"}})
    spec.nodes.append(merge)
    spec.edges.remove([spec.node("input").id,spec.node("extract").id])
    spec.edges.extend([[spec.node("input").id,merge.id],[merge.id,spec.node("extract").id]])
    spec.node("group").params={"method":"fixed","pages":1}
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    assert not run.error,run.error
    with ExtractionStore(run.database) as store:
        mapped=list(store.db.execute("SELECT source_file,source_page FROM provenance ORDER BY page"))
        assert [(r[0],r[1]) for r in mapped]==[(str(first),1),(str(first),3),(str(second),2)]


def test_issue_navigation_and_manual_boundary_audit(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    request={"operation":"review","database":run.database,"groups":[[1,6]],"page":1,"action":"groups"}
    result=dispatch(request,None,None)
    assert result["issues"]==1
    result=dispatch({**request,"groups":[[1,6]],"action":"next_issue"},None,None)
    assert result["page"]==4
    with ExtractionStore(run.database) as store:
        assert store.db.execute("SELECT COUNT(*) FROM group_edits").fetchone()[0]==1


def test_no_text_and_critical_validation_do_not_publish(tmp_path):
    source=tmp_path/"blank.pdf"
    with fitz.open() as pdf:
        pdf.new_page(width=210*MM_TO_PT,height=297*MM_TO_PT)
        pdf.save(source)
    result=scan_pdf(source,ExtractionSpec([Region()]),tmp_path/"data.sqlite")
    with ExtractionStore(result.database) as store:
        assert "No extractable text" in store.page(1)[0]["issue"]
        with pytest.raises(CompositionError):
            store.accept()


def test_headless_core_has_no_qt_dependency():
    import subprocess
    import sys
    script="import sys; import workflow.engine; assert not any(n.startswith('PyQt6') for n in sys.modules)"
    subprocess.run([sys.executable,"-c",script],check=True,capture_output=True)


def test_missing_input_is_a_logged_failure_and_clears_stale_approval(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    source.unlink()
    run=execute(spec,WorkflowRun(accepted=True,output={"status":"completed"}),tmp_path/"run")
    assert run.error and not run.accepted and not run.output
    assert run.statuses[spec.node("input").id]=="Failed"
    logged=json.loads((tmp_path/"run"/"run.json").read_text(encoding="utf-8"))
    assert logged["error"]==run.error


def test_missing_overlay_does_not_block_upstream_review(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    overlay=WorkflowNode("overlay",params={"path":str(tmp_path/"missing.pdcx")})
    spec.nodes.append(overlay)
    a,b=spec.node("review").id,spec.node("output").id
    spec.edges.remove([a,b])
    spec.edges.extend([[a,overlay.id],[overlay.id,b]])
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    assert not run.error and run.groups==[[1,3],[4,6]]
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    run=execute(spec,run,tmp_path/"run",until="output")
    assert run.error and run.statuses[overlay.id]=="Failed" and not run.output


def test_missing_database_rebuilds_and_requires_new_review(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    Path(run.database).unlink()
    run=execute(spec,run,tmp_path/"run",until="output")
    assert not run.error and Path(run.database).exists()
    assert not run.accepted and not run.output


def test_production_rejects_boundaries_different_from_reviewed_database(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    with ExtractionStore(run.database) as store:
        store.accept()
    run.accepted=True
    run.groups=[[1,6]]
    run=execute(spec,run,tmp_path/"run",until="output")
    assert "boundaries differ" in run.error and not run.output


@pytest.mark.parametrize("action",["groups","correct"])
def test_cancelled_review_mutation_rolls_back_data_and_audit(tmp_path,action):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    with ExtractionStore(run.database) as store:
        store.accept()
    request={"operation":"review","database":run.database,"groups":[[1,6]],"page":1,"action":action,
             "field":"Account_No","value":"12345","reason":"Operator correction"}
    with pytest.raises(JobCancelled):
        dispatch(request,None,lambda:True)
    with ExtractionStore(run.database) as store:
        assert store.metadata()["accepted"]=="true"
        assert [list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]==[[1,3],[4,6]]
        assert store.values(1)["Account_No"]=="00001"
        assert store.db.execute("SELECT COUNT(*) FROM edits").fetchone()[0]==0
        assert store.db.execute("SELECT COUNT(*) FROM group_edits").fetchone()[0]==0


def test_csv_export_preserves_sources_and_includes_envelope_findings(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    digest=source.read_bytes()
    with ExtractionStore(run.database) as store:
        for path in (source,run.database):
            with pytest.raises(CompositionError,match="overwrite"):
                store.export(path)
        store.grouped([[1,6]],ExtractionSpec.from_dict(spec.node("extract").params))
        store.export(tmp_path/"report.csv")
    import csv
    with (tmp_path/"report.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    assert any(r["Scope"]=="Envelope" and "inconsistent" in r["Issue"] for r in rows)
    assert source.read_bytes()==digest


def test_overlay_binding_keeps_design_and_sequence_and_preview_checks_groups(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    path=dispatch({"operation":"make_overlay","source":run.source,"groups":run.groups,
                   "spec":spec.to_dict(),"path":str(tmp_path/"overlay.pdcx")},None,None)["path"]
    project=load_project(path)
    project.settings.start=20
    project.objects=[OverlayObject(Element(value="{{Envelope_Account_No}}",x_mm=20,y_mm=60))]
    old_object=project.to_dict()["objects"][0]
    groups=[[1,2],[3,3],[4,6]]
    result=dispatch({"operation":"bind_overlay","source":run.source,"groups":groups,"spec":spec.to_dict(),
                     "path":path,"project":project.to_dict()},None,None)
    bound=type(project).from_dict(result["spec"])
    assert bound.settings.groups==groups and bound.settings.start==20
    assert bound.to_dict()["objects"][0]==old_object
    from composition.worker import dispatch as composition_dispatch
    # The GUI preview must never combine new envelope geometry with old envelope values.
    with pytest.raises(ValueError,match="boundaries changed"):
        composition_dispatch({"task":"overlay_preview","project":bound.to_dict(),"external_database":run.database,
                  "envelope":1,"print_page":1,"target":str(tmp_path/"preview.pdf")})


def test_grouping_failure_can_be_corrected_then_retried_without_rescanning(tmp_path):
    source=fixture_pdf(tmp_path/"source.pdf")
    with fitz.open(source) as pdf:
        page=pdf[3]
        for rect in page.search_for("Account: 00002"):
            page.add_redact_annot(rect)
        page.apply_redactions()
        pdf.saveIncr()
    spec=configured(source,tmp_path/"output")
    run=execute(spec,WorkflowRun(),tmp_path/"run")
    assert "Page 4" in run.error and run.database and not run.groups
    result=dispatch({"operation":"review","action":"correct","database":run.database,"groups":[],
                     "page":4,"field":"Account_No","value":"00002","reason":"Verified original account"},None,None)
    assert result["cells"][0]["value"]=="00002" and not result["accepted"]
    run=execute(spec,run,tmp_path/"run")
    assert not run.error and run.groups==[[1,3],[4,6]]
    with ExtractionStore(run.database) as store:
        assert store.db.execute("SELECT COUNT(*) FROM edits").fetchone()[0]==1
