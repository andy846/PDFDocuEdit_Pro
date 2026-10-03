"""Portable detection profiles contain declarative rules, never scan data."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from composition.template.model import CompositionError
from core.io_atomic import atomic_output

from .detection import DetectionConfig


def save_profile(path, config):
    config.validate()
    if config.version != 2:
        raise CompositionError("Save a spatial detection profile after analysis or teaching.")
    target = Path(path).with_suffix(".pdmp")
    with atomic_output(target) as temporary:
        temporary.write_text(json.dumps({"profile_version": 1, "config": asdict(config)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def load_profile(path):
    target = Path(path)
    if target.stat().st_size > 256*1024:
        raise CompositionError("Detection profile is too large.")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"profile_version", "config"} or type(value["profile_version"]) is not int or value["profile_version"] != 1:
            raise CompositionError("Unsupported detection profile.")
        config = DetectionConfig(**value["config"])
        config.validate()
        if config.version != 2:
            raise CompositionError("Profile requires spatial detection version 2.")
        return asdict(config)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise CompositionError("Invalid detection profile.") from exc
