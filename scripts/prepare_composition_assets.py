"""Prepare pinned qpdf/output-font assets, verifying every SHA-256 before use."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "build_assets" / "composition"


def prepare(*, fonts_only: bool = False, verify_only: bool = False) -> None:
    manifest = json.loads((ASSETS / "BUNDLE_INFO.json").read_text(encoding="utf-8"))
    downloads: dict[str, bytes] = {}
    for asset in manifest["assets"]:
        relative = Path(asset["path"])
        if fonts_only and relative.parts[0] != "fonts":
            continue
        target = (ASSETS / relative).resolve()
        if not target.is_relative_to(ASSETS.resolve()):
            raise ValueError("Invalid asset path in manifest.")
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == asset["sha256"]:
            continue
        if verify_only:
            raise RuntimeError(f"Missing or unverified Composition asset: {relative}")
        url = asset["source"]
        if url not in downloads:
            with urllib.request.urlopen(url, timeout=120) as response:
                downloads[url] = response.read()
        raw = downloads[url]
        if url.endswith(".zip"):
            archive = zipfile.ZipFile(io.BytesIO(raw))
            members = [
                entry for entry in archive.infolist()
                if Path(entry.filename).name == relative.name and "bin" in Path(entry.filename).parts
            ]
            if len(members) != 1:
                raise RuntimeError(f"Unexpected qpdf archive layout for {relative.name}")
            raw = archive.read(members[0])
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise RuntimeError(f"Composition asset checksum mismatch: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_suffix(target.suffix + ".download")
        staged.write_bytes(raw)
        staged.replace(target)
        print(f"Prepared {relative}")
    print("Composition assets verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts-only", action="store_true", default=sys.platform != "win32")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    prepare(fonts_only=args.fonts_only, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
