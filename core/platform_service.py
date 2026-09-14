"""Cross-platform desktop and external-process integration."""

from __future__ import annotations

import locale
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from core.diagnostics import log_failure


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class PlatformService:
    WINDOWS = platform.system() == "Windows"
    MACOS = platform.system() == "Darwin"

    @staticmethod
    def _decode_process_output(value: bytes | str | None) -> str:
        """Decode tool output without assuming every Windows process uses UTF-8."""

        if value is None:
            return ""
        if isinstance(value, str):
            return value
        encodings = ["utf-8-sig"]
        preferred = locale.getpreferredencoding(False)
        if preferred:
            encodings.append(preferred)
        if platform.system() == "Windows":
            encodings.extend(("mbcs", "oem", "cp1252"))
        tried: set[str] = set()
        for encoding in encodings:
            key = encoding.casefold()
            if key in tried:
                continue
            tried.add(key)
            try:
                return value.decode(encoding, errors="strict")
            except (LookupError, UnicodeDecodeError):
                continue
        fallback = preferred or "utf-8"
        try:
            return value.decode(fallback, errors="replace")
        except LookupError:
            return value.decode("utf-8", errors="replace")

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
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        kwargs: dict[str, object] = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                list(command),
                cwd=cwd,
                env=env,
                capture_output=True,
                timeout=timeout,
                check=False,
                **kwargs,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"The external tool did not respond within {timeout}s."
            ) from exc
        return ProcessResult(
            result.returncode,
            PlatformService._decode_process_output(result.stdout),
            PlatformService._decode_process_output(result.stderr),
        )

    @staticmethod
    def run_cancellable(
        command: Sequence[str],
        *,
        is_cancelled,
        timeout: int = 600,
        cwd: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        """Run a hidden process while polling for cooperative cancellation."""
        kwargs: dict[str, object] = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                if is_cancelled and is_cancelled():
                    PlatformService._stop_process(process)
                    from .tasks import TaskCancelled

                    raise TaskCancelled
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    PlatformService._stop_process(process)
                    raise TimeoutError(
                        f"The external tool did not respond within {timeout}s."
                    )
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    return ProcessResult(
                        process.returncode or 0,
                        PlatformService._decode_process_output(stdout),
                        PlatformService._decode_process_output(stderr),
                    )
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                PlatformService._stop_process(process)

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                log_failure('platform_service._stop_process: fallback after failure', 10)
                pass
