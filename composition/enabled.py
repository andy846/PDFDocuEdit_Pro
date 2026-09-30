"""Explicit opt-in during development; frozen builds carry their own flag."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def is_enabled() -> bool:
    override = os.environ.get("PDFDOCUEDIT_ENABLE_COMPOSITION")
    if override is not None:
        return override.lower() in {"1", "true", "yes", "on"}
    if getattr(sys, "frozen", False):
        config = Path(sys._MEIPASS) / "build_assets" / "composition" / "enabled.json"
        try:
            return json.loads(config.read_text(encoding="utf-8")).get("enabled") is True
        except (OSError, ValueError):
            return False
    return False
