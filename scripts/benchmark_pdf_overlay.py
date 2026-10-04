"""Synthetic PDF overlay benchmark, with final-page barcode decoding in every job."""
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


def one_case(pages, directory, duplex, chunk):
    sys.path.insert(0, str(ROOT))
    import fitz

    from composition.overlay.generator import generate
    from composition.overlay.model import BarcodeProfile, EnvelopeSpec, OverlayJob, OverlayObject
    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.source import inspect_source
    from composition.template.model import Element
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "synthetic-source.pdf"
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.insert_text((100, 230), f"Synthetic source page {index+1}")
        document.save(source)
    settings = EnvelopeSettings(duplex=duplex)
    start = time.perf_counter()
    info = inspect_source(source, settings)
    inspected = time.perf_counter()
    project = EnvelopeSpec(info, settings, [
        OverlayObject(Element(value="{{EnvelopeSeq}}", x_mm=20, y_mm=20)),
        OverlayObject(Element(type="code128", x_mm=20, y_mm=35, width_mm=90, height_mm=14),
                      control=True, profile=BarcodeProfile())])
    result = generate(OverlayJob(project.to_dict(), str(directory), chunk_size=chunk))
    end = time.perf_counter()
    if result.status != "completed":
        raise RuntimeError(result.error)
    return {"source_pages": pages, "duplex": duplex, "chunk_size": chunk,
            "envelopes": result.successful_envelopes, "output_pages": result.generated_pages,
            "inserted_blanks": result.inserted_blanks, "sheets": result.sheets,
            "decoded_barcodes": result.decoded_barcodes, "inspection_seconds": inspected-start,
            "generation_and_qc_seconds": end-inspected, "total_seconds": end-start,
            "pages_per_second": result.generated_pages/(end-inspected),
            "composer_peak_memory_bytes": result.composer_peak_memory_bytes,
            "assembler_peak_memory_bytes": result.assembler_peak_memory_bytes,
            "output_bytes": result.output_size, "job_log": str(Path(result.report_dir)/"job.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, nargs="+", default=[300, 3000])
    parser.add_argument("--duplex", action="store_true")
    parser.add_argument("--chunk", type=int, default=500)
    parser.add_argument("--output", type=Path, default=ROOT/".benchmarks"/"pdf-overlay")
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    if args.case:
        print(json.dumps(one_case(args.case, args.output, args.duplex, args.chunk)))
        return
    destination = args.output.resolve()/time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for pages in args.pages:
        command = [sys.executable, __file__, "--case", str(pages), "--output", str(destination/str(pages)),
                   "--chunk", str(args.chunk)]
        if args.duplex:
            command.append("--duplex")
        process = subprocess.run(command, check=True, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        case = json.loads(process.stdout.strip().splitlines()[-1])
        results.append(case)
        print(json.dumps(case), flush=True)
        report = {"version": 1, "platform": platform.platform(), "python": sys.version,
                  "results": results,
                  "limitations": "Synthetic local PDF with simple original text; includes exact barcode decoding. "
                                 "Does not establish inserter compatibility or image-heavy/network PDF performance."}
        (destination/"benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report: " + str(destination/"benchmark.json"))


if __name__ == "__main__":
    main()
