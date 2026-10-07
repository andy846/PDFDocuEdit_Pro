"""Bounded tokenizer: no expression evaluation or attribute traversal."""
from __future__ import annotations

import re
from functools import lru_cache

from .model import CompiledTemplate, Token, Transform, VariableError

NAMESPACES = frozenset(("system", "input", "job", "batch", "workflow", "record", "envelope", "sheet", "production"))
LEGACY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SCOPED_NAME = re.compile(r"([a-z]+)\.((?:[^\W\d]|_)\w*)\Z")
ARITIES = {"upper": 0, "lower": 0, "trim": 0, "title": 0, "capitalize": 0,
           "replace": 2, "pad": 1, "truncate": 1, "default": 1, "date": 1}


def _split(value, separator):
    parts, current, quote, escaped = [], [], "", False
    for character in value:
        if escaped:
            if character not in ("\\", "\"", "'"):
                raise VariableError("Only escaped quotes and backslashes are supported.")
            current.append(character)
            escaped = False
        elif character == "\\" and quote:
            escaped = True
            current.append(character)
        elif quote:
            current.append(character)
            if character == quote:
                quote = ""
        elif character in ("'", '"'):
            quote = character
            current.append(character)
        elif character == separator:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quote or escaped:
        raise VariableError("Unterminated quoted variable argument.")
    parts.append("".join(current).strip())
    return parts


def _argument(value):
    if value.startswith(("'", '"')):
        if len(value) < 2 or value[-1] != value[0]:
            raise VariableError("Invalid quoted variable argument.")
        return re.sub(r"\\([\\\"'])", r"\1", value[1:-1])
    if not re.fullmatch(r"[0-9]{1,6}", value):
        raise VariableError("Text arguments must be quoted; widths must be positive integers.")
    return value


def _closing_braces(text, start):
    quote, escaped = "", False
    index = start
    while index < len(text):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\" and quote:
            escaped = True
        elif quote:
            if character == quote:
                quote = ""
        elif character in ("'", '"'):
            quote = character
        elif text.startswith("}}", index):
            return index
        index += 1
    return -1


@lru_cache(maxsize=512)
def _compile(text):
    tokens, position, references = [], 0, 0
    while position < len(text):
        start = text.find("{{", position)
        literal = text[position:] if start < 0 else text[position:start]
        if "}}" in literal:
            raise VariableError("Unexpected closing variable braces.")
        if literal:
            tokens.append(Token(literal=literal))
        if start < 0:
            break
        end = _closing_braces(text, start + 2)
        if end < 0:
            raise VariableError("Unclosed variable. Use {{Field_Name}} or {{namespace.field}}.")
        parts = _split(text[start + 2:end], "|")
        name = parts[0]
        scoped = SCOPED_NAME.fullmatch(name)
        if not LEGACY_NAME.fullmatch(name) and not (scoped and scoped[1] in NAMESPACES):
            raise VariableError(f"Invalid variable: {name!r}.")
        transforms = []
        for raw in parts[1:]:
            pieces = _split(raw, ":")
            operation = pieces[0]
            if operation not in ARITIES or len(pieces) - 1 != ARITIES[operation]:
                raise VariableError(f"Unsupported transformation or arguments: {raw!r}.")
            arguments = tuple(_argument(part) for part in pieces[1:])
            if operation in ("pad", "truncate") and (not arguments[0].isascii()
                    or not arguments[0].isdigit() or not 1 <= int(arguments[0]) <= 10000):
                raise VariableError("Variable width must be between 1 and 10,000.")
            if operation == "replace" and not arguments[0]:
                raise VariableError("Replace needs a non-empty search value.")
            transforms.append(Transform(operation, arguments))
        if len(transforms) > 16:
            raise VariableError("Use at most 16 transformations per variable.")
        tokens.append(Token(name=name, transforms=tuple(transforms)))
        references += 1
        if references > 1024:
            raise VariableError("Use at most 1,024 variable references.")
        position = end + 2
    return CompiledTemplate(text, tuple(tokens))


def compile_template(text):
    if not isinstance(text, str) or len(text) > 100_000:
        raise VariableError("Variable template must be text of at most 100,000 characters.")
    return _compile(text)
