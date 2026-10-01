"""Collect used glyphs by streaming the snapshot, then subset each exact font once."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from composition.template.model import resolve_value

from .fonts import RecordFontError, permits_subsetting, validate_glyphs


def prepare_subsets(template, tokens, fonts, records, directory, progress=None, is_cancelled=None):
    elements = [element for element in template.elements
                if element.type == "text" or (element.type == "code128" and element.show_barcode_text)]
    original_paths = {str(fonts[element.id][1]) for element in elements}
    glyphs = {path: set() for path in original_paths if permits_subsetting(Path(path))}
    checked = {path: set() for path in original_paths}
    for ordinal, record in records:
        if is_cancelled and is_cancelled():
            from composition.template.model import CompositionError
            raise CompositionError("Production cancelled while preparing fonts.")
        for element in elements:
            font, source = fonts[element.id]
            path = str(source)
            text = resolve_value(tokens[element.id], record)
            used = {ord(char) for char in text if char not in "\r\n\t"}
            unseen = used - checked[path]
            try:
                validate_glyphs(font, "".join(chr(code) for code in sorted(unseen)))
            except ValueError as exc:
                fields = [value for kind, value in tokens[element.id] if kind == "field"]
                raise RecordFontError(ordinal, element, fields, str(exc)) from exc
            checked[path].update(unseen)
            if path in glyphs:
                glyphs[path].update(used)
        if progress and ordinal % 500 == 0:
            progress(0, 0, f"Checking exact font usage: record {ordinal:,}")
    output = {}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for index, (source, used) in enumerate(glyphs.items()):
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
