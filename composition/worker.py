"""Headless worker protocol; no Qt imports or editor state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from composition.data.sequences import open_records
from composition.data.source import import_records, suggest_import
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
        return checked_repair(export_face(request["face"], request["directory"]))
    if task == "font_info":
        from composition.engine.system_fonts import inspect_font_file
        return {"faces": inspect_font_file(request["file"])}
    if task == "suggest":
        from dataclasses import asdict
        return {"config": asdict(suggest_import(request["source"]))}
    if task == "sample":
        import csv

        from composition.data.source import MAX_FIELDS, MAX_RECORD_CHARS, normalize_field
        csv.field_size_limit(MAX_RECORD_CHARS)
        config = DataConfig(**request["config"])
        with Path(config.path).open("r", encoding=config.encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=config.delimiter, strict=True)
            for _ in range(config.header_row-1):
                next(reader, None)
            first = next(reader)
            if len(first) > MAX_FIELDS:
                raise ValueError("The source has too many fields.")
            originals = first if config.header else [f"Field_{i+1}" for i in range(len(first))]
            sample = [] if config.header else [first]
            for _ in range(5):
                values = next(reader, None)
                if values is None:
                    break
                sample.append(values)
        return {"originals": originals,
                "fields": [normalize_field(name, i+1) for i, name in enumerate(originals)],
                "sample": [[cell[:500] for cell in row] for row in sample]}
    if task == "import":
        store = import_records(DataConfig(**request["config"]), request["target"],
                               progress=progress, is_cancelled=cancelled)
        return {"store": str(store.path), "metadata": store.metadata,
                 "sample": [{key: value[:500] for key, value in store.record(i).items()}
                           for i in range(1, min(5, store.count)+1)]}
    if task == "background":
        size = import_background(request["source"], request.get("page", 0), request["target"])
        return {"background": request["target"], "width_mm": size[0], "height_mm": size[1]}
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
                             design=design, rule_details=rules)
        pdf = Path(request["target"])
        pdf.write_bytes(raw)
        image = pdf.with_suffix(".png")
        with fitz.open(stream=raw, filetype="pdf") as document:
            document[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(image)
        return {"pdf": str(pdf), "image": str(image), "record": index, "page": page_index, "glyph_repairs": repairs, "rules": rules}
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
