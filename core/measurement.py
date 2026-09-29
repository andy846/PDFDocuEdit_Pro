"""Physical distances on a PDF page, expressed in metric units."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import hypot, isfinite

import fitz

POINT_TO_MM = 25.4 / 72.0
SCALE_KEY = "PDFDocuEditScale"
MEASUREMENT_KEY = "PDFDocuEditMeasurement"
SCHEMA = 1


@dataclass(frozen=True)
class PageScale:
    real_per_paper: float = 1.0
    state: str = "paper"  # paper, calibrated, invalid


@dataclass(frozen=True)
class SavedMeasurement:
    identifier: str
    line_xref: int
    label_xref: int
    points: tuple[tuple[float, float], tuple[float, float]]
    unit: str
    saved_scale: float


def valid_factor(value: object) -> float:
    if type(value) not in {int, float}:
        raise ValueError("Calibration must be a positive finite number")
    factor = float(value)
    if not isfinite(factor) or factor <= 0:
        raise ValueError("Calibration must be a positive finite number")
    return factor


def calibrated_factor(start: tuple[float, float], end: tuple[float, float],
                      known_mm: float) -> float:
    paper_mm = distance_mm(start, end)
    if paper_mm <= 0:
        raise ValueError("Calibration reference must have a nonzero length")
    return valid_factor(valid_factor(known_mm) / paper_mm)


def page_scale(page: fitz.Page) -> PageScale:
    kind, value = page.parent.xref_get_key(page.xref, SCALE_KEY)
    if kind == "null":
        return PageScale()
    try:
        payload = json.loads(value) if kind == "string" else None
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError("Unknown calibration schema")
        return PageScale(valid_factor(payload["realPerPaper"]), "calibrated")
    except (ValueError, TypeError, KeyError, OverflowError):
        return PageScale(1.0, "invalid")


def set_page_scale(page: fitz.Page, factor: float | None) -> None:
    if factor is None:
        page.parent.xref_set_key(page.xref, SCALE_KEY, "null")
    else:
        payload = json.dumps({"schema": SCHEMA, "realPerPaper": valid_factor(factor)})
        page.parent.xref_set_key(page.xref, SCALE_KEY, fitz.get_pdf_str(payload))


def copy_page_scale(source: fitz.Page, destination: fitz.Page) -> None:
    """insert_pdf copies annotations, but drops unknown keys on page objects."""
    kind, value = source.parent.xref_get_key(source.xref, SCALE_KEY)
    if kind != "null":
        destination.parent.xref_set_key(
            destination.xref, SCALE_KEY,
            fitz.get_pdf_str(value) if kind == "string" else value,
        )


def copy_page_scales(source: fitz.Document, destination: fitz.Document,
                     source_pages: list[int], destination_start: int) -> None:
    for offset, page_number in enumerate(source_pages):
        copy_page_scale(source[page_number], destination[destination_start + offset])


def write_marker(doc: fitz.Document, xref: int, identifier: str,
                 role: str, unit: str, saved_scale: float) -> None:
    payload = {"schema": SCHEMA, "id": identifier, "role": role,
               "unit": unit, "savedScale": valid_factor(saved_scale)}
    doc.xref_set_key(xref, MEASUREMENT_KEY, fitz.get_pdf_str(json.dumps(payload)))


def _marker(doc: fitz.Document, xref: int) -> dict | None:
    kind, value = doc.xref_get_key(xref, MEASUREMENT_KEY)
    if kind != "string":
        return None
    try:
        data = json.loads(value)
        if (not isinstance(data, dict) or data.get("schema") != SCHEMA
                or not isinstance(data.get("id"), str)
                or data.get("role") not in {"line", "label"}
                or data.get("unit") not in {"mm", "cm"}):
            return None
        valid_factor(data.get("savedScale"))
        return data
    except (ValueError, TypeError, OverflowError):
        return None


def saved_measurements(page: fitz.Page) -> list[SavedMeasurement]:
    """Only return complete, unambiguous pairs created by this application."""
    grouped: dict[str, dict[str, list[tuple[fitz.Annot, dict]]]] = {}
    for annot in page.annots() or ():
        data = _marker(page.parent, annot.xref)
        if data is not None:
            grouped.setdefault(data["id"], {"line": [], "label": []})[
                data["role"]
            ].append((annot, data))
    result = []
    for identifier, roles in grouped.items():
        if len(roles["line"]) != 1 or len(roles["label"]) != 1:
            continue
        line, meta = roles["line"][0]
        label, caption_meta = roles["label"][0]
        vertices = line.vertices or ()
        if (line.type[1] != "Line" or label.type[1] != "FreeText"
                or len(vertices) != 2 or meta["unit"] != caption_meta["unit"]
                or meta["savedScale"] != caption_meta["savedScale"]):
            continue
        points = tuple((float(v[0]), float(v[1])) for v in vertices)
        result.append(SavedMeasurement(identifier, line.xref, label.xref,
                                       points, meta["unit"], meta["savedScale"]))
    return result


def distance_mm(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Measure between PyMuPDF page points at the PDF's defined paper size."""
    values = (*start, *end)
    if not all(isfinite(float(value)) for value in values):
        raise ValueError("Measurement points must be finite")
    return hypot(end[0] - start[0], end[1] - start[1]) * POINT_TO_MM


def format_distance(mm: float, unit: str = "mm") -> str:
    if unit == "mm":
        return f"{mm:,.2f} mm"
    if unit == "cm":
        return f"{mm / 10.0:,.2f} cm"
    raise ValueError(f"Unsupported measurement unit: {unit}")
