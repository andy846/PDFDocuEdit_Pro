"""Windows-safe components and collision planning, without altering source data."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .model import ResolvedValue, VariableError
from .resolver import resolve

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = re.compile(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z")


def validate_filename(name, *, extension=None):
    if (not isinstance(name, str) or not name or len(name.encode("utf-16-le")) // 2 > 160
            or INVALID.search(name) or name.rstrip(" .") != name
            or name in (".", "..") or RESERVED.fullmatch(name)
            or (extension and (not name.lower().endswith(extension.lower())
                               or name[:-len(extension)] in ("", ".")))):
        raise VariableError("Output needs a valid filename, without folders or reserved characters (maximum 160 characters).")
    return name


def resolve_filename(template, context, *, extension=None):
    result = resolve(template, context)
    original = result.value
    if not original.strip(" ."):
        raise VariableError("Output filename resolved to an empty value.")
    # Variables are components, not a route to another directory.
    if original in (".", ".."):
        raise VariableError("Output filename cannot be a relative directory.")
    name = INVALID.sub("_", original).rstrip(" .")
    if RESERVED.fullmatch(name):
        name = "_" + name
    if len(name.encode("utf-16-le")) // 2 > 160:
        suffix = Path(name).suffix
        if len(suffix) > 16:
            suffix = ""
        stem = name[:-len(suffix)] if suffix else name
        tail = "_" + hashlib.sha256(original.encode()).hexdigest()[:10] + suffix
        budget = 160 - len(tail.encode("utf-16-le")) // 2
        # Bounded UTF-16 slicing avoids repeatedly encoding a long imported
        # value. Dropping a cut surrogate keeps astral Unicode characters valid.
        stem = stem.encode("utf-16-le")[:budget * 2].decode("utf-16-le", errors="ignore")
        name = stem + tail
    validate_filename(name, extension=extension)
    issues = result.issues + ((f"Filename sanitised: {original!r} → {name!r}",) if name != original else ())
    return ResolvedValue(name, result.dependencies, issues)


def plan_outputs(items, template, output_dir, *, extension=".pdf", sources=()):
    root = Path(output_dir).expanduser().resolve()
    source_keys = {str(Path(p).expanduser().resolve()).casefold() for p in sources}
    planned, used = [], set()
    for context in items:
        resolved = resolve_filename(template, context, extension=extension)
        target = root / resolved.value
        key = str(target).casefold()
        if key in used:
            raise VariableError(f"Duplicate output filename: {resolved.value}")
        if key in source_keys:
            raise VariableError(f"Output cannot replace its source: {target}")
        if target.exists():
            raise VariableError(f"Output already exists: {target}")
        if len(str(target).encode("utf-16-le")) // 2 > 240:
            raise VariableError(f"Output path is too long; choose a shorter folder: {target}")
        used.add(key)
        planned.append((target, resolved))
    return planned
