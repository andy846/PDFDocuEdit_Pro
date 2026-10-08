"""Headless workflow executor. Preview/review is a mandatory production boundary."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import fitz

from composition.overlay.generator import generate
from composition.overlay.model import EnvelopeSpec, OverlayJob
from composition.overlay.serializer import load_project as load_overlay
from composition.pdf_source.detection import DetectionConfig
from composition.pdf_source.detection import scan_pdf as detect_pdf
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.pdf_source.source import inspect_source, snapshot_source
from composition.production.generator import check_cancel
from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output
from core.merge import MergeItem, MergeSpec, merge_pdf_items

from .extraction import ExtractionSpec, ExtractionStore, scan_pdf
from .model import WorkflowRun
from .registry import PDF_OPERATION_KINDS


def context_fingerprint(spec, *, include_overlay=True):
    """Include source/template bytes so timestamps alone cannot retain stale approval."""
    parts=[spec.fingerprint()]
    for path in spec.node("input").params.get("paths",[]):
        parts.append(file_hash(Path(path)))
    overlay=spec.node("overlay")
    if include_overlay and overlay and overlay.params.get("path"):
        project=load_overlay(overlay.params["path"])
        parts.append(json.dumps(project.to_dict(),sort_keys=True))
        for obj in project.objects:
            for path in (obj.element.image,obj.element.font.file,*[f.file for f in obj.element.glyph_repairs.values()]):
                if path:
                    parts.append(file_hash(Path(path)))
    import hashlib
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def execute(spec, run, directory, *, until="review", progress=None, is_cancelled=None, review_context=None):
    spec.chain()
    if review_context is not None and until == "output":
        from .pdf_pipeline import execute_pdf
        return execute_pdf(spec, run, directory, until=until, progress=progress,
                           is_cancelled=is_cancelled, review_context=review_context)
    if spec.workflow_version>=3:
        from .registry import EXTRA_KINDS
        if any(n.kind in EXTRA_KINDS for n in spec.nodes):
            from .pdf_pipeline import execute_pdf
            return execute_pdf(spec,run,directory,until=until,progress=progress,is_cancelled=is_cancelled)
    if spec.project_kind!="pdf_workflow":
        raise CompositionError("Use the Mail Merge batch executor for this workflow type.")
    root=Path(directory)
    root.mkdir(parents=True,exist_ok=True)
    reserved={(root/name).resolve() for name in ("source.pdf","input-source.pdf","extraction.sqlite","source-map.jsonl","run.json")}
    if any(Path(path).resolve() in reserved for path in spec.node("input").params.get("paths",[])):
        raise CompositionError("Use a separate workflow scratch directory; it must not replace an input PDF.")
    import hashlib
    current=spec.node("input")
    run.error=""
    if until=="output":
        run.output={}
    try:
        # Downstream overlay assets are checked when that stage is reached, so a
        # missing template never prevents scanning and reviewing the input PDF.
        fingerprint=context_fingerprint(spec,include_overlay=False)
        prior="|".join(file_hash(Path(p)) for p in spec.node("input").params.get("paths",[]))
        if run.source and not Path(run.source).is_file():
            run=WorkflowRun()
        if run.database:
            try:
                if not Path(run.database).is_file():
                    raise CompositionError("Missing extraction database")
                with ExtractionStore(run.database) as store:
                    if store.metadata()["sha256"]!=file_hash(Path(run.source)):
                        raise CompositionError("Changed workflow snapshot")
            except Exception:
                # Rebuild and demand review rather than reusing missing/tampered data.
                run=WorkflowRun()
        run.fingerprint=fingerprint
        if until=="output" and spec.node("output"):
            run.statuses.pop(spec.node("output").id,None)
        signatures={}
        for node in spec.chain():
            check_cancel(is_cancelled)
            current=node
            content=json.dumps(node.params,sort_keys=True)
            if node.kind=="overlay" and node.params.get("path"):
                content+=context_fingerprint(spec)
            prior=hashlib.sha256((prior+node.kind+content).encode()).hexdigest()
            signatures[node.id]=prior
            unchanged=run.signatures.get(node.id)==signatures[node.id]
            if node.kind in ("input", "merge", *PDF_OPERATION_KINDS) and unchanged:
                cached = run.pdf_sources.get(node.id)
                if cached:
                    path = Path(cached["path"]).resolve()
                    if not path.is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != cached["sha256"]:
                        unchanged = False
                    else:
                        run.source = str(path)
                elif node.kind in PDF_OPERATION_KINDS:
                    unchanged = False
            if node.kind=="review":
                if not unchanged:
                    run.accepted=False
                run.signatures[node.id]=signatures[node.id]
                run.statuses[node.id]="Completed" if run.accepted else "Needs review"
                if not run.accepted or until=="review":
                    return run
                continue
            if unchanged and run.statuses.get(node.id)=="Completed":
                if node.kind==until:
                    return run
                continue
            if not unchanged:
                tail=False
                for downstream in spec.chain():
                    tail=tail or downstream.id==node.id
                    if tail:
                        run.statuses.pop(downstream.id,None)
                        run.signatures.pop(downstream.id,None)
                        run.pdf_operation_reports.pop(downstream.id, None)
                        run.pdf_sources.pop(downstream.id, None)
                if node.kind in ("input","merge","extract","group", *PDF_OPERATION_KINDS):
                    run.accepted=False
                    run.output={}
            run.statuses[node.id]="Running"
            if progress:
                progress(0,0,"Workflow: "+node.kind)
            if node.kind=="input":
                paths=node.params.get("paths",[])
                if not isinstance(paths,list) or not paths or any(not isinstance(p,str) for p in paths):
                    raise CompositionError("Add one or more source PDFs.")
                if len(paths)>1 and not spec.node("merge"):
                    raise CompositionError("Multiple sources require a Merge node.")
                # All downstream work reads an immutable owned snapshot.
                run.source=str(root/("input-source.pdf" if spec.workflow_version == 6 else "source.pdf"))
                if len(paths)==1:
                    # The job snapshot helper intentionally refuses overwrites.
                    # Replace only our owned scratch PDF, after the new copy is complete.
                    with atomic_output(run.source) as temp:
                        temp.unlink()
                        snapshot_source(paths[0],temp,file_hash(Path(paths[0])),is_cancelled=is_cancelled)
            elif node.kind=="merge":
                paths=spec.node("input").params["paths"]
                selections=node.params.get("pages",{})
                if not isinstance(selections,dict):
                    raise CompositionError("Invalid merge page selection.")
                from core.merge import strict_pages
                items=[]
                for path in paths:
                    with fitz.open(path) as doc:
                        selected=strict_pages(selections.get(path,"All"),doc.page_count)
                    items.append(MergeItem(path,pages=selected))
                run.source = str(root / "source.pdf")
                merged=merge_pdf_items(MergeSpec(items,run.source),progress=progress,is_cancelled=is_cancelled)
                with atomic_output(root/"source-map.jsonl") as temp:
                    with temp.open("w",encoding="utf-8") as stream:
                        for row in merged.page_map:
                            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
            elif node.kind in PDF_OPERATION_KINDS:
                from .pdf_operations import process_pdf
                report = process_pdf(node, run.source, root, progress=progress, is_cancelled=is_cancelled)
                run.source = report["output_pdf"]
                run.pdf_operation_reports[node.id] = report
            elif node.kind=="extract":
                result=scan_pdf(run.source,ExtractionSpec.from_dict(node.params),root/"extraction.sqlite",
                                progress=progress,is_cancelled=is_cancelled)
                run.database=result.database
                with ExtractionStore(run.database) as store,store.db:
                    if spec.node("merge"):
                        with (root/"source-map.jsonl").open(encoding="utf-8") as stream:
                            for raw in stream:
                                mapped=json.loads(raw)
                                store.db.execute("UPDATE provenance SET source_file=?,source_page=? WHERE page=?",
                                    (mapped["source_file"],mapped["source_page"],mapped["output_page"]))
                    else:
                        store.db.execute("UPDATE provenance SET source_file=?",(spec.node("input").params["paths"][0],))
            elif node.kind=="group":
                group(spec,run,progress=progress,is_cancelled=is_cancelled)
            elif node.kind=="overlay":
                # Loading/validating the selected project does not start composition yet.
                if not node.params.get("path"):
                    raise CompositionError("Configure an overlay project, or remove the optional Overlay node.")
                load_overlay(node.params["path"])
            elif node.kind=="output":
                if not run.accepted:
                    raise CompositionError("Accept extraction and mailpiece review before production.")
                if context_fingerprint(spec,include_overlay=False)!=run.fingerprint:
                    raise CompositionError("Source or configuration changed; scan and review again.")
                target=node.params.get("directory","")
                if not target:
                    raise CompositionError("Choose an output folder.")
                settings=EnvelopeSettings(pages_per_envelope=1,groups=run.groups)
                overlay=spec.node("overlay")
                project=load_overlay(overlay.params["path"]) if overlay else None
                source=inspect_source(run.source,settings,uniform=True,is_cancelled=is_cancelled)
                # Preserve configured sequence/duplex options while replacing source/grouping.
                if project:
                    settings.start=project.settings.start
                    settings.increment=project.settings.increment
                    settings.digits=project.settings.digits
                    settings.prefix=project.settings.prefix
                    settings.suffix=project.settings.suffix
                    settings.duplex=project.settings.duplex
                composed=EnvelopeSpec(source,settings,objects=project.objects if project else [],
                                      required_scope=project.required_scope if project else "all_source",
                                      name=spec.name,external_fields=external_fields(spec))
                composed.detection_review=detection_audit(composed)
                with ExtractionStore(run.database) as store:
                    if store.metadata()["sha256"]!=source.sha256:
                        raise CompositionError("Extraction source differs from the production PDF; scan and review again.")
                    if store.metadata()["accepted"]!="true":
                        raise CompositionError("Data was modified since review.")
                    reviewed_groups=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
                    if reviewed_groups!=run.groups:
                        raise CompositionError("Envelope boundaries differ from the accepted review; review again.")
                    prior_review = store.metadata().get("mailpiece_review")
                    composed.detection_review = detection_audit(composed, json.loads(prior_review) if prior_review else None)
                    composed.validate()
                    from core.variables import VariableContext
                    job=OverlayJob(composed.to_dict(),target, output_name=node.params.get("output_name", "production.pdf"))
                    job.variable_context = VariableContext.for_job(input_path=spec.node("input").params["paths"][0],
                        job_id=job.job_id, job_name=spec.name, sequence=1).to_dict()
                    def reports(report,result,source=source,settings=settings):
                        store.export(report/"extracted-data.csv")
                        import csv
                        with (report/"workflow-page-map.csv").open("w",encoding="utf-8-sig",newline="") as stream:
                            writer=csv.writer(stream)
                            writer.writerow(["Output page","Envelope","Sequence","Workflow source page","Original source file","Original source page"])
                            for page in EnvelopePlan(source.pages,settings).pages():
                                check_cancel(is_cancelled)
                                original=store.db.execute("SELECT source_file,source_page FROM provenance WHERE page=?",(page.source_page,)).fetchone()
                                writer.writerow([page.output_page,page.envelope,settings.sequence(page.envelope),page.source_page or "",
                                                 original[0] if original else "",original[1] if original else ""])
                        with atomic_output(report/"workflow.json") as temp:
                            temp.write_text(json.dumps({"workflow":spec.to_dict(),"fingerprint":run.fingerprint,
                                "groups":run.groups,"corrections":[dict(r) for r in store.db.execute("SELECT * FROM edits")],
                                "boundary_corrections":[dict(r) for r in store.db.execute("SELECT * FROM group_edits")],
                                "source_sha256":store.metadata()["sha256"],"output_pages":result.generated_pages,
                                "pdf_operations": run.pdf_operation_reports},
                                ensure_ascii=False,indent=2),encoding="utf-8")
                    result=generate(job,progress=progress,is_cancelled=is_cancelled,external_values=store.production_values,
                                    additional_reports=reports)
                    run.output=asdict(result)
                    if result.status!="completed":
                        raise CompositionError(result.error or "Production did not complete.")
            if node.kind in ("input", "merge", *PDF_OPERATION_KINDS) and Path(run.source).is_file():
                run.pdf_sources[node.id] = {"path": run.source, "sha256": file_hash(Path(run.source))}
            run.statuses[node.id]="Completed"
            run.signatures[node.id]=signatures[node.id]
            if node.kind==until:
                return run
        return run
    except Exception as exc:
        run.error=str(exc)
        if current and current.kind in ("input","merge","extract","group", *PDF_OPERATION_KINDS):
            run.accepted=False
            run.output={}
            if current.kind in ("input","merge","extract", *PDF_OPERATION_KINDS):
                run.database=""
                run.groups=[]
            tail=False
            for downstream in spec.chain():
                tail=tail or downstream.id==current.id
                if tail:
                    run.statuses.pop(downstream.id,None)
                    run.signatures.pop(downstream.id,None)
        if current:
            run.statuses[current.id]="Cancelled" if is_cancelled and is_cancelled() else "Failed"
        return run
    finally:
        with atomic_output(root/"run.json") as temp:
            temp.write_text(json.dumps(asdict(run),ensure_ascii=False,indent=2),encoding="utf-8")


def external_fields(spec):
    regions=ExtractionSpec.from_dict(spec.node("extract").params).regions
    page_names={r.name for r in regions}
    names=set(page_names)
    grouped=False
    for node in spec.chain():
        grouped=grouped or node.kind=="group"
        if node.kind=="create_fields":
            names.update(f["field"] for f in node.params.get("fields",[]))
            if not grouped:
                page_names.update(f["field"] for f in node.params.get("fields",[]))
        if node.kind=="running_sequence" and node.params.get("scope")!="page":
            names.add(node.params.get("name","Sequence"))
    fields=["Page_"+name for name in sorted(page_names)]+["Envelope_"+name for name in sorted(names)]
    fields.extend(n.params.get("name","Sequence") for n in spec.nodes if n.kind=="running_sequence")
    return fields


def group(spec,run,*,progress=None,is_cancelled=None):
    node=spec.node("group")
    cfg=node.params
    with ExtractionStore(run.database) as store:
        extraction=ExtractionSpec.from_dict(json.loads(store.metadata()["spec"]))
        pages=int(store.metadata()["pages"])
        method=cfg.get("method","fixed")
        if method=="fixed":
            size=cfg.get("pages",1)
            if type(size) is not int or not 1<=size<=100 or pages%size:
                raise CompositionError("Fixed grouping needs complete envelopes of 1–100 pages.")
            groups=[[start,min(start+size-1,pages)] for start in range(1,pages+1,size)]
        elif method=="field":
            key=cfg.get("field","")
            if key not in [r.name for r in extraction.regions]:
                raise CompositionError("Choose an extracted field for grouping.")
            groups=[]
            previous=None
            for number in range(1,pages+1):
                check_cancel(is_cancelled)
                value=store.values(number).get(key,"")
                if not value.strip():
                    raise CompositionError(f"Page {number}: grouping field {key} is empty; no boundary was guessed.")
                if value!=previous:
                    groups.append([number,number])
                else:
                    groups[-1][1]=number
                previous=value
        elif method=="pattern":
            result=detect_pdf(run.source,DetectionConfig(rules=[{"kind":"page_number","pattern":cfg.get("pattern","")}]),
                              progress=progress,is_cancelled=is_cancelled)
            result=result["detection"]
            if result["findings"]:
                raise CompositionError("Page-pattern detection has findings; resolve the PDF/page sequence before grouping.")
            groups=result["groups"]
        elif method=="reviewed_detection":
            report = cfg.get("detection_review", {})
            if not isinstance(report, dict) or report.get("accepted") is not True or not report.get("groups"):
                raise CompositionError("Analyze and accept mailpiece boundaries before using automatic detection.")
            DetectionConfig(**report.get("config", {})).validate()
            if report.get("source_sha256") != store.metadata()["sha256"] or report.get("pages") != pages:
                raise CompositionError("Detection source changed. Analyze and accept the current PDF again.")
            if report.get("excluded_pages"):
                raise CompositionError("Workflow automatic detection must retain all source pages.")
            groups = report["groups"]
        else:
            raise CompositionError("Unsupported grouping method.")
        EnvelopePlan(pages,EnvelopeSettings(groups=groups,pages_per_envelope=1))
        store.grouped(groups,extraction,progress=progress,is_cancelled=is_cancelled)
        with store.db:
            store.db.execute("DELETE FROM meta WHERE key='mailpiece_review'")
            if method == "reviewed_detection":
                store.db.execute("INSERT INTO meta VALUES (?,?)", ("mailpiece_review", json.dumps(report)))
        run.groups=groups
        run.accepted=False


def detection_audit(spec, review=None):
    if review:
        import copy
        result = copy.deepcopy(review)
        if result.get("groups") != spec.settings.groups:
            result.setdefault("edits", []).append({"method": "workflow_review", "groups": spec.settings.groups})
        result.update(accepted=True, source_sha256=spec.source.sha256, groups=spec.settings.groups,
                      pages=spec.source.pages, excluded_pages=[])
        return result
    return {"accepted":True,"source_sha256":spec.source.sha256,"groups":spec.settings.groups,
            "excluded_pages":[],"config":{"rules":[{"kind":"page_number","pattern":"Page {CURRENT} of {TOTAL}"}],
            "combine":"any","region_mm":None,"remove_separators":True,"version":1},
            "pages":spec.source.pages,"findings":[],"evidence":[],"edits":[{"method":"workflow_review"}]}
