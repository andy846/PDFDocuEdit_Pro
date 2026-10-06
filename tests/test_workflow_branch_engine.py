import copy
import csv
import json
from pathlib import Path

import fitz
import pytest

from composition.template.model import CompositionError, Element, PageSpec, Template
from composition.template.serializer import save_project
from workflow.branch_engine import approve_routes, execute_routes, prepare_routes, rows
from workflow.branch_graph import add_route, edge
from workflow.model import WorkflowNode, WorkflowSpec


def fixture(tmp_path,records=4):
    first=save_project(Template(elements=[Element(value="A {{Name}} / {{WorkflowSeq}}")]),tmp_path/"a.pdcx")
    second=save_project(Template(pages=[PageSpec(elements=[Element(value="B {{Name}} / {{WorkflowSeq}}")]),PageSpec(elements=[Element(value="Second page")])]),tmp_path/"b.pdcx")
    model=WorkflowSpec.branched_mail_merge()
    route=model.node("route")
    route.params["routes"]=[{"id":"letters","name":"A","fallback":False,
                              "condition":{"conditions":[{"field":"Scheme","operator":"eq","value":"A"}]}}]
    model=add_route(model,"B",{"conditions":[{"field":"Scheme","operator":"eq","value":"B"}]})
    paths=list(model.execution_plan().branches.values())
    paths[0][0].params["path"]=str(first)
    paths[1][0].params["path"]=str(second)
    inputs=[]
    for i in range(3):
        data=tmp_path/f"input-{i}.csv"
        data.write_text("Name,Scheme\n"+"".join(f"Customer {i}-{r},{'A' if r%2==0 else 'B'}\n" for r in range(records)),encoding="utf-8")
        inputs.append({"id":f"source_{i}","path":str(data),"options":{}})
    model.node("for_each").params["items"]=inputs
    return model


def test_three_files_two_templates_sequence_reconciliation_and_real_generation(tmp_path):
    model=fixture(tmp_path)
    run=prepare_routes(model,tmp_path/"workspace")
    assert (run["input"],run["routed"],run["exceptions"],run["excluded"])==(12,12,0,0)
    assert len(run["jobs"])==6 and all(j["status"]=="Needs review" for j in run["jobs"])
    assert not (tmp_path/"output").exists()
    evidence=rows(model,run,tmp_path/"workspace")
    assert [r["sequence"] for r in evidence["rows"]]==[str(i).zfill(6) for i in range(1,13)]
    approve_routes(model,run,[j["id"] for j in run["jobs"]])
    completed=execute_routes(model,run,tmp_path/"workspace",tmp_path/"output")
    assert completed["status"]=="Completed"
    assert all(j["status"]=="Completed" for j in completed["jobs"])
    pages=0
    for entry in completed["jobs"]:
        job=entry["batch"]["jobs"][0]
        with fitz.open(job["result"]["output_pdf"]) as pdf:
            pages+=len(pdf)
            assert "Customer" in pdf[0].get_text()
    assert pages==18
    assert completed["published_records"]==12 and completed["unpublished_records"]==0
    assert Path(completed["report_dir"],"record-reconciliation.csv").is_file()
    with Path(completed["report_dir"],"record-reconciliation.csv").open(encoding="utf-8-sig",newline="") as stream:
        mapping=list(csv.DictReader(stream))
    assert len(mapping)==12 and all(Path(r["output_pdf"]).is_file() for r in mapping)
    assert set(int(r["last_output_page"])-int(r["first_output_page"])+1 for r in mapping)=={1,2}
    rerun=prepare_routes(model,tmp_path/"workspace",previous=completed)
    assert all(j["status"]=="Completed" for j in rerun["jobs"])


def test_unmatched_ambiguous_and_invalid_rows_require_acknowledgement(tmp_path):
    model=fixture(tmp_path)
    first=Path(model.node("for_each").params["items"][0]["path"])
    first.write_text("Name,Scheme\nValid,A\nUnknown,X\n,B\n",encoding="utf-8")
    seq=model.node("batch_sequence")
    route=model.node("route")
    validation=WorkflowNode("validate_data",params={"checks":[{"field":"Name","check":"required"}]})
    model.edges=[e for e in model.edges if e["source"]!=seq.id]
    model.nodes.append(validation)
    model.edges += [edge(seq.id,validation.id),edge(validation.id,route.id)]
    run=prepare_routes(model,tmp_path/"workspace")
    assert run["exceptions"]==2 and run["candidates"]==11
    with pytest.raises(CompositionError,match="Acknowledge"):
        approve_routes(model,run,[j["id"] for j in run["jobs"]])
    approve_routes(model,run,[j["id"] for j in run["jobs"]],acknowledge=True)
    completed=execute_routes(model,run,tmp_path/"workspace",tmp_path/"output")
    assert completed["status"]=="Completed with exceptions"
    exception_rows=rows(model,run,tmp_path/"workspace",branch_id="exceptions")
    assert [r["sequence"] for r in exception_rows["rows"]]==["000002","000003"]
    assert "published" in Path(completed["report_dir"],"record-reconciliation.csv").read_text(encoding="utf-8-sig")
    model=copy.deepcopy(model)
    model=add_route(model,"Duplicate A",{"conditions":[{"field":"Scheme","operator":"eq","value":"A"}]})
    run=prepare_routes(model,tmp_path/"workspace")
    issues=rows(model,run,tmp_path/"workspace",view="issues",search="Multiple route")
    assert issues["total"]>0


def test_step_check_never_publishes_and_blocks_approval(tmp_path):
    model=fixture(tmp_path)
    target=model.node("route").id
    run=prepare_routes(model,tmp_path/"workspace",target_id=target)
    assert not any(j["batch"] for j in run["jobs"])
    assert not list((tmp_path/"workspace").rglob("*.ps"))
    with pytest.raises(CompositionError,match="entire graph"):
        approve_routes(model,run,[])
    with pytest.raises(CompositionError,match="Step inspections"):
        execute_routes(model,run,tmp_path/"workspace",tmp_path/"output")
    assert not (tmp_path/"output").exists()


def test_source_and_branch_changes_invalidate_evidence_and_approval(tmp_path):
    model=fixture(tmp_path)
    run=prepare_routes(model,tmp_path/"workspace")
    model.node("compose").params["auto_repair"]=False
    with pytest.raises(CompositionError,match="Branch settings"):
        approve_routes(model,run,[run["jobs"][0]["id"]])
    source=Path(model.node("for_each").params["items"][1]["path"])
    source.write_text(source.read_text()+"Added,A\n",encoding="utf-8")
    with pytest.raises(CompositionError,match="Sources or shared"):
        rows(model,run,tmp_path/"workspace")


def test_cancel_retains_checked_results_without_approval(tmp_path):
    model=fixture(tmp_path)
    stopped=False
    def state(_):
        nonlocal stopped
        stopped=True
    run=prepare_routes(model,tmp_path/"workspace",is_cancelled=lambda:stopped,on_state=state)
    assert run["status"]=="Cancelled" and run["routed"]==4
    assert rows(model,run,tmp_path/"workspace")["total"]==4
    with pytest.raises(CompositionError,match="entire graph"):
        approve_routes(model,run,[j["id"] for j in run["jobs"]])


def test_results_are_paged_without_loading_all_records(tmp_path):
    model=fixture(tmp_path,records=125)
    run=prepare_routes(model,tmp_path/"workspace",target_id=model.node("route").id)
    result=rows(model,run,tmp_path/"workspace",offset=50)
    assert result["total"]==375 and len(result["rows"])==50
    assert result["rows"][0]["source_record"]==51
    assert json.loads(Path(run["directory"],"run.json").read_text())["routed"]==375


def test_cross_file_unique_validation_and_attributed_step_issues(tmp_path):
    model=fixture(tmp_path)
    source=Path(model.node("for_each").params["items"][1]["path"])
    source.write_text(source.read_text().replace("Customer 1-0","Customer 0-0"),encoding="utf-8")
    seq=model.node("batch_sequence")
    route=model.node("route")
    first=WorkflowNode("validate_data",params={"checks":[{"field":"Scheme","check":"required"}]})
    second=WorkflowNode("validate_data",params={"checks":[{"field":"Name","check":"unique"}]})
    model.nodes.extend((first,second))
    model.edges=[e for e in model.edges if e["source"]!=seq.id]+[edge(seq.id,first.id),edge(first.id,second.id),edge(second.id,route.id)]
    run=prepare_routes(model,tmp_path/"work")
    assert run["exceptions"]==2 and run["routed"]==10
    assert rows(model,run,tmp_path/"work",view="issues",node_id=first.id)["total"]==0
    issues=rows(model,run,tmp_path/"work",view="issues",node_id=second.id)
    assert issues["total"]==2 and all(r["node_id"]==second.id for r in issues["rows"])
    partial=prepare_routes(model,tmp_path/"work",target_id=second.id)
    assert rows(model,partial,tmp_path/"work",view="issues",node_id=second.id)["total"]==2


def test_mapping_sort_filter_sequence_evidence_preserves_source_identity(tmp_path):
    model=fixture(tmp_path)
    model.node("mapping").params={"aliases":{"Name":"Customer"}}
    # Templates reference aliases; data import remains unchanged.
    for path in model.execution_plan().branches.values():
        file=Path(path[0].params["path"])
        file.write_text(file.read_text().replace("{{Name}}","{{Customer}}"),encoding="utf-8")
    mapping=model.node("mapping")
    seq=model.node("batch_sequence")
    sort=WorkflowNode("sort_records",params={"keys":[{"field":"Customer","descending":True}]})
    filtered=WorkflowNode("filter_records",params={"conditions":[{"field":"Scheme","operator":"eq","value":"B"}]})
    model.nodes.extend((sort,filtered))
    model.edges=[e for e in model.edges if e["source"]!=mapping.id]+[edge(mapping.id,sort.id),edge(sort.id,filtered.id),edge(filtered.id,seq.id)]
    model.node("for_each").params["items"][0]["id"]="z_first"
    run=prepare_routes(model,tmp_path/"work")
    assert (run["input"],run["excluded"],run["candidates"],run["routed"])==(12,6,6,6)
    before=rows(model,run,tmp_path/"work",node_id=mapping.id,view="input")
    after=rows(model,run,tmp_path/"work",node_id=mapping.id,view="output")
    assert "Name" in before["fields"] and "Customer" in after["fields"]
    evidence=rows(model,run,tmp_path/"work")
    assert evidence["rows"][0]["source_id"]=="z_first" and evidence["rows"][0]["source_record"]==4
    assert [r["sequence"] for r in evidence["rows"]]==[f"{i:06d}" for i in range(1,7)]
    result=rows(model,run,tmp_path/"work",node_id=sort.id,search="Customer 0-3")
    assert result["total"]==1 and result["rows"][0]["source_record"]==4


def test_check_source_with_disconnected_downstream_and_blocked_file(tmp_path):
    model=fixture(tmp_path)
    root=model.node("for_each")
    model.edges=[e for e in model.edges if e["source"]!=root.id]
    run=prepare_routes(model,tmp_path/"work",target_id=root.id)
    assert run["input"]==12 and not run["jobs"]
    assert rows(model,run,tmp_path/"work",node_id=root.id)["total"]==12
    model=fixture(tmp_path)
    Path(model.node("for_each").params["items"][1]["path"]).unlink()
    run=prepare_routes(model,tmp_path/"work")
    assert run["sources"][1]["status"]=="Blocked"
    with pytest.raises(CompositionError,match="Acknowledge"):
        approve_routes(model,run,[j["id"] for j in run["jobs"]])


def test_completed_branches_retained_after_other_branch_template_edit(tmp_path):
    model=fixture(tmp_path)
    run=prepare_routes(model,tmp_path/"work")
    approve_routes(model,run,[j["id"] for j in run["jobs"]])
    run=execute_routes(model,run,tmp_path/"work",tmp_path/"output")
    branches=model.execution_plan().branches
    second=list(branches)[1]
    template_file=Path(branches[second][0].params["path"])
    template_file.write_text(template_file.read_text().replace("Second page","Edited page"),encoding="utf-8")
    checked=prepare_routes(model,tmp_path/"work",previous=run)
    assert all(j["status"]==("Needs review" if j["branch_id"]==second else "Completed") for j in checked["jobs"])


def test_critical_font_error_blocks_only_affected_child_and_locates_record(tmp_path):
    model=fixture(tmp_path)
    first=Path(model.node("for_each").params["items"][0]["path"])
    first.write_text(first.read_text().replace("Customer 0-0","田"),encoding="utf-8")
    model.node("compose").params["auto_repair"]=False
    run=prepare_routes(model,tmp_path/"work")
    assert run["jobs"][0]["status"]=="Blocked" and "U+7530" in run["jobs"][0]["error"]
    assert all(j["status"]=="Needs review" for j in run["jobs"][1:])
    issues=rows(model,run,tmp_path/"work",view="issues",branch_id="letters")
    assert issues["rows"][0]["source_record"]==1
    assert issues["rows"][0]["node_id"]==model.node("compose").id
    with pytest.raises(CompositionError,match="Acknowledge"):
        approve_routes(model,run,[j["id"] for j in run["jobs"]])


def test_cancel_production_retains_first_output_and_manually_continues(tmp_path):
    model=fixture(tmp_path)
    run=prepare_routes(model,tmp_path/"work")
    approve_routes(model,run,[j["id"] for j in run["jobs"]])
    stopped=False
    def state(value):
        nonlocal stopped
        if value.get("branch_job"):
            stopped=True
    cancelled=execute_routes(model,run,tmp_path/"work",tmp_path/"output",is_cancelled=lambda:stopped,on_state=state)
    assert cancelled["status"]=="Cancelled" and cancelled["jobs"][0]["status"]=="Completed"
    first_pdf=Path(cancelled["jobs"][0]["batch"]["jobs"][0]["result"]["output_pdf"])
    first_content=first_pdf.read_bytes()
    completed=execute_routes(model,cancelled,tmp_path/"work",tmp_path/"output")
    assert completed["status"]=="Completed" and first_pdf.read_bytes()==first_content
