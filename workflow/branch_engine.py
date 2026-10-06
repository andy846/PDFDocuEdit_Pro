"""Disk-backed, exclusive Mail Merge routing and explicit partial-job approval."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import sqlite3
import uuid
from contextlib import ExitStack, closing
from dataclasses import asdict
from pathlib import Path

from composition.data.source import import_records, suggest_import
from composition.production.generator import JobCancelled, check_cancel
from composition.template.model import CompositionError, DataConfig
from composition.template.serializer import file_hash, load_project, save_project
from core.io_atomic import atomic_output

from .batch import BatchJob, BatchRun, _assets, _finished_valid, approve, execute_batch, prepare
from .branch_graph import child_spec
from .registry import DATA_KINDS
from .transforms import DataSet, condition, snapshot, transform


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def common_signature(spec):
    """Global sequence depends on ALL ordered inputs and common settings, not layout."""
    plan=spec.execution_plan(spec.node("route").id)
    files={}
    for item in plan.common[0].params.get("items",[]):
        try:
            files[item["id"]]=file_hash(Path(item["path"]))
        except OSError as exc:
            files[item["id"]]="unavailable:"+str(exc)
    return digest({"nodes":[{"id":n.id,"kind":n.kind,"params":n.params} for n in plan.common],
                   "routing":plan.route.params,"files":files})


def branch_signature(spec,common,branch_id):
    path=spec.execution_plan(spec.node("route").id).branches[branch_id]
    files={}
    template_node=path[0]
    try:
        template=load_project(template_node.params.get("path",""))
        for name in [template_node.params["path"],*_assets(template)]:
            files[str(Path(name).resolve())]=file_hash(Path(name))
    except (ValueError,OSError) as exc:
        files["error"]=str(exc)
    return digest({"common":common,"branch":branch_id,"nodes":[{"id":n.id,"kind":n.kind,"params":n.params} for n in path],"files":files})


def _location(directory,run):
    root=Path(directory).resolve()/"branch-runs"
    location=Path(run.get("directory","")).resolve()
    if location.parent!=root or not location.is_dir():
        raise CompositionError("Checked results are unavailable. Check this workflow again.")
    return location


def _check_current(spec,run):
    if common_signature(spec)!=run.get("signature"):
        raise CompositionError("Sources or shared settings changed. Recheck the entire batch sequence.")


def _source(spec,item,folder,sequence_offset,progress,cancelled,target_id=None):
    plan=spec.execution_plan(target_id or spec.node("route").id)
    options=asdict(suggest_import(item["path"]))
    options.update(spec.node("for_each").params.get("options",{}))
    options.update(item.get("options",{}))
    mapping=next((n for n in plan.common if n.kind=="mapping"),None)
    if mapping:
        options["mapping"]={**options.get("mapping",{}),**mapping.params.get("aliases",{})}
    options["path"]=item["path"]
    imported=import_records(DataConfig(**options),folder/"import.sqlite",progress=progress,is_cancelled=cancelled)
    source=DataSet(imported.path)
    current=snapshot(((identity,value) for _,value,identity in source.rows()),source.fields,folder/"source.sqlite",
                     metadata=source.metadata,is_cancelled=cancelled)
    stages=[{"node_id":plan.common[0].id,"input_store":"","output_store":str(current.path),"input":current.count,"output":current.count}]
    numbered=0
    for node in plan.common[1:]:
        check_cancel(cancelled)
        prior=current
        if node.kind in DATA_KINDS:
            current=transform(current,folder/(node.id+".sqlite"),node.kind,node.params,node_id=node.id,
                              progress=progress,is_cancelled=cancelled)
        elif node.kind=="batch_sequence":
            params=copy.deepcopy(node.params)
            params["start"]=params.get("start",1)+sequence_offset*params.get("step",1)
            current=transform(current,folder/(node.id+".sqlite"),"running_sequence",params,node_id=node.id,
                              progress=progress,is_cancelled=cancelled)
            numbered=current.count
        stages.append({"node_id":node.id,"input_store":str(prior.path),"output_store":str(current.path),
                       "input":prior.count,"output":current.count})
    return imported,current,numbered,stages


def prepare_routes(spec,directory,*,previous=None,target_id=None,progress=None,is_cancelled=None,on_state=None):
    plan=spec.execution_plan(target_id)
    source_node=spec.node("for_each")
    items=source_node.params.get("items",[])
    if not items:
        raise CompositionError("Add data files to For each Data File before checking.")
    run_id=uuid.uuid4().hex[:16]
    root=Path(directory).resolve()/"branch-runs"/run_id
    root.mkdir(parents=True)
    signature=common_signature(spec)
    run={"id":run_id,"batch_id":(previous or {}).get("batch_id",run_id),"signature":signature,
         "directory":str(root),"status":"Checking","sources":[],"jobs":[],"stages":[],"acknowledged":False,
         "input":0,"excluded":0,"candidates":0,"exceptions":0,"routed":0,"target_id":target_id or ""}
    routes=spec.node("route").params["routes"]
    matchers={r["id"]:condition(r["condition"]) for r in routes if not r.get("fallback")}
    fallback=next((r["id"] for r in routes if r.get("fallback")),"")
    sequence_name=spec.node("batch_sequence").params.get("name","WorkflowSeq") if spec.node("batch_sequence") else "WorkflowSeq"
    full=not target_id or plan.target.kind in ("template","media_assignment","mail_review","compose","reports","collect")
    numbered=0
    old={(j["source_id"],j["branch_id"]):j for j in (previous or {}).get("jobs",[])}
    with closing(sqlite3.connect(root/"evidence.sqlite")) as evidence:
        evidence.executescript("""
            PRAGMA temp_store=FILE; PRAGMA cache_size=-4096;
            CREATE TABLE records(source_id TEXT,source_record INTEGER,source_row INTEGER,sequence TEXT,
                branch_id TEXT,job_id TEXT,job_record INTEGER,disposition TEXT,value TEXT,
                PRIMARY KEY(source_id,source_record));
            CREATE TABLE issues(source_id TEXT,source_record INTEGER,source_row INTEGER,node_id TEXT,
                field TEXT,severity TEXT,reason TEXT,sequence TEXT);
        """)
        try:
            prepared_sources=[]
            for item_index,item in enumerate(items,1):
                check_cancel(is_cancelled)
                source_summary={"id":item["id"],"path":item["path"],"status":"Checking","error":""}
                run["sources"].append(source_summary)
                folder=root/f"s{item_index:04d}"
                folder.mkdir()
                try:
                    imported,current,count,stages=_source(spec,item,folder,numbered,progress,is_cancelled,target_id if plan.route is None else None)
                    numbered+=count
                    run["stages"].extend({**s,"source_id":item["id"]} for s in stages)
                    source_summary.update(input=imported.count,candidates=current.count,status="Checked")
                    prepared_sources.append((item_index,item,folder,source_summary,imported,current))
                except JobCancelled:
                    raise
                except (ValueError,OSError) as exc:
                    source_summary.update(status="Blocked",error=str(exc))
            if plan.route is not None:
                _batch_unique(plan,prepared_sources,root,is_cancelled)
            for item_index,item,folder,source_summary,imported,current in prepared_sources:
                check_cancel(is_cancelled)
                try:
                    if plan.route is None:
                        continue
                    run["input"]+=imported.count
                    run["candidates"]+=current.count
                    run["excluded"]+=imported.count-current.count
                    route_counts={r["id"]:0 for r in routes}
                    with ExitStack() as stack,closing(sqlite3.connect(current.path)) as db:
                        db.execute("CREATE INDEX IF NOT EXISTS findings_source ON findings(source_id)")
                        db.commit()
                        db.execute("ATTACH DATABASE ? AS original",(str(imported.path),))
                        writers={}
                        for r in routes:
                            stream=stack.enter_context((folder/(r["id"]+".csv")).open("w",encoding="utf-8-sig",newline=""))
                            writers[r["id"]]=csv.DictWriter(stream,fieldnames=current.fields)
                            writers[r["id"]].writeheader()
                        with closing(sqlite3.connect(imported.path)) as original:
                            excluded=db.execute("SELECT DISTINCT source_id FROM exclusions")
                            for (row,) in excluded:
                                ordinal=original.execute("SELECT ordinal FROM records WHERE source_row=?",(row,)).fetchone()[0]
                                evidence.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",(item["id"],ordinal,row,"","","",0,"excluded","{}"))
                        cursor=db.execute("""SELECT r.ordinal,r.value,r.source_row,o.ordinal FROM records r
                            JOIN original.records o ON o.source_row=r.source_row ORDER BY r.ordinal""")
                        for ordinal,raw,source_row,source_record in cursor:
                            check_cancel(is_cancelled)
                            values=json.loads(raw)
                            seq=values.get(sequence_name,"")
                            findings=list(db.execute("SELECT field,severity,reason FROM findings WHERE source_id=?",(source_row,)))
                            problems=[reason for _,severity,reason in findings if severity=="error"]
                            matches=[]
                            for identity,matcher in matchers.items():
                                try:
                                    if matcher.matches(values):
                                        matches.append(identity)
                                except CompositionError as exc:
                                    problems.append(str(exc))
                            if len(matches)>1:
                                problems.append("Multiple route matches: "+", ".join(matches))
                            branch_id=matches[0] if len(matches)==1 else fallback if not matches else ""
                            if not branch_id and not problems:
                                problems.append("No route matched; no explicit fallback.")
                            for name,severity,reason in findings:
                                evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,
                                    next((n.id for n in plan.common if n.kind=="validate_data"),spec.node("route").id),name,severity,reason,seq))
                            if problems:
                                branch_id=""
                                run["exceptions"]+=1
                                for reason in problems:
                                    evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,spec.node("route").id,"","error",reason,seq))
                                job_id=""
                                job_record=0
                                disposition="exception"
                            else:
                                route_counts[branch_id]+=1
                                job_record=route_counts[branch_id]
                                writers[branch_id].writerow(values)
                                run["routed"]+=1
                                job_id=_job_id(run,item["id"],branch_id)
                                disposition="pending"
                            evidence.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,
                                seq,branch_id,job_id,job_record,disposition,raw))
                            if ordinal%250==0 and progress:
                                progress(ordinal,current.count,f"Routing {Path(item['path']).name}")
                    evidence.commit()
                    for r in routes:
                        if target_id and plan.branches and r["id"] not in plan.branches:
                            continue
                        job_id=_job_id(run,item["id"],r["id"])
                        entry={"id":job_id,"source_id":item["id"],"branch_id":r["id"],"branch_name":r["name"],
                               "records":route_counts[r["id"]],"status":"No records" if not route_counts[r["id"]] else "Checked",
                               "approved":False,"error":"","batch":{},"spec":{},"signature":""}
                        run["jobs"].append(entry)
                        if not full or not entry["records"]:
                            continue
                        entry["signature"]=branch_signature(spec,signature,r["id"])
                        prior=old.get((item["id"],r["id"]))
                        if prior and prior["signature"]==entry["signature"] and prior["status"]=="Completed" and _finished_valid(BatchJob(**prior["batch"]["jobs"][0])):
                            entry.update(copy.deepcopy(prior))
                            continue
                        try:
                            path=plan.branches[r["id"]]
                            template=load_project(path[0].params.get("path",""))
                            if sequence_name in {s.name for s in template.sequences}:
                                raise CompositionError("Batch Sequence conflicts with template sequence: "+sequence_name)
                            template.record_mode="imported"
                            prepared=save_project(template,folder/(r["id"]+".pdcx"))
                            linear=child_spec(plan,r["id"])
                            job=BatchJob(id=job_id,name=f"{item_index:04d} · {r['name']}",template_path=str(prepared),
                                data_path=str(folder/(r["id"]+".csv")),data_options=asdict(DataConfig()),
                                output_name=f"{item_index:04d}-{r['id']}.pdf")
                            job.data_options.pop("path",None)
                            batch=prepare(linear,BatchRun(jobs=[job],batch_id=run["batch_id"]),root/f"j{len(run['jobs']):04d}",
                                          progress=progress,is_cancelled=is_cancelled)
                            entry.update(batch=batch.to_dict(),spec=linear.to_dict(),status=job.status,error=job.error)
                        except JobCancelled:
                            raise
                        except (ValueError,OSError) as exc:
                            entry.update(status="Blocked",error=str(exc))
                except JobCancelled:
                    raise
                except (ValueError,OSError) as exc:
                    source_summary.update(status="Blocked",error=str(exc))
                if progress:
                    progress(item_index,len(items),f"Checked source {item_index}/{len(items)}")
                if on_state:
                    on_state({"branch_source":source_summary})
            if run["input"]!=run["excluded"]+run["candidates"] or run["candidates"]!=run["routed"]+run["exceptions"]:
                raise CompositionError("Routing reconciliation failed; no approval is permitted.")
            run["status"]="Needs review"
        except JobCancelled:
            run["status"]="Cancelled"
        evidence.commit()
    _check_current(spec,run)
    _write_manifest(root,run)
    return run


def _write_manifest(root,run):
    with atomic_output(Path(root)/"run.json") as temp:
        temp.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding="utf-8")


def _job_id(run,source,branch):
    return uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([run["batch_id"],source,branch])).hex


def _batch_unique(plan,sources,root,cancelled):
    """Validate unique fields across the ordered batch without loading all values."""
    checks=[(node,check) for node in plan.common if node.kind=="validate_data"
            for check in node.params.get("checks",[]) if check.get("check")=="unique"]
    if not checks:
        return
    with closing(sqlite3.connect(root/"unique.sqlite")) as global_db:
        global_db.executescript("CREATE TABLE seen(node TEXT,field TEXT,value TEXT,source TEXT,row INTEGER);"
                              "CREATE INDEX unique_key ON seen(node,field,value);")
        for _,item,_,_,_,current in sources:
            for _,values,row in current.rows():
                check_cancel(cancelled)
                for node,check in checks:
                    field=check["field"]
                    value=values.get(field,"")
                    if not value:
                        continue
                    global_db.execute("INSERT INTO seen VALUES(?,?,?,?,?)",(node.id,field,value,item["id"],row))
        global_db.commit()
        global_db.executescript("CREATE TABLE duplicates AS SELECT node,field,value FROM seen GROUP BY node,field,value "
                              "HAVING COUNT(DISTINCT source)>1; CREATE INDEX duplicate_key ON duplicates(node,field,value);")
        severities={(node.id,check["field"]):check.get("severity","error") for node,check in checks}
        for _,item,_,_,_,current in sources:
            with closing(sqlite3.connect(current.path)) as db:
                for node,field,row in global_db.execute("SELECT s.node,s.field,s.row FROM seen s JOIN duplicates d "
                                                       "ON s.node=d.node AND s.field=d.field AND s.value=d.value WHERE s.source=?",(item["id"],)):
                    check_cancel(cancelled)
                    reason="Duplicate value across batch source files"
                    db.execute("INSERT INTO findings(source_id,field,severity,reason) SELECT ?,?,?,? "
                               "WHERE NOT EXISTS(SELECT 1 FROM findings WHERE source_id=? AND field=? AND reason=?)",
                               (row,field,severities[(node,field)],reason,row,field,reason))
                db.commit()


def approve_routes(spec,run,identities,*,acknowledge=False):
    _check_current(spec,run)
    if run.get("target_id") or run["status"]=="Cancelled":
        raise CompositionError("Run Check & Preview for the entire graph before approving production.")
    if (run["exceptions"] or any(s["status"]=="Blocked" for s in run["sources"])) and not acknowledge:
        raise CompositionError("Acknowledge the exceptions and blocked source items before approving normal records.")
    selected=[e for e in run["jobs"] if e["id"] in identities and e["status"] in ("Needs review","Ready")]
    for entry in selected:
        if branch_signature(spec,run["signature"],entry["branch_id"])!=entry["signature"]:
            raise CompositionError("Branch settings changed. Check this branch before approval.")
    run["acknowledged"]=acknowledge
    for entry in run["jobs"]:
        if entry["id"] in identities and entry["status"] in ("Needs review","Ready"):
            if branch_signature(spec,run["signature"],entry["branch_id"])!=entry["signature"]:
                raise CompositionError("Branch settings changed. Check this branch before approval.")
            batch=BatchRun.from_dict(entry["batch"])
            approve(batch,[entry["id"]])
            entry.update(batch=batch.to_dict(),approved=True,status="Ready")
    return run


def execute_routes(spec,run,directory,output,*,progress=None,is_cancelled=None,on_state=None):
    _location(directory,run)
    _check_current(spec,run)
    if run.get("target_id"):
        raise CompositionError("Step inspections cannot publish production output.")
    if (run["exceptions"] or any(s["status"]=="Blocked" for s in run["sources"])) and not run["acknowledged"]:
        raise CompositionError("Partial production requires explicit exception acknowledgement.")
    if not any(j["status"]=="Ready" and j["approved"] for j in run["jobs"]):
        raise CompositionError("Approve at least one checked branch before production.")
    if not output:
        raise CompositionError("Choose a production output folder.")
    root=Path(output).resolve()/("batch-"+run["batch_id"])
    root.mkdir(parents=True,exist_ok=True)
    run["report_dir"]=str(root)
    run["status"]="Running"
    try:
        for entry in run["jobs"]:
            check_cancel(is_cancelled)
            if not entry["approved"] or entry["status"]!="Ready":
                continue
            if branch_signature(spec,run["signature"],entry["branch_id"])!=entry["signature"]:
                entry.update(approved=False,status="Needs review",error="Branch inputs changed. Check again.")
                continue
            _check_current(spec,run)
            batch=BatchRun.from_dict(entry["batch"])
            batch=execute_batch(WorkflowSpec_from(entry["spec"]),batch,root/entry["id"],
                                progress=progress,is_cancelled=is_cancelled,on_state=on_state)
            job=batch.jobs[0]
            entry.update(batch=batch.to_dict(),approved=False,status=job.status,error=job.error)
            _write_manifest(_location(directory,run),run)
            if on_state:
                on_state({"branch_job":entry})
        complete=all(j["status"] in ("Completed","No records") for j in run["jobs"])
        run["status"]=("Completed with exceptions" if run["exceptions"] or any(s["status"]=="Blocked" for s in run["sources"])
                       else "Completed") if complete else "Partial / needs attention"
    except JobCancelled:
        run["status"]="Cancelled"
    export_results(directory,run,root)
    _write_manifest(_location(directory,run),run)
    return run


def WorkflowSpec_from(value):
    from .model import WorkflowSpec
    return WorkflowSpec.from_dict(value)


def rows(spec,run,directory,*,source_id="",branch_id="",view="output",offset=0,search="",node_id=""):
    root=_location(directory,run)
    _check_current(spec,run)
    if branch_id and branch_id!="exceptions":
        for entry in run["jobs"]:
            if entry["branch_id"]==branch_id and entry["signature"] and branch_signature(spec,run["signature"],branch_id)!=entry["signature"]:
                raise CompositionError("Branch settings changed. Check this branch again.")
    if type(offset) is not int or offset<0 or not isinstance(search,str) or len(search)>1000:
        raise CompositionError("Invalid result page or search.")
    with closing(sqlite3.connect(root/"evidence.sqlite")) as db:
        db.row_factory=sqlite3.Row
        clauses=[]
        args=[]
        table="issues" if view=="issues" else "records"
        if source_id:
            clauses.append("source_id=?")
            args.append(source_id)
        if branch_id and table=="records":
            clauses.append("disposition='exception'" if branch_id=="exceptions" else "branch_id=?")
            if branch_id!="exceptions":
                args.append(branch_id)
        if search:
            columns=["source_id","CAST(source_record AS TEXT)","sequence", "reason" if table=="issues" else "value"]
            clauses.append("("+" OR ".join(f"instr(lower({c}),lower(?))>0" for c in columns)+")")
            args.extend([search]*len(columns))
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        if table=="records" and node_id:
            stage=next((s for s in run["stages"] if s["node_id"]==node_id and s["source_id"]==source_id),None)
            if stage:
                name=stage["input_store"] if view=="input" else stage["output_store"]
                if name:
                    path=Path(name).resolve()
                    if not path.is_relative_to(root):
                        raise CompositionError("Invalid inspection snapshot.")
                    source=DataSet(path)
                    return {"total":source.count,"fields":source.fields,
                            "rows":[{"source_record":identity,"value":values} for _,values,identity in _page(source,offset,search)]}
        total=db.execute("SELECT COUNT(*) FROM "+table+where,args).fetchone()[0]
        values=[dict(r) for r in db.execute("SELECT * FROM "+table+where+" ORDER BY source_id,source_record LIMIT 50 OFFSET ?",[*args,offset])]
        for value in values:
            if "value" in value:
                content=json.loads(value["value"])
                value["value"]={k:v[:256] for k,v in list(content.items())[:12]}
        return {"total":total,"rows":values}


def _page(source,offset,search):
    with closing(sqlite3.connect(source.path)) as db:
        query="SELECT ordinal,value,source_row FROM records"
        args=[]
        if search:
            query+=" WHERE instr(lower(value),lower(?))>0 OR CAST(source_row AS TEXT)=?"
            args=[search,search]
        for ordinal,value,identity in db.execute(query+" ORDER BY ordinal LIMIT 50 OFFSET ?",[*args,offset]):
            yield ordinal,{k:v[:256] for k,v in list(json.loads(value).items())[:12]},identity


def export_results(directory,run,root):
    folder=_location(directory,run)
    with closing(sqlite3.connect(folder/"evidence.sqlite")) as db:
        for entry in run["jobs"]:
            disposition="printed" if entry["status"]=="Completed" else entry["status"].lower()
            db.execute("UPDATE records SET disposition=? WHERE job_id=?",(disposition,entry["id"]))
        db.commit()
        for name,query in (("record-reconciliation.csv","SELECT source_id,source_record,source_row,sequence,branch_id,job_id,job_record,disposition FROM records ORDER BY source_id,source_record"),
                           ("exceptions.csv","SELECT * FROM issues ORDER BY source_id,source_record")):
            with atomic_output(Path(root)/name) as temp,temp.open("w",encoding="utf-8-sig",newline="") as stream:
                cursor=db.execute(query)
                writer=csv.writer(stream)
                writer.writerow([c[0] for c in cursor.description])
                for row in cursor:
                    writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in row])
    # Public log includes identities/counts/output metadata, not temporary snapshots or record contents.
    public={k:v for k,v in run.items() if k not in ("directory","jobs","stages")}
    public["jobs"]=[{k:v for k,v in entry.items() if k not in ("batch","spec")}|
                    {"result":entry.get("batch",{}).get("jobs",[{}])[0].get("result",{}) if entry.get("batch") else {}} for entry in run["jobs"]]
    _write_manifest(root,public)
    with atomic_output(Path(root)/"batch-summary.csv") as temp,temp.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["Source item","Branch","Records","Status","Error"])
        for entry in run["jobs"]:
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v
                             for v in [entry["source_id"],entry["branch_name"],entry["records"],entry["status"],entry["error"]]])
