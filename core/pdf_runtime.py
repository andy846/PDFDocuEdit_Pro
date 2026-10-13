"""Shared pinned qpdf runtime; usable without enabling Document Designer."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import struct
import sys
from pathlib import Path, PurePosixPath


def asset_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "build_assets" / "composition"


def runtime_platform():
    if sys.platform == "win32":
        return "windows-x64"
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if sys.platform == "linux" and machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if sys.platform == "linux" and machine in {"arm64", "aarch64"}:
        return "linux-arm64"
    raise RuntimeError("No pinned qpdf runtime is supported for this platform/architecture.")


def verify_binary_architecture(executable, target):
    with Path(executable).open("rb") as stream:
        header = stream.read(64)
        valid = False
        if target == "windows-x64" and len(header) >= 64 and header[:2] == b"MZ":
            offset = struct.unpack_from("<I", header, 60)[0]
            if 64 <= offset <= 65536:
                stream.seek(offset)
                pe = stream.read(6)
                valid = len(pe) == 6 and pe[:4] == b"PE\0\0" and struct.unpack_from("<H", pe, 4)[0] == 0x8664
        elif target == "macos-arm64" and len(header) >= 32:
            valid = header[:4] == b"\xcf\xfa\xed\xfe" and struct.unpack_from("<I", header, 4)[0] == 0x100000C
        elif target.startswith("linux-") and len(header) >= 64:
            valid = header[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", header, 18)[0] == (62 if target == "linux-x64" else 183)
    if not valid:
        raise RuntimeError(f"qpdf architecture/platform mismatch; expected {target}. Install a complete matching build.")


def qpdf_executable():
    root = asset_root()
    manifest_path = root / "BUNDLE_INFO.json"
    name = "qpdf/qpdf.exe" if sys.platform == "win32" else "qpdf/qpdf"
    executable = root / name
    if not executable.is_file() or not manifest_path.is_file():
        raise RuntimeError("The pinned qpdf runtime is missing. Install a complete build or run python -m scripts.prepare_composition_assets.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("assets"), list):
            raise ValueError("Unsupported runtime manifest")
        entries = [entry for entry in manifest["assets"] if entry["path"].startswith("qpdf/")]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RuntimeError("The qpdf integrity manifest is invalid. Restore a complete build.") from exc
    target = runtime_platform()
    if manifest.get("platform", "windows-x64") != target:
        raise RuntimeError(f"qpdf manifest platform mismatch; expected {target}. Prepare the matching native runtime.")
    if not any(entry["path"] == name for entry in entries):
        raise RuntimeError("The qpdf executable is missing from its integrity manifest.")
    owned = root.resolve()
    if sys.platform == "darwin" and hasattr(sys, "_MEIPASS"):
        # PyInstaller links data/binaries between Resources and Frameworks.
        bundle = Path(sys._MEIPASS).resolve().parent.parent
        if bundle.suffix == ".app":
            owned = bundle
    for entry in entries:
        relative = entry["path"]
        parts = PurePosixPath(relative)
        if parts.is_absolute() or "\\" in relative or ":" in relative or ".." in parts.parts:
            raise RuntimeError("Invalid qpdf runtime asset path.")
        path = root / relative
        if not path.resolve().is_relative_to(owned):
            raise RuntimeError("qpdf runtime asset points outside its owned path.")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise RuntimeError(f"Runtime integrity check failed: {path.name}")
    if sys.platform != "win32" and not os.access(executable, os.X_OK):
        raise RuntimeError("qpdf executable permission is missing. Restore the complete native runtime.")
    verify_binary_architecture(executable, target)
    return executable
