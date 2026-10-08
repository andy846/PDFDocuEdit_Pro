"""Synthetic raster benchmark, not printer throughput or driver validation.

Run: python scripts/benchmark_printing.py --pages 100 1000 --dpi 72
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def memory(pid):
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in
            ("peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    handle = kernel.OpenProcess(0x1010, False, pid)
    if not handle:
        return None
    try:
        result = Counters()
        result.cb = ctypes.sizeof(result)
        if query(handle, ctypes.byref(result), result.cb):
            return {"rss": result.rss, "peak_rss": result.peak_rss}
    finally:
        kernel.CloseHandle(handle)
    return None


def main():
    import fitz

    from core.printing import (
        PrintJob,
        PrintRenderSettings,
        prepare_print_job,
        render_page_image,
        render_print_page,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, nargs="+", default=[100, 1000])
    parser.add_argument("--dpi", type=int, default=72)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-print-benchmark-") as folder:
        for count in args.pages:
            source = Path(folder) / f"{count}.pdf"
            with fitz.open() as doc:
                for index in range(count):
                    doc.new_page().insert_text((72, 72), f"Synthetic print page {index}")
                doc.save(source)
            cfg = PrintRenderSettings(args.dpi, 595, 842, 0, 0, 0, 100, True, 0, 0)
            started = perf_counter()
            prepared = prepare_print_job(PrintJob(str(source), "benchmark", "benchmark"))
            preparation = perf_counter() - started
            samples = []
            try:
                started = perf_counter()
                for index in range(count):
                    render_print_page(prepared, index, cfg)
                    if index in (0, count // 2, count - 1):
                        samples.append({"page": index + 1, "parent": memory(os.getpid()),
                                        "worker": memory(prepared.session.worker_pid)})
                elapsed = perf_counter() - started
            finally:
                prepared.session.close()
            # Reproduce the old per-page parsing for a comparable raster baseline.
            data = source.read_bytes()
            started = perf_counter()
            for index in range(count):
                with fitz.open(stream=data, filetype="pdf") as doc:
                    render_page_image(doc[index], cfg)
            baseline = perf_counter() - started
            print(json.dumps({"fixture": "synthetic text A4", "pages": count, "dpi": args.dpi,
                              "prepare_seconds": preparation, "process_render_seconds": elapsed,
                              "previous_render_seconds": baseline, "memory_bytes": samples}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
