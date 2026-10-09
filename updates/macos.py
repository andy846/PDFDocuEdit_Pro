"""Mac adapter around the shared signed-update transaction and supervisor."""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import uuid
from pathlib import Path

from .macos_archive import APP
from .protocol import UpdateError, atomic_json, version
from .runtime import FileLock, Installation


def validate_app(folder, expected_version, target):
    app = Path(folder) / APP
    if app.is_symlink() or not app.is_dir():
        raise UpdateError("Mac application directory is invalid.")
    with (app / "Contents/Info.plist").open("rb") as stream:
        metadata = plistlib.load(stream)
    if metadata.get("CFBundleShortVersionString") != expected_version:
        raise UpdateError("Mac application version differs from the signed manifest.")
    identity = json.loads((app / "Contents/Resources/update-target.json").read_text(encoding="utf-8"))
    if identity != {"platform": target.platform, "channel": target.channel, "auth_project": target.auth_project}:
        raise UpdateError("Mac application channel/account identity differs.")
    executable = app / "Contents/MacOS/PDFDocuEdit Pro"
    if not executable.resolve().is_relative_to(app.resolve()):
        raise UpdateError("Mac executable escapes its bundle.")
    architecture = subprocess.check_output(["/usr/bin/lipo", "-archs", str(executable)], text=True).strip()
    if architecture != "arm64":
        raise UpdateError("Mac update is not an arm64 application.")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def installation_for(initial_app, initial_version, target, *, base=None):
    version(initial_version)
    if target.platform != "macos-arm64":
        raise UpdateError("Wrong target for Mac bootstrap.")
    base = Path(base) if base else Path.home() / "Library/Application Support/PDFDocuEditPro/managed"
    root = base / f"{target.channel}-{target.auth_project or 'public'}-arm64"
    installation = Installation(root, target=target, validator=validate_app)
    with FileLock(root / "bootstrap.lock"):
        if not installation.state_path.exists():
            final = root / "versions" / initial_version
            staging = root / "versions" / f".bootstrap-{uuid.uuid4().hex}"
            # Never replace an orphaned version or another installation's data.
            if final.exists():
                raise UpdateError("Bootstrap version already exists without a state file.")
            staging.mkdir()
            try:
                shutil.copytree(initial_app, staging / APP, symlinks=True)
                validate_app(staging, initial_version, target)
                (staging / ".managed-update").write_text(initial_version, encoding="utf-8")
                staging.rename(final)
                atomic_json(installation.state_path, {"current": initial_version, "previous": None, "phase": "stable"})
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                raise
    return installation
