"""Application resource and user-data paths.

All bundled resources are resolved independently of the current working
directory. Writable files live below Qt's per-user application locations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

APP_NAME = "PDFDocuEdit Pro"
APP_SLUG = "PDFDocuEditPro"
APP_VERSION = "2.5.2"
COPYRIGHT_NOTICE = (
    "Copyright © 2026 Andy Leung. All rights reserved. "
    "PDFDocuEdit Pro is proprietary software. Unauthorized copying, "
    "modification, distribution, or commercial use of this software "
    "or its source code is prohibited."
)


def bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def _writable_location(kind: QStandardPaths.StandardLocation, fallback: str) -> Path:
    value = QStandardPaths.writableLocation(kind)
    path = Path(value) if value else Path.home() / fallback
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    path = config_dir_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir_path() -> Path:
    """Resolve the config directory without creating it.

    Read-only consumers (capability detection, settings reads) should not
    create directories on disk; only actual saves need ``config_dir``.
    """
    value = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(value) if value else Path.home() / f".config/{APP_SLUG}"


def cache_dir() -> Path:
    return _writable_location(
        QStandardPaths.StandardLocation.CacheLocation,
        f".cache/{APP_SLUG}",
    )


def data_dir() -> Path:
    return _writable_location(
        QStandardPaths.StandardLocation.AppLocalDataLocation,
        f".local/share/{APP_SLUG}",
    )


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_config_paths() -> list[Path]:
    """Return read-only locations used by historical portable builds."""
    candidates = [
        bundle_root() / "config.json",
        Path(sys.executable).resolve().parent / "config.json",
        Path.cwd() / "config.json",
    ]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def legacy_config_path() -> Path:
    """Compatibility accessor for older callers."""
    return legacy_config_paths()[0]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def normalize_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()
