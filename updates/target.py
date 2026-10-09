"""Trusted build identity; channels cannot install each other's signed assets."""
from __future__ import annotations

import importlib
from dataclasses import dataclass


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


def build_target():
    try:
        module = importlib.import_module("pdfdocuedit_update_build")
    except ModuleNotFoundError as error:
        if error.name != "pdfdocuedit_update_build":
            raise
        return UpdateTarget()
    return UpdateTarget(**module.TARGET)
