"""Shared pinned qpdf runtime; usable without enabling Document Designer."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def asset_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "build_assets" / "composition"


def qpdf_executable():
    root = asset_root()
    manifest_path = root / "BUNDLE_INFO.json"
    name = "qpdf/qpdf.exe" if sys.platform == "win32" else "qpdf/qpdf"
    executable = root / name
    if not executable.is_file() or not manifest_path.is_file():
        raise RuntimeError("The pinned qpdf runtime is missing. Install a complete build or run scripts/prepare_composition_assets.py.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["assets"] if entry["path"].startswith("qpdf/")]
    if not any(entry["path"] == name for entry in entries):
        raise RuntimeError("The qpdf executable is missing from its integrity manifest.")
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Runtime integrity check failed: {path.name}")
    return executable
