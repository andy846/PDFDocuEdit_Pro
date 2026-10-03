"""Operations dispatched in the existing isolated composition worker process."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import fitz

from composition.template.model import MM_TO_PT, CompositionError

from .engine import execute, external_fields
from .extraction import ExtractionSpec, ExtractionStore, extract_page
from .model import WorkflowRun, WorkflowSpec


def dispatch(request, progress, cancelled):
    operation=request["operation"]
    if operation=="run":
        return asdict(execute(WorkflowSpec.from_dict(request["spec"]),WorkflowRun(**request["run"]),
                              request["directory"],until=request.get("until","review"),
                              progress=progress,is_cancelled=cancelled))
    if operation=="save":
        from .serializer import save_workflow
        return {"path":save_workflow(WorkflowSpec.from_dict(request["spec"]),request["path"],is_cancelled=cancelled)}
    if operation=="load":
        from .serializer import load_workflow
        return {"spec":load_workflow(request["path"]).to_dict()}
    if operation=="preview":
        validation_error=""
        try:
            spec=ExtractionSpec.from_dict(request["extraction"]) if request["extraction"].get("regions") else None
        except ValueError as exc:
            if not request.get("allow_invalid_draft",False):
                raise
            spec=None
            validation_error=str(exc)
        with fitz.open(request["source"]) as pdf:
            number=request["page"]
            if type(number) is not int or not 1<=number<=pdf.page_count or pdf.needs_pass:
                raise CompositionError("Requested PDF preview page is unavailable.")
            page=pdf[number-1]
            scale=min(max(request.get("scale",2),1),4096/max(page.rect.width,page.rect.height))
            target=Path(request["target"])
            if request.get("raster",True):
                pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                pix.save(target)
            return {"validation_error":validation_error,"image":str(target),"width_mm":page.rect.width/MM_TO_PT,"height_mm":page.rect.height/MM_TO_PT,
                    "pages":pdf.page_count,"cells":[{"field":r.name,"raw":raw,"value":value,"issue":issue}
                    for r in (spec.regions if spec else []) for raw,value,issue in [extract_page(page,r)]]}
    if operation=="review":
        with ExtractionStore(request["database"]) as store:
            spec=ExtractionSpec.from_dict(json.loads(store.metadata()["spec"]))
            groups=request["groups"]
            action=request.get("action","")
            if action=="correct":
                with store.db:
                    store.correct(request["page"],request["field"],request["value"],request["reason"],commit=False)
                    if groups:
                        store.grouped(groups,spec,is_cancelled=cancelled,commit=False)
            elif action=="groups":
                old=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
                with store.db:
                    store.grouped(groups,spec,is_cancelled=cancelled,commit=False)
                    store.db.execute("INSERT INTO group_edits VALUES (?,?,?)",
                        (json.dumps(old),json.dumps(groups),request.get("reason","Operator boundary correction")))
            elif action=="accept":
                store.accept()
            elif action=="export":
                store.export(request["target"])
            number=request.get("page",1)
            if action in ("next_issue","previous_issue"):
                operator,order=(">","ASC") if action=="next_issue" else ("<","DESC")
                candidates="SELECT page FROM cells WHERE applicable=1 AND issue!='' UNION SELECT issue_page AS page FROM envelope_cells WHERE issue!=''"
                found=store.db.execute(f"SELECT page FROM ({candidates}) WHERE page {operator} ? ORDER BY page {order} LIMIT 1",(number,)).fetchone()
                if not found:
                    found=store.db.execute(f"SELECT page FROM ({candidates}) ORDER BY page {order} LIMIT 1").fetchone()
                number=found[0] if found else number
            rows=store.page(number)
            envelope=store.db.execute("SELECT envelope FROM groups WHERE ? BETWEEN start AND end",(number,)).fetchone()
            return {"groups":[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")],"cells":rows,"page":number,"issues":store.issues(),"accepted":store.metadata()["accepted"]=="true",
                    "pages":int(store.metadata()["pages"]),"envelope":envelope[0] if envelope else None,
                    "envelope_cells":[dict(r) for r in store.db.execute("SELECT * FROM envelope_cells WHERE envelope=?",(envelope[0],))] if envelope else []}
    if operation in ("make_overlay","bind_overlay"):
        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.serializer import save_project
        from composition.pdf_source.model import EnvelopeSettings
        from composition.pdf_source.source import inspect_source

        from .engine import detection_audit
        workflow=WorkflowSpec.from_dict(request["spec"])
        project=EnvelopeSpec.from_dict(request["project"]) if operation=="bind_overlay" else None
        cfg=EnvelopeSettings(pages_per_envelope=1,groups=request["groups"])
        if project:
            for name in ("start","increment","digits","prefix","suffix","duplex"):
                setattr(cfg,name,getattr(project.settings,name))
        import shutil

        from composition.template.serializer import file_hash
        from core.io_atomic import atomic_output
        target=Path(request["path"]).resolve().with_suffix(".pdcx")
        assets=target.parent/(target.stem+".assets")
        assets.mkdir(parents=True,exist_ok=True)
        digest=file_hash(Path(request["source"]))
        source_copy=assets/(digest+".pdf")
        if source_copy.exists() and file_hash(source_copy)!=digest:
            raise CompositionError("The saved overlay source asset has changed. Choose another project filename.")
        if not source_copy.exists():
            with atomic_output(source_copy,overwrite=False) as temp:
                shutil.copyfile(request["source"],temp)
                if file_hash(temp)!=digest:
                    raise CompositionError("Source changed while creating the overlay project.")
        source=inspect_source(source_copy,cfg,uniform=True,is_cancelled=cancelled)
        spec=EnvelopeSpec(source,cfg,objects=project.objects if project else [],
                          required_scope=project.required_scope if project else "all_source",
                          name=project.name if project else workflow.name,external_fields=external_fields(workflow))
        if project and project.source.sha256==source.sha256:
            spec.source_link=project.source_link
        report = workflow.node("group").params.get("detection_review")
        if report and report.get("source_sha256") != source.sha256:
            raise CompositionError("Detection source changed. Analyze and review again before opening Designer.")
        spec.detection_review=detection_audit(spec, report)
        spec.validate()
        if operation=="bind_overlay":
            return {"spec":spec.to_dict()}
        return {"path":str(save_project(spec,request["path"]))}
    raise CompositionError("Unknown workflow worker operation.")
