"""Bounded, screen-aware preview rasterization; production PDFs stay vector."""
from __future__ import annotations

import math

MAX_PREVIEW_PIXELS = 16_000_000
MAX_PREVIEW_EDGE = 8192
SCALE_LEVELS = (2, 3, 4, 6, 8, 12, 16, 24, 32)


def bounded_scale(width_pt, height_pt, requested=2):
    """Cap allocations before calling the native renderer, including custom pages."""
    width, height, desired = float(width_pt), float(height_pt), float(requested)
    if not all(math.isfinite(value) and value > 0 for value in (width, height, desired)):
        raise ValueError("Preview dimensions and scale must be finite positive numbers.")
    desired = min(desired, SCALE_LEVELS[-1])

    def fits(scale):
        x, y = math.ceil(width * scale), math.ceil(height * scale)
        return max(x, y) <= MAX_PREVIEW_EDGE and x * y <= MAX_PREVIEW_PIXELS

    if fits(desired):
        return desired
    low, high = 0.0, desired
    for _ in range(40):
        mid = (low + high) / 2
        if fits(mid):
            low = mid
        else:
            high = mid
    return low


def screen_scale(width_pt, height_pt, pixels_per_point):
    """Oversample screen pixels and bucket zoom changes to avoid render churn."""
    required = max(2, pixels_per_point * 1.25)
    level = next((level for level in SCALE_LEVELS if level >= required), SCALE_LEVELS[-1])
    return bounded_scale(width_pt, height_pt, level)


def save_preview(page, target, requested=2):
    import fitz

    scale = bounded_scale(page.rect.width, page.rect.height, requested)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    pixmap.save(target)
    return {"raster_scale": scale, "image_width": pixmap.width, "image_height": pixmap.height}
