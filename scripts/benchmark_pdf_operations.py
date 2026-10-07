"""Isolated, repeatable local PDF-operation cases; no real-document guarantee."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def one_case(pages, directory, operation):
    sys.path.insert(0, str(ROOT))
    import fitz

    from composition.production.resources import peak_memory
    from core.pdf_operations.model import PdfOptions
    from core.pdf_operations.service import run
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / "fixture.pdf"
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page()
            page.insert_text((40, 40), f"Searchable production page {index + 1:06d}")
            page.add_freetext_annot((40, 70, 240, 110), "Approved annotation")
        doc.save(source)
    started = time.perf_counter()
    report = run(source, directory / "output", PdfOptions(operation=operation, annotations=operation == "flatten"))
    elapsed = time.perf_counter() - started
    return {"operation": operation, "pages": pages, "seconds": elapsed, "pages_per_second": pages / elapsed,
            "peak_process_memory_bytes": peak_memory(), "output_bytes": Path(report["output_pdf"]).stat().st_size,
            "status": report["status"], "validation": report["validation"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--output", type=Path, default=ROOT / ".benchmarks" / "pdf-operations")
    parser.add_argument("--operation", choices=("flatten", "repair"), default="flatten")
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    if args.case:
        print(json.dumps(one_case(args.case, args.output, args.operation)))
        return
    folder = args.output.resolve() / (time.strftime("%Y%m%d-%H%M%S") + "-" + args.operation)
    folder.mkdir(parents=True, exist_ok=False)
    results = []
    for pages in args.pages:
        if not 1 <= pages <= 100000:
            parser.error("Use 1–100,000 pages.")
        process = subprocess.run([sys.executable, __file__, "--case", str(pages), "--output", str(folder / str(pages)),
                                  "--operation", args.operation], check=True, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        case = json.loads(process.stdout.strip().splitlines()[-1])
        results.append(case)
        print(json.dumps(case), flush=True)
        (folder / "benchmark.json").write_text(json.dumps({"platform": platform.platform(), "python": sys.version,
             "results": results, "limitations": "Synthetic simple local pages. Peak includes fixture creation; "
             "not a constant-memory or real customer PDF guarantee. Raster rendering is page-by-page, "
             "but the existing PDF document backend and full rewrite still hold object tables."}, indent=2), encoding="utf-8")
    print("Report: " + str(folder / "benchmark.json"))


if __name__ == "__main__":
    main()
