"""Cross-platform desktop and external-process integration."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class PlatformService:
    WINDOWS = platform.system() == "Windows"
    MACOS = platform.system() == "Darwin"

    @classmethod
    def open_path(cls, path: str | os.PathLike[str]) -> bool:
        target = Path(path).expanduser().resolve()
        return target.exists() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @classmethod
    def open_folder(cls, path: str | os.PathLike[str]) -> bool:
        target = Path(path).expanduser().resolve()
        if target.is_file():
            target = target.parent
        return target.is_dir() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @classmethod
    def reveal_file(cls, path: str | os.PathLike[str]) -> bool:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return False
        try:
            if cls.WINDOWS:
                subprocess.Popen(["explorer.exe", "/select,", str(target)])
            elif cls.MACOS:
                subprocess.Popen(["open", "-R", str(target)])
            else:
                return cls.open_folder(target.parent)
            return True
        except OSError:
            return False

    @staticmethod
    def find_executable(names: Iterable[str], extra_paths: Iterable[str] = ()) -> str | None:
        for candidate in extra_paths:
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        for name in names:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return None

    @staticmethod
    def run(
        command: Sequence[str],
        *,
        timeout: int = 300,
        cwd: str | os.PathLike[str] | None = None,
    ) -> ProcessResult:
        kwargs: dict[str, object] = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                list(command),
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                **kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"The external tool did not respond within {timeout}s.") from exc
        return ProcessResult(result.returncode, result.stdout, result.stderr)
