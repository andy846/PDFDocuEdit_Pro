"""Explicit per-code-point repairs; the primary face always takes precedence."""
from __future__ import annotations

from itertools import groupby
from pathlib import Path

from composition.template.model import CompositionError


def codepoint(character):
    return f"U+{ord(character):04X}"


class GlyphFonts:
    def __init__(self, primary, repairs=None, *, family="", automatic=None):
        self.primary = primary
        self.family = family
        self.automatic = automatic
        self.repairs = repairs or {}
        self.cache = {}

    def select(self, character):
        if character in self.cache:
            return self.cache[character]
        font, _path = self.primary
        if character in "\r\n\t" or font.has_glyph(ord(character), fallback=False):
            selected = self.primary
        else:
            key = codepoint(character)
            selected = self.repairs.get(key)
            if selected is None and self.automatic is not None:
                selected = self.automatic.select(character, font)
            if selected is None:
                raise CompositionError(
                    f"Selected font cannot render {key} ({character}). "
                    f"Template font: {self.family or font.name}; PDF face: {font.name}; "
                    f"font file: {Path(self.primary[1]).name}. "
                    "Imported data supplies values only; its fonts are not used. "
                    "Review this object's selected font or configure an explicit missing-glyph repair "
                    "without changing the primary font."
                )
            if not selected[0].has_glyph(ord(character), fallback=False):
                raise CompositionError(f"Configured repair font cannot render {key} ({character}).")
        self.cache[character] = selected
        return selected

    def runs(self, text):
        if not self.repairs and self.automatic is None:
            for character in set(text):
                self.select(character)
            if text:
                yield text, self.primary[0], self.primary[1]
            return
        for _pair, characters in groupby(text, key=self.select):
            value = "".join(characters)
            font, source = self.select(value[0])
            yield value, font, source

    def text_length(self, text, fontsize):
        if not self.repairs and self.automatic is None:
            return self.primary[0].text_length(text, fontsize=fontsize)
        return sum(font.text_length(value, fontsize=fontsize) for value, font, _ in self.runs(text))

    def repaired_counts(self, text):
        if not self.repairs and self.automatic is None:
            return {}
        counts = {}
        primary = str(self.primary[1])
        for character in text:
            if str(self.select(character)[1]) != primary:
                key = codepoint(character)
                counts[key] = counts.get(key, 0) + 1
        return counts
