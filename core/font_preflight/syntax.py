"""Bounded PDF object syntax reader for resource inspection (not a PDF engine)."""

import re
from dataclasses import dataclass

from .model import FontPreflightError


@dataclass(frozen=True)
class Ref:
    xref: int
    generation: int = 0


@dataclass(frozen=True)
class Name:
    value: str


class Reader:
    def __init__(self, value):
        if len(value) > 1024 * 1024:
            raise FontPreflightError("PDF object exceeds analysis limit.")
        self.text, self.pos, self.nodes = value, 0, 0

    def skip(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace() or self.text[self.pos] == "\x00":
                self.pos += 1
            elif self.text[self.pos] == "%":
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            else:
                break

    def value(self, depth=0):
        self.nodes += 1
        if depth > 64 or self.nodes > 50000:
            raise FontPreflightError("PDF object exceeds nesting/item limit.")
        self.skip()
        s, p = self.text, self.pos
        if p >= len(s):
            raise FontPreflightError("Incomplete PDF object.")
        if s.startswith("<<", p):
            self.pos += 2
            result = {}
            while True:
                self.skip()
                if s.startswith(">>", self.pos):
                    self.pos += 2
                    return result
                key = self.value(depth + 1)
                if not isinstance(key, Name) or key.value in result:
                    raise FontPreflightError("Invalid/duplicate PDF dictionary key.")
                result[key.value] = self.value(depth + 1)
        if s[p] == "[":
            self.pos += 1
            result = []
            while True:
                self.skip()
                if self.pos < len(s) and s[self.pos] == "]":
                    self.pos += 1
                    return result
                result.append(self.value(depth + 1))
        if s[p] == "/":
            match = re.match(r"/([^\s\x00()<>\[\]{}/%]*)", s[p:])
            self.pos += len(match[0])
            return Name(re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)), match[1]))
        if s[p] == "(":
            self.pos += 1
            nesting, result = 1, []
            while self.pos < len(s):
                char = s[self.pos]
                self.pos += 1
                if char == "\\":
                    if self.pos >= len(s):
                        break
                    escaped = s[self.pos]
                    self.pos += 1
                    if escaped in "01234567":
                        raw = escaped
                        for _ in range(2):
                            if self.pos < len(s) and s[self.pos] in "01234567":
                                raw += s[self.pos]
                                self.pos += 1
                        result.append(chr(int(raw, 8)))
                    elif escaped in "\r\n":
                        if escaped == "\r" and self.pos < len(s) and s[self.pos] == "\n":
                            self.pos += 1
                    else:
                        result.append(
                            {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(escaped, escaped)
                        )
                elif char == "(":
                    nesting += 1
                    result.append(char)
                elif char == ")":
                    nesting -= 1
                    if not nesting:
                        return "".join(result).encode("latin1")
                    result.append(char)
                else:
                    result.append(char)
            raise FontPreflightError("Unterminated PDF string.")
        if s[p] == "<":
            end = s.find(">", p + 1)
            if end < 0:
                raise FontPreflightError("Unterminated hex string.")
            self.pos = end + 1
            raw = re.sub(r"\s", "", s[p + 1 : end])
            try:
                return bytes.fromhex(raw + ("0" if len(raw) % 2 else ""))
            except ValueError as exc:
                raise FontPreflightError("Invalid hex string.") from exc
        match = re.match(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)", s[p:])
        if match:
            self.pos += len(match[0])
            number = float(match[0]) if "." in match[0] else int(match[0])
            saved = self.pos
            self.skip()
            ref = re.match(r"(\d+)\s+R(?=$|[\s<>\[\]/])", s[self.pos :])
            if isinstance(number, int) and ref:
                self.pos += len(ref[0])
                return Ref(number, int(ref[1]))
            self.pos = saved
            return number
        for token, value in (("true", True), ("false", False), ("null", None)):
            if s.startswith(token, p):
                self.pos += len(token)
                return value
        raise FontPreflightError("Unsupported PDF object syntax.")


def parse(value):
    reader = Reader(value)
    result = reader.value()
    reader.skip()
    if reader.pos != len(reader.text):
        raise FontPreflightError("Unexpected trailing PDF object data.")
    return result


def refs(value):
    if isinstance(value, Ref):
        yield value.xref
    elif isinstance(value, dict):
        for key, child in value.items():
            if key not in {"Parent", "P", "Pages"}:
                yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)
