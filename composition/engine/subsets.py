"""Collect used glyphs by streaming the snapshot, then subset each exact font once."""
from __future__ import annotations

import csv
import hashlib
from contextlib import ExitStack
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from composition.data.sequences import sequence_record

from .fonts import RecordFontError, permits_subsetting
from .glyphs import GlyphFonts
from .rules import ElementPlan, RecordRuleError


def prepare_subsets(template, tokens, fonts, records, directory, progress=None, is_cancelled=None,
                    *, repair_fonts=None, audit_path=None, summary=None, plans=None, rule_summary=None):
    repair_fonts = repair_fonts or {}
    summary = summary if summary is not None else {}
    summary.update(occurrences=0, records=0)
    all_elements = list(template.all_elements())
    plans = plans if plans is not None else {e.id: ElementPlan(e) for e in all_elements}
    rule_summary = rule_summary if rule_summary is not None else {}
    rule_summary.update(configured_objects=sum(plan.has_rules for plan in plans.values()), records_checked=0,
                        hidden_occurrences=0, alternate_occurrences=0, complete=False)
    elements = [element for element in all_elements
                if element.type == "text" or (element.type == "code128" and element.show_barcode_text)]
    page_numbers = {e.id: index+1 for index, page in enumerate(template.pages) for e in page.elements}
    pairs = list(fonts.values()) + [pair for mapping in repair_fonts.values() for pair in mapping.values()]
    original_paths = {str(path) for _font, path in pairs}
    glyphs = {path: set() for path in original_paths if permits_subsetting(Path(path))}
    selectors = {e.id: GlyphFonts(fonts[e.id], repair_fonts.get(e.id), family=e.font.family) for e in elements}
    with ExitStack() as resources:
        writer = None
        if audit_path:
            stream = resources.enter_context(Path(audit_path).open("w", encoding="utf-8-sig", newline=""))
            writer = csv.writer(stream)
            writer.writerow(["Record", "Object", "Fields", "Code point", "Occurrences",
                             "Primary font", "Repair font", "Template page"])
        for ordinal, record in records:
            if is_cancelled and is_cancelled():
                from composition.template.model import CompositionError
                raise CompositionError("Production cancelled while preparing fonts.")
            repaired_record = False
            page_records = [sequence_record(template, record, ordinal, i) for i in range(len(template.pages))]
            for element in all_elements:
                plan = plans[element.id]
                try:
                    selected = plan.resolve(page_records[page_numbers[element.id]-1])
                except ValueError as exc:
                    raise RecordRuleError(ordinal, element, page_numbers[element.id], exc) from exc
                rule_summary["hidden_occurrences"] += int(not selected.visible)
                rule_summary["alternate_occurrences"] += int(selected.alternative)
                if not selected.visible or element.id not in selectors:
                    continue
                text = selected.value
                selector = selectors[element.id]
                fields = plan.selected_fields(selected.alternative)
                try:
                    for character in set(text) - set("\r\n\t"):
                        _font, source = selector.select(character)
                        if str(source) in glyphs:
                            glyphs[str(source)].add(ord(character))
                    counts = selector.repaired_counts(text)
                except ValueError as exc:
                    raise RecordFontError(ordinal, element, fields,
                                          f"Template page {page_numbers[element.id]}: {exc}") from exc
                for key, count in counts.items():
                    repaired_record = True
                    summary["occurrences"] += count
                    if writer:
                        values = [ordinal, element.id, ", ".join(fields), key, count,
                                  element.font.family, element.glyph_repairs[key].family, page_numbers[element.id]]
                        writer.writerow(["'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                                         else v for v in values])
            summary["records"] += int(repaired_record)
            rule_summary["records_checked"] += 1
            if progress and ordinal % 500 == 0:
                progress(0, 0, f"Checking rules and exact font usage: record {ordinal:,}")
    rule_summary["complete"] = True
    output = {}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for index, (source, used) in enumerate(glyphs.items()):
        if not used:
            continue
        if is_cancelled and is_cancelled():
            from composition.template.model import CompositionError
            raise CompositionError("Production cancelled while preparing fonts.")
        options = subset.Options()
        options.recalc_timestamp = False
        # CID-keyed CFF fonts require original glyph IDs for MuPDF's Identity encoding.
        options.retain_gids = True
        options.layout_features = ["*"]
        options.notdef_outline = True
        options.name_IDs = [0, 1, 2, 3, 4, 5, 6]
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=used)
        target = directory / f"font-{index}{Path(source).suffix}"
        with TTFont(source, recalcTimestamp=False) as font:
            subsetter.subset(font)
            # PDF subset names identify the derivative without replacing the selected face.
            digest = hashlib.sha256((source + repr(sorted(used))).encode("utf-8")).hexdigest()
            prefix = "".join(chr(ord("A")+int(char, 16)) for char in digest[:6]) + "+"
            if "name" in font:
                for entry in font["name"].names:
                    if entry.nameID == 6:
                        entry.string = (prefix + entry.toUnicode()).encode(entry.getEncoding())
            if "CFF " in font:
                cff = font["CFF "].cff
                cff.fontNames[0] = prefix + cff.fontNames[0]
            font.save(target)
        output[source] = target
    return output
