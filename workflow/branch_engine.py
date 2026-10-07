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
from composition.template.model import CompositionError, DataConfig, Template
from composition.template.serializer import file_hash, load_project, save_project
from core.io_atomic import atomic_output

from .batch import BatchJob, BatchRun, _assets, _finished_valid, approve, execute_batch, prepare
from .branch_graph import COMMON, child_spec
from .registry import DATA_KINDS
from .transforms import DataSet, condition, snapshot, transform


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def common_signature(spec):
    """Global sequence depends on ALL ordered inputs and common settings, not layout."""
    spec.validate()
    common=[n for n in spec.nodes if n.kind in (*DATA_KINDS,"for_each","mapping","batch_sequence")]
    files={}
    for item in spec.node("for_each").params.get("items",[]):
        try:
            files[item["id"]]=file_hash(Path(item["path"]))
        except OSError as exc:
            files[item["id"]]="unavailable:"+str(exc)
    return digest({"nodes":[{"id":n.id,"kind":n.kind,"params":n.params} for n in common],
                   "edges":[e for e in spec.edges if e["source"] in {n.id for n in common}],
                   "routing":spec.node("route").params,"files":files})


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
    options["path"]=item["path"]
    imported=import_records(DataConfig(**options),folder/"import.sqlite",progress=progress,is_cancelled=cancelled)
    with closing(sqlite3.connect(imported.path)) as db:
        db.execute("CREATE INDEX source_identity ON records(source_row)")
        db.commit()
    source=DataSet(imported.path)
    current=snapshot(((identity,value) for _,value,identity in source.rows()),source.fields,folder/"source.sqlite",
                     metadata=source.metadata,is_cancelled=cancelled)
    stages=[{"node_id":plan.common[0].id,"input_store":str(imported.path),"output_store":str(current.path),"input":current.count,"output":current.count}]
    numbered=0
    for node in plan.common[1:]:
        check_cancel(cancelled)
        prior=current
        if progress:
            progress(0,current.count,"Workflow node: "+node.id+" | "+node.kind.replace("_"," "))
        if node.kind=="mapping" and node.params.get("aliases"):
            # Shared aliases are a real step: input evidence retains imported names.
            aliases=node.params["aliases"]
            originals=dict(zip(imported.metadata.get("original_fields",[]),imported.fields,strict=True))
            renamed={originals.get(k,k):v for k,v in aliases.items()}
            missing=set(renamed)-set(current.fields)
            fields=[renamed.get(k,k) for k in current.fields]
            if missing or len(set(fields))!=len(fields):
                raise CompositionError("Missing or duplicate shared field aliases: "+", ".join(sorted(missing)))
            current=snapshot(((identity,{renamed.get(k,k):v for k,v in values.items()}) for _,values,identity in current.rows()),
                             fields,folder/(node.id+".sqlite"),metadata=current.metadata,is_cancelled=cancelled)
        elif node.kind in DATA_KINDS:
            current=transform(current,folder/(node.id+".sqlite"),node.kind,node.params,node_id=node.id,
                              progress=progress,is_cancelled=cancelled)
            if node.kind=="validate_data":
                _validation_nodes(prior,current,folder,node.id)
        elif node.kind=="batch_sequence":
            params=copy.deepcopy(node.params)
            params["start"]=params.get("start",1)+sequence_offset*params.get("step",1)
            current=transform(current,folder/(node.id+".sqlite"),"running_sequence",params,node_id=node.id,
                              progress=progress,is_cancelled=cancelled)
            numbered=current.count
        stages.append({"node_id":node.id,"input_store":str(prior.path),"output_store":str(current.path),
                       "input":prior.count,"output":current.count})
    return imported,current,numbered,stages


def _validation_nodes(prior,current,folder,node_id):
    with closing(sqlite3.connect(folder/"issue-nodes.sqlite")) as db:
        db.execute("CREATE TABLE IF NOT EXISTS nodes(row INTEGER,field TEXT,severity TEXT,reason TEXT,node TEXT,PRIMARY KEY(row,field,severity,reason))")
        db.execute("ATTACH DATABASE ? AS current",(str(current.path),))
        db.execute("ATTACH DATABASE ? AS prior",(str(prior.path),))
        db.execute("CREATE INDEX IF NOT EXISTS prior.findings_trace ON findings(source_id,field,severity,reason)")
        db.execute("INSERT OR IGNORE INTO nodes SELECT c.source_id,c.field,c.severity,c.reason,? FROM current.findings c "
                   "WHERE NOT EXISTS(SELECT 1 FROM prior.findings p WHERE p.source_id=c.source_id AND p.field=c.field AND p.severity=c.severity AND p.reason=c.reason)",(node_id,))
        db.commit()


def _findings(current,folder,plan):
    # Stream attributed findings, with a bounded query cache for large datasets.
    with closing(sqlite3.connect(current.path)) as db:
        default=next((n.id for n in plan.common if n.kind=="validate_data"),plan.common[0].id)
        db.execute("ATTACH DATABASE ? AS trace",(str(folder/"issue-nodes.sqlite"),))
        db.execute("CREATE TABLE IF NOT EXISTS trace.nodes(row INTEGER,field TEXT,severity TEXT,reason TEXT,node TEXT,PRIMARY KEY(row,field,severity,reason))")
        for row,field,severity,reason,node in db.execute("SELECT f.source_id,f.field,f.severity,f.reason,t.node FROM findings f LEFT JOIN trace.nodes t "
                                                      "ON f.source_id=t.row AND f.field=t.field AND f.severity=t.severity AND f.reason=t.reason"):
            yield row,field,severity,reason,node or default


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
                branch_id TEXT,job_id TEXT,job_record INTEGER,disposition TEXT,value TEXT,position INTEGER,
                PRIMARY KEY(source_id,source_record));
            CREATE TABLE issues(source_id TEXT,source_record INTEGER,source_row INTEGER,node_id TEXT,
                field TEXT,severity TEXT,reason TEXT,sequence TEXT);
            CREATE TABLE sources(source_id TEXT PRIMARY KEY,position INTEGER,path TEXT);
        """)
        evidence.executemany("INSERT INTO sources VALUES(?,?,?)",((item["id"],i,item["path"]) for i,item in enumerate(items)))
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
                    source_summary.update(input=imported.count,candidates=current.count,status="Prepared",import_store=str(imported.path))
                    prepared_sources.append((item_index,item,folder,source_summary,imported,current))
                except JobCancelled:
                    raise
                except (ValueError,OSError) as exc:
                    source_summary.update(status="Blocked",error=str(exc))
            _batch_unique(plan,prepared_sources,root,is_cancelled)
            for item_index,item,folder,source_summary,imported,current in prepared_sources:
                check_cancel(is_cancelled)
                try:
                    if plan.route is None:
                        source_summary["status"]="Checked"
                        run["input"]+=imported.count
                        run["candidates"]+=current.count
                        run["excluded"]+=imported.count-current.count
                        with closing(sqlite3.connect(imported.path)) as original:
                            for row,field,severity,reason,node in _findings(current,folder,plan):
                                ordinal=original.execute("SELECT ordinal FROM records WHERE source_row=?",(row,)).fetchone()[0]
                                evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],ordinal,row,node,field,severity,reason,""))
                        continue
                    run["input"]+=imported.count
                    run["candidates"]+=current.count
                    run["excluded"]+=imported.count-current.count
                    route_counts={r["id"]:0 for r in routes}
                    with ExitStack() as stack,closing(sqlite3.connect(current.path)) as db:
                        db.execute("CREATE INDEX IF NOT EXISTS findings_source ON findings(source_id)")
                        db.commit()
                        db.execute("ATTACH DATABASE ? AS original",(str(imported.path),))
                        db.execute("ATTACH DATABASE ? AS trace",(str(folder/"issue-nodes.sqlite"),))
                        db.execute("CREATE TABLE IF NOT EXISTS trace.nodes(row INTEGER,field TEXT,severity TEXT,reason TEXT,node TEXT,PRIMARY KEY(row,field,severity,reason))")
                        db.commit()
                        writers={}
                        for r in routes:
                            stream=stack.enter_context((folder/(r["id"]+".csv")).open("w",encoding="utf-8-sig",newline=""))
                            writers[r["id"]]=csv.DictWriter(stream,fieldnames=current.fields)
                            writers[r["id"]].writeheader()
                        with closing(sqlite3.connect(imported.path)) as original:
                            excluded=db.execute("SELECT DISTINCT source_id FROM exclusions")
                            for (row,) in excluded:
                                ordinal=original.execute("SELECT ordinal FROM records WHERE source_row=?",(row,)).fetchone()[0]
                                evidence.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?)",(item["id"],ordinal,row,"","","",0,"excluded","{}",current.count+ordinal))
                        cursor=db.execute("""SELECT r.ordinal,r.value,r.source_row,o.ordinal FROM records r
                            JOIN original.records o ON o.source_row=r.source_row ORDER BY r.ordinal""")
                        for ordinal,raw,source_row,source_record in cursor:
                            check_cancel(is_cancelled)
                            values=json.loads(raw)
                            seq=values.get(sequence_name,"")
                            findings=list(db.execute("SELECT f.field,f.severity,f.reason,t.node FROM findings f LEFT JOIN trace.nodes t "
                                "ON f.source_id=t.row AND f.field=t.field AND f.severity=t.severity AND f.reason=t.reason WHERE f.source_id=?",(source_row,)))
                            invalid_data=any(severity=="error" for _,severity,_,_ in findings)
                            problems=[]
                            matches=[]
                            for identity,matcher in matchers.items():
                                try:
                                    if matcher.matches(values):
                                        matches.append(identity)
                                except CompositionError as exc:
                                    problems.append((getattr(exc,"field",""),str(exc)))
                            if len(matches)>1:
                                problems.append(("","Multiple route matches: "+", ".join(matches)))
                            branch_id=matches[0] if len(matches)==1 else fallback if not matches else ""
                            if not branch_id and not problems and not invalid_data:
                                problems.append(("","No route matched; no explicit fallback."))
                            for name,severity,reason,node in findings:
                                evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,
                                    node or spec.node("route").id,name,severity,reason,seq))
                            if problems or invalid_data:
                                branch_id=""
                                run["exceptions"]+=1
                                for field,reason in problems:
                                    evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,spec.node("route").id,field,"error",reason,seq))
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
                            evidence.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?)",(item["id"],source_record,source_row,
                                seq,branch_id,job_id,job_record,disposition,raw,ordinal))
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
                            if not path[0].params.get("path"):
                                raise CompositionError("Choose a saved letter template for route: "+r["name"])
                            template=load_project(path[0].params.get("path",""))
                            if sequence_name in {s.name for s in template.sequences}:
                                raise CompositionError("Batch Sequence conflicts with template sequence: "+sequence_name)
                            template.record_mode="imported"
                            prepared=save_project(template,folder/(r["id"]+".pdcx"))
                            linear=child_spec(plan,r["id"])
                            job=BatchJob(id=job_id,name=f"{item_index:04d} · {r['name']}",template_path=str(prepared),
                                data_path=str(folder/(r["id"]+".csv")),data_options=asdict(DataConfig()),
                                output_name=f"{item_index:04d}-{r['id'][:8]}.pdf")
                            job.data_options.pop("path",None)
                            batch=prepare(linear,BatchRun(jobs=[job],batch_id=run["batch_id"]),root/f"j{len(run['jobs']):04d}",
                                          progress=progress,is_cancelled=is_cancelled)
                            entry.update(batch=batch.to_dict(),spec=linear.to_dict(),status=job.status,error=job.error)
                            if job.status=="Needs review":
                                _preflight(job,linear,folder/(r["id"][:8]+"-qc"),progress,is_cancelled)
                                entry["preflight"]={"records":job.input_records,"pages":job.expected_pages,"status":"Checked"}
                        except JobCancelled:
                            raise
                        except (ValueError,OSError) as exc:
                            entry.update(status="Blocked",error=str(exc))
                            ordinal=getattr(exc,"record_ordinal",0)
                            source=evidence.execute("SELECT source_record,source_row,sequence FROM records WHERE job_id=? AND job_record=?",
                                                    (entry["id"],ordinal)).fetchone()
                            target=next((n for n in plan.branches[r["id"]] if n.kind=="compose"),plan.branches[r["id"]][0])
                            evidence.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(item["id"],source[0] if source else 0,
                                source[1] if source else 0,target.id,"","error",str(exc),source[2] if source else ""))
                    source_summary["status"]="Checked"
                except JobCancelled:
                    raise
                except (ValueError,OSError) as exc:
                    source_summary.update(status="Blocked",error=str(exc))
                if progress:
                    progress(item_index,len(items),f"Checked source {item_index}/{len(items)}")
                if on_state:
                    on_state({"branch_source":source_summary})
            if run["input"]!=run["excluded"]+run["candidates"] or plan.route is not None and run["candidates"]!=run["routed"]+run["exceptions"]:
                raise CompositionError("Routing reconciliation failed; no approval is permitted.")
            run["status"]="Needs review"
        except JobCancelled:
            run["status"]="Cancelled"
            for source in run["sources"]:
                if source["status"]=="Prepared":
                    source["status"]="Unprocessed"
        evidence.commit()
    _check_current(spec,run)
    _write_manifest(root,run)
    return run


def _write_manifest(root,run):
    with atomic_output(Path(root)/"run.json") as temp:
        temp.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding="utf-8")


def _job_id(run,source,branch):
    return uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([run["batch_id"],source,branch])).hex


def _preflight(job,spec,directory,progress,cancelled):
    from composition.data.sequences import open_records
    from composition.engine.renderer import Renderer
    directory.mkdir(parents=True,exist_ok=True)
    template=Template.from_dict(job.prepared_template)
    records=open_records(template,job.record_store)
    with Renderer(template,auto_repair=spec.node("compose").params.get("auto_repair",True),
                  fallback_directory=directory/"fallback",is_cancelled=cancelled) as renderer:
        renderer.prepare_fonts(records.records(),directory,progress,cancelled,audit_path=directory/"glyph-repairs.csv")


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
        for _,item,folder,_,_,current in sources:
            with closing(sqlite3.connect(current.path)) as db:
                db.execute("CREATE INDEX IF NOT EXISTS findings_trace ON findings(source_id,field,reason)")
                db.execute("ATTACH DATABASE ? AS trace",(str(folder/"issue-nodes.sqlite"),))
                db.execute("CREATE TABLE IF NOT EXISTS trace.nodes(row INTEGER,field TEXT,severity TEXT,reason TEXT,node TEXT,PRIMARY KEY(row,field,severity,reason))")
                for node,field,row in global_db.execute("SELECT s.node,s.field,s.row FROM seen s JOIN duplicates d "
                                                       "ON s.node=d.node AND s.field=d.field AND s.value=d.value WHERE s.source=?",(item["id"],)):
                    check_cancel(cancelled)
                    reason="Duplicate value across batch source files"
                    db.execute("INSERT INTO findings(source_id,field,severity,reason) SELECT ?,?,?,? "
                               "WHERE NOT EXISTS(SELECT 1 FROM findings WHERE source_id=? AND field=? AND reason=?)",
                               (row,field,severities[(node,field)],reason,row,field,reason))
                    db.execute("INSERT OR IGNORE INTO trace.nodes VALUES(?,?,?,?,?)",(row,field,severities[(node,field)],reason,node))
                db.commit()


def approve_routes(spec,run,identities,*,acknowledge=False):
    _check_current(spec,run)
    if run.get("target_id") or run["status"]=="Cancelled":
        raise CompositionError("Run Check & Preview for the entire graph before approving production.")
    if _has_exceptions(run) and not acknowledge:
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
    if _has_exceptions(run) and not run["acknowledged"]:
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
                                progress=progress,is_cancelled=is_cancelled,on_state=on_state,_direct_root=True)
            job=batch.jobs[0]
            entry.update(batch=batch.to_dict(),approved=False,status=job.status,error=job.error)
            if job.status=="Failed":
                with closing(sqlite3.connect(_location(directory,run)/"evidence.sqlite")) as db:
                    ordinal=job.result.get("error_record",0)
                    source=db.execute("SELECT source_record,source_row,sequence FROM records WHERE job_id=? AND job_record=?",
                                      (entry["id"],ordinal)).fetchone()
                    if source:
                        node=next(n for n in spec.execution_plan().branches[entry["branch_id"]] if n.kind=="compose")
                        db.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",(entry["source_id"],source[0],source[1],node.id,"","error",job.error,source[2]))
                        db.commit()
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


def _has_exceptions(run):
    return bool(run["exceptions"] or any(s["status"]=="Blocked" for s in run["sources"]) or
                any(j["status"] in ("Blocked","Failed") for j in run["jobs"]))


def rows(spec,run,directory,*,source_id="",branch_id="",view="output",offset=0,search="",node_id=""):
    root=_location(directory,run)
    _check_current(spec,run)
    if branch_id and branch_id!="exceptions":
        for entry in run["jobs"]:
            if entry["branch_id"]==branch_id and entry["signature"] and branch_signature(spec,run["signature"],branch_id)!=entry["signature"]:
                raise CompositionError("Branch settings changed. Check this branch again.")
    if type(offset) is not int or offset<0 or not isinstance(search,str) or len(search)>1000:
        raise CompositionError("Invalid result page or search.")
    stages=[s for s in run["stages"] if s["node_id"]==node_id and (not source_id or s["source_id"]==source_id)]
    if view!="issues" and stages:
        return _stage_rows(run,root,stages,view,offset,search)
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
        if table=="records":
            clauses.append("disposition!='excluded'")
        if table=="issues" and branch_id and branch_id!="exceptions":
            ids=[n.id for n in spec.execution_plan(spec.node("route").id).branches[branch_id]]
            clauses.append("node_id IN ("+",".join("?" for _ in ids)+")")
            args.extend(ids)
        elif table=="issues" and node_id and any(n.id==node_id and n.kind in COMMON for n in spec.nodes):
            clauses.append("node_id=?")
            args.append(node_id)
        if search:
            columns=["source_id","CAST(source_record AS TEXT)","sequence", "reason" if table=="issues" else "value"]
            clauses.append("("+" OR ".join(f"instr(lower({c}),lower(?))>0" for c in columns)+")")
            args.extend([search]*len(columns))
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        total=db.execute("SELECT COUNT(*) FROM "+table+where,args).fetchone()[0]
        order="(SELECT position FROM sources WHERE sources.source_id="+table+".source_id),"+("position" if table=="records" else "source_record")
        values=[dict(r) for r in db.execute("SELECT * FROM "+table+where+" ORDER BY "+order+" LIMIT 50 OFFSET ?",[*args,offset])]
        for value in values:
            if "value" in value:
                content=json.loads(value["value"])
                value["value"]={k:v[:256] for k,v in list(content.items())[:12]}
        return {"total":total,"rows":values}


def _stage_rows(run,root,stages,view,offset,search):
    """Page over source stores in explicit input order, preserving original ordinals."""
    total=0
    remaining=offset
    result=[]
    fields=[]
    for stage in stages:
        name=stage["input_store"] if view=="input" else stage["output_store"]
        path=Path(name).resolve()
        source=next(s for s in run["sources"] if s["id"]==stage["source_id"])
        original=Path(source["import_store"]).resolve()
        if not path.is_relative_to(root) or not original.is_relative_to(root):
            raise CompositionError("Invalid inspection snapshot.")
        fields.extend(f for f in DataSet(path).fields if f not in fields)
        with closing(sqlite3.connect(path)) as db:
            db.execute("ATTACH DATABASE ? AS original",(str(original),))
            where=" WHERE instr(lower(r.value),lower(?))>0 OR CAST(o.ordinal AS TEXT)=?" if search else ""
            args=[search,search] if search else []
            query=" FROM records r JOIN original.records o ON o.source_row=r.source_row"+where
            count=db.execute("SELECT COUNT(*)"+query,args).fetchone()[0]
            total+=count
            if remaining>=count:
                remaining-=count
                continue
            if len(result)>=50:
                continue
            for raw,ordinal,row in db.execute("SELECT r.value,o.ordinal,r.source_row"+query+" ORDER BY r.ordinal LIMIT ? OFFSET ?",
                                              [*args,50-len(result),remaining]):
                result.append({"source_id":stage["source_id"],"source_record":ordinal,"source_row":row,
                               "value":{k:v[:256] for k,v in list(json.loads(raw).items())[:12]}})
            remaining=0
    return {"total":total,"rows":result,"fields":fields}


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
        db.execute("CREATE TABLE IF NOT EXISTS outputs(job_id TEXT PRIMARY KEY,path TEXT,pages INTEGER,branch_name TEXT)")
        db.execute("DELETE FROM outputs")
        for entry in run["jobs"]:
            disposition="published" if entry["status"]=="Completed" else entry["status"].lower()
            db.execute("UPDATE records SET disposition=? WHERE job_id=?",(disposition,entry["id"]))
            result=entry.get("batch",{}).get("jobs",[{}])[0].get("result",{}) if entry.get("batch") else {}
            db.execute("INSERT INTO outputs VALUES(?,?,?,?)",(entry["id"],result.get("output_pdf",""),result.get("pages_per_record",0),entry["branch_name"]))
        db.commit()
        run["published_records"]=db.execute("SELECT COUNT(*) FROM records WHERE disposition='published'").fetchone()[0]
        run["unpublished_records"]=run["routed"]-run["published_records"]
        if run["published_records"]!=sum(entry["records"] for entry in run["jobs"] if entry["status"]=="Completed"):
            raise CompositionError("Published-record reconciliation failed; inspect the child reports.")
        reconciliation=("SELECT r.source_id,r.source_record,r.source_row,r.sequence,r.branch_id,r.job_id,r.job_record,r.disposition,"
                        "s.path AS source_file,o.branch_name,o.path AS output_pdf,"
                        "CASE WHEN r.disposition='published' THEN (r.job_record-1)*o.pages+1 END AS first_output_page,"
                        "CASE WHEN r.disposition='published' THEN r.job_record*o.pages END AS last_output_page "
                        "FROM records r JOIN sources s ON s.source_id=r.source_id LEFT JOIN outputs o ON o.job_id=r.job_id ORDER BY s.position,r.position")
        for name,query in (("record-reconciliation.csv",reconciliation),
                           ("exceptions.csv","SELECT * FROM issues ORDER BY source_id,source_record")):
            with atomic_output(Path(root)/name) as temp,temp.open("w",encoding="utf-8-sig",newline="") as stream:
                cursor=db.execute(query)
                writer=csv.writer(stream)
                writer.writerow([c[0] for c in cursor.description])
                for row in cursor:
                    writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in row])
    # Public log includes identities/counts/output metadata, not temporary snapshots or record contents.
    public={k:v for k,v in run.items() if k not in ("directory","jobs","stages","sources")}
    public["sources"]=[{k:v for k,v in source.items() if k!="import_store"} for source in run["sources"]]
    public["jobs"]=[{k:v for k,v in entry.items() if k not in ("batch","spec")}|
                    {"result":entry.get("batch",{}).get("jobs",[{}])[0].get("result",{}) if entry.get("batch") else {}} for entry in run["jobs"]]
    _write_manifest(root,public)
    with atomic_output(Path(root)/"batch-summary.csv") as temp,temp.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["Source item","Branch","Records","Status","Error"])
        for entry in run["jobs"]:
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v
                             for v in [entry["source_id"],entry["branch_name"],entry["records"],entry["status"],entry["error"]]])
