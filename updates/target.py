"""Trusted build identity; channels cannot install each other's signed assets."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UpdateTarget:
    platform: str = "windows-x64"
    channel: str = "public"
    auth_project: str = ""

    def __post_init__(self):
        if self.platform not in {"windows-x64", "macos-arm64"} or self.channel not in {"public", "private"}:
            raise ValueError("Unsupported update target.")
        if (self.channel == "private" and not self.auth_project.isalnum()) or (self.channel == "public" and self.auth_project):
            raise ValueError("Invalid update account project.")

    @property
    def legacy(self):
        return self.platform == "windows-x64" and self.channel == "public"

    @property
    def metadata(self):
        return "update" if self.legacy else f"update-{self.platform}-{self.channel}"

    def asset(self, version):
        suffix = "Windows-x64" if self.platform == "windows-x64" else "macOS-arm64"
        if self.channel == "private":
            suffix += "-Private"
        return f"PDFDocuEdit-Pro-v{version}-Update-{suffix}.zip"

    @property
    def executable(self):
        return "PDFDocuEdit Pro.exe" if self.platform == "windows-x64" else "PDFDocuEdit Pro.app/Contents/MacOS/PDFDocuEdit Pro"


DEFAULT_TARGET = UpdateTarget()

# Frozen Launcher.exe shipped in the immutable v3.0.3 managed deployment.
# Its schema-1 transport must remain usable after the editor requires login.
LEGACY_WINDOWS_LAUNCHERS = {
    "172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522",
}


@dataclass(frozen=True)
class UpdateRoute:
    transport: UpdateTarget
    application: UpdateTarget

    @property
    def bridge(self):
        return self.transport != self.application


def resolve_update_route(root: Path | None, application_target: UpdateTarget) -> UpdateRoute:
    """Select the installed launcher's transport, never the user's preference."""
    import json

    from .protocol import UpdateError, digest_file

    if application_target.platform != "windows-x64" or application_target.legacy:
        return UpdateRoute(application_target, application_target)
    if root is None:
        raise UpdateError("Install the account-enabled Managed edition to enable updates.")
    root = Path(root)
    launcher = root / "Launcher.exe"
    identity = root / "launcher_runtime/update-target.json"
    if not launcher.is_file() or launcher.is_symlink():
        raise UpdateError("Managed Launcher.exe is missing. Restore the complete installation.")
    if identity.exists():
        try:
            target = UpdateTarget(**json.loads(identity.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as error:
            raise UpdateError("Installed launcher identity is invalid.") from error
        if target != application_target:
            raise UpdateError("Installed launcher belongs to another account channel/project.")
        return UpdateRoute(target, application_target)
    if digest_file(launcher) not in LEGACY_WINDOWS_LAUNCHERS:
        raise UpdateError("This older launcher is not verified for account updates. Install the new Managed edition.")
    return UpdateRoute(DEFAULT_TARGET, application_target)


def build_target():
    try:
        module = importlib.import_module("pdfdocuedit_update_build")
    except ModuleNotFoundError as error:
        if error.name != "pdfdocuedit_update_build":
            raise
        return UpdateTarget()
    return UpdateTarget(**module.TARGET)
