"""Versioned envelope projects and bounded declarative barcode payloads."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from composition.pdf_source.model import EnvelopeSettings, SourceInfo
from composition.pdf_source.planner import SCOPES, SYSTEM_FIELDS, EnvelopePlan
from composition.production.model import new_job_id, now
from composition.template.model import CompositionError, Element, Template, required_fields


@dataclass
class BarcodeToken:
    kind: str = "field"
    value: str = "EnvelopeSeq"
    width: int = 0


@dataclass
class BarcodeProfile:
    name: str = "Generic envelope identifier"
    version: int = 1
    machine: str = ""
    validation: str = "pending"
    tokens: list[BarcodeToken] = field(default_factory=lambda: [BarcodeToken(),
                   BarcodeToken(value="LetterPage", width=2), BarcodeToken(value="LetterPageCount", width=2)])

    def validate(self):
        if type(self.version) is not int or self.version != 1 or self.validation not in ("pending", "user_verified"):
            raise CompositionError("Unsupported barcode profile version/validation state.")
        if not isinstance(self.name, str) or not self.name or len(self.name) > 200:
            raise CompositionError("Give the barcode profile a name of at most 200 characters.")
        if not isinstance(self.machine, str) or len(self.machine) > 200:
            raise CompositionError("Invalid machine profile name.")
        if self.validation == "user_verified" and not self.machine:
            raise CompositionError("A user-verified profile must identify the machine.")
        if not isinstance(self.tokens, list) or not 1 <= len(self.tokens) <= 30:
            raise CompositionError("A barcode profile needs 1 to 30 tokens.")
        for token in self.tokens:
            if not isinstance(token, BarcodeToken) or token.kind not in ("field", "literal"):
                raise CompositionError("Barcode tokens are fields or literals.")
            if not isinstance(token.value, str) or len(token.value) > 1024:
                raise CompositionError("Invalid barcode token text.")
            if type(token.width) is not int or not 0 <= token.width <= 18:
                raise CompositionError("Barcode field width must be 0 to 18 digits.")
            if token.kind == "field" and token.value not in SYSTEM_FIELDS:
                raise CompositionError(f"Unknown barcode field: {token.value}")
            if token.kind == "literal" and (token.width or any(ord(c) < 32 for c in token.value)):
                raise CompositionError("Barcode literals must be printable and cannot have a numeric width.")

    def payload(self, fields):
        parts = []
        for token in self.tokens:
            value = token.value if token.kind == "literal" else fields[token.value]
            if token.width:
                if not value or not value.isascii() or not value.isdigit() or len(value) > token.width:
                    raise CompositionError(f"Barcode field {token.value} cannot fit {token.width} numeric digits.")
                value = value.zfill(token.width)
            parts.append(value)
        result = "".join(parts)
        if not result or len(result) > 4096:
            raise CompositionError("Barcode payload is empty or exceeds 4,096 characters.")
        return result


@dataclass
class OverlayObject:
    element: Element
    scope: str = "all_source"
    letter_page: int = 1
    control: bool = False
    profile: BarcodeProfile | None = None


@dataclass
class EnvelopeSpec:
    source: SourceInfo
    settings: EnvelopeSettings = field(default_factory=EnvelopeSettings)
    objects: list[OverlayObject] = field(default_factory=list)
    required_scope: str = "all_source"
    name: str = "Envelope overlay"
    overlay_version: int = 1
    project_kind: str = "pdf_overlay"

    def validate(self):
        if type(self.overlay_version) is not int or self.overlay_version != 1 or self.project_kind != "pdf_overlay":
            raise CompositionError("Unsupported envelope project version.")
        if not isinstance(self.name, str) or len(self.name) > 200:
            raise CompositionError("Invalid envelope project name.")
        if not isinstance(self.source.path, str) or not isinstance(self.source.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.source.sha256):
            raise CompositionError("Inspect a PDF source before saving/generating an overlay.")
        if type(self.source.size) is not int or self.source.size < 1 or type(self.source.mtime_ns) is not int:
            raise CompositionError("Invalid source fingerprint.")
        if not isinstance(self.source.geometries, list):
            raise CompositionError("Invalid source geometry.")
        if len(self.source.geometries) != self.settings.pages_per_envelope:
            raise CompositionError("Reinspect the source after changing pages per envelope.")
        import math
        for item in self.source.geometries:
            if (not isinstance(item, dict) or type(item.get("rotation")) is not int or
                item["rotation"] not in (0, 90, 180, 270) or
                any(type(item.get(key)) not in (int, float) or not math.isfinite(item[key])
                    or not 1 <= item[key] <= 2000*72/25.4 for key in ("width_pt", "height_pt"))):
                raise CompositionError("Invalid source page dimensions/rotation.")
        EnvelopePlan(self.source.pages, self.settings)
        if self.required_scope not in SCOPES[:-1]:
            raise CompositionError("Choose a supported required barcode read scope.")
        template = render_template(self)
        unknown = required_fields(template)-SYSTEM_FIELDS-{barcode_field(obj) for obj in self.objects if obj.profile}
        if unknown:
            raise CompositionError("Unknown overlay fields: " + ", ".join(sorted(unknown)))
        for obj in self.objects:
            if obj.scope not in SCOPES or type(obj.letter_page) is not int or not 1 <= obj.letter_page <= self.settings.pages_per_envelope:
                raise CompositionError("Invalid overlay object page scope.")
            if type(obj.control) is not bool or (obj.control and obj.element.type not in ("code128", "qr")):
                raise CompositionError("A machine control object must be a barcode.")
            if obj.element.type in ("code128", "qr"):
                if obj.profile is None:
                    raise CompositionError("Barcode objects need a declarative profile.")
                obj.profile.validate()
            elif obj.profile is not None:
                raise CompositionError("Only barcode objects use barcode profiles.")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        try:
            data = dict(raw)
            data["source"] = SourceInfo(**data["source"])
            data["settings"] = EnvelopeSettings(**data["settings"])
            stub = Template(width_mm=2000, height_mm=2000).to_dict()
            stub["pages"][0]["elements"] = [item["element"] for item in data["objects"]]
            parsed = Template.from_dict(stub)
            objects = []
            for item, element in zip(data["objects"], parsed.elements, strict=True):
                item = dict(item)
                profile = item.get("profile")
                if profile is not None:
                    profile = dict(profile)
                    profile["tokens"] = [BarcodeToken(**token) for token in profile["tokens"]]
                    item["profile"] = BarcodeProfile(**profile)
                item["element"] = element
                objects.append(OverlayObject(**item))
            data["objects"] = objects
            result = cls(**data)
            result.validate()
            return result
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CompositionError):
                raise
            raise CompositionError(f"Invalid envelope project: {exc}") from exc


def barcode_field(obj):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", obj.element.id):
        raise CompositionError("Overlay object IDs need 1 to 64 letters, digits or underscores.")
    return "Barcode_" + obj.element.id


def render_template(spec):
    import copy

    from composition.template.model import validate_template
    elements = []
    for obj in spec.objects:
        element = copy.deepcopy(obj.element)
        if obj.profile:
            element.value = "{{" + barcode_field(obj) + "}}"
        elements.append(element)
    template = Template(width_mm=2000, height_mm=2000, elements=elements)
    validate_template(template)
    return template


@dataclass
class OverlayJob:
    project: dict
    output_dir: str
    job_id: str = field(default_factory=new_job_id)
    chunk_size: int = 500
    auto_repair: bool = True


@dataclass
class OverlayResult:
    job_id: str
    status: str = "running"
    started_at: str = field(default_factory=now)
    finished_at: str = ""
    source_pages: int = 0
    copied_source_pages: int = 0
    rendered_inserted_blanks: int = 0
    input_envelopes: int = 0
    processed_envelopes: int = 0
    composed_envelopes: int = 0
    unverified_envelopes: int = 0
    successful_envelopes: int = 0
    failed_envelopes: int = 0
    expected_pages: int = 0
    generated_pages: int = 0
    inserted_blanks: int = 0
    sheets: int = 0
    expected_barcodes: int = 0
    rendered_barcodes: int = 0
    decoded_barcodes: int = 0
    generated_files: int = 0
    output_pdf: str = ""
    report_dir: str = ""
    error: str = ""
    error_envelope: int | None = None
    error_source_page: int | None = None
    error_output_page: int | None = None
    warnings: list[str] = field(default_factory=list)
    font_scan: dict = field(default_factory=dict)
    composer_peak_memory_bytes: int = 0
    assembler_peak_memory_bytes: int = 0
    output_size: int = 0
