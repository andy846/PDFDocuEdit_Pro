"""Pure page-layout operations in millimetres; no GUI or rendering state."""
from __future__ import annotations

import copy
import math

from .geometry import element_bounds
from .model import CompositionError

OPERATIONS = {
    "left": "Align left", "center": "Align horizontal centres", "right": "Align right",
    "top": "Align top", "middle": "Align vertical centres", "bottom": "Align bottom",
    "horizontal": "Distribute horizontally", "vertical": "Distribute vertically",
    "same_width": "Same width", "same_height": "Same height", "same_size": "Same width and height",
    "gap_horizontal": "Set horizontal gap", "gap_vertical": "Set vertical gap",
}


def arrange_elements(elements, selected_ids, operation, page_size, *, reference="selection", reference_id=None, gap=5):
    """Return selected element copies, or reject the entire operation.

    Edges/gaps use visible rotated bounds. Same-size uses unrotated dimensions;
    the first selected element in document order supplies Selection's dimensions.
    """
    if operation not in OPERATIONS or reference not in {"selection", "page", "object"}:
        raise CompositionError("Unknown arrangement or reference.")
    width, height = page_size
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in page_size):
        raise CompositionError("Invalid page dimensions.")
    ids = set(selected_ids)
    selected = [copy.deepcopy(e) for e in elements if e["id"] in ids]
    if not selected or len(selected) != len(ids):
        raise CompositionError("Select available objects on the current page.")
    bounds = [element_bounds(e) for e in selected]
    target = (min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds))
    size = selected[0]["width_mm"], selected[0]["height_mm"]
    if reference == "page":
        target, size = (0, 0, width, height), (width, height)
    elif reference == "object":
        obj = next((e for e in elements if e["id"] == reference_id), None)
        if obj is None:
            raise CompositionError("Choose an available reference object.")
        target, size = element_bounds(obj), (obj["width_mm"], obj["height_mm"])
    if operation.startswith("same_"):
        for e in selected:
            if operation in {"same_width", "same_size"}:
                e["width_mm"] = size[0]
            if operation in {"same_height", "same_size"}:
                e["height_mm"] = size[1]
    elif operation in {"horizontal", "vertical", "gap_horizontal", "gap_vertical"}:
        distributing = operation in {"horizontal", "vertical"}
        if len(selected) < (3 if distributing else 2):
            raise CompositionError("Select at least three objects to distribute." if distributing else "Select at least two objects to set gaps.")
        axis = 0 if operation in {"horizontal", "gap_horizontal"} else 1
        ordered = sorted(selected, key=lambda e: (element_bounds(e)[axis], e["id"]))
        if distributing:
            first = ordered[0]
            last = max(ordered, key=lambda e: element_bounds(e)[axis+2])
            if first is last:
                raise CompositionError("Nested objects have no distinct outer anchors for distribution.")
            ordered = [first, *[e for e in ordered if e is not first and e is not last], last]
            low, high = element_bounds(first)[axis], element_bounds(last)[axis+2]
            gap = (high-low-sum(element_bounds(e)[axis+2]-element_bounds(e)[axis] for e in ordered))/(len(ordered)-1)
        if type(gap) not in (int, float) or not math.isfinite(gap) or gap < -1e-8:
            raise CompositionError("There is not enough space for non-overlapping gaps.")
        gap = max(0, gap)
        position = element_bounds(ordered[0])[axis]
        for index, e in enumerate(ordered):
            b = element_bounds(e)
            extent = b[axis+2]-b[axis]
            # Outer anchors retain their original exact positions.
            if not distributing or index not in (0, len(ordered)-1):
                e["x_mm" if axis == 0 else "y_mm"] += position-b[axis]
            position += extent+gap
    else:
        for e in selected:
            b = element_bounds(e)
            delta = {
                "left": target[0]-b[0], "center": (target[0]+target[2]-b[0]-b[2])/2,
                "right": target[2]-b[2], "top": target[1]-b[1],
                "middle": (target[1]+target[3]-b[1]-b[3])/2, "bottom": target[3]-b[3],
            }[operation]
            e["x_mm" if operation in {"left", "center", "right"} else "y_mm"] += delta
    for e in selected:
        x0, y0, x1, y1 = element_bounds(e)
        if min(x0, y0, e["x_mm"], e["y_mm"]) < -1e-8 or x1 > width+1e-8 or y1 > height+1e-8:
            raise CompositionError(f"Object {e['id']}: arrangement exceeds the supported page bounds; no objects were changed.")
        # Clear floating point noise at zero without rounding general positions.
        e["x_mm"], e["y_mm"] = max(0, e["x_mm"]), max(0, e["y_mm"])
    return selected
