"""Reuse only verified native runtimes from the signed v3.0.3 Windows payload."""
from __future__ import annotations

import shutil
from pathlib import Path

from updates.protocol import Manifest, Release, UpdateError, download, extract_archive, fetch_small
from updates.trust import PUBLIC_KEY_HEX, REPOSITORY

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = f"https://github.com/{REPOSITORY}/releases/download/v3.0.3/"
    raw, signature = fetch_small(base + "update.json", 65536), fetch_small(base + "update.sig", 64)
    manifest = Manifest.verify(raw, signature, PUBLIC_KEY_HEX)
    if manifest.version != "3.0.3":
        raise UpdateError("The fixed native-runtime baseline differs.")
    stage = ROOT / "build/windows-native-baseline"
    package = download(Release(manifest, raw, signature, base + manifest.asset, ""), stage, lambda *args: None, lambda: False)
    extracted = stage / "application"
    if not extracted.exists():
        extract_archive(package, extracted, manifest)
    for source, destination in (("tesseract", "Tesseract"), ("ghostscript", "Ghostscript"), ("verapdf", "VeraPDF")):
        shutil.copytree(extracted / "_internal" / source, ROOT / destination, dirs_exist_ok=True)
    from scripts.build import validate_tesseract_bundle, validate_verapdf_bundle
    validate_tesseract_bundle()
    validate_verapdf_bundle()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
