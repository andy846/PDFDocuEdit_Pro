"""Data preparation and whole-mailpiece production without weakening source grouping."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing, nullcontext
from dataclasses import asdict
from pathlib import Path

from composition.overlay.generator import generate
from composition.overlay.model import EnvelopeSpec, OverlayJob
from composition.overlay.serializer import load_project
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.pdf_source.source import inspect_source
from composition.production.generator import check_cancel
from composition.production.model import new_job_id
from composition.template.model import CompositionError, SequenceSpec
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output
from core.pdf_io import validate_pdf_file

from .extraction import ExtractionSpec, ExtractionStore, Region
from .pipeline import split_names, summary
from .registry import EXTRA_KINDS
from .splitter import qpdf_select, split_composed
from .transforms import DataSet, assert_valid, export_audit, snapshot, transform


def production_view(spec,run,root,*,progress=None,is_cancelled=None,prepared=None):
    """Separate production selection/order from the untouched original boundaries."""
    from .engine import external_fields
    data=prepared or prepare_mailpieces(spec,run,root,progress=progress,is_cancelled=is_cancelled)
    if not data.count:
        raise CompositionError("No envelopes selected. Production will write an exclusion report without a PDF.")
    selected=[]
    ranges=[]
    groups=[]
    cursor=1
    with closing(sqlite3.connect(data.path)) as db:
        db.executescript("DROP TABLE IF EXISTS page_map; CREATE TABLE page_map(page INTEGER PRIMARY KEY,original_page INTEGER,envelope INTEGER);")
        for _ordinal,_values,original_envelope in data.rows():
            check_cancel(is_cancelled)
            start,end=run.groups[original_envelope-1]
            selected.append(original_envelope)
            ranges.append(f"{start}-{end}")
            groups.append([cursor,cursor+end-start])
            db.executemany("INSERT INTO page_map VALUES(?,?,?)",((cursor+page-start,page,original_envelope) for page in range(start,end+1)))
            cursor+=end-start+1
        production_source=Path(root)/"production-source.pdf"
        if production_source.resolve() in {Path(p).resolve() for p in spec.node("input").params.get("paths",[])}:
            raise CompositionError("Use a separate scratch folder; production snapshots must not replace source PDFs.")
        with atomic_output(production_source) as temp:
            qpdf_select(run.source,",".join(ranges),temp,is_cancelled)
            validate_pdf_file(temp,expected_page_count=cursor-1)
        info=dict(data.metadata)
        info.update(production_source_sha256=file_hash(production_source),production_groups=groups,
                    original_groups=run.groups,external_fields=external_fields(spec),
                    page_sequences=[n.params for n in _post_nodes(spec) if n.kind=="running_sequence" and n.params.get("scope")=="page"],
                    record_sequences=[n.params["name"] for n in _post_nodes(spec) if n.kind=="running_sequence" and n.params.get("scope")!="page"])
        db.execute("UPDATE metadata SET value=? WHERE key='import'",(json.dumps(info),))
        db.commit()
    return DataSet(data.path),production_source,groups,selected


class ProductionValues:
    """One provider for Designer preview, barcode samples and PDF production."""
    def __init__(self,path,database,project):
        self.path=path
        self.database=database
        self.project=project

    def __enter__(self):
        self.data=DataSet(self.path)
        self.store=ExtractionStore(self.database)
        self.db=sqlite3.connect(self.data.path)
        self.record_ordinal=None
        self.record_values={}
        try:
            info=self.data.metadata
            if (info.get("production_source_sha256")!=self.project.source.sha256
                    or info.get("production_groups")!=self.project.settings.groups
                    or info.get("source",{}).get("sha256")!=self.store.metadata()["sha256"]
                    or info.get("original_groups")!=[list(r) for r in self.store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]):
                raise CompositionError("Workflow preview changed. Reopen the overlay from Workflow to refresh its production data.")
            return self
        except Exception:
            self.__exit__()
            raise

    def __exit__(self,*_):
        self.db.close()
        self.store.db.close()

    def __call__(self,page):
        if page.source_page:
            original=self.db.execute("SELECT original_page FROM page_map WHERE page=?",(page.source_page,)).fetchone()[0]
            values={"Page_"+k:v for k,v in self.store.values(original).items()}
        else:
            values={"Page_"+r.name:"" for r in ExtractionSpec.from_dict(json.loads(self.store.metadata()["spec"])).regions}
        if self.record_ordinal!=page.envelope:
            self.record_values=json.loads(self.db.execute("SELECT value FROM records WHERE ordinal=?",(page.envelope,)).fetchone()[0])
            self.record_ordinal=page.envelope
        record=self.record_values
        values.update({"Envelope_"+k:v for k,v in record.items()})
        for name in self.data.metadata.get("record_sequences",[]):
            values[name]=record[name]
        for params in self.data.metadata.get("page_sequences",[]):
            from composition.data.sequences import sequence_value
            seq=SequenceSpec(**{**params,"scope":"record"})
            values[seq.name]=sequence_value(seq,page.output_page)
        if set(values)!=set(self.project.external_fields):
            raise CompositionError("Computed fields changed. Refresh the overlay from Workflow.")
        return values


def _legacy(spec):
    result=copy.deepcopy(spec)
    result.workflow_version=1
    result.nodes=copy.deepcopy([n for n in spec.chain() if n.kind not in EXTRA_KINDS])
    result.edges=[[a.id,b.id] for a,b in zip(result.nodes,result.nodes[1:],strict=False)]
    result.chain()
    return result


def _post_nodes(spec):
    grouped=False
    for node in spec.chain():
        grouped=grouped or node.kind=="group"
        if grouped and node.kind in EXTRA_KINDS:
            yield node


def prepare_mailpieces(spec,run,directory,*,progress=None,is_cancelled=None,until_id=None):
    root=Path(directory)/"envelope-data"
    root.mkdir(parents=True,exist_ok=True)
    with ExtractionStore(run.database) as store:
        groups=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
        if groups!=run.groups:
            raise CompositionError("Original envelope boundaries changed. Review them again.")
        fields=[r[0] for r in store.db.execute("SELECT DISTINCT field FROM envelope_cells ORDER BY field")]
        def rows():
            for envelope in range(1,len(groups)+1):
                values={r[0]:r[1] for r in store.db.execute("SELECT field,value FROM envelope_cells WHERE envelope=?",(envelope,))}
                yield envelope,values
        current=snapshot(rows(),fields,root/"input.sqlite",metadata={
            "source":{"path":run.source,"sha256":store.metadata()["sha256"]},"source_records":len(groups),"mailpieces":True},is_cancelled=is_cancelled)
    for node in _post_nodes(spec):
        run.statuses[node.id]="Running"
        if node.kind=="running_sequence" and node.params.get("scope")=="page":
            if node.params["name"] in current.fields:
                raise CompositionError("Page sequence conflicts with supplied field: "+node.params["name"])
        current=transform(current,root/(node.id+".sqlite"),node.kind,node.params,node_id=node.id,
                          progress=progress,is_cancelled=is_cancelled)
        run.statuses[node.id]="Completed"
        if node.id==until_id:
            break
    run.data_set=str(current.path)
    run.data_summary=summary(current,len(groups))
    run.data_summary["outputs"]=split_names(current,"production.pdf")
    reports=root/"review-reports"
    export_audit(current,reports)
    run.data_summary.update(findings_report=str(reports/"findings.csv"),exclusions_report=str(reports/"exclusions.csv"))
    run.data_steps=[s for s in run.data_steps if s.get("scope")=="page"]+current.metadata.get("steps",[])
    assert_valid(current)
    return current


def _prepare_pages(spec,run,root,*,progress=None,is_cancelled=None,until_id=None):
    nodes=[]
    for node in spec.chain():
        if node.kind=="group":
            break
        if node.kind in EXTRA_KINDS:
            nodes.append(node)
            if node.id==until_id:
                break
    if not nodes:
        return
    with ExtractionStore(run.database) as store:
        cfg=ExtractionSpec.from_dict(json.loads(store.metadata()["spec"]))
        fields=[r.name for r in cfg.regions]
        pages=int(store.metadata()["pages"])
        current=snapshot(((page,store.values(page)) for page in range(1,pages+1)),fields,root/"page-input.sqlite",
            metadata={"source":{"path":run.source,"sha256":store.metadata()["sha256"]}},is_cancelled=is_cancelled)
        for node in nodes:
            run.statuses[node.id]="Running"
            current=transform(current,root/(node.id+".sqlite"),node.kind,node.params,node_id=node.id,
                              progress=progress,is_cancelled=is_cancelled)
            run.statuses[node.id]="Completed"
        run.data_steps=[]
        reports=root/"page-review-reports"
        export_audit(current,reports)
        for finding in current.metadata.get("steps",[]):
            run.data_steps.append({**finding,"scope":"page","findings_report":str(reports/"findings.csv")})
        # Original raw text and provenance remain untouched. Computed fields have no text rectangle.
        known={r.name:r for r in cfg.regions}
        for name in current.fields:
            if name not in known:
                region=Region(name=name,required=False,max_length=100000)
                cfg.regions.append(region)
                known[name]=region
        cfg.validate()
        with store.db:
            for _,values,page in current.rows():
                check_cancel(is_cancelled)
                for name,value in values.items():
                    issue=known[name].problem(value)
                    store.db.execute("INSERT INTO cells VALUES(?,?,?,?,?,1) ON CONFLICT(page,field) DO UPDATE SET value=excluded.value,issue=excluded.issue",
                        (page,name,"",value,issue))
            store.db.execute("UPDATE meta SET value=? WHERE key='spec'",(json.dumps(cfg.to_dict()),))
            store.db.execute("UPDATE meta SET value='false' WHERE key='accepted'")
        assert_valid(current)


def execute_pdf(spec,run,directory,*,until="review",progress=None,is_cancelled=None):
    from .engine import context_fingerprint, execute
    root=Path(directory)
    root.mkdir(parents=True,exist_ok=True)
    run.error=""
    try:
        fingerprint=context_fingerprint(spec,include_overlay=False)
        if until=="output":
            run.output={}
            if not run.accepted or run.fingerprint!=fingerprint:
                raise CompositionError("Source or workflow changed. Check and accept review before production.")
            run.statuses[spec.node("output").id]="Running"
            return _produce(spec,run,root,progress=progress,is_cancelled=is_cancelled)
        legacy=_legacy(spec)
        target=next((n for n in spec.chain() if n.id==until or n.kind==until),None)
        if target and target.kind in ("input","merge","extract"):
            run=execute(legacy,run,root,until=target.kind,progress=progress,is_cancelled=is_cancelled)
            return run
        page_nodes=[]
        for node in spec.chain():
            if node.kind=="group":
                break
            if node.kind in EXTRA_KINDS:
                page_nodes.append(node)
        signature=hashlib.sha256(json.dumps([fingerprint,[{"id":n.id,"kind":n.kind,"params":n.params} for n in page_nodes]],sort_keys=True).encode()).hexdigest()
        page_target=target and target.id in {n.id for n in page_nodes}
        if page_nodes and (signature!=run.page_pipeline_signature or page_target):
            run.statuses.pop(legacy.node("extract").id,None)
            run.signatures.pop(legacy.node("extract").id,None)
            run=execute(legacy,run,root,until="extract",progress=progress,is_cancelled=is_cancelled)
            if run.error:
                return run
            _prepare_pages(spec,run,root,progress=progress,is_cancelled=is_cancelled,
                           until_id=target.id if page_target else None)
            run.page_pipeline_signature="" if page_target else signature
            if page_target:
                run.fingerprint=fingerprint
                return run
        legacy.node("group").params["data_pipeline"]=signature
        group_target=target and (target.kind=="group" or target.kind in EXTRA_KINDS)
        run=execute(legacy,run,root,until="group" if group_target else "review",progress=progress,is_cancelled=is_cancelled)
        if run.error:
            return run
        run.fingerprint=fingerprint
        if target and target.kind=="group":
            return run
        prepare_mailpieces(spec,run,root,progress=progress,is_cancelled=is_cancelled,
                           until_id=target.id if group_target else None)
        if target and target.kind=="overlay":
            if not run.accepted:
                raise CompositionError("Accept review before checking the overlay project.")
            load_project(target.params["path"])
            run.statuses[target.id]="Completed"
        return run
    except Exception as exc:
        run.error=str(exc)
        run.accepted=False
        if not run.output.get("report_dir"):
            run.output={}
        if until=="output":
            run.statuses[spec.node("output").id]="Cancelled" if is_cancelled and is_cancelled() else "Failed"
        for node in spec.nodes:
            if node.kind in EXTRA_KINDS and run.statuses.get(node.id)=="Running":
                run.statuses[node.id]="Cancelled" if is_cancelled and is_cancelled() else "Failed"
                break
        return run
    finally:
        with atomic_output(root/"run.json") as temp:
            temp.write_text(json.dumps(asdict(run),ensure_ascii=False,indent=2),encoding="utf-8")


def _produce(spec,run,root,*,progress=None,is_cancelled=None):
    from .engine import detection_audit, external_fields
    with ExtractionStore(run.database) as store:
        if store.metadata()["accepted"]!="true" or store.metadata()["sha256"]!=file_hash(Path(run.source)):
            raise CompositionError("Extracted data or source changed since acceptance.")
        original_groups=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
        if original_groups!=run.groups:
            raise CompositionError("Original grouping differs from the accepted review.")
        data=prepare_mailpieces(spec,run,root,progress=progress,is_cancelled=is_cancelled)
        folder=spec.node("output").params.get("directory","")
        if not folder:
            raise CompositionError("Choose an output folder.")
        if data.count==0:
            report=Path(folder)/new_job_id()
            report.mkdir(parents=True)
            export_audit(data,report)
            run.output={"job_id":report.name,"status":"completed","input_envelopes":0,"generated_pages":0,
                "generated_files":0,"output_pdf":"","report_dir":str(report),"original_envelopes":len(run.groups),
                "excluded_envelopes":len(run.groups),"error":""}
            (report/"job.json").write_text(json.dumps(run.output,indent=2),encoding="utf-8")
            run.statuses[spec.node("output").id]="Completed"
            return run
        data,production_source,groups,selected=production_view(spec,run,root,progress=progress,is_cancelled=is_cancelled,prepared=data)
        overlay=spec.node("overlay")
        project=load_project(overlay.params["path"]) if overlay else None
        settings=copy.deepcopy(project.settings) if project else EnvelopeSettings(pages_per_envelope=1)
        settings.groups=groups
        settings.excluded_pages=[]
        source=inspect_source(production_source,settings,uniform=True,is_cancelled=is_cancelled)
        composed=EnvelopeSpec(source,settings,objects=project.objects if project else [],
            required_scope=project.required_scope if project else "all_source",name=spec.name,external_fields=external_fields(spec))
        # External computed names are checked against configured marks, not guessed.
        composed.detection_review=detection_audit(composed)
        composed.validate()
        plan=EnvelopePlan(source.pages,settings)
        with closing(sqlite3.connect(data.path)) as db:
            db.executescript("DROP TABLE IF EXISTS page_spans; CREATE TABLE page_spans(ordinal INTEGER PRIMARY KEY,start INTEGER,end INTEGER);")
            for i,start in enumerate(plan.output_starts):
                end=plan.output_starts[i+1]-1 if i+1<len(plan.output_starts) else plan.output_pages
                db.execute("INSERT INTO page_spans VALUES(?,?,?)",(i+1,start,end))
            db.commit()
            partitions=run.data_summary.get("outputs",[])
            def reports(report,result):
                export_audit(data,report)
                store.export(report/"extracted-data.csv")
                with (report/"workflow-page-map.csv").open("w",encoding="utf-8-sig",newline="") as stream:
                    writer=csv.writer(stream)
                    writer.writerow(["Output page","Production envelope","Original envelope","Original workflow page","Original file","Original file page"])
                    for page in plan.pages():
                        original=db.execute("SELECT original_page,envelope FROM page_map WHERE page=?",(page.source_page,)).fetchone() if page.source_page else None
                        trace=store.db.execute("SELECT source_file,source_page FROM provenance WHERE page=?",(original[0],)).fetchone() if original else None
                        writer.writerow([page.output_page,page.envelope,selected[page.envelope-1],original[0] if original else "",
                                         trace[0] if trace else "",trace[1] if trace else ""])
                (report/"original-boundaries.json").write_text(json.dumps({"groups":run.groups,"selected":selected,
                    "input_envelopes":len(run.groups),"kept":data.count,"excluded":len(run.groups)-data.count},indent=2),encoding="utf-8")
            with ProductionValues(data.path,run.database,composed) as values:
                # Keep nested renderer/font caches beneath a short owned Windows path.
                context=tempfile.TemporaryDirectory(prefix="wf-overlay-") if partitions else nullcontext(folder)
                with context as generation_root:
                    result=asdict(generate(OverlayJob(composed.to_dict(),str(generation_root)),progress=progress,is_cancelled=is_cancelled,
                                           external_values=values,additional_reports=reports))
                    if result["status"]=="completed" and partitions:
                        result=split_composed(result,data,partitions,folder,0,is_cancelled=is_cancelled,progress=progress)
                    elif partitions and result.get("report_dir"):
                        report=Path(folder)/(result["job_id"]+"-failed")
                        shutil.copytree(result["report_dir"],report)
                        result["report_dir"]=str(report)
        result.update(original_envelopes=len(run.groups),retained_envelopes=data.count,
            excluded_envelopes=len(run.groups)-data.count,original_source_pages=int(store.metadata()["pages"]))
        run.output=result
        if result["status"]!="completed":
            raise CompositionError(result.get("error") or "Production failed.")
        if len(run.groups)!=data.count+run.data_summary["excluded"]:
            raise CompositionError("Original/kept/excluded envelope reconciliation failed.")
        run.statuses[spec.node("output").id]="Completed"
        return run
