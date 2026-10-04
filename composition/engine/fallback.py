"""Deterministic, cached fallback discovery; exact embeddable glyphs, no Qt."""
from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

from composition.template.model import CompositionError, FontSpec

from .fonts import load_font
from .system_fonts import export_face, font_catalogue


def private_use(point):
    return 0xE000 <= point <= 0xF8FF or 0xF0000 <= point <= 0xFFFFD or 0x100000 <= point <= 0x10FFFD


class AutoFallback:
    def __init__(self, directory, is_cancelled=None):
        self.directory = Path(directory)
        self.is_cancelled = is_cancelled
        self.cache = {}
        self.faces = None
        self.loaded = {}
        self.catalogue_errors = []

    def _check(self):
        if self.is_cancelled and self.is_cancelled():
            raise CompositionError("Production cancelled during automatic font discovery.")

    def select(self, character, primary):
        key = (ord(character), bool(primary.is_bold), bool(primary.is_italic))
        if key in self.cache:
            return self.cache[key]
        self._check()
        # Bundled exact fonts are portable and avoid scanning Windows for ordinary CJK.
        for family in ("Noto Sans CJK HK", "Noto Sans"):
            spec = FontSpec(family=family, bold=key[1])
            pair = load_font(spec)
            if pair[0].has_glyph(key[0], fallback=False):
                self.cache[key] = pair
                return pair
        if self.faces is None:
            inventory = font_catalogue(is_cancelled=self.is_cancelled)
            self.faces = [face for face in inventory["faces"] if face["usable"]]
        def rank(face):
            style = face["style"].casefold()
            bold = "bold" in style
            italic = "italic" in style or "oblique" in style
            preferred = 0 if private_use(key[0]) and face["family"] == "MingLiU_HKSCS" else 1
            return (preferred, bold != key[1], italic != key[2],
                    face["family"].casefold(), style, face["source"], face["index"])
        for face in sorted(self.faces, key=rank):
            self._check()
            try:
                with TTFont(face["source"], fontNumber=face["index"], lazy=True) as font:
                    if key[0] not in (font.getBestCmap() or {}):
                        continue
                face_key = (face["source"], face["index"], tuple(sorted(face["axes"].items())))
                if face_key not in self.loaded:
                    exact = export_face(face, self.directory)
                    self.loaded[face_key] = load_font(FontSpec(family=exact["family"], file=exact["file"]))
                pair = self.loaded[face_key]
                if pair[0].has_glyph(key[0], fallback=False):
                    self.cache[key] = pair
                    return pair
            except CompositionError as exc:
                self.catalogue_errors.append(str(exc))
            except (OSError, KeyError, ValueError):
                continue
        self.cache[key] = None
        return None
