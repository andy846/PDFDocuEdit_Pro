"""Strict, versioned declarative template models (no Qt)."""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache as _value_cache
from pathlib import Path
from typing import Any

TEMPLATE_VERSION = 12
MAX_TEMPLATE_PAGES = 100
MM_TO_PT = 72 / 25.4
ELEMENT_TYPES = frozenset({"text", "image", "line", "rectangle", "code128", "i25", "qr"})
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
class RuleCondition:
    field: str = ""
    operator: str = "eq"
    data_type: str = "text"
    value: str = ""


@dataclass
class ConditionGroup:
    mode: str = "all"
    conditions: list[RuleCondition] = field(default_factory=list)


@dataclass
class AlternativeContent:
    when: ConditionGroup = field(default_factory=ConditionGroup)
    value: str = ""
    image: str = ""


@dataclass
class ElementRules:
    visible_when: ConditionGroup | None = None
    alternative: AlternativeContent | None = None

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw, dict):
            raise CompositionError("Object rules must be a JSON object.")
        def group(value):
            if not isinstance(value, dict) or not isinstance(value.get("conditions"), list):
                raise CompositionError("A condition group needs a conditions list.")
            if len(value["conditions"]) > 20:
                raise CompositionError("Use at most 20 conditions per group.")
            return ConditionGroup(**{**value, "conditions": [RuleCondition(**item) for item in value["conditions"]]})
        values = dict(raw)
        if values.get("visible_when") is not None:
            values["visible_when"] = group(values["visible_when"])
        if values.get("alternative") is not None:
            alternative = values["alternative"]
            if not isinstance(alternative, dict) or "when" not in alternative:
                raise CompositionError("Alternative content needs a condition group.")
            values["alternative"] = AlternativeContent(**{**alternative, "when": group(alternative["when"])})
        return cls(**values)



@dataclass
class Element:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "text"
    x_mm: float = 20.0
    y_mm: float = 20.0
    width_mm: float = 70.0
    height_mm: float = 12.0
    rotation_deg: float = 0.0
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
    barcode_profile: dict = field(default_factory=dict)
    # Explicit repairs apply only when the primary face lacks that exact code point.
    glyph_repairs: dict[str, FontSpec] = field(default_factory=dict)
    rules: ElementRules = field(default_factory=ElementRules)


@dataclass
class DataConfig:
    path: str = ""
    encoding: str = "utf-8-sig"
    delimiter: str = ","
    header: bool = True
    header_row: int = 1
    mapping: dict[str, str] = field(default_factory=dict)
    sheet: str = ""
    excel_formulas: str = "reject"
    preserve_zeros: bool = True


@dataclass
class SequenceSpec:
    name: str = "Seq"
    start: int = 1
    step: int = 1
    padding: int = 6
    prefix: str = ""
    suffix: str = ""
    scope: str = "record"


@dataclass
class PageSpec:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Page"
    width_mm: float = 210.0
    height_mm: float = 297.0
    background: str = ""
    elements: list[Element] = field(default_factory=list)


@dataclass(init=False)
class Template:
    template_version: int
    name: str
    pages: list[PageSpec]
    data: DataConfig
    sequences: list[SequenceSpec]
    record_mode: str
    generated_count: int
    source_link: dict
    media: dict

    def __init__(self, template_version=TEMPLATE_VERSION, name="Untitled document",
                 width_mm=210.0, height_mm=297.0, background="", elements=None, data=None,
                 *, pages=None, sequences=None, record_mode="imported", generated_count=100, source_link=None, media=None):
        self.template_version = template_version
        self.name = name
        self.pages = pages if pages is not None else [
            PageSpec(id="page_1", name="Page 1", width_mm=width_mm, height_mm=height_mm,
                     background=background, elements=elements if elements is not None else [])]
        self.data = data if data is not None else DataConfig()
        self.sequences = sequences if sequences is not None else []
        self.record_mode = record_mode
        self.generated_count = generated_count
        self.source_link = source_link if source_link is not None else {}
        self.media = media if media is not None else {}

    # Existing headless callers can still construct/access a single-page template.
    # Designer code explicitly chooses a page; serialization never duplicates page data.
    @property
    def width_mm(self):
        return self.pages[0].width_mm

    @width_mm.setter
    def width_mm(self, value):
        self.pages[0].width_mm = value

    @property
    def height_mm(self):
        return self.pages[0].height_mm

    @height_mm.setter
    def height_mm(self, value):
        self.pages[0].height_mm = value

    @property
    def background(self):
        return self.pages[0].background

    @background.setter
    def background(self, value):
        self.pages[0].background = value

    @property
    def elements(self):
        return self.pages[0].elements

    @elements.setter
    def elements(self, value):
        self.pages[0].elements = value

    def all_elements(self):
        return (element for page in self.pages for element in page.elements)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Template:
        if not isinstance(value, dict):
            raise CompositionError("A template must be a JSON object.")
        version = value.get("template_version")
        if type(version) is not int or version not in range(1, TEMPLATE_VERSION + 1):
            raise CompositionError(
                f"Unsupported template version: {version!r}. This build reads version {TEMPLATE_VERSION}.")
        try:
            raw = dict(value)
            if version<10 and raw.get("media"):
                raise CompositionError("Print Media requires template version 10.")
            if version < 8 and raw.get("source_link"):
                raise CompositionError("PDF source links require template version 8.")
            if version < 9 and isinstance(raw.get("source_link"), dict) and raw["source_link"].get("version") == 2:
                raise CompositionError("Multi-page PDF source links require template version 9.")
            if version < 6 and any(key in raw.get("data", {}) for key in ("sheet", "excel_formulas", "preserve_zeros")):
                raise CompositionError("Excel source settings require template version 6.")
            if version < 5 and any(key in raw for key in ("sequences", "record_mode", "generated_count")):
                raise CompositionError("Running sequences require template version 5.")
            if not isinstance(raw.get("sequences", []), list) or len(raw.get("sequences", [])) > 100:
                raise CompositionError("Use at most 100 running sequence fields.")
            raw["sequences"] = [SequenceSpec(**item) for item in raw.get("sequences", [])]
            if version < 3:
                if "pages" in raw:
                    raise CompositionError("Legacy templates cannot contain a pages list.")
                page = {"id": "page_1", "name": "Page 1"}
                for key in ("width_mm", "height_mm", "background", "elements"):
                    if key in raw:
                        page[key] = raw.pop(key)
                raw["pages"] = [page]
            elif any(key in raw for key in ("width_mm", "height_mm", "background", "elements")):
                raise CompositionError("Version 3 or later uses pages; remove ambiguous top-level page properties.")
            if not isinstance(raw.get("pages"), list) or not 1 <= len(raw["pages"]) <= MAX_TEMPLATE_PAGES:
                raise CompositionError(f"A template needs 1 to {MAX_TEMPLATE_PAGES} pages.")
            pages = []
            for page in raw["pages"]:
                page = dict(page)
                elements = page.get("elements", [])
                if not isinstance(elements, list) or len(elements) > 5000:
                    raise CompositionError("A template can contain at most 5,000 elements.")
                if version < 11 and any(e.get("barcode_profile") for e in elements):
                    raise CompositionError("Barcode profiles require template version 11.")
                if version < 12 and any(e.get("barcode_profile", {}).get("layout_mode") == "fixed" for e in elements):
                    raise CompositionError("Fixed-length barcode layouts require template version 12.")
                if version < 7 and any(e.get("rotation_deg", 0) != 0 for e in elements):
                    raise CompositionError("Object rotation requires template version 7.")
                if version < 4 and any(e.get("rules", {}).get("visible_when") is not None or
                                       e.get("rules", {}).get("alternative") is not None for e in elements):
                    raise CompositionError("Conditional rules require template version 4.")
                page["elements"] = [
                    Element(**{**element, "font": FontSpec(**element.get("font", {})),
                               "rules": ElementRules.from_dict(element.get("rules", {})),
                               "glyph_repairs": {key: FontSpec(**spec) for key, spec
                                                 in element.get("glyph_repairs", {}).items()}})
                    for element in elements]
                pages.append(PageSpec(**page))
            raw["pages"] = pages
            raw["template_version"] = TEMPLATE_VERSION
            raw["data"] = DataConfig(**raw.get("data", {}))
            template = cls(**raw)
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            raise CompositionError(f"Invalid template schema: {exc}") from exc
        validate_template(template, check_assets=False)
        return template


def canonical_codepoint(value: str) -> str:
    if len(value) == 1:
        value = f"U+{ord(value):04X}"
    if not re.fullmatch(r"U\+[0-9A-Fa-f]{4,6}", value):
        raise CompositionError("Enter one character or a code point such as U+E473.")
    code = int(value[2:], 16)
    if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF or code < 32 or 0x7F <= code <= 0x9F:
        raise CompositionError("Choose a printable Unicode scalar value.")
    return f"U+{code:04X}"


def _number(value: object, label: str, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CompositionError(f"{label} must be a number.")
    if not math.isfinite(value) or not low <= value <= high:
        raise CompositionError(f"{label} must be between {low:g} and {high:g}.")


def parse_value(value: str) -> tuple[tuple[str, str], ...]:
    """Compile field references into literal/field tokens; never execute input."""
    from core.variables import VariableError, compile_template

    try:
        compiled = compile_template(value)
        # Keep the existing project grammar until extended text tokens have a
        # saved-format gate. Naming can already use the full shared grammar.
        if any(token.transforms or "." in token.name for token in compiled.tokens):
            raise VariableError("Invalid variable syntax. Use {{Field_Name}}.")
        if len(VARIABLE.findall(value)) != sum(bool(token.name) for token in compiled.tokens):
            raise VariableError("Invalid variable syntax. Use {{Field_Name}} without spaces.")
        tokens = [("field", token.name) if token.name else ("literal", token.literal)
                  for token in compiled.tokens]
        if not tokens or tokens[-1][0] != "literal":
            tokens.append(("literal", ""))
        return tuple(tokens)
    except VariableError as exc:
        raise CompositionError(f"Invalid variable syntax. {exc}") from exc


def resolve_value(tokens: tuple[tuple[str, str], ...], record: dict[str, str]) -> str:
    from core.variables import VariableContext, VariableError, resolve
    compiled = _shared_value_tokens(tokens)
    try:
        return resolve(compiled, VariableContext.for_record(record)).value
    except VariableError as exc:
        raise CompositionError(str(exc)) from exc


@_value_cache(maxsize=512)
def _shared_value_tokens(tokens):
    from core.variables.model import CompiledTemplate, Token
    return CompiledTemplate("", tuple(Token(literal=text) if kind == "literal" else Token(name=text)
                                      for kind, text in tokens))


def required_fields(template: Template) -> set[str]:
    from composition.engine.rules import rule_fields
    fields = {
        text for element in template.all_elements()
        if element.type in {"text", "code128", "i25", "qr"} and not element.barcode_profile
        for kind, text in parse_value(element.value) if kind == "field"
    }
    for element in template.all_elements():
        if element.barcode_profile:
            from composition.engine.barcode_profiles import BarcodeProfile
            fields.update(BarcodeProfile.from_dict(element.barcode_profile).required_fields())
        fields.update(rule_fields(element.rules))
        if element.rules.alternative and element.type != "image":
            fields.update(text for kind, text in parse_value(element.rules.alternative.value) if kind == "field")
    return fields


def validate_template(template: Template, *, check_assets: bool = True) -> None:
    from composition.media.model import MediaSpec
    MediaSpec.from_dict(template.media)
    from composition.handoff import validate_link
    validate_link(template.source_link)
    if type(template.template_version) is not int or template.template_version != TEMPLATE_VERSION:
        raise CompositionError("Unsupported template version.")
    if not isinstance(template.name, str) or len(template.name) > 500:
        raise CompositionError("Invalid template name.")
    if not isinstance(template.pages, list) or not 1 <= len(template.pages) <= MAX_TEMPLATE_PAGES:
        raise CompositionError(f"A template needs 1 to {MAX_TEMPLATE_PAGES} pages.")
    from composition.data.sequences import validate_sequences
    validate_sequences(template)
    page_ids = set()
    for page in template.pages:
        if not isinstance(page, PageSpec) or not isinstance(page.id, str) or not page.id or page.id in page_ids:
            raise CompositionError("Page IDs must be non-empty and unique.")
        page_ids.add(page.id)
        if not isinstance(page.name, str) or len(page.name) > 500:
            raise CompositionError("Invalid page name.")
        _number(page.width_mm, "Page width", 10, 2000)
        _number(page.height_mm, "Page height", 10, 2000)
        if not isinstance(page.background, str) or not isinstance(page.elements, list):
            raise CompositionError("Invalid background or element list.")
        if page.background and check_assets and not Path(page.background).is_file():
            raise CompositionError(f"PDF background not found: {page.background}")
    if template.source_link.get("version") == 2:
        mapped = template.source_link["template_page_map"]
        if any(key not in page_ids for key in mapped):
            raise CompositionError("A linked template page no longer exists.")
        if any(page.id in mapped and not page.background for page in template.pages):
            raise CompositionError("A linked template page needs its PDF background.")
    if sum(len(page.elements) for page in template.pages) > 5000:
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
    if not isinstance(data.sheet, str) or len(data.sheet) > 255:
        raise CompositionError("Invalid Excel worksheet name.")
    if data.excel_formulas not in ("reject", "cached") or type(data.preserve_zeros) is not bool:
        raise CompositionError("Invalid Excel formula/number-format configuration.")
    seen = set()
    for page, element in ((spec, item) for spec in template.pages for item in spec.elements):
        if not isinstance(element, Element):
            raise CompositionError("Invalid page element.")
        if not isinstance(element.id, str) or not element.id or element.id in seen:
            raise CompositionError("Element IDs must be non-empty and unique.")
        seen.add(element.id)
        from composition.engine.rules import validate_rules
        validate_rules(element, check_assets)
        if not isinstance(element.barcode_profile, dict):
            raise CompositionError("Barcode profile must be a JSON object.")
        if element.barcode_profile:
            from composition.engine.barcode_profiles import INSERTER_I25, BarcodeProfile
            profile = BarcodeProfile.from_dict(element.barcode_profile)
            profile.validate(profile.fields())
            if element.type not in {"code128", "i25", "qr"}:
                raise CompositionError("Only barcode objects use a barcode profile.")
            if profile.preset == INSERTER_I25 and element.type != "i25":
                raise CompositionError("The 18-digit inserter preset requires I25.")
            if element.rules.alternative is not None:
                raise CompositionError("Profile barcodes use their configured payload; remove alternative content.")
        if not isinstance(element.type, str) or element.type not in ELEMENT_TYPES:
            raise CompositionError(f"Unsupported element type: {element.type}")
        for prop in ("x_mm", "y_mm"):
            _number(getattr(element, prop), f"{element.id}: {prop}", 0, 2000)
        for prop in ("width_mm", "height_mm"):
            _number(getattr(element, prop), f"{element.id}: {prop}", 0.1, 2000)
        _number(element.rotation_deg, "Rotation angle", -360, 360)
        from composition.template.geometry import element_bounds
        x0, y0, x1, y1 = element_bounds(element)
        if x0 < -.01 or x1 > page.width_mm + .01:
            raise CompositionError(f"{element.id}: rotated object extends beyond the page width.")
        if y0 < -.01 or y1 > page.height_mm + .01:
            raise CompositionError(f"{element.id}: rotated object extends beyond the page height.")
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
        if not isinstance(element.glyph_repairs, dict) or len(element.glyph_repairs) > 1000:
            raise CompositionError("Invalid missing-glyph repair map.")
        for key, spec in element.glyph_repairs.items():
            if not isinstance(key, str) or not re.fullmatch(r"U\+[0-9A-F]{4,6}", key):
                raise CompositionError("Glyph repair keys must use U+XXXX.")
            if canonical_codepoint(key) != key:
                raise CompositionError("Invalid glyph repair code point.")
            if element.type != "text" and not (element.type in {"code128", "i25"} and element.show_barcode_text):
                raise CompositionError("Glyph repairs require a text object.")
            if not isinstance(spec, FontSpec) or not isinstance(spec.family, str) or not isinstance(spec.file, str):
                raise CompositionError("Invalid glyph repair font.")
            if type(spec.bold) is not bool or type(spec.italic) is not bool:
                raise CompositionError("Invalid glyph repair font style.")
            _number(spec.size_pt, "Repair font size", 1, 500)
        if not isinstance(element.qr_error, str) or element.qr_error not in {"L", "M", "Q", "H"}:
            raise CompositionError("Invalid QR error correction level.")
        if not isinstance(element.image, str) or type(element.show_barcode_text) is not bool:
            raise CompositionError("Invalid image or barcode text configuration.")
        for colour in (element.colour, element.fill):
            if not isinstance(colour, str) or (colour and not re.fullmatch(r"#[0-9a-fA-F]{6}", colour)):
                raise CompositionError("Colours must use #RRGGBB.")
        if not element.colour:
            raise CompositionError("Object colour is required.")
        if element.type in {"text", "code128", "i25", "qr"}:
            parse_value(element.value)
        if element.type == "image" and check_assets and not Path(element.image).is_file():
            raise CompositionError(f"Image not found: {element.image}")
    template._has_barcode_profiles = any(e.barcode_profile for e in template.all_elements())
    template._has_inserter_profiles = any(e.barcode_profile.get("preset") == "inserter_i25_18"
                                        for e in template.all_elements() if isinstance(e.barcode_profile, dict))
