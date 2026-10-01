"""Fixed envelope settings and source identity; independent of template records."""
from __future__ import annotations

from dataclasses import dataclass, field

from composition.template.model import CompositionError


@dataclass
class EnvelopeSettings:
    pages_per_envelope: int = 3
    duplex: bool = False
    start: int = 1
    increment: int = 1
    digits: int = 6
    prefix: str = ""
    suffix: str = ""

    def validate(self):
        for key, low, high in (("pages_per_envelope", 1, 100), ("start", 0, 10**18-1),
                               ("increment", 1, 10**18-1), ("digits", 1, 18)):
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise CompositionError(f"{key} must be an integer from {low} to {high}.")
        if type(self.duplex) is not bool:
            raise CompositionError("Duplex must be explicitly enabled or disabled.")
        for value in (self.prefix, self.suffix):
            if not isinstance(value, str) or len(value) > 100 or any(ord(c) < 32 for c in value):
                raise CompositionError("Sequence prefix/suffix must be printable text, at most 100 characters.")

    @property
    def output_pages_per_envelope(self):
        return self.pages_per_envelope + int(self.duplex and self.pages_per_envelope % 2 == 1)

    @property
    def sheets_per_envelope(self):
        return self.output_pages_per_envelope // 2 if self.duplex else self.pages_per_envelope

    def sequence(self, index):
        value = self.start + (index-1)*self.increment
        if len(str(value)) > self.digits:
            raise CompositionError(f"Envelope {index}: sequence {value} exceeds {self.digits} digits.")
        return self.prefix + str(value).zfill(self.digits) + self.suffix


@dataclass
class SourceInfo:
    path: str
    sha256: str
    size: int
    mtime_ns: int
    pages: int
    geometries: list[dict]
    warnings: list[str] = field(default_factory=list)
