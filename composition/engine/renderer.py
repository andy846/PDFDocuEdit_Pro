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
    parse_value,
    resolve_value,
    validate_template,
)

from .fonts import load_font, permits_subsetting, validate_glyphs


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

    def __init__(self, template: Template):
        validate_template(template)
        self.template = template
        self.tokens = {
            element.id: parse_value(element.value) for element in template.elements
            if element.type in {"text", "qr", "code128"}
        }
        self.stack = ExitStack()
        self.background = None
        if template.background:
            self.background = self.stack.enter_context(fitz.open(template.background))
            if self.background.needs_pass or self.background.page_count != 1:
                self.close()
                raise CompositionError("The static background must be an unencrypted single-page PDF.")
        self.fonts = {}
        self.images = {}
        try:
            for element in template.elements:
                if element.type == "text" or element.show_barcode_text:
                    self.fonts[element.id] = load_font(element.font)
                if element.type == "image":
                    image_path = Path(element.image)
                    if image_path.stat().st_size > 50 * 1024 * 1024:
                        raise CompositionError("Static images must be smaller than 50 MB.")
                    with Image.open(image_path) as image:
                        if image.width * image.height > 50_000_000:
                            raise CompositionError("Static images must have at most 50 million pixels.")
                        image.verify()
                    self.images[element.id] = image_path.read_bytes()
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.stack.close()

    def finalize(self, document):
        if all(permits_subsetting(path) for _font, path in self.fonts.values()):
            document.subset_fonts()

    def render(self, document: fitz.Document, record: dict[str, str], ordinal: int = 1) -> None:
        page = document.new_page(
            width=self.template.width_mm * MM_TO_PT, height=self.template.height_mm * MM_TO_PT
        )
        if self.background is not None:
            page.show_pdf_page(page.rect, self.background, 0, overlay=False)
        for element in self.template.elements:
            try:
                self._render_element(page, element, record)
            except Exception as exc:
                fields = [text for kind, text in self.tokens.get(element.id, ()) if kind == "field"]
                raise CompositionError(
                    f"Record {ordinal}, object {element.id}"
                    + (f", field {', '.join(fields)}" if fields else "")
                    + f": {exc}"
                ) from exc

    def _render_element(self, page, element: Element, record) -> None:
        rect = fitz.Rect(
            element.x_mm * MM_TO_PT, element.y_mm * MM_TO_PT,
            (element.x_mm + element.width_mm) * MM_TO_PT,
            (element.y_mm + element.height_mm) * MM_TO_PT,
        )
        if element.type == "text":
            self._text(page, rect, element, resolve_value(self.tokens[element.id], record))
        elif element.type == "image":
            page.insert_image(rect, stream=self.images[element.id], keep_proportion=True)
        elif element.type == "line":
            page.draw_line(rect.tl, rect.br, color=rgb(element.colour), width=element.stroke_pt)
        elif element.type == "rectangle":
            page.draw_rect(
                rect, color=rgb(element.colour), width=element.stroke_pt,
                fill=rgb(element.fill) if element.fill else None,
            )
        else:
            value = resolve_value(self.tokens[element.id], record)
            self._barcode(page, rect, element, value)

    def _text(self, page, rect, element, text):
        font, font_path = self.fonts[element.id]
        validate_glyphs(font, text)
        lines = wrap_text(text, font, element.font.size_pt, rect.width)
        glyph_height = (font.ascender - font.descender) * element.font.size_pt
        step = element.font.size_pt * element.line_spacing
        height = glyph_height + max(0, len(lines) - 1) * step
        if height > rect.height + 0.01:
            raise CompositionError(f"Text overflows its box ({height / MM_TO_PT:.2f} mm required).")
        offset = 0 if element.vertical_align == "top" else (
            (rect.height - height) / 2 if element.vertical_align == "center" else rect.height - height
        )
        # A non-reserved font name embeds the exact selected TTF/OTF.
        fontname = "font_" + str(abs(hash(str(font_path))))
        page.insert_font(fontname=fontname, fontfile=str(font_path), set_simple=False)
        baseline = rect.y0 + offset + font.ascender * element.font.size_pt
        for index, line in enumerate(lines):
            length = font.text_length(line, fontsize=element.font.size_pt)
            x = rect.x0
            if element.align == "center":
                x += (rect.width - length) / 2
            elif element.align == "right":
                x += rect.width - length
            if line:
                page.insert_text(
                    (x, baseline + index * step), line,
                    fontname=fontname, fontsize=element.font.size_pt, color=rgb(element.colour),
                )

    def _barcode(self, page, rect, element, value):
        if not value:
            raise CompositionError("Barcode content is empty.")
        shape = page.new_shape()
        # A white quiet-zone backing prevents PDF background art from obscuring codes.
        shape.draw_rect(rect)
        shape.finish(color=None, fill=(1, 1, 1))
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
                shape.draw_rect(fitz.Rect(
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
                for x, dark in enumerate(row):
                    if dark:
                        shape.draw_rect(fitz.Rect(
                            origin_x + (x + 4) * module, origin_y + (y + 4) * module,
                            origin_x + (x + 5) * module, origin_y + (y + 5) * module,
                        ))
        shape.finish(color=None, fill=(0, 0, 0))
        shape.commit()
        if element.type == "code128" and element.show_barcode_text:
            label = fitz.Rect(rect.x0, rect.y0 + height, rect.x1, rect.y1)
            self._text(page, label, element, value)


def render_preview(template: Template, record: dict[str, str], ordinal: int = 1) -> bytes:
    with Renderer(template) as renderer, fitz.open() as document:
        renderer.render(document, record, ordinal)
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
