"""Headless, non-publishing step checks with disk snapshots and bounded readers."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fitz

from composition.data.sequences import open_records
from composition.data.source import import_records, normalize_field, suggest_import
from composition.production.generator import JobCancelled, check_cancel
from composition.template.model import (
    CompositionError,
    DataConfig,
    Template,
    required_fields,
    validate_template,
)
from composition.template.serializer import file_hash, load_project
from core.io_atomic import atomic_output

from .model import WorkflowRun
from .registry import EXTRA_KINDS
from .transforms import DataSet, _sample, snapshot, transform


@dataclass
class StepInspectionResult:
    run_id: str
    node_id: str
    job_id: str = ""
    status: str = "Checked"
    signature: str = ""
    input_count: int = 0
    output_count: int = 0
    input_scope: str = "record"
    output_scope: str = "record"
    fields: list = field(default_factory=list)
    input_store: str = ""
    output_store: str = ""
    error: str = ""
    issue_count: int = 0
    plan: dict = field(default_factory=dict)
    template: dict = field(default_factory=dict)
    overlay: dict = field(default_factory=dict)
    source_hashes: dict = field(default_factory=dict)


class PrefixSpec:
    """Reuse existing headless helpers against only the checked prefix."""
    def __init__(self, spec, nodes):
        self.spec, self.nodes = spec, nodes
        self.project_kind, self.workflow_version = spec.project_kind, spec.workflow_version

    def chain(self):
        return self.nodes

    def node(self, kind):
        return next((node for node in self.nodes if node.kind == kind), None)


def _assets(template):
    from composition.engine.fonts import resolve_font
    paths = {page.background for page in template.pages if page.background}
    for element in template.all_elements():
        paths.update(p for p in (element.image, element.rules.alternative.image if element.rules.alternative else "") if p)
        if element.type == "text" or element.show_barcode_text:
            paths.add(str(resolve_font(element.font)))
        paths.update(str(resolve_font(font)) for font in element.glyph_repairs.values())
    return paths


def signature(spec, node_id, job=None, *, hashes=None):
    prefix = spec.execution_prefix(node_id)
    paths = set()
    if spec.project_kind == "mail_merge_workflow":
        if job is None:
            raise CompositionError("Select exactly one batch job to inspect.")
        paths.update(p for p in (job.data_path, job.template_path) if p)
        if job.template_path and any(n.kind == "template" for n in prefix):
            paths.update(_assets(load_project(job.template_path)))
    else:
        paths.update(spec.node("input").params.get("paths", []))
        overlay = next((n for n in prefix if n.kind == "overlay" and n.params.get("path")), None)
        if overlay:
            from composition.overlay.model import render_template
            from composition.overlay.serializer import load_project as load_overlay
            paths.add(overlay.params["path"])
            paths.update(_assets(render_template(load_overlay(overlay.params["path"]))))
    cached = hashes if hashes is not None else {}
    digests = {}
    for raw in sorted(paths):
        path = str(Path(raw).resolve())
        if path not in cached:
            cached[path] = file_hash(Path(path))
        digests[path] = cached[path]
    settings = {"project_kind": spec.project_kind, "nodes": [{"id": n.id, "kind": n.kind, "params": n.params} for n in prefix],
                "job": {k: getattr(job, k) for k in ("id", "data_path", "template_path", "data_options", "mapping_profile", "sequence_starts", "output_name")} if job else None,
                "sources": digests}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest(), digests


def _write(path, value):
    with atomic_output(path) as staged:
        staged.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")


def _folder(directory, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise CompositionError("Invalid inspection identity.")
    return Path(directory) / "inspections" / run_id


def _store(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise CompositionError("Inspection snapshot is unavailable. Check this step again.")
    return DataSet(path)


def _issue(db, node, scope, source_id, field_name, reason, severity="error", object_id=""):
    db.execute("INSERT INTO issues VALUES(?,?,?,?,?,?,?)", (node.id, scope, source_id, field_name, severity, str(reason), object_id))


def _findings(db, node, current, prior, scope):
    with closing(sqlite3.connect(current.path)) as records:
        previous = 0
        if prior:
            with closing(sqlite3.connect(prior.path)) as before:
                previous = before.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        for source_id, name, severity, reason in records.execute("SELECT source_id,field,severity,reason FROM findings WHERE rowid>?", (previous,)):
            _issue(db, node, scope, source_id, name, reason, severity)


def inspect_step(spec, node_id, directory, *, job=None, progress=None, is_cancelled=None, emit_state=None):
    prefix = spec.execution_prefix(node_id)
    check_cancel(is_cancelled)
    job_id = job.id if job else ""
    cache_root = Path(directory) / "inspections"
    cache_root.mkdir(parents=True, exist_ok=True)
    target_signature = ""
    hashes = {}
    try:
        target_signature, _ = signature(spec, node_id, job, hashes=hashes)
    except (ValueError, OSError):
        # Let the actual stage attribute the failure; upstream checks remain useful.
        hashes.clear()
    for manifest in cache_root.glob("*/results.json"):
        try:
            values = json.loads(manifest.read_text(encoding="utf-8"))
            cached = values.get(node_id)
            if cached and target_signature and cached["signature"] == target_signature and cached["status"] == "Checked":
                root = manifest.parent
                for item in values.values():
                    for name in ("input_store", "output_store"):
                        if item[name]:
                            _store(item[name], root)
                return {"result": cached, "steps": values, "cached": True}
        except (ValueError, OSError, KeyError, sqlite3.Error):
            continue
    run_id = uuid.uuid4().hex
    root = _folder(directory, run_id)
    root.mkdir()
    results = {}
    run = WorkflowRun()
    current = None
    scope = "record" if spec.project_kind == "mail_merge_workflow" else "page"
    template = None
    composed = None
    data_config = None
    page_ids = {}
    context = PrefixSpec(spec, prefix)
    with closing(sqlite3.connect(root / "evidence.sqlite")) as evidence:
        evidence.executescript("""
            CREATE TABLE issues(node_id TEXT,scope TEXT,source_id INTEGER,field TEXT,severity TEXT,reason TEXT,object_id TEXT);
            CREATE TABLE pages(source_id INTEGER PRIMARY KEY,workflow_page INTEGER,source_file TEXT,source_page INTEGER);
            CREATE TABLE envelopes(source_id INTEGER PRIMARY KEY,start INTEGER,end INTEGER);
        """)
        for node in prefix:
            prior = current
            incoming_scope = scope
            result = StepInspectionResult(run_id, node.id, job_id, input_count=prior.count if prior else 0,
                                          input_scope=scope, output_scope=scope, input_store=str(prior.path) if prior else "")
            if emit_state:
                emit_state({"inspection": {"node_id": node.id, "job_id": job_id, "status": "Checking"}})
            def report(done,total,message,n=node):
                if progress:
                    progress(done,total,"Workflow node: "+n.id+" | "+message)
            try:
                check_cancel(is_cancelled)
                result.signature, result.source_hashes = signature(spec, node.id, job, hashes=hashes)
                if node.kind in EXTRA_KINDS:
                    if current is None:
                        raise CompositionError("Check the input before adding data steps.")
                    label = node.kind.replace("_", " ")
                    current = transform(current, root / (node.id + ".sqlite"), node.kind, node.params,
                                        node_id=node.id, is_cancelled=is_cancelled,
                                        progress=lambda done,total,message,callback=report,label=label: callback(done,total,label))
                    if node.kind == "media_assignment" and template:
                        template.media = copy.deepcopy(node.params)
                    if node.kind == "running_sequence" and template and node.params.get("scope") == "page":
                        from composition.template.model import SequenceSpec
                        if node.params["name"] in {seq.name for seq in template.sequences}:
                            raise CompositionError("Sequence field already exists in the template.")
                        template.sequences.append(SequenceSpec(**node.params))
                    _findings(evidence, node, current, prior, scope)
                    if scope == "page":
                        from .extraction import ExtractionStore
                        from .pdf_pipeline import apply_page_data
                        with ExtractionStore(run.database) as store:
                            apply_page_data(store, current, is_cancelled=is_cancelled)
                elif spec.project_kind == "mail_merge_workflow":
                    current, template, data_config = _mail_node(context, node, job, current, template, data_config, root,
                                                               report, is_cancelled)
                else:
                    current, scope, composed = _pdf_node(context, node, current, run, scope, composed, root, evidence,
                                                         page_ids, report, is_cancelled)
                if current:
                    result.output_count, result.fields = current.count, current.fields
                    result.output_store, result.output_scope = str(current.path), scope
                if template and node.kind in ("mail_review", "compose", "reports", "media_assignment", "split_output"):
                    result.template = template.to_dict()
                    compose=spec.node("compose")
                    result.plan = _mail_plan(template, current, node, root, report, is_cancelled,
                                             auto_repair=compose.params.get("auto_repair",True) if compose else True)
                if not template and scope=="envelope" and current and node.kind in ("media_assignment","split_output"):
                    result.plan=_pdf_plan(run,current,is_cancelled)
                if composed:
                    result.overlay = composed.to_dict()
                    from composition.media.planner import PrintPlan, overlay_plan
                    plan = overlay_plan(composed, is_cancelled=is_cancelled)
                    result.plan = asdict(plan.preflight()) if isinstance(plan, PrintPlan) else {"pages": plan.output_pages, "envelopes": plan.envelopes}
                result.input_scope = incoming_scope
                # Recheck the actual bytes after processing, not just timestamps.
                live, _ = signature(spec, node.id, job)
                if live != result.signature:
                    raise CompositionError("Source or template assets changed during checking. Check again.")
            except Exception as exc:
                result.status = "Cancelled" if isinstance(exc, JobCancelled) or is_cancelled and is_cancelled() else "Failed"
                result.error = str(exc)
                ordinal = getattr(exc, "record_ordinal", 0)
                source_id = current.source_id(ordinal) if current and 1 <= ordinal <= current.count else 0
                matched = re.search(r"(?:Source record|Record|Page)\s+(\d+)", str(exc), re.I)
                if not source_id and matched:
                    source_id = int(matched[1])
                obj = re.search(r"object ([A-Za-z0-9_-]+)", str(exc))
                field_match = re.search(r"field ([A-Za-z0-9_, ]+):", str(exc))
                _issue(evidence, node, scope, source_id, field_match[1] if field_match else "", str(exc),
                       "warning" if result.status == "Cancelled" else "error", obj[1] if obj else "")
                if prior:
                    result.output_store, result.output_count, result.fields = str(prior.path), prior.count, prior.fields
            result.issue_count = evidence.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
            evidence.commit()
            if result.status == "Checked" and evidence.execute("SELECT 1 FROM issues WHERE severity='error' LIMIT 1").fetchone():
                result.status = "Needs review"
            results[node.id] = asdict(result)
            _write(root / "results.json", results)
            if emit_state:
                emit_state({"inspection": results[node.id]})
            if result.status in ("Failed", "Cancelled"):
                break
    return {"result": results[next(reversed(results))], "steps": results, "cached": False}


def _mail_node(spec, node, job, current, template, config, root, progress, cancelled):
    from .batch import _config
    if node.kind == "data":
        if job is None:
            raise CompositionError("Select exactly one batch job.")
        template = load_project(job.template_path) if job.template_path else Template()
        if job.data_path:
            # Decode the source once with its configured format; mapping is a later step.
            base=asdict(template.data) if template.data.path else asdict(suggest_import(job.data_path))
            base.update(node.params.get("options",{}))
            base.update(job.data_options)
            base["path"]=job.data_path
            config=DataConfig(**base)
            raw_config = copy.deepcopy(config)
            raw_config.mapping = {}
            imported = import_records(raw_config, root / "import.sqlite", progress=progress, is_cancelled=cancelled)
            imported.metadata["imported_fields"] = list(imported.fields)
            current = snapshot(((sid, values) for _, values, sid in DataSet(imported.path).rows()), imported.fields,
                               root / (node.id + ".sqlite"), metadata=imported.metadata, is_cancelled=cancelled)
        elif template.record_mode == "generated":
            records = open_records(template)
            current = snapshot(records.records(), [], root / (node.id + ".sqlite"), metadata=records.metadata, is_cancelled=cancelled)
        else:
            raise CompositionError("Choose a data source for the selected job.")
    elif node.kind == "mapping" and config:
        config=_config(spec,job,template)
        originals = current.metadata.get("original_fields", current.fields)
        imported_fields = current.metadata.get("imported_fields", current.fields)
        mapping = {old: config.mapping.get(original, normalize_field(original, i + 1))
                   for i, (old, original) in enumerate(zip(imported_fields, originals, strict=True))}
        renamed = {old: mapping.get(old, old) for old in current.fields}
        if len(set(renamed.values())) != len(renamed) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in renamed.values()):
            raise CompositionError("Mapped field names must be unique valid names.")
        current = snapshot(((sid, {renamed[key]: value for key, value in values.items()}) for _, values, sid in current.rows()),
                           list(renamed.values()), root / (node.id + ".sqlite"), metadata=current.metadata, is_cancelled=cancelled)
    elif node.kind == "template":
        if not job.template_path:
            raise CompositionError("Choose a letter template for this job.")
        validate_template(template)
        from composition.engine.fonts import load_font
        for element in template.all_elements():
            check_cancel(cancelled)
            if element.type == "text" or element.show_barcode_text:
                load_font(element.font)
    elif node.kind == "sequences":
        names = {seq.name for seq in template.sequences}
        if set(job.sequence_starts) - names:
            raise CompositionError("Unknown template sequence field.")
        for seq in template.sequences:
            seq.start = job.sequence_starts.get(seq.name, seq.start)
        for seq in template.sequences:
            if seq.scope == "page":
                continue
            current = transform(current, root / (node.id + "-" + seq.name + ".sqlite"), "running_sequence", asdict(seq),
                                node_id=node.id, progress=progress, is_cancelled=cancelled)
        # These values are already materialised for inspection and later preview.
        template.sequences = [seq for seq in template.sequences if seq.scope == "page"]
    elif node.kind in ("mail_review", "compose", "reports"):
        missing = required_fields(template) - set(current.fields) - {seq.name for seq in template.sequences}
        if missing:
            raise CompositionError("Missing mapped fields: " + ", ".join(sorted(missing)))
        if node.kind == "reports":
            _output_folder(node.params.get("directory", ""))
    return current, template, config


def _mail_plan(template, current, node, root, progress, cancelled,*,auto_repair=True):
    from composition.engine.renderer import Renderer
    from composition.media.planner import PrintPlan, build_print_plan

    from .pipeline import split_names
    if not current.count:
        return {"pages": 0, "records": 0, "outputs": []}
    plan = build_print_plan(template, current.count, is_cancelled=cancelled)
    summary = asdict(plan.preflight()) if isinstance(plan, PrintPlan) else {"pages": plan.output_pages}
    summary.update(records=current.count, outputs=split_names(current, "inspection.pdf"))
    if node.kind in ("mail_review", "compose", "reports"):
        folder = root / (node.id + "-fonts")
        folder.mkdir(exist_ok=True)
        with Renderer(template, auto_repair=auto_repair, fallback_directory=folder / "fallback", is_cancelled=cancelled) as renderer:
            renderer.prepare_fonts(((ordinal, values) for ordinal, values, _ in current.rows()), folder,
                                   progress, cancelled, audit_path=folder / "glyph-repairs.csv")
        summary["checked_records"] = current.count
    return summary


def _pdf_plan(run,current,cancelled):
    from composition.media.planner import PrintPlan
    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.planner import EnvelopePlan
    from composition.pdf_source.source import inspect_source

    from .pipeline import split_names
    if not current.count:
        return {"pages":0,"envelopes":0,"outputs":[]}
    groups=[]
    cursor=1
    for _,_,original in current.rows():
        start,end=run.groups[original-1]
        groups.append([cursor,cursor+end-start])
        cursor+=end-start+1
    media=current.metadata.get("media",{})
    base=EnvelopePlan(cursor-1,EnvelopeSettings(groups=groups,pages_per_envelope=1,digits=18))
    summary={"pages":base.output_pages,"envelopes":current.count}
    if media.get("enabled"):
        source=inspect_source(run.source,EnvelopeSettings(groups=run.groups,pages_per_envelope=1),uniform=True,is_cancelled=cancelled)
        geometry=source.geometries[0]
        dimensions=[(geometry["width_pt"]*25.4/72,geometry["height_pt"]*25.4/72)]*base.max_source_pages
        summary.update(asdict(PrintPlan(base,media,dimensions=dimensions,is_cancelled=cancelled).preflight()))
    summary["outputs"]=split_names(current,"inspection.pdf")
    return summary


def _output_folder(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise CompositionError("Choose an output folder. Inspection does not create it.")
    path = Path(raw).resolve()
    if path.exists() and not path.is_dir():
        raise CompositionError("Output path is a file, not a folder.")
    parent = path
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    if not parent.is_dir():
        raise CompositionError("Output parent folder is unavailable.")


def _pdf_node(spec, node, current, run, scope, composed, root, evidence, page_ids, progress, cancelled):
    from composition.pdf_source.source import snapshot_source

    from .extraction import ExtractionSpec, ExtractionStore, scan_pdf
    if node.kind == "input":
        paths = node.params.get("paths", [])
        if not paths:
            raise CompositionError("Add one or more source PDFs.")
        def rows():
            identity = 0
            for path in paths:
                with fitz.open(path) as pdf:
                    if pdf.needs_pass or not pdf.page_count:
                        raise CompositionError("Unlock a nonempty source PDF before checking.")
                    for index in range(pdf.page_count):
                        check_cancel(cancelled)
                        identity += 1
                        page_ids[(str(Path(path).resolve()), index + 1)] = identity
                        evidence.execute("INSERT INTO pages VALUES(?,?,?,?)", (identity, identity, str(Path(path).resolve()), index + 1))
                        yield identity, {"SourceFile": str(path), "SourcePage": str(index + 1)}
        current = snapshot(rows(), ["SourceFile", "SourcePage"], root / (node.id + ".sqlite"), is_cancelled=cancelled)
        if len(paths) == 1:
            run.source = str(root / "source.pdf")
            snapshot_source(paths[0], run.source, file_hash(Path(paths[0])), is_cancelled=cancelled)
    elif node.kind == "merge":
        from core.merge import MergeItem, MergeSpec, merge_pdf_items, strict_pages
        items = []
        for path in spec.node("input").params["paths"]:
            with fitz.open(path) as pdf:
                selected = strict_pages(node.params.get("pages", {}).get(path, "All"), pdf.page_count)
            items.append(MergeItem(path, pages=selected))
        run.source = str(root / "merged-source.pdf")
        merged = merge_pdf_items(MergeSpec(items, run.source), progress=progress, is_cancelled=cancelled)
        evidence.execute("UPDATE pages SET workflow_page=NULL")
        def rows():
            for mapped in merged.page_map:
                identity = page_ids[(str(Path(mapped["source_file"]).resolve()), mapped["source_page"])]
                evidence.execute("UPDATE pages SET workflow_page=? WHERE source_id=?", (mapped["output_page"], identity))
                yield identity, {"SourceFile": mapped["source_file"], "SourcePage": str(mapped["source_page"])}
        current = snapshot(rows(), current.fields, root / (node.id + ".sqlite"), is_cancelled=cancelled)
    elif node.kind == "extract":
        if not run.source:
            raise CompositionError("Connect Merge PDFs before extracting multiple sources.")
        extracted = scan_pdf(run.source, ExtractionSpec.from_dict(node.params), root / "extraction.sqlite", progress=progress, is_cancelled=cancelled)
        run.database = extracted.database
        with ExtractionStore(run.database) as store, store.db:
            for _identity, workflow_page, source_file, source_page in evidence.execute("SELECT * FROM pages WHERE workflow_page IS NOT NULL"):
                store.db.execute("UPDATE provenance SET source_file=?,source_page=? WHERE page=?", (source_file, source_page, workflow_page))
            mapping = {row[1]: row[0] for row in evidence.execute("SELECT source_id,workflow_page FROM pages WHERE workflow_page IS NOT NULL")}
            current = snapshot(((mapping[page], store.values(page)) for page in range(1, extracted.pages + 1)), extracted.fields,
                               root / (node.id + ".sqlite"), metadata={"source": {"path": run.source, "sha256": extracted.source_sha256}}, is_cancelled=cancelled)
            for row in store.db.execute("SELECT page,field,issue FROM cells WHERE issue!=''"):
                _issue(evidence, node, "page", mapping[row[0]], row[1], row[2])
    elif node.kind == "group":
        from .engine import group
        group(spec, run, progress=progress, is_cancelled=cancelled)
        with ExtractionStore(run.database) as store:
            fields = [r[0] for r in store.db.execute("SELECT DISTINCT field FROM envelope_cells ORDER BY field")]
            current = snapshot(((i, {r["field"]: r["value"] for r in store.db.execute("SELECT field,value FROM envelope_cells WHERE envelope=?", (i,))})
                                for i in range(1, len(run.groups) + 1)), fields, root / (node.id + ".sqlite"),
                               metadata={"source": {"path": run.source, "sha256": store.metadata()["sha256"]}}, is_cancelled=cancelled)
            for i, (start, end) in enumerate(run.groups, 1):
                evidence.execute("INSERT INTO envelopes VALUES(?,?,?)", (i, start, end))
            for row in store.db.execute("SELECT envelope,field,issue FROM envelope_cells WHERE issue!=''"):
                _issue(evidence, node, "envelope", row[0], row[1], row[2])
        scope = "envelope"
    elif node.kind in ("overlay", "output"):
        if node.kind == "output":
            _output_folder(node.params.get("directory", ""))
        composed = _overlay_check(spec, run, current, root, progress, cancelled)
    return current, scope, composed


def _overlay_check(spec, run, current, root, progress, cancelled):
    from composition.media.planner import overlay_plan
    from composition.overlay.model import EnvelopeSpec
    from composition.overlay.renderer import OverlayRenderer, page_records, page_values
    from composition.overlay.serializer import load_project as load_overlay
    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.source import inspect_source

    from .engine import detection_audit, external_fields
    from .pdf_pipeline import ProductionValues, production_view
    if not current.count:
        return None
    overlay = spec.node("overlay")
    project = load_overlay(overlay.params["path"]) if overlay and overlay.params.get("path") else None
    if overlay and not project:
        raise CompositionError("Choose an overlay project, or remove the optional Overlay node.")
    _, source_path, groups, _ = production_view(spec, run, root, progress=progress, is_cancelled=cancelled, prepared=current)
    settings = copy.deepcopy(project.settings) if project else EnvelopeSettings(pages_per_envelope=1)
    settings.groups, settings.excluded_pages = groups, []
    source = inspect_source(source_path, settings, uniform=True, progress=progress, is_cancelled=cancelled)
    composed = EnvelopeSpec(source, settings, objects=project.objects if project else [],
                            required_scope=project.required_scope if project else "all_source", external_fields=external_fields(spec),
                            media=copy.deepcopy(current.metadata.get("media", project.media if project else {})))
    # Renderer geometry requires a self-consistent boundary audit. This belongs
    # only to the scratch render context: neither WorkflowRun nor BatchJob is
    # accepted/approved, and this operation has no production/publication path.
    composed.detection_review=detection_audit(composed)
    composed.detection_review["edits"].append({"method":"inspection_render_context_not_operator_approval"})
    composed.validate()
    plan = overlay_plan(composed, is_cancelled=cancelled)
    folder = root / "overlay-fonts"
    folder.mkdir(exist_ok=True)
    with ProductionValues(current.path, run.database, composed) as values, OverlayRenderer(composed, auto_repair=True,
            fallback_directory=folder / "fallback", is_cancelled=cancelled) as renderer:
        renderer.renderer.prepare_fonts(page_records(composed, plan, "inspection", cancelled, values), folder,
                                        progress, cancelled, audit_path=folder / "glyph-repairs.csv")
        for page in plan.pages():
            check_cancel(cancelled)
            renderer.selections(page_values(composed, page, "inspection", values), source.page_geometry(page))
    return composed


def load_result(directory, run_id, node_id, spec, job=None, *, failed_issues=False):
    root = _folder(directory, run_id)
    values = json.loads((root / "results.json").read_text(encoding="utf-8"))
    result = values[node_id]
    if failed_issues and result["status"] in ("Failed", "Cancelled"):
        # Historical error evidence can still be read if a missing source caused
        # the check to fail. It cannot be used as current data or preview evidence.
        return root, result
    live, _ = signature(spec, node_id, job)
    if live != result["signature"]:
        raise CompositionError("Inspection is out of date. Source or upstream settings changed; check this step again.")
    return root, result


def inspection_rows(directory, run_id, node_id, spec, *, job=None, view="output", offset=0, search=""):
    if view not in ("input", "output", "issues") or type(offset) is not int or offset < 0 or not isinstance(search, str) or len(search) > 200:
        raise CompositionError("Invalid inspection page request.")
    root, result = load_result(directory, run_id, node_id, spec, job, failed_issues=view == "issues")
    with closing(sqlite3.connect(root / "evidence.sqlite")) as evidence:
        if view == "issues":
            identities = [node.id for node in spec.execution_prefix(node_id)]
            where = " WHERE node_id IN (" + ",".join("?" for _ in identities) + ")"
            args = list(identities)
            if search:
                where += " AND (CAST(source_id AS TEXT) LIKE ? OR field LIKE ? OR reason LIKE ?)"
                args += ["%" + search + "%"] * 3
            total = evidence.execute("SELECT COUNT(*) FROM issues" + where, args).fetchone()[0]
            rows = [{"node_id": n, "scope": scope, "source_id": sid, "field": name, "severity": severity, "reason": reason,
                     "object_id": obj, "trace": _trace(evidence, scope, sid)}
                    for n, scope, sid, name, severity, reason, obj in evidence.execute(
                        "SELECT * FROM issues" + where + " ORDER BY rowid LIMIT 50 OFFSET ?", [*args, offset])]
        else:
            path = result[view + "_store"]
            if not path:
                return {"rows": [], "total": 0, "offset": 0, "fields": [], "truncated_values": True}
            store = _store(path, root)
            where = " WHERE CAST(source_row AS TEXT) LIKE ? OR value LIKE ?" if search else ""
            args = ["%" + search + "%"] * 2 if search else []
            with closing(sqlite3.connect(store.path)) as records:
                records.execute("CREATE INDEX IF NOT EXISTS inspection_source ON records(source_row)")
                total = records.execute("SELECT COUNT(*) FROM records" + where, args).fetchone()[0]
                rows = []
                before = _store(result["input_store"], root) if view == "output" and result["input_store"] and result["input_scope"] == result["output_scope"] else None
                with closing(sqlite3.connect(before.path)) if before else closing(sqlite3.connect(":memory:")) as previous:
                    if before:
                        previous.execute("CREATE INDEX IF NOT EXISTS inspection_source ON records(source_row)")
                    for ordinal, raw, sid in records.execute("SELECT ordinal,value,source_row FROM records" + where + " ORDER BY ordinal LIMIT 50 OFFSET ?", [*args, offset]):
                        prior = previous.execute("SELECT value FROM records WHERE source_row=? LIMIT 1", (sid,)).fetchone() if before else None
                        rows.append({"ordinal": ordinal, "source_id": sid, "values": _sample(json.loads(raw)),
                                     "before": _sample(json.loads(prior[0])) if prior else {},
                                     "trace": _trace(evidence, result[view + "_scope"], sid)})
            return {"rows": rows, "total": total, "offset": offset, "fields": store.fields, "truncated_values": True}
    return {"rows": rows, "total": total, "offset": offset}


def _trace(db, scope, sid):
    if scope == "page":
        row = db.execute("SELECT source_file,source_page,workflow_page FROM pages WHERE source_id=?", (sid,)).fetchone()
    elif scope == "envelope":
        group = db.execute("SELECT start,end FROM envelopes WHERE source_id=?", (sid,)).fetchone()
        row = db.execute("SELECT source_file,source_page,workflow_page FROM pages WHERE workflow_page=?", (group[0],)).fetchone() if group else None
    else:
        row = None
    return {"source_file": row[0], "source_page": row[1], "workflow_page": row[2]} if row else {}


def inspection_preview(directory, run_id, node_id, spec, target, *, job=None, record=1, page=1):
    from composition.engine.preview_raster import save_preview
    from composition.engine.renderer import render_preview
    root, result = load_result(directory, run_id, node_id, spec, job)
    store = _store(result["output_store"], root)
    if type(record) is not int or not 1 <= record <= store.count or type(page) is not int or page < 1:
        raise CompositionError("Choose a valid record and page to preview.")
    if result["template"]:
        template = Template.from_dict(result["template"])
        if page > len(template.pages):
            raise CompositionError("Template page is out of range.")
        raw = render_preview(template, store.record(record), ordinal=record, page_index=page - 1,
                             auto_repair=spec.node("compose").params.get("auto_repair", True) if spec.node("compose") else True)
    elif result["overlay"]:
        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.renderer import render_preview as overlay_preview

        from .pdf_pipeline import ProductionValues
        composed = EnvelopeSpec.from_dict(result["overlay"])
        with ProductionValues(store.path, str(root / "extraction.sqlite"), composed) as values:
            raw, _ = overlay_preview(composed, record, page, external_values=values)
    else:
        raise CompositionError("Check a template composition or overlay step to preview one record.")
    destination = Path(target).resolve()
    if not destination.is_relative_to(Path(directory).resolve()):
        raise CompositionError("Preview output must remain in the workspace scratch directory.")
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        save_preview(pdf[0], destination, 2)
    return {"image": str(destination), "record": record, "page": page}
