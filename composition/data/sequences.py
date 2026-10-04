"""Stateless sequence values and bounded record sources; no GUI or mutable counters."""
from __future__ import annotations

import re
from dataclasses import asdict

from composition.template.model import CompositionError, SequenceSpec


def validate_sequences(template):
    if template.record_mode not in ("imported", "generated"):
        raise CompositionError("Choose imported data or generated records.")
    if type(template.generated_count) is not int or not 1 <= template.generated_count <= 1_000_000:
        raise CompositionError("Generated record quantity must be 1 to 1,000,000.")
    if not isinstance(template.sequences, list) or len(template.sequences) > 100:
        raise CompositionError("Use at most 100 running sequence fields.")
    names = set()
    for seq in template.sequences:
        if not isinstance(seq, SequenceSpec):
            raise CompositionError("Invalid sequence specification.")
        if not isinstance(seq.name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", seq.name):
            raise CompositionError("Sequence field names need 1–64 letters, digits or underscores; start with a letter or underscore.")
        if seq.name in names:
            raise CompositionError(f"Duplicate sequence field: {seq.name}")
        names.add(seq.name)
        for key in ("start", "step"):
            value = getattr(seq, key)
            if type(value) is not int or not -(10**18) <= value <= 10**18:
                raise CompositionError(f"Sequence {seq.name}: {key} must be an integer within ±10^18.")
        if seq.step == 0:
            raise CompositionError(f"Sequence {seq.name}: increment cannot be zero.")
        if type(seq.padding) is not int or not 0 <= seq.padding <= 32:
            raise CompositionError(f"Sequence {seq.name}: padding must be 0 to 32.")
        if seq.scope not in ("record", "page"):
            raise CompositionError(f"Sequence {seq.name}: choose per record or per output page.")
        for key in ("prefix", "suffix"):
            value = getattr(seq, key)
            if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
                raise CompositionError(f"Sequence {seq.name}: {key} must be printable text of at most 200 characters.")


def sequence_value(seq, ordinal, page_index=0, pages_per_record=1):
    if type(ordinal) is not int or ordinal < 1:
        raise CompositionError("Sequence record ordinal must be a positive integer.")
    if type(page_index) is not int or not 0 <= page_index < pages_per_record:
        raise CompositionError("Sequence template page index is out of range.")
    offset = ordinal - 1 if seq.scope == "record" else (ordinal - 1) * pages_per_record + page_index
    number = seq.start + offset * seq.step
    # Padding counts digits; a negative sign is preserved separately.
    digits = str(abs(number)).zfill(seq.padding)
    return seq.prefix + ("-" if number < 0 else "") + digits + seq.suffix


def sequence_record(template, record, ordinal, page_index=0, *, design=False):
    if not template.sequences:
        return record
    values = dict(record)
    physical_index=page_index
    physical_count=len(template.pages)
    if template.media.get("enabled"):
        from composition.media.planner import build_print_plan
        key=repr((template.media,[(p.id,p.width_mm,p.height_mm) for p in template.pages]))
        if getattr(template,"_media_sequence_key",None)!=key:
            plan=build_print_plan(template,1)
            template._media_sequence_offsets={p.logical_page-1:p.print_page-1 for p in plan.pages() if p.logical_page}
            template._media_sequence_count=plan.output_pages
            template._media_sequence_key=key
        physical_index=template._media_sequence_offsets[page_index]
        physical_count=template._media_sequence_count
    for seq in template.sequences:
        if not design and seq.name in record:
            raise CompositionError(f"Sequence field conflicts with supplied record: {seq.name}")
        values[seq.name] = ("{{" + seq.name + "}}" if design else
                            sequence_value(seq, ordinal, physical_index, physical_count))
    return values


def check_field_collisions(template, fields):
    collisions = {seq.name for seq in template.sequences} & set(fields)
    if collisions:
        raise CompositionError("Sequence fields conflict with imported fields: " + ", ".join(sorted(collisions))
                               + ". Rename the sequence; imported values will not be overwritten.")


class CompositionRecords:
    """Imported SQLite snapshot or virtual empty rows; repeated iteration is deterministic."""
    def __init__(self, template, store=None):
        self.template = template
        self.store = store if template.record_mode == "imported" else None
        store = self.store
        validate_sequences(template)
        if template.record_mode == "imported" and store is None:
            raise CompositionError("Import data or choose generated records in Running sequences.")
        source_fields = store.fields if store else []
        check_field_collisions(template, source_fields)
        self.fields = source_fields + [seq.name for seq in template.sequences]
        self.count = store.count if store else template.generated_count
        self.metadata = (dict(store.metadata) if store else {
            "source": {"path": "", "type": "generated_records", "record_count": self.count},
            "record_count": self.count, "original_fields": [],
        })
        self.metadata["fields"] = self.fields
        self.metadata["sequences"] = [asdict(seq) for seq in template.sequences]

    def record(self, ordinal):
        if type(ordinal) is not int or not 1 <= ordinal <= self.count:
            raise CompositionError(f"Record {ordinal} is out of range.")
        return self.store.record(ordinal) if self.store else {}

    def records(self):
        if self.store:
            yield from self.store.records()
        else:
            for ordinal in range(1, self.count + 1):
                yield ordinal, {}


def open_records(template, path=""):
    from composition.data.source import RecordStore
    return CompositionRecords(template, RecordStore(path) if template.record_mode == "imported" and path else None)
