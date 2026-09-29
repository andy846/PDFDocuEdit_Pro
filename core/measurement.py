"""Physical distances on a PDF page, expressed in metric units."""

from __future__ import annotations

from math import hypot, isfinite

POINT_TO_MM = 25.4 / 72.0


def distance_mm(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Measure between PyMuPDF page points at the PDF's defined paper size."""
    values = (*start, *end)
    if not all(isfinite(float(value)) for value in values):
        raise ValueError("Measurement points must be finite")
    return hypot(end[0] - start[0], end[1] - start[1]) * POINT_TO_MM


def format_distance(mm: float, unit: str = "mm") -> str:
    if unit == "mm":
        return f"{mm:.2f} mm"
    if unit == "cm":
        return f"{mm / 10.0:.2f} cm"
    raise ValueError(f"Unsupported measurement unit: {unit}")
