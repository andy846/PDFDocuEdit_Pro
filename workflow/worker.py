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
from .registry import EXTRA_KINDS


def dispatch(request, progress, cancelled, emit_state=None):
    operation=request["operation"]
    if operation == "production_review_prepare":
        from .production_review import prepare_contexts
        return prepare_contexts(request, progress=progress, is_cancelled=cancelled)
    if request.get("production_reviews"):
        from .production_review import validate_receipts
        validate_receipts(request, is_cancelled=cancelled)
    if operation.startswith("branch_"):
        from .branch_engine import approve_routes, execute_routes, prepare_routes, rows
        spec=WorkflowSpec.from_dict(request["spec"])
        if operation=="branch_folder":
            check=Path(request["folder"])
            paths=[]
            for file in sorted(check.iterdir(),key=lambda p:p.name.casefold()):
                if cancelled():
                    from composition.production.generator import JobCancelled
                    raise JobCancelled()
                if file.suffix.lower() in (".csv",".txt",".tsv",".xlsx",".xlsm") and file.is_file():
                    paths.append(str(file.resolve()))
                if len(paths)>10000:
                    raise CompositionError("A folder snapshot supports at most 10,000 data files.")
            return {"paths":paths}
        if operation=="branch_template":
            from composition.template.serializer import load_project
            return {"template":load_project(request["path"]).to_dict()}
        if operation=="branch_check":
            return {"run":prepare_routes(spec,request["directory"],previous=request.get("run"),target_id=request.get("node_id"),
                                         progress=progress,is_cancelled=cancelled,on_state=emit_state)}
        if operation=="branch_approve":
            return {"run":approve_routes(spec,request["run"],request["identities"],acknowledge=request.get("acknowledge",False))}
        if operation=="branch_run":
            return {"run":execute_routes(spec,request["run"],request["directory"],request["output_dir"],
                                         progress=progress,is_cancelled=cancelled,on_state=emit_state)}
        if operation=="branch_rows":
            return rows(spec,request["run"],request["directory"],source_id=request.get("source_id",""),
                        branch_id=request.get("branch_id",""),view=request.get("view","output"),offset=request.get("offset",0),
                        search=request.get("search",""),node_id=request.get("node_id",""))
        if operation=="branch_preview":
            from .branch_engine import _check_current, _location, branch_signature
            _location(request["directory"],request["run"])
            _check_current(spec,request["run"])
            entry=next((e for e in request["run"]["jobs"] if e["id"]==request["job_id"]),None)
            if not entry or not entry["batch"] or branch_signature(spec,request["run"]["signature"],entry["branch_id"])!=entry["signature"]:
                raise CompositionError("Check this branch before previewing it.")
            target=Path(request["target"]).resolve()
            if not target.is_relative_to(Path(request["directory"]).resolve()):
                raise CompositionError("Invalid preview destination.")
            return dispatch({**request,"operation":"batch_preview","spec":entry["spec"],"batch":entry["batch"]},progress,cancelled,emit_state)
        raise CompositionError("Unknown branch operation.")
    if operation in ("inspect_step","inspection_rows","inspection_preview","inspection_value"):
        from .batch import BatchJob
        from .inspection import inspect_step, inspection_preview, inspection_rows, inspection_value
        spec=WorkflowSpec.from_dict(request["spec"])
        job=BatchJob(**request["job"]) if request.get("job") else None
        if job:
            job.validate()
        if operation=="inspect_step":
            return inspect_step(spec,request["node_id"],request["directory"],job=job,progress=progress,
                                is_cancelled=cancelled,emit_state=emit_state)
        options=dict(job=job)
        if operation=="inspection_value":
            return inspection_value(request["directory"],request["run_id"],request["node_id"],spec,
                                    **options,view=request.get("view","output"),record=request.get("record",1),field_name=request.get("field_name",""))
        if operation=="inspection_rows":
            return inspection_rows(request["directory"],request["run_id"],request["node_id"],spec,
                                   **options,view=request.get("view","output"),offset=request.get("offset",0),search=request.get("search",""),source_id=request.get("source_id"))
        return inspection_preview(request["directory"],request["run_id"],request["node_id"],spec,request["target"],
                                  **options,record=request.get("record",1),page=request.get("page",1))
    if operation.startswith("batch_"):
        from .batch import BatchRun, approve, execute_batch, load_record, prepare, save_record
        if operation=="batch_load":
            return {"batch":load_record(request["path"]).to_dict()}
        run=BatchRun.from_dict(request["batch"])
        if operation=="batch_project_save":
            from .serializer import save_workflow
            path=save_workflow(WorkflowSpec.from_dict(request["spec"]),request["path"],is_cancelled=cancelled)
            save_record(run,Path(path).with_suffix(".batch.json"))
            return {"path":path}
        if operation=="batch_save":
            save_record(run,request["path"])
            return {"path":request["path"]}
        spec=WorkflowSpec.from_dict(request["spec"])
        if operation=="batch_check":
            return {"batch":prepare(spec,run,request["directory"],progress=progress,is_cancelled=cancelled).to_dict()}
        if operation=="batch_run":
            approve(run,request["approved"])
            return {"batch":execute_batch(spec,run,request["output_dir"],progress=progress,is_cancelled=cancelled,on_state=emit_state).to_dict()}
        if operation=="batch_preview":
            from composition.data.sequences import open_records
            from composition.engine.preview_raster import save_preview
            from composition.engine.renderer import render_preview
            from composition.template.model import Template
            job=next(j for j in run.jobs if j.id==request["job_id"])
            # Preview the exact frozen input that was checked, only one requested page.
            template=Template.from_dict(job.prepared_template)
            records=open_records(template,job.record_store)
            ordinal=request["record"]
            raw=render_preview(template,records.record(ordinal),ordinal=ordinal,page_index=request.get("page",1)-1,
                               auto_repair=bool(spec.node("compose").params.get("auto_repair",True)))
            image=Path(request["target"])
            with fitz.open(stream=raw,filetype="pdf") as doc:
                save_preview(doc[0],image,2)
            return {"image":str(image),"job_id":job.id,"record":ordinal,"pages":len(template.pages)}
        raise CompositionError("Unknown batch operation.")
    if operation=="run":
        return asdict(execute(WorkflowSpec.from_dict(request["spec"]),WorkflowRun(**request["run"]),
                              request["directory"],until=request.get("until","review"),
                              progress=progress,is_cancelled=cancelled,
                              review_context=request["production_reviews"][0]["context"] if request.get("production_reviews") else None))
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
            checked=None
            has_pipeline=request.get("workflow",{}).get("workflow_version",1)>=3 and any(
                n["kind"] in EXTRA_KINDS for n in request["workflow"]["nodes"])
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
                if has_pipeline:
                    from .pdf_pipeline import prepare_mailpieces
                    checked=WorkflowRun(**request["workflow_run"])
                    checked.groups=groups
                    prepare_mailpieces(WorkflowSpec.from_dict(request["workflow"]),checked,request["directory"],
                                       progress=progress,is_cancelled=cancelled)
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
            pipeline={}
            if has_pipeline and action in ("accept","correct","groups"):
                from .pdf_pipeline import prepare_mailpieces
                if checked is None:
                    checked=WorkflowRun(**request["workflow_run"])
                    checked.groups=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
                    prepare_mailpieces(WorkflowSpec.from_dict(request["workflow"]),checked,request["directory"],
                                       progress=progress,is_cancelled=cancelled)
                pipeline={"data_summary":checked.data_summary,"data_steps":checked.data_steps,"data_set":checked.data_set}
            return {**pipeline,"groups":[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")],"cells":rows,"page":number,"issues":store.issues(),"accepted":store.metadata()["accepted"]=="true",
                    "pages":int(store.metadata()["pages"]),"envelope":envelope[0] if envelope else None,
                    "envelope_cells":[dict(r) for r in store.db.execute("SELECT * FROM envelope_cells WHERE envelope=?",(envelope[0],))] if envelope else []}
    if operation in ("make_overlay","bind_overlay"):
        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.serializer import save_project
        from composition.pdf_source.model import EnvelopeSettings
        from composition.pdf_source.source import inspect_source
        from composition.template.serializer import file_hash

        from .engine import detection_audit
        workflow=WorkflowSpec.from_dict(request["spec"])
        project=EnvelopeSpec.from_dict(request["project"]) if operation=="bind_overlay" else None
        external={}
        source_path=request["source"]
        groups=request["groups"]
        if workflow.workflow_version>=3 and any(n.kind in EXTRA_KINDS for n in workflow.nodes):
            import shutil
            import uuid

            from .pdf_pipeline import production_view
            state=WorkflowRun(**request["workflow_run"])
            state.groups=groups
            data,source_path,groups,_selected=production_view(workflow,state,request["directory"],progress=progress,is_cancelled=cancelled)
            frozen=Path(request["directory"])/("overlay-data-"+uuid.uuid4().hex+".sqlite")
            shutil.copyfile(data.path,frozen)
            external={"external_data":str(frozen),"external_database":state.database,"external_data_sha256":file_hash(frozen)}
        cfg=EnvelopeSettings(pages_per_envelope=1,groups=groups)
        if project:
            for name in ("start","increment","digits","prefix","suffix","duplex"):
                setattr(cfg,name,getattr(project.settings,name))
        import shutil

        from composition.template.serializer import file_hash
        from core.io_atomic import atomic_output
        target=Path(request["path"]).resolve().with_suffix(".pdcx")
        assets=target.parent/(target.stem+".assets")
        assets.mkdir(parents=True,exist_ok=True)
        digest=file_hash(Path(source_path))
        source_copy=assets/(digest+".pdf")
        if source_copy.exists() and file_hash(source_copy)!=digest:
            raise CompositionError("The saved overlay source asset has changed. Choose another project filename.")
        if not source_copy.exists():
            with atomic_output(source_copy,overwrite=False) as temp:
                shutil.copyfile(source_path,temp)
                if file_hash(temp)!=digest:
                    raise CompositionError("Source changed while creating the overlay project.")
        source=inspect_source(source_copy,cfg,uniform=True,is_cancelled=cancelled)
        spec=EnvelopeSpec(source,cfg,objects=project.objects if project else [],
                          required_scope=project.required_scope if project else "all_source",
                          name=project.name if project else workflow.name,external_fields=external_fields(workflow))
        media=workflow.node("media_assignment")
        spec.media=media.params.copy() if media else project.media.copy() if project else {}
        if project and project.source.sha256==source.sha256:
            spec.source_link=project.source_link
        report = None if external else workflow.node("group").params.get("detection_review")
        if report and report.get("source_sha256") != source.sha256:
            raise CompositionError("Detection source changed. Analyze and review again before opening Designer.")
        spec.detection_review=detection_audit(spec, report)
        spec.validate()
        if operation=="bind_overlay":
            return {"spec":spec.to_dict(),**external}
        return {"path":str(save_project(spec,request["path"])),**external}
    raise CompositionError("Unknown workflow worker operation.")
