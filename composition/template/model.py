"""Strict, versioned declarative template models (no Qt)."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TEMPLATE_VERSION = 1
MM_TO_PT = 72 / 25.4
ELEMENT_TYPES = frozenset({"text", "image", "line", "rectangle", "code128", "qr"})
VARIABLE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class CompositionError(ValueError):
    """An actionable template, data or production validation error."""


@dataclass
class FontSpec:
    family: str = "Noto Sans"
    size_pt: float = 10.0
    bold: bool = False
    italic: bool = False
    file: str = ""


@dataclass
class Element:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "text"
    x_mm: float = 20.0
    y_mm: float = 20.0
    width_mm: float = 70.0
    height_mm: float = 12.0
    value: str = "Text"
    font: FontSpec = field(default_factory=FontSpec)
    align: str = "left"
    vertical_align: str = "top"
    line_spacing: float = 1.2
    colour: str = "#000000"
    fill: str = ""
    stroke_pt: float = 1.0
    image: str = ""
    qr_error: str = "M"
    # Quiet zones are included in the element bounding box.
    barcode_module_mm: float = 0.25
    show_barcode_text: bool = False


@dataclass
class DataConfig:
    path: str = ""
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    header: bool = True
    header_row: int = 1
    mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class Template:
    template_version: int = TEMPLATE_VERSION
    name: str = "Untitled document"
    width_mm: float = 210.0
    height_mm: float = 297.0
    background: str = ""
    elements: list[Element] = field(default_factory=list)
    data: DataConfig = field(default_factory=DataConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Template:
        if not isinstance(value, dict):
            raise CompositionError("A template must be a JSON object.")
        if type(value.get("template_version")) is not int or value["template_version"] != TEMPLATE_VERSION:
            raise CompositionError(
                f"Unsupported template version: {value.get('template_version')!r}. "
                f"This build reads version {TEMPLATE_VERSION}."
            )
        try:
            raw = dict(value)
            if len(raw.get("elements", [])) > 5000:
                raise CompositionError("A template can contain at most 5,000 elements.")
            raw["elements"] = [
                Element(**{**element, "font": FontSpec(**element.get("font", {}))})
                for element in raw.get("elements", [])
            ]
            raw["data"] = DataConfig(**raw.get("data", {}))
            template = cls(**raw)
        except (TypeError, KeyError, AttributeError) as exc:
            raise CompositionError(f"Invalid template schema: {exc}") from exc
        validate_template(template, check_assets=False)
        return template


def _number(value: object, label: str, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CompositionError(f"{label} must be a number.")
    if not math.isfinite(value) or not low <= value <= high:
        raise CompositionError(f"{label} must be between {low:g} and {high:g}.")


def parse_value(value: str) -> tuple[tuple[str, str], ...]:
    """Compile field references into literal/field tokens; never execute input."""
    if not isinstance(value, str) or len(value) > 100_000:
        raise CompositionError("Element content must be text of at most 100,000 characters.")
    tokens: list[tuple[str, str]] = []
    cursor = 0
    for match in VARIABLE.finditer(value):
        if match.start() > cursor:
            tokens.append(("literal", value[cursor:match.start()]))
        tokens.append(("field", match.group(1)))
        cursor = match.end()
    tokens.append(("literal", value[cursor:]))
    for kind, text in tokens:
        if kind == "literal" and ("{{" in text or "}}" in text):
            raise CompositionError("Invalid variable syntax. Use {{Field_Name}}.")
    return tuple(tokens)


def resolve_value(tokens: tuple[tuple[str, str], ...], record: dict[str, str]) -> str:
    parts = []
    for kind, text in tokens:
        if kind == "literal":
            parts.append(text)
        elif text not in record:
            raise CompositionError(f"Missing field: {text}")
        else:
            parts.append(record[text])
    return "".join(parts)


def required_fields(template: Template) -> set[str]:
    return {
        text for element in template.elements
        if element.type in {"text", "code128", "qr"}
        for kind, text in parse_value(element.value) if kind == "field"
    }


def validate_template(template: Template, *, check_assets: bool = True) -> None:
    if type(template.template_version) is not int or template.template_version != TEMPLATE_VERSION:
        raise CompositionError("Unsupported template version.")
    _number(template.width_mm, "Page width", 10, 2000)
    _number(template.height_mm, "Page height", 10, 2000)
    if not isinstance(template.name, str) or len(template.name) > 500:
        raise CompositionError("Invalid template name.")
    if not isinstance(template.background, str) or not isinstance(template.elements, list):
        raise CompositionError("Invalid background or element list.")
    if len(template.elements) > 5000:
        raise CompositionError("A template can contain at most 5,000 elements.")
    data = template.data
    if not all(isinstance(value, str) for value in (data.path, data.encoding, data.delimiter)):
        raise CompositionError("Data paths, encodings and delimiters must be strings.")
    if type(data.header) is not bool or type(data.header_row) is not int or not 1 <= data.header_row <= 100000:
        raise CompositionError("Invalid header/start row configuration.")
    if len(data.delimiter) != 1 or data.delimiter in "\r\n\0":
        raise CompositionError("Choose a single-character delimiter.")
    if not isinstance(data.mapping, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
        for key, value in data.mapping.items()
    ):
        raise CompositionError("Invalid variable field mapping.")
    seen = set()
    for element in template.elements:
        if not isinstance(element.id, str) or not element.id or element.id in seen:
            raise CompositionError("Element IDs must be non-empty and unique.")
        seen.add(element.id)
        if not isinstance(element.type, str) or element.type not in ELEMENT_TYPES:
            raise CompositionError(f"Unsupported element type: {element.type}")
        for prop in ("x_mm", "y_mm"):
            _number(getattr(element, prop), f"{element.id}: {prop}", 0, 2000)
        for prop in ("width_mm", "height_mm"):
            _number(getattr(element, prop), f"{element.id}: {prop}", 0.1, 2000)
        if element.x_mm + element.width_mm > template.width_mm + 0.01:
            raise CompositionError(f"{element.id}: object extends beyond the page width.")
        if element.y_mm + element.height_mm > template.height_mm + 0.01:
            raise CompositionError(f"{element.id}: object extends beyond the page height.")
        if not isinstance(element.align, str) or element.align not in {"left", "center", "right"}:
            raise CompositionError("Text alignment must be left, center or right.")
        if not isinstance(element.vertical_align, str) or element.vertical_align not in {"top", "center", "bottom"}:
            raise CompositionError("Vertical alignment must be top, center or bottom.")
        _number(element.font.size_pt, "Font size", 1, 500)
        _number(element.line_spacing, "Line spacing", 0.5, 5)
        _number(element.stroke_pt, "Line width", 0.1, 20)
        _number(element.barcode_module_mm, "Barcode module size", 0.1, 5)
        if not isinstance(element.font.family, str) or not isinstance(element.font.file, str):
            raise CompositionError("Invalid font specification.")
        if type(element.font.bold) is not bool or type(element.font.italic) is not bool:
            raise CompositionError("Font styles must be boolean values.")
        if not isinstance(element.qr_error, str) or element.qr_error not in {"L", "M", "Q", "H"}:
            raise CompositionError("Invalid QR error correction level.")
        if not isinstance(element.image, str) or type(element.show_barcode_text) is not bool:
            raise CompositionError("Invalid image or barcode text configuration.")
        for colour in (element.colour, element.fill):
            if not isinstance(colour, str) or (colour and not re.fullmatch(r"#[0-9a-fA-F]{6}", colour)):
                raise CompositionError("Colours must use #RRGGBB.")
        if not element.colour:
            raise CompositionError("Object colour is required.")
        if element.type in {"text", "code128", "qr"}:
            parse_value(element.value)
        if element.type == "image" and check_assets and not Path(element.image).is_file():
            raise CompositionError(f"Image not found: {element.image}")
    if template.background and check_assets and not Path(template.background).is_file():
        raise CompositionError(f"PDF background not found: {template.background}")
