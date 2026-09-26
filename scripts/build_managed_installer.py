"""Build a first-install Inno Setup package from the managed deployment ZIP."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from scripts.build import (
    ROOT,
    _find_inno_setup_compiler,
    _inno_signing_args,
    _windows_signing_settings,
    sha256,
)
from updates.protocol import EXECUTABLE, PRODUCT, UpdateError, version


def extract_deployment(package: Path, destination: Path, app_version: str) -> Path:
    """Stage only the expected managed root from a locally built release ZIP."""
    root = destination / PRODUCT
    with zipfile.ZipFile(package) as archive:
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (
                not path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or path.parts[0] != PRODUCT
                or any(part in {"", ".", ".."} for part in path.parts)
                or entry.is_dir() and len(path.parts) == 1
            ):
                if entry.is_dir() and path.parts == (PRODUCT,):
                    continue
                raise UpdateError(f"Unexpected deployment path: {entry.filename}")
            if entry.external_attr >> 16 & 0o170000 == 0o120000:
                raise UpdateError("Deployment ZIP contains a link.")
        archive.extractall(destination)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    if state != {"current": app_version, "previous": None, "phase": "stable"}:
        raise UpdateError("Deployment state does not match the installer version.")
    application = root / "versions" / app_version
    if not (root / "Launcher.exe").is_file() or not (application / EXECUTABLE).is_file():
        raise UpdateError("Managed deployment is incomplete.")
    if (application / ".managed-update").read_text(encoding="utf-8") != app_version:
        raise UpdateError("Managed deployment marker is invalid.")
    return root


def build_installer(package: Path, app_version: str) -> Path:
    version(app_version)
    compiler = _find_inno_setup_compiler()
    if not compiler:
        raise UpdateError("Inno Setup 6 (ISCC.exe) is required for the Windows installer.")
    package = package.resolve()
    if not package.is_file():
        raise FileNotFoundError(package)
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="managed-installer-", dir=build_dir) as temporary:
        stage = Path(temporary).resolve()
        if not stage.is_relative_to(build_dir.resolve()):
            raise UpdateError("Installer stage escaped the build directory.")
        extract_deployment(package, stage, app_version)
        command = [
            compiler,
            f"/DManagedStage={stage}",
            f"/DManagedVersion={app_version}",
            *_inno_signing_args(_windows_signing_settings()),
            str(ROOT / "installer" / "PDFDocuEditProManaged.iss"),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
    output = ROOT / "release" / f"PDFDocuEdit-Pro-v{app_version}-Setup-Windows-x64.exe"
    if not output.is_file():
        raise UpdateError("Inno Setup did not create the expected installer.")
    sha256(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deployment", type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    if os.name != "nt":
        raise UpdateError("Inno Setup packages require Windows.")
    print(build_installer(args.deployment, args.version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
