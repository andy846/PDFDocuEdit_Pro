"""Declarative fixed-length barcode layouts and namespaced values; no Qt."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from composition.pdf_source.planner import SYSTEM_FIELDS
from composition.template.model import CompositionError, SequenceSpec

CONTEXT_KEY = "__BarcodeContext"


@dataclass
class BarcodeContext:
    data: dict = field(default_factory=dict)
    system: dict = field(default_factory=dict)
    sequences: dict = field(default_factory=dict)

    @classmethod
    def from_values(cls, values):
        if isinstance(values, cls):
            return values
        if isinstance(values.get(CONTEXT_KEY), cls):
            return values[CONTEXT_KEY]
        system = {k: v for k, v in values.items() if k in SYSTEM_FIELDS}
        system.update({k[9:]: v for k, v in values.items() if k.startswith("__Barcode") and k[9:] in SYSTEM_FIELDS})
        return cls({k: v for k, v in values.items() if not k.startswith("__Barcode")}, system)


@dataclass
class BarcodeSegment:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "New segment"
    length: int = 1
    source: str = "fixed"
    value: str = ""
    format: str = "text"
    overflow: str = "stop"
    start: int = 0
    step: int = 1
    scope: str = "record"

    def validate(self):
        if not isinstance(self.id, str) or not 1 <= len(self.id) <= 64:
            raise CompositionError("Barcode segment requires a stable ID.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise CompositionError("Give each barcode segment a name (1–200 characters).")
        if type(self.length) is not int or not 1 <= self.length <= 4096:
            raise CompositionError(f"Segment {self.name}: length must be 1–4,096.")
        if self.source not in {"fixed", "data", "system", "sequence"} or self.format not in {"numeric", "text"}:
            raise CompositionError(f"Segment {self.name}: invalid source or format.")
        if not isinstance(self.value, str) or len(self.value) > 4096:
            raise CompositionError(f"Segment {self.name}: invalid value/field.")
        if self.source in {"data", "system"} and not self.value:
            raise CompositionError(f"Segment {self.name}: choose a source field.")
        if self.source == "system" and self.value not in SYSTEM_FIELDS:
            raise CompositionError(f"Segment {self.name}: unknown system field {self.value}.")
        if self.overflow not in {"stop", "cycle"} or (self.overflow == "cycle" and
                (self.source != "sequence" or self.format != "numeric")):
            raise CompositionError(f"Segment {self.name}: cycling is available only for Numeric running sequences.")
        if self.source == "sequence" and not self.value:
            if self.scope not in {"record", "page", "sheet"}:
                raise CompositionError(f"Segment {self.name}: choose per record/envelope, output page or sheet in envelope.")
            if any(type(v) is not int or not 0 <= v <= 10**18 for v in (self.start, self.step)) or not self.step:
                raise CompositionError(f"Segment {self.name}: start must be nonnegative and increment must be positive (≤10^18).")


@dataclass
class SegmentValue:
    id: str
    name: str
    source: str
    position: int
    length: int
    raw: str
    formatted: str
    cycled: bool = False


@dataclass
class LayoutResult:
    payload: str
    segments: list[SegmentValue]


class SegmentError(CompositionError):
    def __init__(self, segment, reason):
        self.segment_id, self.segment_name = segment.id, segment.name
        self.source_field = segment.value
        super().__init__(f"Segment {segment.name} ({segment.source}: {segment.value or segment.scope}): {reason}")


def validate_layout(total, segments):
    if type(total) is not int or not 1 <= total <= 4096:
        raise CompositionError("Set Total length to 1–4,096 characters.")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 30:
        raise CompositionError("Add 1–30 barcode segments.")
    ids = set()
    for segment in segments:
        if not isinstance(segment, BarcodeSegment):
            raise CompositionError("Invalid barcode segment.")
        segment.validate()
        if segment.id in ids:
            raise CompositionError("Barcode segment IDs must be unique.")
        ids.add(segment.id)
    configured = sum(s.length for s in segments)
    if configured != total:
        raise CompositionError(f"Configured length {configured} does not match Total length {total}. Adjust segment lengths or Total length.")


def segment_value(segment, context):
    segment.validate()
    if segment.source == "fixed":
        raw = segment.value
    elif segment.source == "sequence" and not segment.value:
        from composition.data.sequences import sequence_value
        key = {"record": "EnvelopeIndex", "page": "OutputPage", "sheet": "SheetNo"}[segment.scope]
        ordinal = context.system.get(key, "")
        if not isinstance(ordinal, str) or not ordinal.isascii() or not ordinal.isdigit() or int(ordinal) < 1:
            raise SegmentError(segment, f"{key} is unavailable; load a record/page context.")
        raw = sequence_value(SequenceSpec(start=segment.start, step=segment.step, padding=0), int(ordinal))
    else:
        namespace = {"data": context.data, "system": context.system, "sequence": context.sequences}[segment.source]
        if segment.value not in namespace:
            raise SegmentError(segment, "Missing field. Check the source/mapping.")
        raw = namespace[segment.value]
    if not isinstance(raw, str) or not raw:
        raise SegmentError(segment, "Empty value; a fixed-length segment requires a value.")
    if segment.format == "text":
        if any(ord(c) < 32 for c in raw):
            raise SegmentError(segment, "Control characters are not supported.")
        if len(raw) != segment.length:
            raise SegmentError(segment, f"Text has {len(raw)} characters; exactly {segment.length} required. Content is retained without truncation or padding.")
        return raw, raw, False
    if not raw.isascii() or not raw.isdigit():
        raise SegmentError(segment, "Numeric requires nonnegative ASCII digits only; remove prefix/suffix or choose Text.")
    # Remove padding, never significant digits. Avoid arbitrary-size integer
    # conversion for data; only explicit sequence cycling needs modulo.
    number = raw.lstrip("0") or "0"
    cycled = len(number) > segment.length
    if cycled:
        if segment.overflow != "cycle":
            raise SegmentError(segment, f"Value {raw} needs {len(number)} digits; {segment.length} configured. Increase Length.")
        number = number[-segment.length:].lstrip("0") or "0"
    return raw, number.zfill(segment.length), cycled


def evaluate_layout(total, segments, values):
    validate_layout(total, segments)
    context = BarcodeContext.from_values(values)
    output, position = [], 1
    for segment in segments:
        raw, formatted, cycled = segment_value(segment, context)
        output.append(SegmentValue(segment.id, segment.name, segment.source, position, segment.length, raw, formatted, cycled))
        position += segment.length
    return LayoutResult("".join(s.formatted for s in output), output)
