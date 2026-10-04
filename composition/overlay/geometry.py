"""Page-aware overlay bounds shared by output validation and editing."""
from __future__ import annotations

from composition.pdf_source.planner import EnvelopePlan, applies
from composition.template.geometry import element_bounds
from composition.template.model import MM_TO_PT, CompositionError


def check_object_bounds(element, geometry):
    x0, y0, x1, y1 = element_bounds(element)
    if (x0*MM_TO_PT < -.03 or y0*MM_TO_PT < -.03 or
            x1*MM_TO_PT > geometry["width_pt"]+.03 or y1*MM_TO_PT > geometry["height_pt"]+.03):
        raise CompositionError(f"Object {element.id} extends outside the visible source page.")


def validate_changed_geometry(before, after):
    """Validate edited objects on applicable page roles, without scanning records.

    Existing invalid projects remain loadable so operators can repair them.
    Unchanged objects are still checked by production validation.
    """
    previous = {obj.element.id: obj for obj in before.objects}
    keys = ("x_mm", "y_mm", "width_mm", "height_mm", "rotation_deg")
    plan = None
    for obj in after.objects:
        old = previous.get(obj.element.id)
        if (old and old.scope == obj.scope and old.letter_page == obj.letter_page and
                all(getattr(old.element, key) == getattr(obj.element, key) for key in keys)):
            continue
        if after.source.geometry_mode == "uniform":
            check_object_bounds(obj.element, after.source.geometries[0])
            continue
        if plan is None:
            plan = EnvelopePlan(after.source.pages, after.settings)
        for number in range(1, after.settings.output_pages_per_envelope+1):
            page = plan.page(1, number)
            if applies(obj.scope, page.fields(), obj.letter_page):
                check_object_bounds(obj.element, after.source.page_geometry(page))
