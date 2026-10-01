"""Isolated import benchmarks for synthetic inline-string XLSX data."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))


def fixture(path, count):
    from openpyxl import Workbook
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Data")
    sheet.append(["Name", "Account", "Balance", "Date", "Flag"])
    for i in range(1, count+1):
        sheet.append(["Customer", f"{i:08}", 10000.25, date(2026, 10, 2), True])
    book.save(path)
    book.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", nargs="+", type=int, default=[1000, 10000, 50000])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT/"build/benchmarks-excel")
    parser.add_argument("--case", type=Path)
    args = parser.parse_args()
    if args.case:
        from composition.data.source import import_records
        from composition.production.resources import peak_memory
        from composition.template.model import DataConfig
        start = time.perf_counter()
        store = import_records(DataConfig(str(args.case), sheet="Data"), args.output)
        seconds = time.perf_counter()-start
        assert store.record(store.count)["Account"] == f"{store.count:08}"
        print(json.dumps({"records":store.count,"import_seconds":seconds,"records_per_second":store.count/seconds,
                          "peak_memory_bytes":peak_memory(),"snapshot_bytes":store.path.stat().st_size}))
        return
    directory = args.output/time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for count in args.records:
        source = directory/f"source-{count}.xlsx"
        fixture(source, count)
        for trial in range(args.repeat):
            case = directory/f"snapshot-{count}-{trial}.db"
            process = subprocess.run([sys.executable, __file__, "--case", str(source), "--output", str(case)],
                                     check=True, capture_output=True, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            values = json.loads(process.stdout.strip().splitlines()[-1])
            assert values["records"] == count
            values["trial"] = trial
            results.append(values)
            print(json.dumps(values), flush=True)
            report = {"platform":platform.platform(),"python":sys.version,"results":results,
                      "limitations":"Synthetic local XLSX with inline strings; cache/host load uncontrolled. Read-only XML rows do not imply constant memory for shared strings/styles. Legacy XLS loads the selected worksheet."}
            (directory/"benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report: "+str(directory/"benchmark.json"))


if __name__ == "__main__":
    main()
