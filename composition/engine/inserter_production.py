"""Streamed template control-barcode preflight and final-PDF reconciliation."""
from __future__ import annotations

import csv
import json

import fitz

from composition.data.sequences import sequence_record
from composition.overlay.qc import check_mark
from composition.production.generator import _csv_value, check_cancel
from composition.template.geometry import element_bounds
from composition.template.model import MM_TO_PT, CompositionError

from .barcode_profiles import INSERTER_I25, profile_values
from .rules import ElementPlan


class BarcodeRecordError(CompositionError):
    def __init__(self, ordinal, reason):
        self.record_ordinal = ordinal
        super().__init__(f"Barcode preflight: Record {ordinal}: {reason}")


def mark_for(element, profile, fields):
    parts = profile.inserter_parts(fields)
    return {"output_page": int(fields["OutputPage"]), "source_page": "", "envelope": int(fields["EnvelopeIndex"]),
            "sheet": int(fields["SheetNo"]), "object": element.id, "symbology": "i25", "profile": profile.name,
            "payload": parts["payload"], "parts": parts, "rect": [v*MM_TO_PT for v in element_bounds(element)]}


def validate_size(element, payload):
    from barcode import ITF
    modules = len(ITF(payload, narrow=1, wide=3).build()[0])+20
    if element.width_mm/modules+.001/MM_TO_PT < element.barcode_module_mm:
        raise CompositionError("I25 box is too narrow for its minimum module size.")
    if element.show_barcode_text and element.height_mm-element.font.size_pt*1.6/MM_TO_PT < 5:
        raise CompositionError("I25 is too short for the bars and readable text.")


def preflight(template, records, plan, is_cancelled=None, progress=None):
    plans = {e.id: ElementPlan(e) for e in template.all_elements() if e.barcode_profile}
    pattern = list(plan.pages()) if plan.envelopes == 1 else [plan.page(1, p) for p in range(1, plan.settings_for(1).output_pages_per_envelope+1)]
    total = 0
    for ordinal, record in records:
        check_cancel(is_cancelled)
        try:
            for page in pattern:
                if page.source_page is None or page.fields()["Side"] != "Front":
                    continue
                controls = []
                values = sequence_record(template, record, ordinal, page.role)
                for element in template.pages[page.role].elements:
                    target = plans.get(element.id)
                    if target is None or target.profile.preset != INSERTER_I25:
                        continue
                    try:
                        selected = target.resolve(values)
                        if selected.visible:
                            validate_size(element, selected.value)
                            controls.append(element)
                    except ValueError as exc:
                        raise CompositionError(f"Template page {page.role+1}, output page {profile_values(values)['OutputPage']}, object {element.id}: {exc}") from exc
                if len(controls) != 1:
                    raise CompositionError(f"Template page {page.role+1}, sheet {page.fields()['SheetNo']}: required exactly one visible inserter barcode; found {len(controls)}.")
                total += 1
        except ValueError as exc:
            raise BarcodeRecordError(ordinal, exc) from exc
        if progress and ordinal % 100 == 0:
            progress(ordinal, plan.envelopes, "Checking inserter barcodes and sheet positions")
    return total


def audit_pdf(pdf, marks_path, csv_path, *, is_cancelled=None, progress=None, expected=None):
    count = 0
    columns = ["Envelope", "Sheet", "Output page", "Object", "Profile", "Payload", "Group sequence",
               "Inserts 1-3", "Inserts 4-6", "EOG", "Check digit", "QC", "Sheet sequence", "Symbology", "Source page"]
    with fitz.open(pdf) as document, marks_path.open(encoding="utf-8") as stream, csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(columns)
        for line in stream:
            check_cancel(is_cancelled)
            mark = json.loads(line)
            try:
                check_mark(document[mark["output_page"]-1], mark)
            except ValueError as exc:
                raise BarcodeRecordError(mark["envelope"], f"Output page {mark['output_page']}, object {mark['object']}: {exc}") from exc
            parts = mark.get("parts", {})
            writer.writerow([mark["envelope"], mark["sheet"], mark["output_page"], _csv_value(mark["object"]), _csv_value(mark["profile"]),
                             mark["payload"], parts.get("group", ""), parts.get("inserts_1_3", ""), parts.get("inserts_4_6", ""), parts.get("eog", ""), parts.get("check_digit", ""), "Decoded: exact match", parts.get("sheet", ""), mark["symbology"], mark.get("source_page", "")])
            count += 1
            if progress and count % 100 == 0:
                progress(count, expected or count, "Decoding final production barcodes")
    if expected is not None and count != expected:
        raise CompositionError("RECONCILIATION FAILED: expected/rendered/decoded inserter barcodes do not agree.")
    return count
