"""Shared fixed-page rendering for preview and production."""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path

import fitz
import segno
from barcode import Code128
from PIL import Image

from composition.template.model import (
    MM_TO_PT,
    CompositionError,
    Element,
    Template,
    validate_template,
)

from .fonts import load_font, permits_subsetting
from .glyphs import GlyphFonts
from .rules import ElementPlan


def rgb(value: str):
    return tuple(int(value[index:index + 2], 16) / 255 for index in (1, 3, 5))


def wrap_text(text: str, font: fitz.Font, size: float, width: float) -> list[str]:
    """Wrap at words, splitting long tokens/CJK sequences at glyph boundaries."""
    result = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"):
        line = ""
        for word in re.findall(r"\s+|\S+", paragraph):
            if font.text_length(line + word, fontsize=size) <= width + 0.001:
                line += word
                continue
            if line:
                result.append(line.rstrip())
                line = ""
                word = word.lstrip()
            for character in word:
                if font.text_length(character, fontsize=size) > width + 0.001:
                    raise CompositionError("Text box is narrower than a character.")
                if line and font.text_length(line + character, fontsize=size) > width + 0.001:
                    result.append(line)
                    line = ""
                line += character
        result.append(line.rstrip())
    return result


class Renderer:
    """Owns its font/background resources inside one process; no GUI state."""

    def __init__(self, template: Template, *, page_index=None, design=False):
        validate_template(template)
        if page_index is not None and (type(page_index) is not int or not 0 <= page_index < len(template.pages)):
            raise CompositionError("Template page number is out of range.")
        self.resource_pages = template.pages if page_index is None else [template.pages[page_index]]
        self.preview_page_index = page_index
        self.template = template
        self.design = design
        self.plans = {element.id: ElementPlan(element) for spec in self.resource_pages for element in spec.elements}
        self.tokens = {key: plan.tokens for key, plan in self.plans.items() if plan.tokens}
        self.rule_summary = {"configured_objects": sum(plan.has_rules for plan in self.plans.values()),
                             "records_checked": 0, "hidden_occurrences": 0,
                             "alternate_occurrences": 0, "complete": False}
        self.stack = ExitStack()
        self.backgrounds = {}
        self.fonts = {}
        self.repair_fonts = {}
        self.repair_summary = {"occurrences": 0, "records": 0}
        self.resource_document = None
        self.font_xrefs = {}
        self.output_fonts = {}
        self.images = {}
        try:
            for spec in self.resource_pages:
                if spec.background:
                    background = self.stack.enter_context(fitz.open(spec.background))
                    if background.needs_pass or background.page_count != 1:
                        raise CompositionError("The static background must be an unencrypted single-page PDF.")
                    self.backgrounds[spec.id] = background
            for element in (item for spec in self.resource_pages for item in spec.elements):
                if element.type == "text" or element.show_barcode_text:
                    self.fonts[element.id] = load_font(element.font)
                    self.repair_fonts[element.id] = {key: load_font(spec)
                                                     for key, spec in element.glyph_repairs.items()}
                if element.type == "image":
                    paths = [element.image]
                    if element.rules.alternative:
                        paths.append(element.rules.alternative.image)
                    for raw in paths:
                        if raw in self.images:
                            continue
                        image_path = Path(raw)
                        if image_path.stat().st_size > 50 * 1024 * 1024:
                            raise CompositionError("Static images must be smaller than 50 MB.")
                        with Image.open(image_path) as image:
                            if image.width * image.height > 50_000_000:
                                raise CompositionError("Static images must have at most 50 million pixels.")
                            image.verify()
                        self.images[raw] = image_path.read_bytes()
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.stack.close()
        self.resource_document = None
        self.font_xrefs.clear()

    def prepare_fonts(self, records, directory, progress=None, is_cancelled=None, audit_path=None):
        from .subsets import prepare_subsets
        self.output_fonts = prepare_subsets(
            self.template, self.tokens, self.fonts, records, directory, progress, is_cancelled,
            repair_fonts=self.repair_fonts, audit_path=audit_path, summary=self.repair_summary,
            plans=self.plans, rule_summary=self.rule_summary,
        )

    def glyph_usage(self, record, page_index=None, ordinal=1):
        result = []
        elements = (self.template.all_elements() if page_index is None
                    else self.template.pages[page_index].elements)
        for element in elements:
            if element.id not in self.fonts:
                continue
            selector = GlyphFonts(self.fonts[element.id], self.repair_fonts.get(element.id), family=element.font.family)
            from composition.data.sequences import sequence_record
            index = next(i for i, p in enumerate(self.template.pages) if element in p.elements)
            values = sequence_record(self.template, record, ordinal, index, design=self.design)
            selected = self.plans[element.id].resolve(values, design=self.design)
            if not selected.visible:
                continue
            counts = selector.repaired_counts(selected.value)
            for key, count in counts.items():
                result.append({"object": element.id, "codepoint": key, "occurrences": count,
                               "primary_font": element.font.family,
                               "repair_font": element.glyph_repairs[key].family})
        return result

    def rule_usage(self, record, page_index=None, ordinal=1):
        if self.design:
            return []
        elements = (self.template.all_elements() if page_index is None
                    else self.template.pages[page_index].elements)
        result = []
        for element in elements:
            plan = self.plans[element.id]
            if plan.has_rules:
                from composition.data.sequences import sequence_record
                index = next(i for i, p in enumerate(self.template.pages) if element in p.elements)
                selected = plan.resolve(sequence_record(self.template, record, ordinal, index))
                result.append({"object": element.id, "visible": selected.visible,
                               "alternative": selected.alternative})
        return result

    def finalize(self, document):
        paths = list(self.fonts.values()) + [pair for mapping in self.repair_fonts.values() for pair in mapping.values()]
        if all(permits_subsetting(path) for _font, path in paths):
            document.subset_fonts()

    def render(self, document: fitz.Document, record: dict[str, str], ordinal: int = 1,
               *, page_index: int | None = None, is_cancelled=None) -> None:
        if page_index is not None and (type(page_index) is not int or not 0 <= page_index < len(self.template.pages)):
            raise CompositionError("Template page number is out of range.")
        if self.preview_page_index is not None:
            if page_index is not None and page_index != self.preview_page_index:
                raise CompositionError("Preview renderer owns only the requested template page.")
            page_index = self.preview_page_index
        if self.resource_document is not document:
            self.resource_document = document
            self.font_xrefs.clear()
        indices = range(len(self.template.pages)) if page_index is None else [page_index]
        for index in indices:
            if is_cancelled and is_cancelled():
                raise CompositionError("Production cancelled between template pages.")
            from composition.data.sequences import sequence_record
            values = sequence_record(self.template, record, ordinal, index, design=self.design)
            spec = self.template.pages[index]
            page = document.new_page(width=spec.width_mm * MM_TO_PT, height=spec.height_mm * MM_TO_PT)
            background = self.backgrounds.get(spec.id)
            if background is not None:
                page.show_pdf_page(page.rect, background, 0, overlay=False)
            for element in spec.elements:
                try:
                    self._render_element(page, element, values)
                except Exception as exc:
                    fields = sorted(self.plans[element.id].fields)
                    raise CompositionError(
                        f"Record {ordinal}, template page {index+1}, object {element.id}"
                        + (f", field {', '.join(fields)}" if fields else "")
                        + f": {exc}"
                    ) from exc

    def _render_element(self, page, element: Element, record) -> None:
        selected = self.plans[element.id].resolve(record, design=self.design)
        if not selected.visible:
            return
        rect = fitz.Rect(
            element.x_mm * MM_TO_PT, element.y_mm * MM_TO_PT,
            (element.x_mm + element.width_mm) * MM_TO_PT,
            (element.y_mm + element.height_mm) * MM_TO_PT,
        )
        if element.type == "text":
            self._text(page, rect, element, selected.value)
        elif element.type == "image":
            page.insert_image(rect, stream=self.images[selected.image], keep_proportion=True)
        elif element.type == "line":
            page.draw_line(rect.tl, rect.br, color=rgb(element.colour), width=element.stroke_pt)
        elif element.type == "rectangle":
            page.draw_rect(
                rect, color=rgb(element.colour), width=element.stroke_pt,
                fill=rgb(element.fill) if element.fill else None,
            )
        else:
            value = selected.value
            self._barcode(page, rect, element, value)

    def _text(self, page, rect, element, text):
        font, font_path = self.fonts[element.id]
        selector = GlyphFonts((font, font_path), self.repair_fonts.get(element.id), family=element.font.family)
        used = [font] + [face for _value, face, _path in selector.runs(text)]
        lines = wrap_text(text, selector, element.font.size_pt, rect.width)
        glyph_height = (font.ascender - font.descender) * element.font.size_pt
        step = element.font.size_pt * element.line_spacing
        height = glyph_height + max(0, len(lines) - 1) * step
        if height > rect.height + 0.01:
            raise CompositionError(f"Text overflows its box ({height / MM_TO_PT:.2f} mm required).")
        offset = 0 if element.vertical_align == "top" else (
            (rect.height - height) / 2 if element.vertical_align == "center" else rect.height - height
        )
        baseline = rect.y0 + offset + font.ascender * element.font.size_pt
        if baseline - max(face.ascender for face in used) * element.font.size_pt < rect.y0 - 0.01:
            raise CompositionError("Repair font extends above the original baseline box. Choose compatible metrics or adjust the box alignment.")
        if baseline + max(0, len(lines)-1) * step - min(face.descender for face in used) * element.font.size_pt > rect.y1 + 0.01:
            raise CompositionError("Repair font extends below the original text box. Adjust the box or choose compatible metrics.")
        for index, line in enumerate(lines):
            length = selector.text_length(line, fontsize=element.font.size_pt)
            x = rect.x0
            if element.align == "center":
                x += (rect.width - length) / 2
            elif element.align == "right":
                x += rect.width - length
            for value, face, source in selector.runs(line):
                fontname = self._embed_font(page, source)
                page.insert_text(
                    (x, baseline + index * step), value,
                    fontname=fontname, fontsize=element.font.size_pt, color=rgb(element.colour),
                )
                x += face.text_length(value, fontsize=element.font.size_pt)

    def _embed_font(self, page, font_path):
        # A non-reserved font name embeds the exact selected TTF/OTF.
        font_path = self.output_fonts.get(str(font_path), font_path)
        fontname = "font_" + str(abs(hash(str(font_path))))
        document = page.parent
        if str(font_path) not in self.font_xrefs:
            self.font_xrefs[str(font_path)] = page.insert_font(
                fontname=fontname, fontfile=str(font_path), set_simple=False,
            )
        else:
            # Reuse the chunk's exact embedded font; reparsing a CJK face per page is costly.
            font_xref = self.font_xrefs[str(font_path)]
            resource_type, resources = document.xref_get_key(page.xref, "Resources")
            if resource_type != "xref":
                raise CompositionError("The generated page has invalid PDF resources.")
            resource_xref = int(resources.split()[0])
            kind, fonts = document.xref_get_key(resource_xref, "Font")
            if kind == "xref":
                document.xref_set_key(int(fonts.split()[0]), fontname, f"{font_xref} 0 R")
            else:
                document.xref_set_key(resource_xref, f"Font/{fontname}", f"{font_xref} 0 R")
        return fontname

    def _barcode(self, page, rect, element, value):
        if not value:
            raise CompositionError("Barcode content is empty.")
        rectangles = []
        # A white quiet-zone backing prevents PDF background art from obscuring codes.
        page.draw_rect(rect, color=None, fill=(1, 1, 1))
        module_min = element.barcode_module_mm * MM_TO_PT
        if element.type == "code128":
            if any(not 32 <= ord(c) <= 126 for c in value):
                raise CompositionError("Code 128 currently accepts printable ASCII; use QR for Unicode.")
            pattern = Code128(value).build()[0]
            count = len(pattern) + 20
            module = rect.width / count
            if module + 0.001 < module_min:
                raise CompositionError("Code 128 box is too narrow for its minimum module size.")
            height = rect.height
            if element.show_barcode_text:
                height -= element.font.size_pt * 1.6
                if height < 5 * MM_TO_PT:
                    raise CompositionError("Code 128 is too short for the bars and readable text.")
            start = 0
            while start < len(pattern):
                if pattern[start] == "0":
                    start += 1
                    continue
                end = start + 1
                while end < len(pattern) and pattern[end] == "1":
                    end += 1
                rectangles.append(fitz.Rect(
                    rect.x0 + (10 + start) * module, rect.y0,
                    rect.x0 + (10 + end) * module, rect.y0 + height,
                ))
                start = end
        else:
            qr = segno.make_qr(value, error=element.qr_error, boost_error=False, encoding="utf-8")
            matrix = list(qr.matrix)
            count = len(matrix) + 8
            module = min(rect.width, rect.height) / count
            if module + 0.001 < module_min:
                raise CompositionError("QR box is too small for its minimum module size.")
            origin_x = rect.x0 + (rect.width - count * module) / 2
            origin_y = rect.y0 + (rect.height - count * module) / 2
            for y, row in enumerate(matrix):
                x = 0
                while x < len(row):
                    if not row[x]:
                        x += 1
                        continue
                    end = x + 1
                    while end < len(row) and row[end]:
                        end += 1
                    rectangles.append(fitz.Rect(
                        origin_x + (x + 4) * module, origin_y + (y + 4) * module,
                        origin_x + (end + 4) * module, origin_y + (y + 5) * module,
                    ))
                    x = end
        # One vector path avoids thousands of Python/native shape calls.
        operators = ["q", "0 g"]
        for box in rectangles:
            operators.append(f"{box.x0:.6f} {page.rect.height-box.y1:.6f} "
                             f"{box.width:.6f} {box.height:.6f} re")
        operators.extend(["f", "Q"])
        document = page.parent
        stream = document.get_new_xref()
        document.update_object(stream, "<<>>")
        document.update_stream(stream, ("\n".join(operators)+"\n").encode("ascii"))
        contents = page.get_contents() + [stream]
        document.xref_set_key(page.xref, "Contents", "["+" ".join(f"{xref} 0 R" for xref in contents)+"]")
        if element.type == "code128" and element.show_barcode_text:
            label = fitz.Rect(rect.x0, rect.y0 + height, rect.x1, rect.y1)
            self._text(page, label, element, value)


def render_preview(template: Template, record: dict[str, str], ordinal: int = 1,
                   repair_details: list | None = None, *, page_index: int | None = None,
                   design=False, rule_details: list | None = None) -> bytes:
    with Renderer(template, page_index=page_index, design=design) as renderer, fitz.open() as document:
        renderer.render(document, record, ordinal, page_index=page_index)
        if repair_details is not None:
            repair_details.extend(renderer.glyph_usage(record, page_index, ordinal))
        if rule_details is not None:
            rule_details.extend(renderer.rule_usage(record, page_index, ordinal))
        renderer.finalize(document)
        return document.tobytes(deflate=True, garbage=1)


def import_background(path: str | Path, page_number: int, target: str | Path) -> tuple[float, float]:
    """Copy and flatten a selected PDF page, keeping the source unchanged."""
    if Path(path).expanduser().resolve() == Path(target).expanduser().resolve():
        raise CompositionError("The background snapshot must not overwrite its source PDF.")
    from core.io_atomic import atomic_output

    with fitz.open(path) as source, fitz.open() as background:
        if source.needs_pass:
            raise CompositionError("Unlock the background PDF with the existing editor before importing it.")
        if not 0 <= page_number < source.page_count:
            raise CompositionError("Background page number is out of range.")
        background.insert_pdf(source, from_page=page_number, to_page=page_number)
        background.bake(annots=True, widgets=True)
        rect = background[0].rect
        with atomic_output(target, overwrite=False) as staged:
            background.save(staged, deflate=True)
    return rect.width / MM_TO_PT, rect.height / MM_TO_PT
