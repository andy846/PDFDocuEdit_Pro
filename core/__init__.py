"""Core services with lazy public exports.

Importing a headless submodule must not initialize editor models or Qt.
The existing from-core-import-PdfEngine interface remains available.
"""
from __future__ import annotations

from importlib import import_module

__all__ = ["PdfEngine", "RecentFilesManager", "SettingsManager", "parse_page_range"]
_EXPORTS = {
    "PdfEngine": ".pdf_engine",
    "parse_page_range": ".pdf_engine",
    "RecentFilesManager": ".settings",
    "SettingsManager": ".settings",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
