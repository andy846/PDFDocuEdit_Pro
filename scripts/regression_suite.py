"""Run every selected module in a fresh process and retain individual JUnit evidence.

Qt's application/style globals and native handles must not leak between modules.
No test is filtered; a crash or timeout is a failing module, never a skip.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(paths: list[str], output: Path, *, timeout: int = 600) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, path in enumerate(paths, 1):
        stem = path.replace("/", "_").removesuffix(".py")
        xml = output / (stem + ".xml")
        started = time.monotonic()
        print(f"[{index}/{len(paths)}] {path}", flush=True)
        with (output / (stem + ".log")).open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    [sys.executable, "-u", "-m", "pytest", "-q", path,
                     "--tb=short", f"--junitxml={xml}"], cwd=ROOT,
                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONFAULTHANDLER": "1",
                         "PYTHONIOENCODING": "utf-8"},
                    stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = -1
                log.write(f"\nModule exceeded {timeout}s; counted as failure.\n")
        row = {"module": path, "exit_code": code, "seconds": round(time.monotonic()-started, 2)}
        if xml.exists():
            suites = ET.parse(xml).getroot()
            for key in ("tests", "failures", "errors", "skipped"):
                row[key] = sum(int(s.get(key, 0)) for s in suites.iter("testsuite"))
        rows.append(row)
        print(json.dumps(row), flush=True)
        if code:
            # CI must expose assertion/native-crash details, not only counts.
            # Full per-module logs remain retained alongside JUnit evidence.
            lines = (output / (stem + ".log")).read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(lines[-160:]), flush=True)
        (output / "result.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return int(any(row["exit_code"] for row in rows))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "core", "ui", "cross"), default="all")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from scripts.ci_plan import CROSS_PLATFORM_TESTS, UI_TESTS
    all_paths = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py"))
    paths = {"all": all_paths, "core": [p for p in all_paths if p not in UI_TESTS],
             "ui": list(UI_TESTS), "cross": list(CROSS_PLATFORM_TESTS)}[args.group]
    return run(paths, args.output.resolve())


if __name__ == "__main__":
    # Also permit direct script execution without relying on PYTHONPATH.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
