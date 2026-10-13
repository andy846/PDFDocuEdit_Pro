"""Headless identifier and containment checks before output filesystem operations."""
from __future__ import annotations

import re
import stat
from pathlib import Path

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def validate_identifier(value, *, limit=80, label="job"):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1," + str(limit) + "}", value)
            or value.upper() in _RESERVED):
        raise ValueError(f"Invalid {label} identity.")
    return value


def contained_path(root, *components):
    """The selected root is trusted; descendants must not redirect through links."""
    root = Path(root).resolve()
    current = root
    for value in components:
        if not isinstance(value, str) or value in ("", ".", "..") or any(c in value for c in '/\\:'):
            raise ValueError("Invalid production output component.")
        current = current / value
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Production output may not traverse a symlink or junction.")
    result = current.resolve()
    if not result.is_relative_to(root):
        raise ValueError("Production output escaped the selected directory.")
    return result
