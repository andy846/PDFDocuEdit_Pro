"""Headless worker protocol; no Qt imports or editor state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from composition.data.source import RecordStore, import_records, suggest_import
from composition.engine.renderer import import_background, render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import DataConfig, Template, required_fields


def emit(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=True), flush=True)


def dispatch(request: dict) -> dict:
    task = request["task"]
    def cancelled():
        return bool(request.get("cancel_file") and Path(request["cancel_file"]).exists())

    def progress(done, total, message):
        emit("progress", done=done, total=total, message=message)

    if task == "suggest":
        from dataclasses import asdict
        return {"config": asdict(suggest_import(request["source"]))}
    if task == "sample":
        import csv
        from composition.data.source import normalize_field
        config = DataConfig(**request["config"])
        with Path(config.path).open("r", encoding=config.encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=config.delimiter, strict=True)
            for _ in range(config.header_row-1):
                next(reader, None)
            first = next(reader)
            originals = first if config.header else [f"Field_{i+1}" for i in range(len(first))]
            sample = [] if config.header else [first]
            for _ in range(5):
                values = next(reader, None)
                if values is None:
                    break
                sample.append(values)
        return {"originals": originals,
                "fields": [normalize_field(name, i+1) for i, name in enumerate(originals)],
                "sample": sample}
    if task == "import":
        store = import_records(DataConfig(**request["config"]), request["target"],
                               progress=progress, is_cancelled=cancelled)
        return {"store": str(store.path), "metadata": store.metadata,
                "sample": [store.record(i) for i in range(1, min(5, store.count)+1)]}
    if task == "background":
        size = import_background(request["source"], request.get("page", 0), request["target"])
        return {"background": request["target"], "width_mm": size[0], "height_mm": size[1]}
    if task == "preview":
        import fitz
        template = Template.from_dict(request["template"])
        index = request.get("record", 1)
        if request.get("store"):
            record = RecordStore(request["store"]).record(index)
        else:
            record = {name: "{{" + name + "}}" for name in required_fields(template)}
        raw = render_preview(template, record, index)
        pdf = Path(request["target"])
        pdf.write_bytes(raw)
        image = pdf.with_suffix(".png")
        with fitz.open(stream=raw, filetype="pdf") as document:
            document[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(image)
        return {"pdf": str(pdf), "image": str(image), "record": index}
    if task == "generate":
        result = generate(ProductionJob(**request["job"]), progress=progress, is_cancelled=cancelled)
        return result.to_dict()
    raise ValueError("Unknown composition worker task.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="PDFDocuEdit headless composition worker")
    parser.add_argument("request")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request_path = Path(args.request)
        if request_path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Worker request is too large.")
        result = dispatch(json.loads(request_path.read_text(encoding="utf-8")))
        emit("result", result=result)
        return 0
    except Exception as exc:
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
