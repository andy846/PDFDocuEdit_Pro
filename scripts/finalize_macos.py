"""Refresh packaged runtime hashes after relocation/signing, then seal the app."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.prepare_macos import digest, require_arm64


def finalize(app):
    require_arm64()
    app = Path(app).resolve()
    root = app / "Contents/Resources/build_assets/composition"
    manifest_path = root / "BUNDLE_INFO.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("platform") != "macos-arm64":
        raise RuntimeError("Mac bundle has an incorrect native manifest.")
    executable = root / "qpdf/qpdf"
    subprocess.run([str(executable), "--version"], check=True)
    for entry in manifest["assets"]:
        file = (root / entry["path"]).resolve()
        if not file.is_relative_to(app):
            raise RuntimeError("Mac asset points outside its application.")
        # PyInstaller relocates/signs Mach-O files. Font hashes must remain exact.
        if entry["path"].startswith("qpdf/"):
            entry["sha256"] = digest(file)
        elif entry["sha256"] != digest(file):
            raise RuntimeError("Packaged font integrity changed.")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    identity = os.environ.get("PDFDOCUEDIT_CODESIGN_IDENTITY") or "-"
    args = ["codesign", "--force", "--sign", identity]
    if identity != "-":
        args += ["--options", "runtime", "--timestamp"]
    subprocess.run([*args, str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


if __name__ == "__main__":
    finalize(sys.argv[1])
