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


def register_shell(installation, executable):
    """Remember the fixed, installed shell rather than a versioned child."""
    executable = Path(executable).resolve()
    if executable.parent.name != "MacOS" or executable.parent.parent.name != "Contents":
        raise UpdateError("Invalid Mac launcher bundle.")
    atomic_json(installation.root / "installation.json", {"launcher": str(executable)})


def managed_shell(executable, target):
    """Finder may open a versioned app; route it back through its supervisor."""
    executable = Path(executable).resolve()
    # versions/<version>/<app>/Contents/MacOS/<executable>
    if len(executable.parents) < 6 or executable.parents[4].name != "versions":
        return None
    folder = executable.parents[3]
    root = folder.parent.parent
    marker = folder / ".managed-update"
    if not marker.exists() and not (root / "state.json").exists():
        return None
    try:
        if marker.read_text(encoding="utf-8").strip() != folder.name:
            raise UpdateError("Managed version marker differs.")
        installation = Installation(root, target=target, validator=validate_app)
        installation.executable(installation.state()["current"])
        launcher = Path(json.loads((root / "installation.json").read_text())["launcher"])
        if not launcher.is_absolute() or not launcher.is_file() or launcher.parent.name != "MacOS":
            raise UpdateError("The fixed Mac launcher is missing.")
        resources = launcher.parent.parent / "Resources"
        settings = json.loads((resources / "bootstrap.json").read_text())
        from dataclasses import asdict
        if settings["target"] != asdict(target):
            raise UpdateError("The fixed Mac launcher channel differs.")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(launcher.parents[2])],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return launcher
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, UpdateError) as exc:
        raise UpdateError("Managed Mac installation is incomplete. Open the installed fixed application.") from exc
