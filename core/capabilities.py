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

from .ocr_language import OCR_LANGUAGE, normalize_ocr_language
from .platform_service import PlatformService
from .settings import SettingsManager


class CapabilityId(StrEnum):
    OFFICE_TO_PDF = "office_to_pdf"
    POSTSCRIPT = "postscript"
    BARCODE = "barcode"
    VERAPDF = "verapdf"
    OCR = "ocr"
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


def bundled_tesseract_runtime() -> tuple[Path | None, Path | None, str]:
    """Return the bundled Windows x64 Tesseract executable and tessdata."""
    if platform.system() == "Darwin":
        return None, None, "OCR is not bundled in the macOS build."
    if platform.system() != "Windows":
        return None, None, "OCR is currently supported only on Windows x64."
    if platform.machine().casefold() not in {"amd64", "x86_64"}:
        return None, None, "OCR requires a Windows x64 build."
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            roots.append(Path(base) / "tesseract")
        roots.append(Path(sys.executable).resolve().parent / "tesseract")
    else:
        roots.append(Path(__file__).resolve().parent.parent / "Tesseract")
    missing_by_root: list[str] = []
    required = (
        Path("tesseract.exe"),
        *(Path(f"tessdata/{language}.traineddata")
          for language in normalize_ocr_language(OCR_LANGUAGE).split("+")),
        Path("tessdata/configs/pdf"),
    )
    for root in roots:
        missing = [str(item) for item in required if not (root / item).is_file()]
        if not missing:
            return root / "tesseract.exe", root / "tessdata", ""
        missing_by_root = missing
    detail = ", ".join(missing_by_root) if missing_by_root else "Tesseract directory"
    return None, None, f"Bundled OCR assets are incomplete: {detail}."


def _ocr_capability() -> Capability:
    executable, tessdata, reason = bundled_tesseract_runtime()
    return Capability(
        CapabilityId.OCR,
        "OCR",
        executable is not None,
        "Bundled Tesseract 5.5.3" if executable else "",
        str(executable) if executable else "",
        reason,
        (
            "Install the complete Tesseract 5.5.3 runtime under the bundled "
            "tesseract folder, including eng and chi_tra language data."
            if executable is None
            else f"Language data: {tessdata}"
        ),
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


def _verapdf_capability() -> Capability:
    from .verapdf import find_verapdf_runtime

    runtime = find_verapdf_runtime(_configured_executable("verapdf_path"))
    launcher = runtime.launcher if runtime else ""
    backend = runtime.backend if runtime else ""
    return Capability(
        CapabilityId.VERAPDF,
        "PDF/A and PDF/UA validation",
        bool(launcher),
        backend,
        launcher or "",
        "The offline veraPDF runtime was not found." if not launcher else "",
        (
            "Install the pinned veraPDF runtime or configure its launcher in Settings."
            if not launcher
            else "PDF/UA reports machine-verifiable checks."
        ),
    )



@lru_cache(maxsize=1)
def detect_capabilities() -> dict[CapabilityId, Capability]:
    values = [
        _office_capability(),
        _postscript_capability(),
        _barcode_capability(),
        _ocr_capability(),
        _verapdf_capability(),
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
