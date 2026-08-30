"""Inspect the PDF font span located under a page coordinate."""

from __future__ import annotations

import re
from collections.abc import Iterable

import fitz

from .system_fonts import is_pdf_base_font, resolve_system_font

_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_STYLE_SUFFIX = re.compile(
    r"(?:[-,](?:bold|italic|oblique|regular|roman|medium|light|black|semibold))+",
    re.IGNORECASE,
)


def remove_subset_prefix(name: str) -> tuple[str, bool]:
    """Return a readable PDF font name and whether it used a subset prefix."""

    value = str(name or "").strip().lstrip("/")
    subset = bool(_SUBSET_PREFIX.match(value))
    return _SUBSET_PREFIX.sub("", value), subset


def _normalise_font_name(name: str) -> str:
    clean, _subset = remove_subset_prefix(name)
    return re.sub(r"[^a-z0-9]+", "", clean.casefold())


def suggested_annotation_font(name: str) -> str:
    """Map common PDF/PostScript names to an annotation-compatible family."""

    clean, _subset = remove_subset_prefix(name)
    normalised = _normalise_font_name(clean)
    if normalised.startswith("helvetica"):
        return "Helv"
    if normalised in {"courier", "courierbold", "courieroblique"}:
        return "Cour"
    if normalised.startswith("timesroman") or normalised == "times":
        return "Times-Roman"

    family = _STYLE_SUFFIX.sub("", clean)
    family = re.sub(r"(?:PS)?MT$", "", family, flags=re.IGNORECASE)
    for compact, readable in (
        ("TimesNewRoman", "Times New Roman"),
        ("CourierNew", "Courier New"),
        ("ArialUnicodeMS", "Arial Unicode MS"),
    ):
        if family.casefold().startswith(compact.casefold()):
            family = readable
            break
    return family.strip(" -,") or clean or "Helv"


def _font_flags(flags: int) -> list[str]:
    labels = []
    for mask, label in (
        (1, "Superscript"),
        (2, "Italic"),
        (4, "Serif"),
        (8, "Monospaced"),
        (16, "Bold"),
    ):
        if flags & mask:
            labels.append(label)
    return labels


def _resource_for_span(page: fitz.Page, font_name: str) -> tuple | None:
    wanted = _normalise_font_name(font_name)
    candidates: Iterable[tuple] = page.get_fonts(full=True)
    for entry in candidates:
        names = (
            entry[3] if len(entry) > 3 else "",
            entry[4] if len(entry) > 4 else "",
        )
        if wanted and any(_normalise_font_name(value) == wanted for value in names):
            return entry
    return None


def _span_candidates(page: fitz.Page) -> list[dict]:
    spans: list[dict] = []
    for block in page.get_text("dict").get("blocks", []):
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []):
            spans.extend(
                span
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip() and span.get("bbox")
            )
    return spans


def inspect_font_at(page: fitz.Page, point: fitz.Point) -> dict[str, object] | None:
    """Return font metadata for the smallest text span under ``point``."""

    candidates = []
    for span in _span_candidates(page):
        rect = fitz.Rect(span["bbox"])
        if rect.contains(point):
            candidates.append((max(0.0, rect.get_area()), span, rect))
    if not candidates:
        # A few PDF producers report very tight glyph boxes. Permit a small
        # click tolerance without selecting an unrelated line of text.
        for span in _span_candidates(page):
            rect = fitz.Rect(span["bbox"])
            if (rect + (-3, -3, 3, 3)).contains(point):
                candidates.append((max(0.0, rect.get_area()), span, rect))
    if not candidates:
        return None

    _area, span, rect = min(candidates, key=lambda item: item[0])
    raw_name = str(span.get("font") or "Unknown")
    display_name, subset_from_span = remove_subset_prefix(raw_name)
    flags = int(span.get("flags") or 0)
    resource = _resource_for_span(page, raw_name)
    xref = int(resource[0]) if resource and resource[0] else 0
    extension = str(resource[1]) if resource and len(resource) > 1 else ""
    font_type = str(resource[2]) if resource and len(resource) > 2 else "Unknown"
    base_name = str(resource[3]) if resource and len(resource) > 3 else raw_name
    encoding = str(resource[5]) if resource and len(resource) > 5 else "Unknown"
    _base_clean, subset_from_resource = remove_subset_prefix(base_name)
    embedded = bool(xref and extension and extension.casefold() != "n/a")
    suggested = suggested_annotation_font(display_name)
    usable = is_pdf_base_font(suggested) or resolve_system_font(suggested) is not None
    color_value = int(span.get("color") or 0) & 0xFFFFFF
    alpha = max(0, min(255, int(span.get("alpha", 255))))

    return {
        "page": page.number,
        "text": str(span.get("text") or "").strip(),
        "raw_font": raw_name,
        "display_font": display_name,
        "suggested_font": suggested,
        "usable_for_annotations": usable,
        "size": float(span.get("size") or 0.0),
        "color": f"#{color_value:06x}",
        "alpha": alpha,
        "flags": flags,
        "styles": _font_flags(flags),
        "bold": bool(flags & 16),
        "italic": bool(flags & 2),
        "subset": subset_from_span or subset_from_resource,
        "embedded": embedded,
        "xref": xref,
        "font_type": font_type,
        "encoding": encoding,
        "bbox": tuple(float(value) for value in rect),
    }
