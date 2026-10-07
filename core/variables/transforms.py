"""Explicit formatting operations; data values are never executable."""
from __future__ import annotations

import re
from datetime import datetime

from .model import VariableError


def apply_transform(value, transformation):
    name, args = transformation.name, transformation.arguments
    if name == "default":
        return args[0] if value is None or value == "" else value
    if value is None:
        return None
    if not isinstance(value, (str, int, float, bool, datetime)):
        raise VariableError("Variables must contain scalar values.")
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    if name in ("upper", "lower", "title", "capitalize"):
        return getattr(text, name)()
    if name == "trim":
        return text.strip()
    if name == "replace":
        return text.replace(*args)
    if name == "truncate":
        return text[:int(args[0])]
    if name == "pad":
        if not re.fullmatch(r"[+-]?[0-9]+", text):
            raise VariableError("Pad requires an ASCII integer.")
        width = int(args[0])
        if len(text) > width:
            raise VariableError(f"Value {text!r} does not fit {width} digits; it was not truncated.")
        return text.zfill(width)
    if name == "date":
        if re.search(r"%(?![aAbBcdHIjmMpSUwWxXyYZfzGVu])", args[0].replace("%%", "")):
            raise VariableError("Unsupported date format directive.")
        try:
            return datetime.fromisoformat(text).strftime(args[0])
        except ValueError as exc:
            raise VariableError("Date formatting requires an ISO date or datetime.") from exc
    raise VariableError(f"Unsupported transformation: {name}.")
