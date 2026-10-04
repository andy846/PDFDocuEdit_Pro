"""Object geometry in millimetres; shared by validation, layout and PDF output."""
from __future__ import annotations

import math


def element_bounds(element):
    get = element.__getitem__ if isinstance(element, dict) else lambda key: getattr(element, key)
    x, y, width, height = (get(key) for key in ("x_mm", "y_mm", "width_mm", "height_mm"))
    angle = math.radians(element.get("rotation_deg", 0) if isinstance(element, dict) else element.rotation_deg)
    c, s = abs(math.cos(angle)), abs(math.sin(angle))
    half_width, half_height = (width*c + height*s)/2, (width*s + height*c)/2
    cx, cy = x + width/2, y + height/2
    return cx-half_width, cy-half_height, cx+half_width, cy+half_height


def fit_rotated_position(element, page_width, page_height):
    """Keep the rotation centre where possible; translate only to clear page edges."""
    x0, y0, x1, y1 = element_bounds(element)
    if x1-x0 > page_width+.01 or y1-y0 > page_height+.01:
        raise ValueError("The rotated object is larger than the page. Reduce its width or height first.")
    dx = -x0 if x0 < 0 else min(0, page_width-x1)
    dy = -y0 if y0 < 0 else min(0, page_height-y1)
    element["x_mm"] += dx
    element["y_mm"] += dy
