"""Repeatable isolated synthetic scan benchmark; no customer PDFs or font assets."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def peak_memory_mb():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                *[
                    (name, ctypes.c_size_t)
                    for name in (
                        "PeakWorkingSetSize",
                        "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage",
                        "PagefileUsage",
                        "PeakPagefileUsage",
                    )
                ],
            ]

        value = Counters()
        value.cb = ctypes.sizeof(value)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(value), value.cb
        ):
            raise OSError("Cannot measure process memory.")
        return value.PeakWorkingSetSize / 1024**2
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024**2 if sys.platform == "darwin" else 1024)


def single(pages):
    import fitz

    from core.font_preflight.inventory import analyze

    with tempfile.TemporaryDirectory(prefix="font-benchmark-") as directory:
        path = Path(directory) / "synthetic.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((24, 40), "Synthetic shared Base-14 resource")
            for _ in range(pages - 1):
                doc.fullcopy_page(0)
            doc.save(path)
        start = time.perf_counter()
        report = analyze(path)
        elapsed = time.perf_counter() - start
        if not report.complete or len(report.resources[0].pages) != pages:
            raise RuntimeError("Benchmark inventory is incomplete.")
        return {
            "pages": pages,
            "scan_seconds": round(elapsed, 4),
            "pages_per_second": round(pages / elapsed, 2),
            "peak_process_memory_mb": round(peak_memory_mb(), 2),
            "input_bytes": path.stat().st_size,
            "complete": report.complete,
            "fixture": "Synthetic shared Base-14; not representative of image-heavy/CJK customer PDFs",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", type=int)
    parser.add_argument("--pages", type=int, nargs="+", default=[1000, 20000])
    parser.add_argument("--output", default="build/font-preflight-benchmark.json")
    args = parser.parse_args()
    if args.single:
        print(json.dumps(single(args.single)))
        return
    results = []
    for count in args.pages:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.benchmark_font_preflight", "--single", str(count)],
            check=True,
            capture_output=True,
            text=True,
        )
        results.append(json.loads(result.stdout))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "results": results}, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
