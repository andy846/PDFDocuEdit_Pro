"""Exact font resolution and glyph/embedding checks; no implicit substitution."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import fitz
from fontTools.ttLib import TTFont

from composition.template.model import CompositionError, FontSpec

from .assets import asset_root

FAMILIES = ("Noto Sans", "Noto Sans CJK HK")


def resolve_font(spec: FontSpec) -> Path:
    if spec.file:
        if spec.bold or spec.italic:
            raise CompositionError("Custom fonts use their exact selected face. Choose the actual bold/italic file.")
        return Path(spec.file).expanduser().resolve()
    if spec.family == "Noto Sans":
        style = ("BoldItalic" if spec.bold and spec.italic else
                 "Bold" if spec.bold else "Italic" if spec.italic else "Regular")
        filename = f"NotoSans-{style}.ttf"
    elif spec.family == "Noto Sans CJK HK":
        if spec.italic:
            raise CompositionError("Noto Sans CJK HK has no italic face. Select an actual italic font file.")
        filename = f"NotoSansCJKhk-{'Bold' if spec.bold else 'Regular'}.otf"
    else:
        raise CompositionError(f"Missing font: {spec.family}. Locate its TTF/OTF font file.")
    return asset_root() / "fonts" / filename


@lru_cache(maxsize=32)
def _open_font(path: str, size: int, mtime: int) -> fitz.Font:
    del size, mtime
    source = Path(path)
    try:
        with TTFont(source, lazy=True) as metadata:
            restrictions = int(getattr(metadata.get("OS/2"), "fsType", 0))
            # Restricted-license embedding and bitmap-only embedding are unsupported.
            if restrictions & (0x0002 | 0x0200):
                raise CompositionError(f"Font does not permit outline embedding: {source.name}")
        return fitz.Font(fontfile=str(source))
    except CompositionError:
        raise
    except Exception as exc:
        raise CompositionError(f"Unable to read font {source.name}: {exc}") from exc


def load_font(spec: FontSpec) -> tuple[fitz.Font, Path]:
    path = resolve_font(spec)
    if not path.is_file():
        raise CompositionError(f"Missing output font: {path.name}. Locate the font or prepare Composition assets.")
    if path.stat().st_size > 64 * 1024 * 1024:
        raise CompositionError("The font file is larger than 64 MB.")
    stat = path.stat()
    return _open_font(str(path), stat.st_size, stat.st_mtime_ns), path


def validate_glyphs(font: fitz.Font, text: str) -> None:
    for character in set(text):
        if character in "\r\n\t":
            continue
        if not font.has_glyph(ord(character), fallback=False):
            raise CompositionError(
                f"Selected font cannot render U+{ord(character):04X} ({character}). Select a font with that glyph."
            )


def permits_subsetting(path: Path) -> bool:
    with TTFont(path, lazy=True) as metadata:
        return not int(getattr(metadata.get("OS/2"), "fsType", 0)) & 0x0100
