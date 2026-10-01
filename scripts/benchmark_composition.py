"""Repeatable isolated-process production benchmarks, not a real-document guarantee."""
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


def one_case(count, directory, fixture, pages=1):
    sys.path.insert(0, str(ROOT))
    from composition.data.source import import_records
    from composition.production.generator import generate
    from composition.production.model import ProductionJob
    from composition.template.model import DataConfig, Element, FontSpec, PageSpec, Template
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "input.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        stream.write("Account,Name,Address\n")
        for index in range(count):
            stream.write(f'{index:010},Customer {index},"Hong Kong"\n')
    start = time.perf_counter()
    store = import_records(DataConfig(path=str(source)), directory / "records.db")
    imported = time.perf_counter()
    elements = [Element(value="Account: {{Account}}", height_mm=20)]
    if fixture == "mixed":
        elements.extend([
            Element(value="{{Name}}\n{{Address}}", y_mm=55, width_mm=130, height_mm=25),
            Element(type="rectangle", y_mm=100, width_mm=160, height_mm=30),
            Element(type="code128", value="{{Account}}", y_mm=145, width_mm=110, height_mm=25),
            Element(type="qr", value="{{Account}}", y_mm=190, width_mm=35, height_mm=35),
            Element(value="\u9999\u6e2f\u5ba2\u6236", y_mm=235, height_mm=20,
                    font=FontSpec(family="Noto Sans CJK HK")),
        ])
    import copy
    import uuid
    model = Template(elements=elements)
    for index in range(1, pages):
        copied = copy.deepcopy(elements)
        for element in copied:
            element.id = uuid.uuid4().hex
        model.pages.append(PageSpec(name=f"Page {index+1}", elements=copied))
    result = generate(ProductionJob(model.to_dict(), str(store.path), str(directory)))
    end = time.perf_counter()
    if result.status != "completed":
        raise RuntimeError(result.error)
    values = {"records": count, "pages_per_record": pages, "generated_pages": result.generated_pages, "fixture": fixture, "import_seconds": imported-start,
              "generation_seconds": end-imported, "total_seconds": end-start,
              "records_per_second": count/(end-imported),
              "pages_per_second": result.generated_pages/(end-imported), "output_size_bytes": result.output_size,
              "composer_peak_memory_bytes": result.composer_peak_memory_bytes,
              "assembler_peak_memory_bytes": result.assembler_peak_memory_bytes,
              "job_log": str(Path(result.report_dir)/"job.json")}
    print(json.dumps(values))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", nargs="+", type=int, default=[100, 1000, 10000, 50000])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--fixture", choices=["plain", "mixed"], default="plain")
    parser.add_argument("--output", type=Path, default=ROOT / ".benchmarks" / "composition")
    parser.add_argument("--case", type=int)
    parser.add_argument("--pages", type=int, choices=range(1, 101), default=1)
    args = parser.parse_args()
    if args.case:
        one_case(args.case, args.output, args.fixture, args.pages)
        return
    destination = args.output.resolve() / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for count in args.records:
        for repeat in range(args.repeat):
            case = destination / f"{count}-{repeat}"
            process = subprocess.run([sys.executable, __file__, "--case", str(count),
                                      "--output", str(case), "--fixture", args.fixture, "--pages", str(args.pages)],
                                     check=True, capture_output=True, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            result = json.loads(process.stdout.strip().splitlines()[-1])
            results.append(result)
            print(json.dumps(result), flush=True)
            report = {"benchmark_version": 1, "platform": platform.platform(),
                      "python": sys.version, "fixture": args.fixture, "results": results,
                      "limitations": "Synthetic fixed-page local data; assembler memory is separate, not zero."}
            (destination / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report: " + str(destination / "benchmark.json"))


if __name__ == "__main__":
    main()
