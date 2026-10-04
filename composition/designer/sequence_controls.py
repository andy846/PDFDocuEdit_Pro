"""Designer integration for sequences; no production counter state."""
from __future__ import annotations

from dataclasses import asdict

from composition.data.sequences import check_field_collisions, sequence_record
from composition.template.model import CompositionError, Template, required_fields


class SequenceOperations:
    def _sequence_info(self, raw):
        if self.template.record_mode == "imported" and not raw:
            return None
        if not self.template.sequences and self.template.record_mode == "imported":
            return raw
        key = (self._config_key(), id(raw), self.template.record_mode, self.template.generated_count,
               repr([asdict(seq) for seq in self.template.sequences]), len(self.template.pages))
        if getattr(self, "_sequence_cache_key", None) == key:
            return self._sequence_cache
        generated = self.template.record_mode == "generated"
        base = [] if generated else raw["metadata"]["fields"]
        try:
            check_field_collisions(self.template, base)
        except CompositionError as exc:
            self.message.setText(str(exc))
            return None
        count = self.template.generated_count if generated else raw["metadata"]["record_count"]
        names = [seq.name for seq in self.template.sequences]
        samples = [{} for _ in range(min(5, count))] if generated else raw["sample"]
        info = {
            "store": "" if generated else raw["store"],
            "metadata": {"record_count": count, "fields": base + names,
                         "original_fields": ([] if generated else raw["metadata"]["original_fields"]) + names},
            "sample": [sequence_record(self.template, row, i+1) for i, row in enumerate(samples)],
        }
        self._sequence_cache_key, self._sequence_cache = key, info
        return info

    def edit_sequences(self):
        self.properties.apply()
        if self.content_invalid or self.import_worker or self.production_worker or self.font_requests:
            self._error("Finish the active edit/job before configuring running sequences.")
            return
        from .sequence_dialog import SequenceDialog
        raw = self.stores.get(self._config_key()) or {}
        metadata = raw.get("metadata", {})
        dialog = SequenceDialog(self.template, metadata.get("fields", []), metadata.get("record_count", 0), self)
        if dialog.exec() and dialog.choice:
            self.apply_sequences(dialog.choice.sequences, dialog.choice.record_mode, dialog.choice.generated_count)

    def apply_sequences(self, sequences, mode, count):
        if self.content_invalid or self.import_worker or self.production_worker or self.font_requests:
            return False
        before, after = self.template.to_dict(), self.template.to_dict()
        after.update(sequences=[asdict(seq) for seq in sequences], record_mode=mode, generated_count=count)
        try:
            candidate = Template.from_dict(after)
            raw = self.stores.get(self._config_key())
            fields = raw["metadata"]["fields"] if raw and mode == "imported" else []
            check_field_collisions(candidate, fields)
            removed = {seq.name for seq in self.template.sequences} - {seq.name for seq in sequences}
            used = removed & required_fields(candidate) - set(fields)
            if used:
                raise CompositionError("Sequence fields are still used by text/barcodes/rules: " + ", ".join(sorted(used))
                                       + ". Update those objects before removing or renaming the fields.")
        except CompositionError as exc:
            self._error(str(exc))
            return False
        self._commit(before, after, "Configure running sequences")
        self.message.setText("Sequence fields updated. Drag a field onto the page, then Preview records.")
        return True
