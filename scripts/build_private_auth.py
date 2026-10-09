"""Isolated Windows auth test artifacts. Never signs/publishes a public update."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-only", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        parser.error("Private auth test builds require Windows x64 / Python 3.12.")
    from core.resources import APP_VERSION
    from scripts.build import validate_tesseract_bundle, validate_verapdf_bundle
    from scripts.build_managed_installer import build_installer
    from scripts.distribution_safety import assert_public_distribution
    from scripts.update_release import build_launcher
    from updates.protocol import PRODUCT, atomic_json

    # Always rebuild: a stale/public executable must not be labelled auth-gated.
    validate_tesseract_bundle()
    validate_verapdf_bundle()
    environment = {**os.environ, "PDFDOCUEDIT_BUILD_AUTH": "1"}
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "--distpath", "dist-private-auth", "PDFDocuEdit Pro.spec"], cwd=ROOT, env=environment, check=True)
    dist = ROOT / "dist-private-auth/PDFDocuEdit Pro"
    # Scan before packaging: no developer files, tokens, private PEMs, or logs.
    from scripts.build import _clean_portable_tree, sha256
    _clean_portable_tree(dist)
    assert_public_distribution(dist)
    from updates.target import UpdateTarget
    project = json.loads((ROOT / "build_assets/auth/PROJECT.json").read_text(encoding="utf-8"))
    launcher = build_launcher(target=UpdateTarget("windows-x64", "private", project["project_ref"]))
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    deployment = release / f"PDFDocuEdit-Pro-v{APP_VERSION}-Private-Auth-Managed-Portable-Windows-x64.zip"
    with tempfile.TemporaryDirectory(prefix="private-auth-deployment-", dir=ROOT / "build") as temporary:
        folder = Path(temporary) / PRODUCT
        shutil.copytree(launcher, folder)
        shutil.copytree(dist, folder / "versions" / APP_VERSION)
        (folder / "versions" / APP_VERSION / ".managed-update").write_text(APP_VERSION, encoding="utf-8")
        atomic_json(folder / "state.json", {"current": APP_VERSION, "previous": None, "phase": "stable"})
        (folder / "PRIVATE-TEST.txt").write_text(
            "Internal authentication acceptance build. Not a public release.\n"
            "Extract into an empty folder and launch Launcher.exe. Only signed private-channel updates are accepted.\n"
            "First sign-in requires an approved account online; later launches may work offline.\n", encoding="utf-8")
        assert_public_distribution(folder)
        with zipfile.ZipFile(deployment, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in folder.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(Path(temporary)))
    sha256(deployment)
    print(deployment)
    if not args.portable_only:
        print(build_installer(deployment, APP_VERSION, private_test=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
