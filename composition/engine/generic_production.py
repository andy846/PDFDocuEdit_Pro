"""Streamed fixed-layout preflight and explicit sequence-cycle evidence; no Qt."""
from __future__ import annotations

import csv
import sqlite3
from contextlib import ExitStack

from composition.data.sequences import sequence_record
from composition.template.geometry import element_bounds
from composition.template.model import MM_TO_PT

from .barcodes import validate_size
from .generic_layout import BarcodeContext
from .inserter_production import BarcodeRecordError
from .rules import ElementPlan


def has_fixed_layout(template):
    return any(e.barcode_profile.get("layout_mode") == "fixed" for e in template.all_elements())


class CycleAudit:
    def __init__(self, stream, source_row=None):
        self.writer = csv.writer(stream)
        self.source_row = source_row or (lambda ordinal: ordinal)
        self.count = 0
        self.writer.writerow(["Record ordinal", "Envelope", "Source page", "Output page", "Sheet", "Object",
                              "Segment ID", "Segment", "Raw sequence", "Encoded sequence", "Source row"])

    def write(self, element, profile, values, ordinal):
        from composition.production.generator import _csv_value
        context = BarcodeContext.from_values(values)
        for segment in profile.evaluate(values).segments:
            if segment.cycled:
                self.writer.writerow([_csv_value(v) for v in [ordinal, context.system.get("EnvelopeIndex", ordinal),
                    context.system.get("SourcePage", ""), context.system.get("OutputPage", ""),
                    context.system.get("SheetNo", ""), element.id, segment.id, segment.name, segment.raw, segment.formatted,
                    self.source_row(ordinal)]])
                self.count += 1


def mark_for(element, profile, values, payload=None):
    system = BarcodeContext.from_values(values).system
    return {"output_page": int(system["OutputPage"]), "source_page": system.get("SourcePage", ""),
            "envelope": int(system["EnvelopeIndex"]), "sheet": int(system["SheetNo"]),
            "object": element.id, "symbology": element.type, "profile": profile.name,
            "payload": payload if payload is not None else profile.payload(values), "layout": "fixed",
            "rotation_deg": element.rotation_deg, "rect": [v * MM_TO_PT for v in element_bounds(element)]}


def preflight(template, records, plan=None, is_cancelled=None, progress=None, *, audit_path=None, record_store=None):
    from composition.media.planner import build_print_plan
    from composition.production.generator import check_cancel
    if not has_fixed_layout(template):
        return 0
    plan = plan or build_print_plan(template, getattr(template, "_barcode_record_count",
        template.generated_count if template.record_mode == "generated" else 1), is_cancelled=is_cancelled)
    template._barcode_record_count = plan.envelopes
    targets = {e.id: ElementPlan(e) for e in template.all_elements() if e.barcode_profile.get("layout_mode") == "fixed"}
    pattern = [plan.page(1, p) for p in range(1, plan.settings_for(1).output_pages_per_envelope + 1)]
    total = 0
    with ExitStack() as resources:
        source_row = None
        if record_store and audit_path:
            db = sqlite3.connect(record_store)
            resources.callback(db.close)
            def source_row(ordinal):
                row = db.execute("SELECT source_row FROM records WHERE ordinal=?", (ordinal,)).fetchone()
                return row[0] if row else ""
        audit = CycleAudit(resources.enter_context(audit_path.open("w", encoding="utf-8-sig", newline="")), source_row) if audit_path else None
        for ordinal, record in records:
            check_cancel(is_cancelled)
            for page in pattern:
                if page.source_page is None:
                    continue
                values = sequence_record(template, record, ordinal, page.role)
                for element in template.pages[page.role].elements:
                    check_cancel(is_cancelled)
                    target = targets.get(element.id)
                    if target is None:
                        continue
                    try:
                        selected = target.resolve(values)
                        if not selected.visible:
                            continue
                        validate_size(element, selected.value)
                        if audit:
                            audit.write(element, target.profile, values, ordinal)
                        total += 1
                    except (ValueError, KeyError) as exc:
                        output = BarcodeContext.from_values(values).system.get("OutputPage", "")
                        error = BarcodeRecordError(ordinal, f"Template page {page.role+1}, output page {output}, object {element.id}: {exc}")
                        error.field = getattr(exc, "source_field", getattr(exc, "field", ""))
                        raise error from exc
            if progress and (ordinal % 100 == 0 or ordinal == plan.envelopes):
                progress(ordinal, plan.envelopes, "Checking Generic layouts, values and barcode dimensions")
    return total
