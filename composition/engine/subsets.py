"""Collect used glyphs by streaming the snapshot, then subset each exact font once."""
from __future__ import annotations

import csv
import hashlib
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from composition.data.sequences import sequence_record

from .fallback import private_use
from .fonts import RecordFontError, permits_subsetting
from .glyphs import GlyphFonts
from .rules import ElementPlan, RecordRuleError


def prepare_subsets(template, tokens, fonts, records, directory, progress=None, is_cancelled=None,
                    *, repair_fonts=None, audit_path=None, summary=None, plans=None, rule_summary=None, selectors=None):
    repair_fonts = repair_fonts or {}
    summary = summary if summary is not None else {}
    summary.update(occurrences=0, records=0, automatic_occurrences=0, unresolved_occurrences=0,
                   unresolved_records=0, private_use_occurrences=0, checked_records=0, complete=False)
    all_elements = list(template.all_elements())
    plans = plans if plans is not None else {e.id: ElementPlan(e) for e in all_elements}
    rule_summary = rule_summary if rule_summary is not None else {}
    rule_summary.update(configured_objects=sum(plan.has_rules for plan in plans.values()), records_checked=0,
                        hidden_occurrences=0, alternate_occurrences=0, complete=False)
    elements = [element for element in all_elements
                if element.type == "text" or (element.type in {"code128", "i25"} and element.show_barcode_text)]
    page_numbers = {e.id: index+1 for index, page in enumerate(template.pages) for e in page.elements}
    pairs = list(fonts.values()) + [pair for mapping in repair_fonts.values() for pair in mapping.values()]
    original_paths = {str(path) for _font, path in pairs}
    glyphs = {path: set() for path in original_paths if permits_subsetting(Path(path))}
    selectors = selectors if selectors is not None else {e.id: GlyphFonts(fonts[e.id], repair_fonts.get(e.id), family=e.font.family) for e in elements}
    first_unresolved = None
    def csv_cell(value):
        return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
    with ExitStack() as resources:
        writer = None
        if audit_path:
            stream = resources.enter_context(Path(audit_path).open("w", encoding="utf-8-sig", newline=""))
            writer = csv.writer(stream)
            writer.writerow(["Record", "Object", "Fields", "Code point", "Occurrences",
                             "Primary font", "Repair font", "Template page", "Output page", "Character",
                             "Mode", "Font file", "Review note"])
        for ordinal, record in records:
            if is_cancelled and is_cancelled():
                from composition.template.model import CompositionError
                raise CompositionError("Production cancelled while preparing fonts.")
            repaired_record = False
            unresolved_record = False
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
                for character, count in Counter(text).items():
                    if character in "\r\n\t":
                        continue
                    key = f"U+{ord(character):04X}"
                    try:
                        face, source = selector.select(character)
                    except ValueError as exc:
                        error = RecordFontError(ordinal, element, fields,
                                                f"Template page {page_numbers[element.id]}: {exc}")
                        if selector.automatic is None:
                            raise error from exc
                        if is_cancelled and is_cancelled():
                            raise error from exc
                        first_unresolved = first_unresolved or (ordinal, element, fields, error)
                        unresolved_record = True
                        summary["unresolved_occurrences"] += count
                        face, source = None, None
                    if source is not None:
                        source_key = str(source)
                        if source_key not in glyphs and permits_subsetting(Path(source)):
                            glyphs[source_key] = set()
                        if source_key in glyphs:
                            glyphs[source_key].add(ord(character))
                        if source_key == str(fonts[element.id][1]):
                            continue
                        repaired_record = True
                        summary["occurrences"] += count
                        if private_use(ord(character)):
                            summary["private_use_occurrences"] += count
                        automatic = key not in element.glyph_repairs
                        summary["automatic_occurrences"] += count if automatic else 0
                        repair_name = face.name if automatic else element.glyph_repairs[key].family
                        mode = "Automatic" if automatic else "Explicit"
                    else:
                        repair_name, mode = "", "Unresolved"
                    if writer:
                        values = [ordinal, element.id, ", ".join(fields), key, count,
                                  element.font.family, repair_name, page_numbers[element.id],
                                  (ordinal-1)*len(template.pages)+page_numbers[element.id], character,
                                  mode, Path(source).name if source else "",
                                  "Private-use glyph; verify appearance" if private_use(ord(character)) else ""]
                        writer.writerow([csv_cell(value) for value in values])
            summary["records"] += int(repaired_record)
            rule_summary["records_checked"] += 1
            summary["checked_records"] += 1
            summary["unresolved_records"] += int(unresolved_record)
            if progress and ordinal % 500 == 0:
                progress(0, 0, f"Checking rules and exact font usage: record {ordinal:,}")
    rule_summary["complete"] = True
    summary["complete"] = True
    if first_unresolved is not None:
        ordinal, element, fields, error = first_unresolved
        raise RecordFontError(ordinal, element, fields,
                              f"Automatic font scan checked all {summary['checked_records']} records; "
                              f"{summary['unresolved_occurrences']} unresolved character occurrence(s) "
                              f"in {summary['unresolved_records']} record(s). Review the complete glyph-repairs.csv. "
                              f"First issue: {error}")
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
