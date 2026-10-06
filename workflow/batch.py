"""Headless Mail Merge queue: immutable checks, explicit approval and per-job publishing."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from composition.data.sequences import open_records
from composition.data.source import import_records, suggest_import
from composition.engine.fonts import load_font
from composition.production.generator import JobCancelled, check_cancel, generate
from composition.production.model import ProductionJob, new_job_id, now, validate_output_name
from composition.template.model import CompositionError, DataConfig, required_fields, validate_template
from composition.template.serializer import file_hash, load_project, save_project
from core.io_atomic import atomic_output

from .model import WorkflowSpec
from .registry import EXTRA_KINDS


def _validate_summary(summary):
    """Validate cached findings before the UI uses counts and nested rows."""
    for name in ("input","retained","excluded","errors","warnings"):
        value=summary.get(name,0)
        if type(value) is not int or not 0<=value<=100_000_000:
            raise CompositionError("Invalid workflow data counts.")
    fields=summary.get("fields",[])
    steps=summary.get("steps",[])
    outputs=summary.get("outputs",[])
    if (not isinstance(fields,list) or len(fields)>10000 or any(not isinstance(v,str) for v in fields)
            or not isinstance(steps,list) or len(steps)>64
            or not isinstance(outputs,list) or len(outputs)>10000):
        raise CompositionError("Invalid workflow data summary.")
    for step in steps:
        if not isinstance(step,dict) or any(not isinstance(step.get(k),str) for k in ("node_id","kind")):
            raise CompositionError("Invalid workflow step findings.")
        for name in ("input","retained","excluded","issues","errors"):
            value=step.get(name,0)
            if type(value) is not int or not 0<=value<=100_000_000:
                raise CompositionError("Invalid workflow step counts.")
        samples=step.get("samples",[])
        if not isinstance(samples,list) or len(samples)>8:
            raise CompositionError("Invalid workflow preview samples.")
        for sample in samples:
            if not isinstance(sample,dict) or type(sample.get("source_id")) is not int:
                raise CompositionError("Invalid workflow source identity.")
            for name in ("before","after"):
                values=sample.get(name,{})
                if not isinstance(values,dict) or len(values)>12 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in values.items()):
                    raise CompositionError("Invalid workflow preview values.")
    for item in outputs:
        if not isinstance(item,dict) or not isinstance(item.get("name"),str) or type(item.get("records")) is not int:
            raise CompositionError("Invalid workflow output partition.")
    if any(not isinstance(summary.get(name,""),str) for name in ("findings_report","exclusions_report")):
        raise CompositionError("Invalid workflow findings paths.")


@dataclass
class BatchJob:
    name: str = "Letter job"
    template_path: str = ""
    data_path: str = ""
    data_options: dict = field(default_factory=dict)
    mapping_profile: str = ""
    sequence_starts: dict = field(default_factory=dict)
    output_name: str = "letters.pdf"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "Pending"
    signature: str = ""
    approved: bool = False
    input_records: int = 0
    pages_per_record: int = 0
    expected_pages: int = 0
    template_fields: list = field(default_factory=list)
    sequence_fields: list = field(default_factory=list)
    error: str = ""
    stage: str = ""
    warnings: list = field(default_factory=list)
    prepared_template: dict = field(default_factory=dict)
    record_store: str = ""
    snapshot_dir: str = ""
    snapshot_hashes: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    data_summary: dict = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",self.id):
            raise CompositionError("Invalid batch item identity.")
        if not isinstance(self.name,str) or not 1<=len(self.name)<=200:
            raise CompositionError("Use a job name of 1–200 characters.")
        if any(not isinstance(v,str) or len(v)>4096 for v in (self.template_path,self.data_path,self.mapping_profile)):
            raise CompositionError("Invalid batch input path/profile.")
        validate_output_name(self.output_name)
        if not isinstance(self.data_options,dict) or not isinstance(self.sequence_starts,dict):
            raise CompositionError("Invalid import or sequence settings.")
        if (type(self.approved) is not bool or not isinstance(self.status,str)
                or self.status not in ("Pending","Ready","Needs review","Blocked","Running","Completed","Failed","Cancelled")
                or any(type(v) is not int or not 0<=v<=100_000_000 for v in (self.input_records,self.pages_per_record,self.expected_pages))
                or self.pages_per_record>200):
            raise CompositionError("Invalid batch status/counts.")
        if (any(not isinstance(v,str) for v in (self.signature,self.error,self.stage,self.record_store,self.snapshot_dir))
                or not isinstance(self.warnings,list) or any(not isinstance(v,str) for v in self.warnings)
                or not isinstance(self.prepared_template,dict) or not isinstance(self.snapshot_hashes,dict)
                or not isinstance(self.result,dict) or not isinstance(self.history,list)
                or not isinstance(self.data_summary,dict)
                or any(not isinstance(v,dict) for v in self.history)
                or not isinstance(self.template_fields,list) or any(not isinstance(v,str) for v in self.template_fields)
                or not isinstance(self.sequence_fields,list) or any(not isinstance(v,dict) for v in self.sequence_fields)):
            raise CompositionError("Invalid batch findings or snapshot metadata.")
        if any(not isinstance(self.result.get(k,""),str) for k in ("output_pdf","report_dir","job_id","status")):
            raise CompositionError("Invalid batch output record.")
        _validate_summary(self.data_summary)
        for name,value in self.sequence_starts.items():
            if not isinstance(name,str) or type(value) is not int or abs(value)>10**18:
                raise CompositionError("Sequence starts must be integers within ±10^18.")

    def record(self):
        value=asdict(self)
        # Reopen always rechecks inputs. Never rely on stale temporary snapshots.
        for key in ("prepared_template","record_store","snapshot_dir","snapshot_hashes"):
            value.pop(key)
        for step in value.get("data_summary",{}).get("steps",[]):
            step.pop("samples",None)
        for key in ("findings_report","exclusions_report"):
            value.get("data_summary",{}).pop(key,None)
        return value


@dataclass
class BatchRun:
    jobs: list[BatchJob] = field(default_factory=list)
    batch_id: str = field(default_factory=new_job_id)
    status: str = "Pending"
    started_at: str = ""
    finished_at: str = ""
    report_dir: str = ""

    @classmethod
    def from_dict(cls, raw):
        try:
            if len(raw.get("jobs",[]))>10000:
                raise CompositionError("Use at most 10,000 batch items.")
            run=cls(**{**raw,"jobs":[BatchJob(**j) for j in raw.get("jobs",[])]})
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",run.batch_id):
                raise CompositionError("Invalid batch identity.")
            ids=set()
            for job in run.jobs:
                job.validate()
                if job.id in ids:
                    raise CompositionError("Duplicate batch item identity.")
                ids.add(job.id)
            if any(not isinstance(v,str) for v in (run.status,run.started_at,run.finished_at,run.report_dir)):
                raise CompositionError("Invalid batch run metadata.")
            return run
        except (TypeError,KeyError,AttributeError) as exc:
            raise CompositionError("Invalid batch record.") from exc

    def to_dict(self):
        return asdict(self)


def _assets(template):
    assets={p.background for p in template.pages if p.background}
    for element in template.all_elements():
        assets.update(p for p in (element.image,element.rules.alternative.image if element.rules.alternative else "") if p)
        if element.type=="text" or element.show_barcode_text:
            assets.add(str(load_font(element.font)[1]))
        assets.update(str(load_font(font)[1]) for font in element.glyph_repairs.values())
    return sorted(assets)


def _config(spec, job, template):
    settings=spec.node("data").params.get("options",{})
    base=(asdict(template.data) if template.data.path else asdict(suggest_import(job.data_path)))
    base.update(settings)
    base.update(job.data_options)
    base["path"]=job.data_path
    profiles=spec.node("mapping").params.get("profiles",{})
    profile=job.mapping_profile or spec.node("mapping").params.get("default_profile","")
    if profile:
        if profile not in profiles or not isinstance(profiles[profile],dict):
            raise CompositionError(f"Mapping profile not found: {profile}")
        base["mapping"]=copy.deepcopy(profiles[profile])
    return DataConfig(**base)


def _signature(spec, job):
    template=load_project(job.template_path)
    validate_template(template)
    config=_config(spec,job,template) if template.record_mode=="imported" else None
    assets=_assets(template)
    sources=[job.template_path,*assets]+([job.data_path] if config else [])
    hashes={str(Path(p).resolve()):file_hash(Path(p)) for p in sources}
    signature=hashlib.sha256(json.dumps({"files":hashes,"config":asdict(config) if config else None,
        "starts":job.sequence_starts,"output":job.output_name,
        "pipeline":[{"kind":n.kind,"id":n.id,"params":n.params} if n.kind in EXTRA_KINDS else n.kind for n in spec.chain()],
        "auto_repair":spec.node("compose").params.get("auto_repair",True)},sort_keys=True).encode()).hexdigest()
    return signature,template,config,hashes


def _finished_valid(job):
    result=job.result
    if result.get("status")=="completed" and result.get("generated_files")==0 and result.get("input_records")==0:
        return Path(result.get("report_dir",""),"job.json").is_file()
    if result.get("output_files"):
        return (result.get("status")=="completed" and all(Path(f["output_pdf"]).is_file()
            and f.get("output_sha256")==file_hash(Path(f["output_pdf"])) for f in result["output_files"])
            and Path(result.get("report_dir",""),"job.json").is_file())
    pdf=Path(result.get("output_pdf", ""))
    return (result.get("status")=="completed" and pdf.is_file()
            and result.get("output_sha256")==file_hash(pdf)
            and Path(result.get("report_dir", ""),"job.json").is_file())


def prepare(spec: WorkflowSpec, run: BatchRun, directory, *, progress=None, is_cancelled=None):
    """Inspect all pairs and create isolated snapshots; does not approve or produce PDFs."""
    spec.chain()
    if spec.project_kind!="mail_merge_workflow":
        raise CompositionError("This queue requires a Mail Merge workflow.")
    root=Path(directory).resolve()/"mail-snapshots"
    root.mkdir(parents=True,exist_ok=True)
    names={}
    for job in run.jobs:
        names.setdefault(job.output_name.casefold(),[]).append(job.id)
    run.status="Checking"
    for index,job in enumerate(run.jobs,1):
        if is_cancelled and is_cancelled():
            run.status="Cancelled"
            break
        job.error=""
        job.stage="Check inputs"
        try:
            job.validate()
            check_cancel(is_cancelled)
            if len(names[job.output_name.casefold()])>1:
                raise CompositionError("Duplicate output name in batch. Give each job a distinct filename.")
            signature,template,config,before=_signature(spec,job)
            job.template_fields=sorted(required_fields(template)-{seq.name for seq in template.sequences})
            job.sequence_fields=[asdict(seq) for seq in template.sequences]
            if job.status=="Completed" and signature==job.signature and _finished_valid(job):
                job.stage="Finished"
                continue
            job.warnings=[]
            was_approved=job.approved and job.signature==signature
            if job.snapshot_dir:
                previous=Path(job.snapshot_dir).resolve()
                if previous.parent==root and previous.name.startswith((job.id+"-",job.id[:8]+"-")) and previous.exists():
                    shutil.rmtree(previous)
            # Leave room for bundled font asset names under Windows MAX_PATH.
            snapshot=root/(job.id[:8]+"-"+uuid.uuid4().hex[:12])
            snapshot.mkdir()
            job.snapshot_dir=str(snapshot)
            if job.result:
                job.history.append(job.result)
                job.result={}
            sequence_names={seq.name for seq in template.sequences}
            unknown=set(job.sequence_starts)-sequence_names
            if unknown:
                raise CompositionError("Unknown sequence fields: "+", ".join(sorted(unknown)))
            for seq in template.sequences:
                seq.start=job.sequence_starts.get(seq.name,seq.start)
            validate_template(template)
            # Resolve and copy exact faces, including bundled fonts, into the job snapshot.
            for element in template.all_elements():
                if element.type=="text" or element.show_barcode_text:
                    element.font.file=str(load_font(element.font)[1])
                    element.font.bold=element.font.italic=False
                for font in element.glyph_repairs.values():
                    font.file=str(load_font(font)[1])
                    font.bold=font.italic=False
            saved=save_project(template,snapshot/"template.pdcx")
            template=load_project(saved)
            job.record_store=""
            if config:
                job.stage="Import data"
                store=import_records(config,snapshot/"records.sqlite",progress=progress,is_cancelled=is_cancelled)
                job.record_store=str(store.path)
            with_records=open_records(template,job.record_store)
            job.data_summary={}
            if any(n.kind in EXTRA_KINDS for n in spec.chain()):
                from .pipeline import prepare_records, split_names, summary, validate_result
                transformed=prepare_records(spec,with_records,snapshot/"pipeline",template=template,
                    progress=progress,is_cancelled=is_cancelled)
                job.record_store=str(transformed.path)
                job.data_summary=summary(transformed,with_records.count)
                job.data_summary["outputs"]=split_names(transformed,job.output_name)
                from .transforms import export_audit
                report=snapshot/"data-review"
                export_audit(transformed,report)
                job.data_summary.update(findings_report=str(report/"findings.csv"),exclusions_report=str(report/"exclusions.csv"))
                validate_result(transformed)
                template.record_mode="imported"
                with_records=open_records(template,job.record_store)
            missing=required_fields(template)-set(with_records.fields)
            if missing:
                raise CompositionError("Missing mapped fields: "+", ".join(sorted(missing)))
            if any(file_hash(Path(p))!=digest for p,digest in before.items()):
                raise CompositionError("Input changed during checking. Check this job again.")
            job.prepared_template=template.to_dict()
            job.snapshot_hashes={str(p):file_hash(p) for p in snapshot.rglob("*") if p.is_file()}
            job.input_records=with_records.count
            job.pages_per_record=len(template.pages)
            job.expected_pages=job.input_records*job.pages_per_record
            if template.media.get("enabled") and job.input_records:
                from composition.media.planner import build_print_plan
                media_plan=build_print_plan(template,job.input_records,is_cancelled=is_cancelled)
                job.pages_per_record=media_plan.settings_for(1).output_pages_per_envelope
                job.expected_pages=media_plan.output_pages
                if not job.data_summary:
                    job.data_summary={"input":job.input_records,"retained":job.input_records,"excluded":0,
                                      "errors":0,"warnings":0,"steps":[],"fields":list(with_records.fields)}
                job.data_summary["media"]={**asdict(media_plan.preflight()),"profile":template.media["printer_profile"]}
            job.warnings=list(with_records.metadata.get("warnings",[]))
            if job.data_summary.get("warnings"):
                job.warnings.append(f"Data validation: {job.data_summary['warnings']} warning(s). Review findings.csv.")
            job.signature=signature
            job.approved=was_approved
            job.status="Ready" if was_approved else "Needs review"
            job.stage="Preview & Review"
        except Exception as exc:
            job.approved=False
            job.prepared_template={}
            job.record_store=""
            job.input_records=job.expected_pages=job.pages_per_record=0
            job.status="Pending" if is_cancelled and is_cancelled() else "Blocked"
            job.error=str(exc)
            if is_cancelled and is_cancelled():
                run.status="Cancelled"
                break
        if progress:
            progress(index,len(run.jobs),f"Checked {index}/{len(run.jobs)} · {job.name}")
    if run.status!="Cancelled":
        run.status="Needs review"
    return run


def approve(run, identities):
    selected=set(identities)
    for job in run.jobs:
        if job.id in selected and job.status in ("Needs review","Ready") and job.prepared_template:
            job.approved=True
            job.status="Ready"
    return run


def save_record(run, path):
    value={**run.to_dict(),"jobs":[job.record() for job in run.jobs],"batch_version":1}
    with atomic_output(Path(path)) as temp:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def load_record(path):
    file=Path(path)
    if file.stat().st_size>32*1024*1024:
        raise CompositionError("Batch record exceeds 32 MB.")
    value=json.loads(file.read_text(encoding="utf-8"))
    if value.pop("batch_version",None)!=1:
        raise CompositionError("Unsupported batch record version.")
    run=BatchRun.from_dict(value)
    for job in run.jobs:
        job.approved=False
        if job.status!="Completed":
            job.status="Needs review"
    if run.status=="Running":
        run.status="Needs review"
    return run


def _reports(run, root):
    save_record(run,root/"batch.json")
    with atomic_output(root/"batch-summary.csv") as temp, temp.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["Batch ID","Name","Template","Data","Status","Job ID","Retained records","Expected pages","Generated pages","PDF","Reports","Error","Source records","Excluded records"])
        for job in run.jobs:
            values=[run.batch_id,job.name,job.template_path,job.data_path,job.status,job.result.get("job_id",""),job.input_records,
                job.expected_pages,job.result.get("generated_pages",0),job.result.get("output_pdf",""),job.result.get("report_dir",""),job.error,
                job.data_summary.get("input",job.input_records),job.data_summary.get("excluded",0)]
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(("=","+","-","@")) else v for v in values])


def execute_batch(spec, run, output_dir, *, progress=None, is_cancelled=None, on_state=None):
    spec.chain()
    if not output_dir:
        raise CompositionError("Choose a batch output folder.")
    root=Path(output_dir).resolve()/("batch-"+run.batch_id)
    root.mkdir(parents=True,exist_ok=True)
    run.report_dir=str(root)
    run.status="Running"
    run.started_at=run.started_at or now()
    _reports(run,root)
    if on_state:
        on_state({"status":run.status,"jobs":[]})
    for index,job in enumerate(run.jobs,1):
        if is_cancelled and is_cancelled():
            run.status="Cancelled"
            break
        if job.status!="Ready" or not job.approved:
            continue
        try:
            job.stage="Recheck inputs"
            signature,_,_,_=_signature(spec,job)
            if signature!=job.signature or not job.prepared_template:
                job.approved=False
                job.status="Needs review"
                job.error="Inputs/settings changed. Check and approve this item again."
                _reports(run,root)
                if on_state:
                    on_state({"status":run.status,"jobs":[job.record()]})
                continue
            if not job.snapshot_hashes or any(not Path(p).is_file() or file_hash(Path(p))!=digest for p,digest in job.snapshot_hashes.items()):
                raise CompositionError("Checked snapshot changed or is unavailable. Check this item again.")
            check_cancel(is_cancelled)
            job.status="Running"
            job.stage="Compose"
            _reports(run,root)
            if on_state:
                on_state({"status":run.status,"jobs":[job.record()]})
            def job_progress(done,total,message,current_job=job,current_index=index):
                current_job.stage=message
                if progress:
                    progress(done,total,f"Job {current_index}/{len(run.jobs)} · {current_job.name} · {message}")
            partitions=job.data_summary.get("outputs",[])
            if job.input_records==0:
                from .transforms import DataSet, export_audit
                empty_id=new_job_id()
                report=root/empty_id
                report.mkdir()
                export_audit(DataSet(job.record_store),report)
                result={"job_id":empty_id,"status":"completed","input_records":0,"successful_records":0,
                    "generated_pages":0,"generated_files":0,"output_pdf":"","report_dir":str(report),"error":"",
                    "source_records":job.data_summary.get("input",0),"excluded_records":job.data_summary.get("excluded",0),
                    "warnings":["No records selected. No empty PDF was generated."]}
                (report/"job.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
            else:
                result=_compose_item(spec,job,root,partitions,job_progress,is_cancelled)
            if job.data_summary:
                result.update(source_records=job.data_summary["input"],excluded_records=job.data_summary["excluded"],
                              retained_records=job.data_summary["retained"])
            job.result=result
            job.error=result["error"]
            job.status={"completed":"Completed","cancelled":"Cancelled"}.get(result["status"],"Failed")
            if job.status=="Completed":
                if result["output_pdf"]:
                    job.result["output_sha256"]=file_hash(Path(result["output_pdf"]))
                job.warnings=list(result.get("warnings",[]))
            job.stage="Finished"
        except JobCancelled:
            job.status="Cancelled"
            job.error="Cancellation requested."
        except Exception as exc:
            job.status="Failed"
            job.error=str(exc)
        job.approved=False
        _reports(run,root)
        if on_state:
            on_state({"status":run.status,"jobs":[job.record()]})
        if job.status=="Cancelled":
            run.status="Cancelled"
            break
    if run.status!="Cancelled":
        run.status="Completed" if run.jobs and all(j.status=="Completed" for j in run.jobs) else "Partial / needs attention"
    run.finished_at=now()
    _reports(run,root)
    return run


def _compose_item(spec,job,root,partitions,progress,is_cancelled):
    from contextlib import nullcontext
    # Short owned scratch paths avoid Windows MAX_PATH failures in nested font caches.
    context=tempfile.TemporaryDirectory(prefix="wf-prod-") if partitions else nullcontext(str(root))
    with context as directory:
        def reports(report,result):
            if job.data_summary.get("steps"):
                from .transforms import DataSet, export_audit
                export_audit(DataSet(job.record_store),report)
                (report/"workflow-data.json").write_text(json.dumps({
                    "input":job.data_summary["input"],"retained":job.data_summary["retained"],
                    "excluded":job.data_summary["excluded"],"errors":job.data_summary["errors"],
                    "warnings":job.data_summary["warnings"]},indent=2),encoding="utf-8")
        result=generate(ProductionJob(job.prepared_template,job.record_store,str(directory),
            auto_repair=bool(spec.node("compose").params.get("auto_repair",True)),output_name=job.output_name),
            progress=progress,is_cancelled=is_cancelled,additional_reports=reports,_defer_media_ticket=bool(partitions)).to_dict()
        if result["status"]=="completed" and partitions:
            from .splitter import split_composed
            from .transforms import DataSet
            result=split_composed(result,DataSet(job.record_store),partitions,root,job.pages_per_record,
                                  is_cancelled=is_cancelled,progress=progress)
        elif partitions and result.get("report_dir"):
            report=root/(result["job_id"]+"-failed")
            shutil.copytree(result["report_dir"],report)
            result["report_dir"]=str(report)
        return result
