"""Resolve installed font families to files that can be embedded in PDFs."""

from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path

FONT_SUFFIXES = frozenset({".ttf", ".otf", ".ttc", ".otc"})
PDF_BASE_FONTS = frozenset({"helv", "cour", "times-roman"})


def is_pdf_base_font(family: str) -> bool:
    """Return whether *family* is one of the portable PDF built-in choices."""

    return str(family).strip().casefold() in PDF_BASE_FONTS


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _plain_family(value: str) -> str:
    value = re.sub(r"\s+\([^)]*(?:type|font)[^)]*\)\s*$", "", value, flags=re.I)
    return value.strip()


@lru_cache(maxsize=1)
def _windows_font_entries() -> tuple[tuple[str, Path], ...]:
    if sys.platform != "win32":
        return ()
    try:
        import winreg
    except ImportError:
        return ()

    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    entries: list[tuple[str, Path]] = []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for root, key_name in locations:
        try:
            with winreg.OpenKey(root, key_name) as key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    label, raw_path, _kind = winreg.EnumValue(key, index)
                    path = Path(os.path.expandvars(str(raw_path)))
                    if not path.is_absolute():
                        path = font_dir / path
                    if path.suffix.casefold() in FONT_SUFFIXES and path.is_file():
                        entries.append((_plain_family(str(label)), path))
        except OSError:
            continue
    return tuple(dict.fromkeys(entries))


@lru_cache(maxsize=1)
def _font_files() -> tuple[Path, ...]:
    """Return fallback font files for non-Windows systems and local installs."""

    if sys.platform == "darwin":
        roots = (
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        )
    elif sys.platform.startswith("linux"):
        roots = (
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
        )
    else:
        roots = ()
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            files.extend(
                path
                for path in root.rglob("*")
                if path.suffix.casefold() in FONT_SUFFIXES and path.is_file()
            )
        except OSError:
            continue
    return tuple(dict.fromkeys(files))


def _font_score(family: str, label: str, path: Path) -> tuple[int, int, int, str]:
    wanted = _normalise(family)
    candidate = _normalise(label)
    stem = _normalise(path.stem)
    exact = 0 if candidate == wanted else 1
    contains = 0 if wanted and (candidate.startswith(wanted) or stem.startswith(wanted)) else 1
    style_penalty = sum(
        token in candidate or token in stem
        for token in ("bold", "italic", "oblique", "light", "black", "semibold")
    )
    return exact, contains, style_penalty, str(path).casefold()


@lru_cache(maxsize=256)
def resolve_system_font(family: str) -> Path | None:
    """Resolve a system font family to an embeddable local font file.

    The result is cached because this function is called while committing text
    annotations. PDF Base-14 names deliberately return ``None``.
    """

    family = str(family).strip()
    if not family or is_pdf_base_font(family):
        return None
    entries = list(_windows_font_entries())
    if entries:
        candidates = [
            entry
            for entry in entries
            if _normalise(family) in _normalise(entry[0])
            or _normalise(family) in _normalise(entry[1].stem)
        ]
        if candidates:
            return min(candidates, key=lambda entry: _font_score(family, *entry))[1]

    files = [
        path for path in _font_files() if _normalise(family) in _normalise(path.stem)
    ]
    if files:
        return min(files, key=lambda path: _font_score(family, path.stem, path))
    return None
