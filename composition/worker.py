"""Headless worker protocol; no Qt imports or editor state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from composition.data.sequences import open_records
from composition.data.source import import_records, suggest_import
from composition.engine.preview_raster import save_preview
from composition.engine.renderer import import_background, render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import DataConfig, FontSpec, Template, canonical_codepoint, required_fields

EVENTS_FILE = None


def emit(event, **values):
    line = json.dumps({"event": event, **values}, ensure_ascii=True) + "\n"
    if EVENTS_FILE is not None:
        with EVENTS_FILE.open("a", encoding="utf-8") as stream:
            stream.write(line)
    elif sys.stdout is not None:
        print(line, end="", flush=True)


def dispatch(request: dict) -> dict:
    task = request["task"]
    def cancelled():
        return bool(request.get("cancel_file") and Path(request["cancel_file"]).exists())

    def progress(done, total, message):
        emit("progress", done=done, total=total, message=message)

    if task == "workflow":
        from workflow.worker import dispatch as workflow_dispatch
        return workflow_dispatch(request, progress, cancelled,emit_state=lambda state:emit("state",state=state))
    if task == "media_preview":
        from dataclasses import asdict

        from composition.media.planner import PrintPlan, build_print_plan, overlay_plan
        from composition.media.ticket import plan_rows
        from composition.overlay.model import EnvelopeSpec
        context=request["context"]
        if context["kind"]=="template":
            template=Template.from_dict(context["project"])
            template.media=request["media"]
            plan=build_print_plan(template,context.get("records",1),is_cancelled=cancelled)
        elif context["kind"]=="workflow_pdf":
            from composition.overlay.model import EnvelopeSpec
            from composition.pdf_source.model import EnvelopeSettings
            from composition.pdf_source.source import inspect_source
            groups=context["groups"]
            cfg=EnvelopeSettings(pages_per_envelope=1,groups=groups,digits=18)
            source=inspect_source(context["source"],cfg,uniform=True,is_cancelled=cancelled)
            if context.get("data_set"):
                from workflow.transforms import DataSet
                selected=DataSet(context["data_set"])
                projected=[]
                cursor=1
                for _,_,original in selected.rows():
                    first,last=groups[original-1]
                    projected.append([cursor,cursor+last-first])
                    cursor+=last-first+1
                source.pages=cursor-1
                cfg.groups=projected
            spec=EnvelopeSpec(source,cfg,media=request["media"])
            plan=overlay_plan(spec,is_cancelled=cancelled)
        else:
            spec=EnvelopeSpec.from_dict(context["project"])
            spec.media=request["media"]
            plan=overlay_plan(spec,is_cancelled=cancelled)
        if not isinstance(plan,PrintPlan):
            return {"disabled":True,"pages":plan.output_pages,"rows":[]}
        start=max(1,int(request.get("start",1)))
        stop=min(plan.output_pages,start+199)
        # Read a bounded window, without walking preceding pages.
        class Window:
            def pages(self):
                return (plan.output_page(i) for i in range(start,stop+1))
        return {**asdict(plan.preflight()),"start":start,"rows":list(plan_rows(Window()))}
    if task == "mailpiece_preview":
        import fitz

        from composition.pdf_source.source import _stat, geometry
        from composition.template.model import CompositionError
        source = Path(request["source"])
        expected = (request["size"], request["mtime_ns"])
        if _stat(source) != expected:
            raise CompositionError("Source changed. Reinspect and scan again.")
        check_page = request["page"]
        with fitz.open(source) as pdf:
            if pdf.needs_pass or type(check_page) is not int or not 1 <= check_page <= pdf.page_count:
                raise CompositionError("Source page is unavailable.")
            page = pdf[check_page-1]
            image = Path(request["target"])
            scale = min(max(float(request.get("scale", 1)), 1), 4096/max(page.rect.width, page.rect.height))
            page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(image)
            geom = geometry(page)
        if _stat(source) != expected:
            image.unlink(missing_ok=True)
            raise CompositionError("Source changed during preview.")
        return {"image": str(image), "geometry": geom}
    if task in ("mailpiece_analyze", "mailpiece_smart_scan", "mailpiece_teach"):
        from composition.pdf_source.detection import DetectionConfig
        from composition.pdf_source.smart_detection import analyze_pdf, scan_pdf, teach_pdf
        options = dict(expected_sha256=request.get("expected_sha256"), progress=progress, is_cancelled=cancelled)
        if task == "mailpiece_analyze":
            return analyze_pdf(request["source"], request["cache"], **options)
        if task == "mailpiece_teach":
            return teach_pdf(request["source"], request["cache"], request["first_page"], request["continuation_page"],
                             request["marker_region"], request.get("id_regions", []), request.get("marker_terms"), **options)
        return scan_pdf(request["source"], DetectionConfig(**request["config"]), cache_path=request["cache"], **options)
    if task == "mailpiece_profile_save":
        from composition.pdf_source.detection import DetectionConfig
        from composition.pdf_source.profiles import save_profile
        return {"path": save_profile(request["path"], DetectionConfig(**request["config"]))}
    if task == "mailpiece_profile_load":
        from composition.pdf_source.profiles import load_profile
        return {"config": load_profile(request["path"])}
    if task == "mailpiece_review_source":
        from dataclasses import asdict

        from composition.pdf_source.model import EnvelopeSettings
        from composition.pdf_source.source import inspect_source
        from composition.template.model import CompositionError
        source = inspect_source(request["source"], EnvelopeSettings(pages_per_envelope=1),
                                uniform=True, progress=progress, is_cancelled=cancelled)
        if source.sha256 != request["expected_sha256"]:
            raise CompositionError("Source PDF changed. Reinspect the source, then scan and review before accepting boundaries.")
        return {"source": asdict(source)}
    if task == "mailpiece_scan":
        from composition.pdf_source.detection import DetectionConfig, scan_pdf
        return scan_pdf(request["source"], DetectionConfig(**request["config"]),
                        expected_sha256=request.get("expected_sha256"), progress=progress, is_cancelled=cancelled)
    if task == "overlay_inspect":
        from dataclasses import asdict

        from composition.pdf_source.model import EnvelopeSettings
        from composition.pdf_source.source import inspect_source
        return asdict(inspect_source(request["source"], EnvelopeSettings(**request["settings"]),
                                     progress=progress, is_cancelled=cancelled, uniform=request.get("uniform", False)))
    if task == "overlay_preview":
        import fitz

        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.renderer import render_preview as overlay_preview
        spec=EnvelopeSpec.from_dict(request["project"])
        database=request.get("external_database", "")
        if database and request.get("external_data"):
            from composition.template.serializer import file_hash
            from workflow.pdf_pipeline import ProductionValues
            if file_hash(Path(request["external_data"]))!=request.get("external_data_sha256"):
                raise ValueError("Checked workflow preview data changed. Refresh the overlay from Workflow.")
            with ProductionValues(request["external_data"],database,spec) as values:
                raw,fields=overlay_preview(spec,request["envelope"],request["print_page"],
                    auto_repair=request.get("auto_repair",True),external_values=values)
        elif database:
            from workflow.extraction import ExtractionStore
            with ExtractionStore(database) as store:
                if store.metadata()["sha256"]!=spec.source.sha256:
                    raise ValueError("Workflow source changed; reopen the overlay from Workflow.")
                groups=[list(r) for r in store.db.execute("SELECT start,end FROM groups ORDER BY envelope")]
                if groups!=spec.settings.groups:
                    raise ValueError("Workflow envelope boundaries changed; reopen the overlay from Workflow to synchronise the preview.")
                raw, fields = overlay_preview(spec,request["envelope"],request["print_page"],
                    auto_repair=request.get("auto_repair", True),external_values=store.production_values)
        else:
            raw, fields = overlay_preview(spec,request["envelope"],request["print_page"],
                                          auto_repair=request.get("auto_repair", True))
        pdf = Path(request["target"])
        pdf.write_bytes(raw)
        image = pdf.with_suffix(".png")
        with fitz.open(stream=raw, filetype="pdf") as document:
            raster = save_preview(document[0], image, request.get("raster_scale", 2))
        return {"pdf": str(pdf), "image": str(image), "fields": fields, **raster}
    if task == "overlay_generate":
        from dataclasses import asdict

        from composition.overlay.generator import generate as overlay_generate
        from composition.overlay.model import OverlayJob
        return asdict(overlay_generate(OverlayJob(**request["job"]), progress=progress, is_cancelled=cancelled))
    if task == "overlay_save":
        from composition.overlay.model import EnvelopeSpec
        from composition.overlay.serializer import load_project, save_project
        target = save_project(EnvelopeSpec.from_dict(request["project"]), request["target"])
        return {"project": str(target), "spec": load_project(target).to_dict()}
    if task == "fonts":
        from composition.engine.system_fonts import font_catalogue
        return font_catalogue(progress=progress, is_cancelled=cancelled)
    def checked_repair(result):
        if request.get("codepoint"):
            from composition.engine.fonts import load_font
            key = canonical_codepoint(request["codepoint"])
            spec = FontSpec(**result["spec"]) if "spec" in result else FontSpec(
                family=result["family"], file=result["file"])
            font, _ = load_font(spec)
            if not font.has_glyph(int(key[2:], 16), fallback=False):
                raise ValueError(f"Selected repair face cannot render {key}. Primary font unchanged.")
        return result
    if task == "glyph_repair_font":
        from dataclasses import asdict
        spec = FontSpec(**request["spec"])
        return checked_repair({"spec": asdict(spec), "family": spec.family, "file": spec.file,
                               "style": "Saved exact face", "note": ""})
    if task == "font_export":
        from composition.engine.system_fonts import export_face
        result = checked_repair(export_face(request["face"], request["directory"]))
        if request.get("validate_pdf"):
            from composition.engine.fonts import load_font
            load_font(FontSpec(family=result["family"], file=result["file"]))
        return result
    if task == "font_info":
        from composition.engine.system_fonts import inspect_font_file
        return {"faces": inspect_font_file(request["file"])}
    if task == "suggest":
        from dataclasses import asdict

        from composition.data.excel_source import is_excel, workbook_info
        result = {"config": asdict(suggest_import(request["source"]))}
        if is_excel(request["source"]):
            result.update(workbook_info(request["source"]))
        return result
    if task == "sample":
        from composition.data.source import sample_records
        return sample_records(DataConfig(**request["config"]))
    if task == "import":
        store = import_records(DataConfig(**request["config"]), request["target"],
                               progress=progress, is_cancelled=cancelled)
        return {"store": str(store.path), "metadata": store.metadata,
                 "sample": [{key: value[:500] for key, value in store.record(i).items()}
                           for i in range(1, min(5, store.count)+1)]}
    if task == "background":
        size = import_background(request["source"], request.get("page", 0), request["target"])
        return {"background": request["target"], "width_mm": size[0], "height_mm": size[1]}
    if task == "template_backgrounds":
        import fitz

        from composition.production.generator import check_cancel
        from composition.template.model import MAX_TEMPLATE_PAGES, CompositionError, PageSpec
        from composition.template.serializer import file_hash
        source=Path(request["source"])
        digest=file_hash(source)
        target=Path(request["target"])
        target.mkdir(parents=True,exist_ok=True)
        pages=[]
        with fitz.open(source) as pdf:
            if pdf.needs_pass or pdf.get_sigflags()>0 or not 1<=pdf.page_count<=MAX_TEMPLATE_PAGES:
                raise CompositionError("Use an unlocked, unsigned PDF within the template page limit.")
            for index in range(pdf.page_count):
                check_cancel(cancelled)
                background=target/f"page-{index+1}.pdf"
                width,height=import_background(source,index,background)
                pages.append(PageSpec(name=f"Page {index+1}",width_mm=width,height_mm=height,background=str(background)))
        if file_hash(source)!=digest:
            raise CompositionError("Source changed during template import; import it again.")
        return {"template":Template(name=source.stem,pages=pages).to_dict()}
    if task == "preview":
        import fitz
        template = Template.from_dict(request["template"])
        index = request.get("record", 1)
        design = request.get("design", not bool(request.get("store")))
        if not design:
            record = open_records(template, request.get("store", "")).record(index)
        else:
            record = {name: "{{" + name + "}}" for name in required_fields(template)}
        repairs, rules = [], []
        page_index = request.get("page", 0)
        raw = render_preview(template, record, index, repair_details=repairs, page_index=page_index,
                             design=design, rule_details=rules, auto_repair=request.get("auto_repair", False))
        pdf = Path(request["target"])
        pdf.write_bytes(raw)
        image = pdf.with_suffix(".png")
        with fitz.open(stream=raw, filetype="pdf") as document:
            raster = save_preview(document[0], image, request.get("raster_scale", 2))
        return {"pdf": str(pdf), "image": str(image), "record": index, "page": page_index, "glyph_repairs": repairs, "rules": rules, **raster}
    if task == "save":
        from composition.template.serializer import load_project, save_project
        target = save_project(Template.from_dict(request["template"]), request["target"])
        return {"project": str(target), "template": load_project(target).to_dict()}
    if task == "generate":
        result = generate(ProductionJob(**request["job"]), progress=progress, is_cancelled=cancelled)
        return result.to_dict()
    raise ValueError("Unknown composition worker task.")


def main(argv=None):
    global EVENTS_FILE
    parser = argparse.ArgumentParser(description="PDFDocuEdit headless composition worker")
    parser.add_argument("request")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request_path = Path(args.request)
        if request_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Worker request is too large.")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("events_file"):
            EVENTS_FILE = Path(request["events_file"])
        result = dispatch(request)
        emit("result", result=result)
        return 0
    except Exception as exc:
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
