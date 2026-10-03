"""Copy original PDF pages, then add a separate vector overlay Form XObject."""
from __future__ import annotations

from pathlib import Path

import fitz

from composition.engine.renderer import Renderer
from composition.engine.rules import ElementPlan, Selection
from composition.pdf_source.planner import EnvelopePlan, applies
from composition.pdf_source.source import _stat
from composition.template.geometry import element_bounds
from composition.template.model import MM_TO_PT, CompositionError

from .geometry import check_object_bounds
from .model import barcode_field, render_template


class ScopedPlan(ElementPlan):
    def __init__(self, element, obj):
        super().__init__(element)
        self.obj = obj

    def resolve(self, record, *, design=False):
        if not applies(self.obj.scope, record, self.obj.letter_page):
            return Selection(False)
        return super().resolve(record, design=design)


def page_values(spec, plan, job_id, external_values=None):
    fields = plan.fields(job_id)
    if spec.external_fields:
        values=external_values(plan) if external_values else dict.fromkeys(spec.external_fields, "")
        if set(values)!=set(spec.external_fields) or any(not isinstance(v,str) for v in values.values()):
            raise CompositionError("Workflow values do not match the declared extraction fields.")
        fields.update(values)
    for obj in spec.objects:
        if obj.profile:
            fields[barcode_field(obj)] = (obj.profile.payload(fields)
                                          if applies(obj.scope, fields, obj.letter_page) else "")
    return fields


def page_records(spec, plan, job_id, is_cancelled=None, external_values=None):
    from composition.production.generator import check_cancel
    for page in plan.pages():
        check_cancel(is_cancelled)
        try:
            yield page.output_page, page_values(spec, page, job_id, external_values)
        except ValueError as exc:
            raise CompositionError(f"Output page {page.output_page}, envelope {page.envelope}: {exc}") from exc


class OverlayRenderer:
    def __init__(self, spec, *, auto_repair=True, fallback_directory=None, is_cancelled=None):
        self.spec = spec
        self.renderer = Renderer(render_template(spec), auto_repair=auto_repair,
                                 fallback_directory=fallback_directory, is_cancelled=is_cancelled)
        self.elements = list(self.renderer.template.elements)
        self.renderer.plans = {element.id: ScopedPlan(element, obj)
                               for element, obj in zip(self.elements, spec.objects, strict=True)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.renderer.close()

    def selections(self, fields, geometry, *, enforce_control=True):
        visible, controls = [], []
        for element, obj in zip(self.elements, self.spec.objects, strict=True):
            selected = self.renderer.plans[element.id].resolve(fields)
            if not selected.visible:
                continue
            check_object_bounds(element, geometry)
            visible.append((element,obj,selected))
            if obj.control:
                controls.append(element)
        if (enforce_control and self.spec.requires_control_barcode
                and applies(self.spec.required_scope,fields) and len(controls) != 1):
            raise CompositionError(f"Required barcode read position needs exactly one visible control barcode; found {len(controls)}.")
        return visible

    def build_layer(self, layers, page_plan, fields, geometry, *, enforce_control=True):
        selected = self.selections(fields, geometry, enforce_control=enforce_control)
        marks = []
        if not selected:
            return None, marks
        layer = layers.new_page(width=geometry["width_pt"], height=geometry["height_pt"])
        self.renderer.paint_elements(layer, [element for element, _obj, _value in selected], fields,
                                     page_plan.envelope,
                                     context=f"source page {page_plan.source_page}, output page {page_plan.output_page}")
        for element, obj, value in selected:
            if element.type in ("qr", "code128", "i25"):
                marks.append({"output_page": page_plan.output_page, "source_page": page_plan.source_page,
                              "envelope": page_plan.envelope, "object": element.id, "symbology": element.type,
                              "profile": obj.profile.name, "payload": value.value,
                              "rotation_deg": element.rotation_deg,
                              "rect": [value*MM_TO_PT for value in element_bounds(element)]})
        return layer.number, marks

    @staticmethod
    def stamp(output, layers, layer_index, source, page_plan, geometry):
        if page_plan.source_page is None:
            target = output.new_page(width=geometry["width_pt"], height=geometry["height_pt"])
        else:
            index = page_plan.source_page-1
            output.insert_pdf(source, from_page=index, to_page=index, links=False,
                              annots=True, widgets=False, final=0)
            target = output[-1]
        if layer_index is not None:
            # The complete layer batch must be immutable before grafting: MuPDF's
            # source graft map is sized when first used and cannot accept new xrefs.
            rotation = target.rotation
            target.set_rotation(0)
            try:
                # Resolve CropBox translation with an unrotated target, then rotate
                # the layer into the original display orientation.
                target.show_pdf_page(target.rect, layers, layer_index, rotate=rotation)
            finally:
                target.set_rotation(rotation)

    def paint(self, output, layers, source, page_plan, fields, geometry, *, enforce_control=True):
        layer_index, marks = self.build_layer(layers, page_plan, fields, geometry, enforce_control=enforce_control)
        self.stamp(output, layers, layer_index, source, page_plan, geometry)
        return marks


def render_preview(spec, envelope, print_page, *, auto_repair=True, external_values=None):
    spec.validate()
    source_path=Path(spec.source.path)
    if _stat(source_path) != (spec.source.size,spec.source.mtime_ns):
        raise CompositionError("Source PDF changed since inspection. Reinspect before previewing.")
    plan=EnvelopePlan(spec.source.pages,spec.settings).page(envelope,print_page)
    fields=page_values(spec,plan,"preview",external_values)
    with fitz.open(source_path) as source, fitz.open() as output, fitz.open() as layers, OverlayRenderer(
        spec,auto_repair=auto_repair,
    ) as renderer:
        if source.page_count != spec.source.pages:
            raise CompositionError("Source page count changed since inspection.")
        renderer.paint(output,layers,source,plan,fields,spec.source.page_geometry(plan), enforce_control=False)
        # Fonts belong to the separate layer; never subset the copied source document.
        return output.tobytes(deflate=True,garbage=1),fields
