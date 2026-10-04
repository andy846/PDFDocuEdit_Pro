"""Pinned production assets, resolved without importing Qt."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from composition.template.model import CompositionError


def asset_root() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "build_assets" / "composition"


def qpdf_executable() -> Path:
    folder = asset_root()
    manifest_path = folder / "BUNDLE_INFO.json"
    name = "qpdf/qpdf.exe" if sys.platform == "win32" else "qpdf/qpdf"
    executable = folder / name
    if not executable.is_file() or not manifest_path.is_file():
        raise CompositionError(
            "The pinned qpdf production runtime is missing. "
            "Run scripts/prepare_composition_assets.py or install a complete Composition build."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for asset in manifest["assets"]:
        if asset["path"].startswith("qpdf/"):
            path = folder / asset["path"]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                raise CompositionError(f"Production runtime integrity check failed: {path.name}")
    return executable
