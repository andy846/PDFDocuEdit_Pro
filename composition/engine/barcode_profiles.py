"""Declarative barcode profiles shared by template and overlay engines; no Qt."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from composition.pdf_source.planner import SYSTEM_FIELDS
from composition.template.model import CompositionError, ConditionGroup, ElementRules

from .generic_layout import CONTEXT_KEY, BarcodeContext, BarcodeSegment, evaluate_layout, validate_layout

INSERTER_I25 = "inserter_i25_18"


def check_digit(body):
    if not isinstance(body, str) or len(body) != 17 or not body.isascii() or not body.isdigit():
        raise CompositionError("Inserter checksum requires exactly 17 ASCII digits.")
    return str((-sum(int(digit)*(3 if index % 2 == 0 else 1)
                     for index, digit in enumerate(body))) % 10)


@dataclass
class InsertSpec:
    mode: str = "never"
    when: ConditionGroup | None = None

    def validate(self):
        from .rules import validate_group
        if self.mode not in {"never", "always", "conditional"}:
            raise CompositionError("Choose Never, Always or Conditional for each insert.")
        if self.mode == "conditional":
            validate_group(self.when)
        elif self.when is not None:
            raise CompositionError("Only conditional inserts can have a condition.")

    @classmethod
    def from_dict(cls, raw):
        values = dict(raw)
        if values.get("when") is not None:
            values["when"] = ElementRules.from_dict({"visible_when": values["when"]}).visible_when
        return cls(**values)

@dataclass
class BarcodeToken:
    kind: str = "field"
    value: str = "EnvelopeSeq"
    width: int = 0


@dataclass
class BarcodeProfile:
    name: str = "Generic envelope identifier"
    version: int = 2
    machine: str = ""
    validation: str = "pending"
    tokens: list[BarcodeToken] = field(default_factory=lambda: [BarcodeToken(),
                   BarcodeToken(value="LetterPage", width=2), BarcodeToken(value="LetterPageCount", width=2)])
    preset: str = "generic"
    group_start: int = 0
    inserts: list[InsertSpec] = field(default_factory=lambda: [InsertSpec() for _ in range(6)])
    customer_field: str = ""
    layout_mode: str = "legacy"
    total_length: int = 0
    segments: list[BarcodeSegment] = field(default_factory=list)

    @classmethod
    def fixed_layout(cls, total_length=0, segments=None, **kwargs):
        return cls(version=3, layout_mode="fixed", total_length=total_length, segments=segments or [], **kwargs)

    @classmethod
    def inserter(cls):
        return cls(name="Inserter I25 — 18 digits", preset=INSERTER_I25)

    @classmethod
    def from_dict(cls, raw):
        try:
            values = dict(raw)
            version = values.get("version", 1)
            if type(version) is not int or version not in {1, 2, 3}:
                raise CompositionError("Unsupported barcode profile version.")
            if version == 1 and any(k in values for k in ("preset", "group_start", "inserts", "customer_field")):
                raise CompositionError("Inserter options require barcode profile version 2.")
            if version < 3 and (values.get("layout_mode", "legacy") != "legacy" or
                                values.get("total_length", 0) or values.get("segments")):
                raise CompositionError("Fixed-length layouts require barcode profile version 3.")
            values["version"] = max(2, version)
            if "segments" in values:
                if not isinstance(values["segments"], list) or len(values["segments"]) > 30:
                    raise CompositionError("Use at most 30 barcode segments.")
                values["segments"] = [BarcodeSegment(**s) for s in values["segments"]]
            if "tokens" in values:
                values["tokens"] = [BarcodeToken(**token) for token in values["tokens"]]
            if "inserts" in values:
                if not isinstance(values["inserts"], list) or len(values["inserts"]) != 6:
                    raise CompositionError("Configure exactly six insert positions.")
                values["inserts"] = [InsertSpec.from_dict(item) for item in values["inserts"]]
            return cls(**values)
        except (TypeError, KeyError, ValueError) as exc:
            raise CompositionError(f"Invalid barcode profile: {exc}") from exc

    def to_dict(self):
        values = asdict(self)
        if self.version < 3:
            for key in ("layout_mode", "total_length", "segments"):
                values.pop(key)
        return values

    def fields(self):
        from .rules import rule_fields
        if self.preset == "generic":
            if self.layout_mode == "fixed":
                return {s.value for s in self.segments if s.source in {"data", "system", "sequence"} and s.value}
            return {token.value for token in self.tokens if token.kind == "field"}
        values = {self.customer_field} if self.customer_field else set()
        for insert in self.inserts:
            values.update(rule_fields(ElementRules(visible_when=insert.when)))
        return values

    def required_fields(self):
        if self.preset == "generic" and self.layout_mode == "fixed":
            return {s.value for s in self.segments if s.source in {"data", "sequence"} and s.value}
        return self.fields()-SYSTEM_FIELDS

    def evaluate(self, values):
        if self.preset != "generic" or self.layout_mode != "fixed":
            raise CompositionError("Segment evaluation requires a fixed-length Generic profile.")
        return evaluate_layout(self.total_length, self.segments, values)

    def validate(self, allowed_fields=()):
        if type(self.version) is not int or self.version not in {1, 2, 3} or self.validation not in ("pending", "user_verified"):
            raise CompositionError("Unsupported barcode profile version/validation state.")
        if not isinstance(self.name, str) or not self.name or len(self.name) > 200:
            raise CompositionError("Give the barcode profile a name of at most 200 characters.")
        if not isinstance(self.machine, str) or len(self.machine) > 200:
            raise CompositionError("Invalid machine profile name.")
        if self.validation == "user_verified" and not self.machine:
            raise CompositionError("A user-verified profile must identify the machine.")
        if self.preset not in {"generic", INSERTER_I25}:
            raise CompositionError("Unsupported barcode preset.")
        if self.preset == INSERTER_I25:
            if self.version not in {2, 3}:
                raise CompositionError("Inserter I25 requires barcode profile version 2.")
            if type(self.group_start) is not int or not 0 <= self.group_start <= 99:
                raise CompositionError("Group sequence start must be 00 to 99.")
            if not isinstance(self.inserts, list) or len(self.inserts) != 6:
                raise CompositionError("Configure exactly six insert positions.")
            if not isinstance(self.customer_field, str):
                raise CompositionError("Choose a customer information field or nine zeros.")
            for insert in self.inserts:
                if not isinstance(insert, InsertSpec):
                    raise CompositionError("Invalid insert configuration.")
                insert.validate()
            unknown = self.fields()-set(allowed_fields)-SYSTEM_FIELDS
            if unknown:
                raise CompositionError("Unknown barcode field: " + ", ".join(sorted(unknown)))
            return
        if self.layout_mode not in {"legacy", "fixed"}:
            raise CompositionError("Unknown Generic barcode layout mode.")
        if self.layout_mode == "legacy" and (self.segments or self.total_length):
            raise CompositionError("Legacy barcode profiles cannot contain fixed-length segments.")
        if self.layout_mode == "fixed":
            if self.version != 3:
                raise CompositionError("Fixed-length layouts require barcode profile version 3.")
            validate_layout(self.total_length, self.segments)
            unknown = self.required_fields()-set(allowed_fields)
            if unknown:
                raise CompositionError("Unknown barcode field: " + ", ".join(sorted(unknown)))
            return
        if not isinstance(self.tokens, list) or not 1 <= len(self.tokens) <= 30:
            raise CompositionError("A barcode profile needs 1 to 30 tokens.")
        for token in self.tokens:
            if not isinstance(token, BarcodeToken) or token.kind not in ("field", "literal"):
                raise CompositionError("Barcode tokens are fields or literals.")
            if not isinstance(token.value, str) or len(token.value) > 1024:
                raise CompositionError("Invalid barcode token text.")
            if type(token.width) is not int or not 0 <= token.width <= 18:
                raise CompositionError("Barcode field width must be 0 to 18 digits.")
            if token.kind == "field" and token.value not in SYSTEM_FIELDS and token.value not in allowed_fields:
                raise CompositionError(f"Unknown barcode field: {token.value}")
            if token.kind == "literal" and (token.width or any(ord(c) < 32 for c in token.value)):
                raise CompositionError("Barcode literals must be printable and cannot have a numeric width.")

    def payload(self, fields):
        if self.preset == INSERTER_I25:
            return self.inserter_parts(fields)["payload"]
        if self.layout_mode == "fixed":
            return self.evaluate(fields).payload
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

    def inserter_parts(self, fields):
        from .rules import CompiledGroup, RuleValueError
        values = []
        for key in ("EnvelopeIndex", "SheetNo", "SheetCount"):
            value = fields.get(key, "")
            if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 18:
                raise RuleValueError(key, "Physical sheet context is required for Inserter I25.")
            values.append(int(value))
        envelope, sheet, count = values
        if envelope < 1 or not 1 <= sheet <= count <= 99:
            raise CompositionError("Inserter I25 requires 1–99 physical sheets per envelope and a valid sheet number.")
        masks = [0, 0]
        for index, insert in enumerate(self.inserts):
            enabled = insert.mode == "always" or (insert.mode == "conditional" and CompiledGroup(insert.when).matches(fields))
            if enabled:
                masks[index//3] += 1 << (index % 3)
        customer = fields.get(self.customer_field) if self.customer_field else "000000000"
        if not isinstance(customer, str) or len(customer) != 9 or not customer.isascii() or not customer.isdigit():
            raise RuleValueError(self.customer_field or "CustomerInformation", "Expected exactly nine ASCII digits; leading zeros are preserved.")
        group = f"{(self.group_start+envelope-1) % 100:02d}"
        page = f"{sheet-1:02d}"
        eog = str(int(sheet == count))
        body = group+page+str(masks[0])+str(masks[1])+eog+"0"+customer
        digit = check_digit(body)
        return {"group": group, "sheet": page, "inserts_1_3": str(masks[0]), "inserts_4_6": str(masks[1]),
                "eog": eog, "location": "0", "customer": customer, "check_digit": digit, "payload": body+digit}


def has_profiles(template):
    cached = getattr(template, "_has_barcode_profiles", None)
    return cached if cached is not None else any(element.barcode_profile for element in template.all_elements())


def has_inserter(template):
    cached = getattr(template, "_has_inserter_profiles", None)
    return cached if cached is not None else any(element.barcode_profile.get("preset") == INSERTER_I25 for element in template.all_elements())


def profile_record(template, record, ordinal, page_index):
    """Attach physical context to a copy; never overwrite imported field values."""
    if not has_profiles(template):
        return record
    from composition.media.planner import build_print_plan
    key = repr((template.media, [(p.id, p.width_mm, p.height_mm) for p in template.pages]))
    if getattr(template, "_barcode_context_key", None) != key:
        plan = build_print_plan(template, 1)
        contexts = {p.role: p.fields() for p in plan.pages() if p.source_page is not None}
        template._barcode_contexts = contexts
        template._barcode_output_count = plan.output_pages
        template._barcode_context_key = key
    context = dict(template._barcode_contexts[page_index])
    context.update(EnvelopeIndex=str(ordinal), EnvelopeSeq=str(ordinal).zfill(18),
                   EnvelopeCount=str(getattr(template, "_barcode_record_count", template.generated_count if template.record_mode == "generated" else 1)),
                   OutputPage=str(int(context["OutputPage"])+(ordinal-1)*template._barcode_output_count))
    # Legacy concatenation retains its historical values. New layouts have an
    # explicit runtime-job identity; preview uses a clearly provisional ID.
    typed = {**context, "JobId": getattr(template, "_barcode_job_id", "00000000-000000-00000000")}
    return {**record, **{"__Barcode"+k: v for k, v in context.items()},
            CONTEXT_KEY: BarcodeContext(dict(record), typed)}


def profile_values(record):
    return {**record, **{key[len("__Barcode"):]: value for key, value in record.items()
                        if key.startswith("__Barcode") and key != CONTEXT_KEY}}


