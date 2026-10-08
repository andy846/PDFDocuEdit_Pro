"""Disk-backed review using the existing planners, rules, fonts and renderers.

Only writes owned scratch files. Never invokes a generator or approves a workflow.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import tempfile
import uuid
from contextlib import ExitStack, closing
from dataclasses import asdict
from pathlib import Path

import fitz

from composition.data.sequences import open_records, sequence_record
from composition.engine.barcode_profiles import INSERTER_I25, profile_values
from composition.engine.generic_layout import CONTEXT_KEY
from composition.engine.renderer import Renderer
from composition.media.planner import build_print_plan, overlay_plan
from composition.overlay.model import EnvelopeSpec
from composition.overlay.renderer import OverlayRenderer, page_records, page_values
from composition.pdf_source.source import _hash
from composition.production.generator import JobCancelled, check_cancel
from composition.production.model import ProductionJob, resolve_output_name
from composition.template.model import MM_TO_PT, CompositionError, Template, required_fields

from .model import ReviewContext, ReviewIssue, ReviewSnapshot

PAGE_SIZE = 50


def _root(directory):
    root = Path(directory).resolve() / "production-review"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _folder(directory, identity):
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise CompositionError("Invalid production review identity.")
    return _root(directory) / identity


def _context(raw):
    context = ReviewContext(**copy.deepcopy(raw))
    if context.kind not in ("template", "overlay"):
        raise CompositionError("Unknown production review kind.")
    return context


def _resources(context):
    job = context.job
    project = job["template" if context.kind == "template" else "project"]
    paths = [context.external_data, context.external_database, job.get("record_store", "")]
    if context.kind == "template":
        value = Template.from_dict(project)
        paths += [p.background for p in value.pages]
        elements = list(value.all_elements())
        if value.data:
            paths.append(value.data.path)
    else:
        value = EnvelopeSpec.from_dict(project)
        paths.append(value.source.path)
        elements = [o.element for o in value.objects]
    for e in elements:
        paths += [e.image, e.font.file, *(f.file for f in e.glyph_repairs.values())]
        if e.rules.alternative:
            paths.append(e.rules.alternative.image)
    paths += context.binding.get("files", [])
    return sorted(set(str(Path(p).resolve()) for p in paths if p))


def fingerprint(raw, *, cancelled=None, resource_hashes=None):
    context = _context(raw)
    hashes, stats = {}, {}
    for path in _resources(context):
        check_cancel(cancelled)
        file = Path(path)
        stat = file.stat()
        hashes[path] = _hash(file, cancelled)
        stats[path] = [stat.st_size, stat.st_mtime_ns]
        after = file.stat()
        if stats[path] != [after.st_size, after.st_mtime_ns]:
            raise CompositionError("Review source changed during checking.")
    digest = hashlib.sha256(json.dumps([asdict(context), hashes], sort_keys=True,
                                     ensure_ascii=True).encode()).hexdigest()
    if resource_hashes is not None:
        resource_hashes.update(hashes)
    return digest, stats


def load_snapshot(directory, identity, *, full=False, is_cancelled=None):
    folder = _folder(directory, identity)
    packet = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    for path, expected in packet["stats"].items():
        stat = Path(path).stat()
        if [stat.st_size, stat.st_mtime_ns] != expected:
            raise CompositionError("Review is stale. Source or settings changed; check again.")
    if full and fingerprint(packet["context"], cancelled=is_cancelled)[0] != packet["fingerprint"]:
        raise CompositionError("Review is stale. Source or settings changed; check again.")
    return folder, packet


def validate_snapshot(directory, identity, raw, *, warnings_acknowledged=False, is_cancelled=None):
    _, packet = load_snapshot(directory, identity)
    if not packet["complete"] or packet["status"] != "checked":
        raise CompositionError("Complete the full production check before confirming.")
    load_snapshot(directory, identity, full=True, is_cancelled=is_cancelled)
    if fingerprint(raw, cancelled=is_cancelled)[0] != packet["fingerprint"]:
        raise CompositionError("Settings changed. Review the current production job again.")
    if any(i["severity"] == "error" for i in packet["issues"]):
        raise CompositionError("Fix production review errors before confirming.")
    if packet["issues"] and not warnings_acknowledged:
        raise CompositionError("Acknowledge the production warnings before confirming.")
    return packet


def _external(stack, context, spec):
    if context.external_data:
        from workflow.pdf_pipeline import ProductionValues
        return stack.enter_context(ProductionValues(context.external_data, context.external_database, spec))
    if context.external_database:
        from workflow.extraction import ExtractionStore
        store = stack.enter_context(ExtractionStore(context.external_database))
        return store.production_values
    return None


def _issue(exc, envelope=0, page=0):
    reason = str(exc)
    field = re.search(r"field ([^:\n]+):", reason, re.I)
    def number(pattern):
        match = re.search(pattern, reason, re.I)
        return int(match[1]) if match else 0
    obj = re.search(r"object ([A-Za-z0-9_-]+)", reason, re.I)
    return asdict(ReviewIssue("error", reason,
        getattr(exc, "record_ordinal", 0) or number(r"(?:Record|Envelope) (\d+)") or envelope,
        number(r"output page (\d+)") or page, number(r"template page (\d+)"),
        obj[1] if obj else "", getattr(exc, "field", getattr(exc, "source_field", field[1] if field else "")),
        "object" if obj else "media" if "media" in reason.lower() else "settings"))


def _barcodes(elements, plans, values):
    results = []
    for element in elements:
        if element.type not in ("i25", "code128", "qr"):
            continue
        selected = plans[element.id].resolve(values)
        if not selected.visible:
            continue
        from composition.engine.barcodes import validate_size
        validate_size(element, selected.value)
        profile = plans[element.id].profile
        results.append({"object_id": element.id, "symbology": element.type,
            "payload": selected.value, "profile": profile.name if profile else "Generic text",
            "parts": profile.inserter_parts(profile_values(values)) if profile and profile.preset == INSERTER_I25 else {},
            "segments": [asdict(s) for s in profile.evaluate(values).segments]
                        if profile and profile.layout_mode == "fixed" else [],
            "x_mm": element.x_mm, "y_mm": element.y_mm, "width_mm": element.width_mm,
            "height_mm": element.height_mm, "rotation": element.rotation_deg})
    return results


def _summary(context, plan, media, output_name, source):
    output = Path(context.job["output_dir"]).resolve() / context.job["job_id"] / output_name
    if output.parent.exists() or output.parent.with_name(output.parent.name + "-failed").exists():
        raise CompositionError("This production job already has output. Choose a new output folder / job.")
    data = context.binding.get("data_summary", {})
    return {"job_id": context.job["job_id"], "label": context.label,
        "input_records": data.get("input", plan.envelopes), "excluded_records": data.get("excluded", 0),
        "records": plan.envelopes, "pages": plan.output_pages, "sheets": plan.sheets,
        "inserted_blanks": plan.inserted_blanks,
        "printing": "Duplex" if plan.settings.duplex else "Simplex", "output_name": output_name,
        "output_dir": context.job["output_dir"], "stock_sheets": getattr(plan, "stock_sheets", {}),
        "backend": media.get("printer_profile", {}).get("backend", "pdf") if media.get("enabled") else "pdf",
        "printer_profile": media.get("printer_profile", {}).get("profile_name", "Not configured"),
        "outputs": context.outputs, "expected_barcodes": 0, "source": source or "Generated records"}


def create_review(directory, raw, *, progress=None, is_cancelled=None):
    context = _context(raw)
    identity = uuid.uuid4().hex
    folder = _folder(directory, identity)
    folder.mkdir()
    initial_hashes = {}
    digest, stats = fingerprint(raw, cancelled=is_cancelled, resource_hashes=initial_hashes)
    issues, summary = [], {}
    complete, status = False, "checking"
    current = None
    with closing(sqlite3.connect(folder / "rows.sqlite")) as db, ExitStack() as stack:
        db.executescript("CREATE TABLE envelopes(ordinal INTEGER PRIMARY KEY,value TEXT,search TEXT);"
                        "CREATE TABLE pages(output_page INTEGER PRIMARY KEY,envelope INTEGER,value TEXT);"
                        "CREATE INDEX envelope_pages ON pages(envelope,output_page);")
        try:
            check_cancel(is_cancelled)
            if context.kind == "template":
                job = ProductionJob(**context.job)
                template = Template.from_dict(job.template)
                template._barcode_job_id = job.job_id
                records = open_records(template, job.record_store)
                if not records.count:
                    raise CompositionError("No retained records. There is no production PDF to review.")
                missing = required_fields(template) - set(records.fields)
                if missing:
                    raise CompositionError("Missing mapped fields: " + ", ".join(sorted(missing)))
                plan = build_print_plan(template, records.count, is_cancelled=is_cancelled)
                job.variable_context["namespaces"].setdefault("job", {}).update(id=job.job_id, records=records.count)
                output_name = job.resolved_output_name()
                context.job = asdict(job)
                summary = _summary(context, plan, template.media, output_name, template.data.path if template.data else "")
                renderer = stack.enter_context(Renderer(template, auto_repair=job.auto_repair,
                    fallback_directory=folder / "fallback", is_cancelled=is_cancelled))
                from composition.engine.barcode_profiles import has_inserter
                from composition.engine.generic_production import preflight as generic_preflight
                from composition.engine.inserter_production import preflight
                if has_inserter(template):
                    preflight(template, records.records(), plan, is_cancelled, progress)
                generic_preflight(template, records.records(), plan, is_cancelled, progress)
                with tempfile.TemporaryDirectory(prefix="review-font-") as fonts:
                    renderer.prepare_fonts(records.records(), fonts, progress, is_cancelled,
                                           audit_path=folder / "glyph-repairs.csv")
                profile_objects = [e.barcode_profile for e in template.all_elements() if e.barcode_profile]
            else:
                spec = EnvelopeSpec.from_dict(context.job["project"])
                if spec.needs_source_review or spec.needs_detection_review:
                    raise CompositionError("Accept source and mailpiece boundaries before production review.")
                from composition.pdf_source.source import inspect_source
                checked_source = inspect_source(spec.source.path, spec.settings,
                    uniform=spec.source.geometry_mode == "uniform", is_cancelled=is_cancelled)
                if (checked_source.sha256 != spec.source.sha256 or checked_source.pages != spec.source.pages
                        or checked_source.geometries != spec.source.geometries):
                    raise CompositionError("Source PDF changed. Reinspect and accept boundaries before reviewing production.")
                plan = overlay_plan(spec, is_cancelled=is_cancelled)
                output_name = resolve_output_name(context.job.get("output_name", "production.pdf"), context.job.get("variable_context", {}))
                summary = _summary(context, plan, spec.media, output_name, spec.source.path)
                renderer = stack.enter_context(OverlayRenderer(spec, auto_repair=context.job.get("auto_repair", True),
                    fallback_directory=folder / "fallback", is_cancelled=is_cancelled))
                external = _external(stack, context, spec)
                with tempfile.TemporaryDirectory(prefix="review-font-") as fonts:
                    renderer.renderer.prepare_fonts(page_records(spec, plan, context.job["job_id"], is_cancelled, external),
                        fonts, progress, is_cancelled, audit_path=folder / "glyph-repairs.csv")
                profile_objects = [o.profile.to_dict() for o in spec.objects if o.profile]
            if context.kind == "template" and context.job.get("record_store"):
                source_db = stack.enter_context(closing(sqlite3.connect(context.job["record_store"])))
            elif context.kind == "overlay" and context.external_data:
                source_db = stack.enter_context(closing(sqlite3.connect(context.external_data)))
            else:
                source_db = None
            provenance_db = (stack.enter_context(closing(sqlite3.connect(context.external_database)))
                             if context.external_database else None)
            for envelope in range(1, plan.envelopes + 1):
                check_cancel(is_cancelled)
                record = (records.record(envelope) if context.kind == "template" else
                          page_values(spec, plan.page(envelope, 1), context.job["job_id"], external))
                record = {k: v for k, v in record.items() if k != CONTEXT_KEY}
                first, last, output = plan.group(envelope)
                cfg = plan.settings_for(envelope)
                original = source_db.execute("SELECT source_row FROM records WHERE ordinal=?", (envelope,)).fetchone() if source_db else None
                row = {"envelope": envelope, "source_record": original[0] if original else envelope, "source_start": first,
                    "source_end": last, "output_start": output, "output_end": output + cfg.output_pages_per_envelope - 1,
                    "sheets": cfg.sheets_per_envelope, "pages": cfg.output_pages_per_envelope,
                    "values": record, "status": "Checked"}
                db.execute("INSERT INTO envelopes VALUES(?,?,?)", (envelope, json.dumps(row, ensure_ascii=False),
                    json.dumps(record, ensure_ascii=False)))
                for index in range(1, cfg.output_pages_per_envelope + 1):
                    check_cancel(is_cancelled)
                    current = plan.page(envelope, index)
                    fields = current.fields(context.job["job_id"])
                    if context.kind == "template":
                        values = sequence_record(template, record, envelope, current.role)
                        marks = (_barcodes(template.pages[current.role].elements, renderer.plans, values)
                                 if current.source_page is not None else [])
                    else:
                        values = page_values(spec, current, context.job["job_id"], external)
                        selected = renderer.selections(values, spec.source.page_geometry(current))
                        marks = _barcodes([e for e, _, _ in selected], renderer.renderer.plans, values)
                    page_row = {"output_page": current.output_page, "envelope": envelope,
                        "sheet": fields["SheetNo"], "job_sheet": fields["JobSheetNo"], "side": fields["Side"],
                        "source_page": current.source_page, "template_page": current.role + 1 if context.kind == "template" and current.source_page else None,
                        "stock": getattr(current, "stock", "") or "Not assigned", "blank": current.source_page is None,
                        "reason": getattr(current, "reason", "Envelope-end blank back" if current.source_page is None else "Source content"),
                        "barcodes": marks, "values": {k: v for k, v in values.items() if k != CONTEXT_KEY}}
                    if current.source_page is not None:
                        if context.kind == "overlay":
                            page_row.update(source_file=spec.source.path, original_page=current.source_page)
                            if source_db and provenance_db:
                                original_page = source_db.execute("SELECT original_page FROM page_map WHERE page=?", (current.source_page,)).fetchone()
                                trace = provenance_db.execute("SELECT source_file,source_page FROM provenance WHERE page=?", (original_page[0],)).fetchone() if original_page else None
                                if trace:
                                    page_row.update(source_file=trace[0], original_page=trace[1])
                        elif template.pages[current.role].background:
                            page_row.update(source_file=template.pages[current.role].background, original_page=1)
                    summary["expected_barcodes"] += len(marks)
                    db.execute("INSERT INTO pages VALUES(?,?,?)", (current.output_page, envelope, json.dumps(page_row, ensure_ascii=False)))
                if envelope % 100 == 0:
                    db.commit()
                    if progress:
                        progress(envelope, plan.envelopes, "Checking production page and barcode plan")
            engine = renderer if context.kind == "template" else renderer.renderer
            summary["font_substitutions"] = engine.repair_summary.get("occurrences", 0)
            summary["conditional_objects"] = engine.rule_summary.get("configured_objects", 0)
            summary["hidden_objects"] = engine.rule_summary.get("hidden_occurrences", 0)
            if engine.repair_summary.get("occurrences"):
                summary["font_report"] = str(folder / "glyph-repairs.csv")
                issues.append(asdict(ReviewIssue("warning", f"Automatic font substitutions: {engine.repair_summary['occurrences']} occurrence(s). Review glyph-repairs.csv.", action="font")))
            media = template.media if context.kind == "template" else spec.media
            if media.get("enabled"):
                summary["printer_profile"] = media.get("printer_profile", {}).get("profile_name", "Unnamed profile")
                issues.append(asdict(ReviewIssue("warning", "Printer profile requires physical stock/tray/duplex verification.", action="media")))
            if any(p.get("validation", "pending") == "pending" for p in profile_objects):
                issues.append(asdict(ReviewIssue("warning", "Barcode machine acceptance is pending. Preview is not final-PDF decoding or inserter certification.", action="barcode")))
            # Normalize the resolved job context before binding the approval.
            raw = asdict(context)
            final_hashes = {}
            digest, final_stats = fingerprint(raw, cancelled=is_cancelled, resource_hashes=final_hashes)
            if final_stats != stats or initial_hashes != final_hashes:
                raise CompositionError("Source changed during review. Check again.")
            complete, status = True, "checked"
        except JobCancelled:
            status = "cancelled"
        except (ValueError, OSError, KeyError, TypeError) as exc:
            status = "blocked"
            issues.append(_issue(exc, current.envelope if current else 0, current.output_page if current else 0))
        finally:
            db.commit()
    result = asdict(ReviewSnapshot(identity, digest, status, summary, issues, complete))
    packet = {**result, "context": asdict(context), "stats": stats}
    (folder / "snapshot.json").write_text(json.dumps(packet, ensure_ascii=True), encoding="utf-8")
    return {**result, "context": asdict(context)}


def review_rows(directory, identity, *, offset=0, search="", envelope=0, output_page=0):
    folder, packet = load_snapshot(directory, identity)
    offset = max(0, int(offset))
    with closing(sqlite3.connect(folder / "rows.sqlite")) as db:
        where, params = (" WHERE search LIKE ?", ["%" + str(search).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"]) if search else ("", [])
        if search:
            where += " ESCAPE '\\'"
        if output_page:
            match = db.execute("SELECT envelope FROM pages WHERE output_page=?", (int(output_page),)).fetchone()
            envelope = match[0] if match else 0
            before = db.execute("SELECT COUNT(*) FROM pages WHERE envelope=? AND output_page<?", (envelope, int(output_page))).fetchone()[0]
            offset = before // PAGE_SIZE * PAGE_SIZE
        total = db.execute("SELECT COUNT(*) FROM envelopes" + where, params).fetchone()[0]
        rows = [json.loads(r[0]) for r in db.execute("SELECT value FROM envelopes" + where + " ORDER BY ordinal LIMIT ? OFFSET ?", [*params, PAGE_SIZE, offset])]
        pages = [json.loads(r[0]) for r in db.execute("SELECT value FROM pages WHERE envelope=? ORDER BY output_page LIMIT ? OFFSET ?", (int(envelope), PAGE_SIZE, offset if envelope else 0))] if envelope else []
    return {"rows": rows, "pages": pages, "total": total, "offset": offset, "envelope": envelope, "snapshot_id": identity,
            "status": packet["status"], "page_offset": offset if output_page else 0}


def preview_sheet(directory, identity, output_page, *, scale=2):
    folder, packet = load_snapshot(directory, identity)
    context = _context(packet["context"])
    with closing(sqlite3.connect(folder / "rows.sqlite")) as db:
        selected = db.execute("SELECT value FROM pages WHERE output_page=?", (int(output_page),)).fetchone()
        if not selected:
            raise CompositionError("Selected production page is not checked.")
        row = json.loads(selected[0])
        pages = [json.loads(r[0]) for r in db.execute("SELECT value FROM pages WHERE envelope=? AND json_extract(value,'$.sheet')=? ORDER BY output_page LIMIT 2", (row["envelope"], row["sheet"]))]
    from composition.engine.preview_raster import save_preview
    images = []
    with ExitStack() as stack:
        if context.kind == "template":
            template = Template.from_dict(context.job["template"])
            template._barcode_job_id = context.job["job_id"]
            records = open_records(template, context.job.get("record_store", ""))
        else:
            spec = EnvelopeSpec.from_dict(context.job["project"])
            plan = overlay_plan(spec)
            source = stack.enter_context(fitz.open(spec.source.path))
            renderer = stack.enter_context(OverlayRenderer(spec, auto_repair=context.job.get("auto_repair", True)))
            external = _external(stack, context, spec)
        for face in pages:
            with fitz.open() as pdf:
                if context.kind == "template":
                    page_plan = build_print_plan(template, records.count).output_page(face["output_page"])
                    if face["blank"]:
                        spec_page = template.pages[page_plan.role]
                        pdf.new_page(width=spec_page.width_mm * MM_TO_PT, height=spec_page.height_mm * MM_TO_PT)
                    else:
                        with Renderer(template, page_index=page_plan.role, auto_repair=context.job.get("auto_repair", False)) as render:
                            render.render(pdf, records.record(face["envelope"]), face["envelope"], page_index=page_plan.role)
                            render.finalize(pdf)
                else:
                    page_plan = plan.output_page(face["output_page"])
                    values = page_values(spec, page_plan, context.job["job_id"], external)
                    with fitz.open() as layers:
                        renderer.paint(pdf, layers, source, page_plan, values, spec.source.page_geometry(page_plan))
                image = folder / (uuid.uuid4().hex + ".png")
                save_preview(pdf[0], image, scale)
                images.append({"image": str(image), "page": face})
    return {"images": images, "envelope": row["envelope"], "sheet": row["sheet"]}
