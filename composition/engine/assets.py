"""Pinned production assets, resolved without importing Qt."""

from __future__ import annotations

from pathlib import Path

from composition.template.model import CompositionError


def asset_root() -> Path:
    from core.pdf_runtime import asset_root as shared_root
    return shared_root()


def qpdf_executable() -> Path:
    from core.pdf_runtime import qpdf_executable as shared_executable
    try:
        return shared_executable()
    except (RuntimeError, ValueError, KeyError) as exc:
        raise CompositionError(str(exc)) from exc
