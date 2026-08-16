"""Optional feature detection without importing platform-specific modules."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from .platform_service import PlatformService
from .settings import SettingsManager


class CapabilityId(StrEnum):
    OFFICE_TO_PDF = "office_to_pdf"
    POSTSCRIPT = "postscript"
    BARCODE = "barcode"
    PDF_TO_WORD = "pdf_to_word"
    SPREADSHEET = "spreadsheet"


@dataclass(frozen=True)
class Capability:
    id: CapabilityId
    name: str
    available: bool
    backend: str = ""
    path: str = ""
    reason: str = ""
    guidance: str = ""


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _configured_executable(key: str) -> str | None:
    value = SettingsManager().get(key)
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None


def _office_capability() -> Capability:
    if platform.system() == "Windows" and _has_module("comtypes.client"):
        return Capability(
            CapabilityId.OFFICE_TO_PDF,
            "Office to PDF",
            True,
            "Microsoft Office COM",
        )
    soffice = _configured_executable("libreoffice_path") or PlatformService.find_executable(
        ("soffice", "libreoffice"),
        (
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/Program Files/LibreOffice/program/soffice.exe",
            "/Program Files (x86)/LibreOffice/program/soffice.exe",
        ),
    )
    if soffice:
        return Capability(
            CapabilityId.OFFICE_TO_PDF,
            "Office to PDF",
            True,
            "LibreOffice",
            soffice,
        )
    return Capability(
        CapabilityId.OFFICE_TO_PDF,
        "Office to PDF",
        False,
        reason="No supported Office conversion backend was found.",
        guidance="Install Microsoft Office on Windows or LibreOffice on either platform.",
    )


def _bundled_ghostscript() -> str | None:
    """Ghostscript shipped inside the application bundle.

    The PyInstaller build places the whole Ghostscript tree (bin/lib/Resource/
    iccprofiles) under a ``ghostscript`` folder, so the bundled executable can
    resolve its support files relative to its own location.
    """
    names = ("gswin64c.exe", "gswin32c.exe") if platform.system() == "Windows" else ("gs",)
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidates.append(Path(base) / "ghostscript" / "bin")
        candidates.append(Path(sys.executable).resolve().parent / "ghostscript" / "bin")
    elif platform.system() == "Windows":
        # Development tree on Windows: the repository ships the GS binaries.
        candidates.append(Path(__file__).resolve().parent.parent / "Ghostscript" / "bin")
    for root in candidates:
        for name in names:
            path = root / name
            # os.access(X_OK) is meaningless for files on Windows (it checks
            # existence there); on POSIX the binary needs the exec bit.
            runnable = (
                path.is_file()
                if platform.system() == "Windows"
                else path.is_file() and os.access(path, os.X_OK)
            )
            if runnable:
                return str(path)
    return None


def _postscript_capability() -> Capability:
    gs = (
        _bundled_ghostscript()
        or _configured_executable("ghostscript_path")
        or PlatformService.find_executable(
            ("gswin64c.exe", "gswin32c.exe", "gs"),
            (
                "/opt/homebrew/bin/gs",
                "/usr/local/bin/gs",
                "/usr/bin/gs",
            ),
        )
    )
    return Capability(
        CapabilityId.POSTSCRIPT,
        "PostScript",
        bool(gs),
        "Ghostscript" if gs else "",
        gs or "",
        "Ghostscript was not found." if not gs else "",
        "Install Ghostscript or select its executable in Settings." if not gs else "",
    )


def _barcode_capability() -> Capability:
    missing = [name for name in ("PIL", "pyzbar") if not _has_module(name)]
    zbar = PlatformService.find_executable(("zbarimg",), ("/opt/homebrew/bin/zbarimg",))
    load_error = ""
    if not missing:
        try:
            from pyzbar.pyzbar import decode as _decode  # noqa: F401
        except (ImportError, OSError) as exc:
            load_error = str(exc)
    available = (not missing and not load_error) or bool(zbar)
    reason = ""
    if missing and not zbar:
        reason = f"Missing Python packages: {', '.join(missing)}."
    elif load_error and not zbar:
        reason = f"The zbar native library could not be loaded: {load_error}"
    return Capability(
        CapabilityId.BARCODE,
        "Barcode / QR Code",
        available,
        "pyzbar / zbar" if available and not load_error and not missing else "zbarimg CLI" if zbar else "",
        zbar or "",
        reason,
        "Install Pillow, pyzbar and the zbar native library." if not available else "",
    )


def _module_capability(
    capability_id: CapabilityId,
    display_name: str,
    modules: Iterable[str],
    guidance: str,
) -> Capability:
    missing = [name for name in modules if not _has_module(name)]
    return Capability(
        capability_id,
        display_name,
        not missing,
        "Python" if not missing else "",
        reason=f"Missing Python packages: {', '.join(missing)}." if missing else "",
        guidance=guidance if missing else "",
    )


@lru_cache(maxsize=1)
def detect_capabilities() -> dict[CapabilityId, Capability]:
    values = [
        _office_capability(),
        _postscript_capability(),
        _barcode_capability(),
        _module_capability(
            CapabilityId.PDF_TO_WORD,
            "PDF to Word",
            ("pdf2docx",),
            "Install the pdf2docx package.",
        ),
        _module_capability(
            CapabilityId.SPREADSHEET,
            "Spreadsheet export",
            ("openpyxl",),
            "Install openpyxl.",
        ),
    ]
    return {value.id: value for value in values}


def refresh_capabilities() -> dict[CapabilityId, Capability]:
    detect_capabilities.cache_clear()
    return detect_capabilities()
