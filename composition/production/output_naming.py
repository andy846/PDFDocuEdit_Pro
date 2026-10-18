"""Part naming adapter around the one declarative variable engine."""

from dataclasses import dataclass
from pathlib import Path

from composition.template.model import CompositionError
from core.variables import VariableContext, VariableError, compile_template, resolve, resolve_filename

SUMMARY_PATTERN = (
    '{{job.name}}_{{system.date|date:"%Y%m%d"}}_part{{part.number}}_'
    "{{part.sheet_count}}SHT_{{part.envelope_count}}ENV_{{part.print_mode_code}}"
)
PART_FIELDS = {
    "number",
    "total_number",
    "sheet_count",
    "envelope_count",
    "page_count",
    "print_mode_code",
    "first_envelope",
    "last_envelope",
}


@dataclass(frozen=True)
class NamingSpec:
    mode: str = "original"
    pattern: str = ""
    single: bool = False

    @classmethod
    def from_dict(cls, raw=None):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict) or set(raw) - {"mode", "pattern", "single"}:
            raise CompositionError("Invalid file naming settings.")
        spec = cls(**(raw or {}))
        spec.validate()
        return spec

    def validate(self):
        if self.mode not in ("original", "summary", "custom") or type(self.single) is not bool:
            raise CompositionError("Choose a valid file naming preset.")
        if not isinstance(self.pattern, str) or len(self.pattern) > 4096:
            raise CompositionError("Naming structure is too long.")
        if self.mode != "custom":
            return
        try:
            compiled = compile_template(self.pattern)
            found = 0
            for token in compiled.tokens:
                if token.literal:
                    if any(c in token.literal for c in '/\\<>:"|?*'):
                        raise VariableError("Naming structure is a filename, not a folder path.")
                    continue
                scope, _, name = token.name.partition(".")
                if token.name == "part.number":
                    found += 1
                    if token.transforms:
                        raise VariableError("The six-digit part number cannot be changed or truncated.")
                elif scope == "part":
                    if name not in PART_FIELDS or not found:
                        raise VariableError("Place changing part fields after the part number.")
                elif scope == "group":
                    if name != "value" or not found:
                        raise VariableError("Place the group value after the part number.")
                elif scope not in ("job", "system", "input", "batch", "workflow"):
                    raise VariableError("Customer rows are not job-level filename values.")
            if found != 1:
                raise VariableError("Include exactly one {{part.number}} in the naming structure.")
        except VariableError as exc:
            raise CompositionError(str(exc)) from exc


def part_filename(
    spec,
    context,
    original,
    *,
    index,
    total,
    sheets,
    envelopes,
    pages,
    duplex,
    first=None,
    last=None,
    group=None,
):
    spec.validate()
    if (
        type(index) is not int
        or type(total) is not int
        or not 1 <= index <= total <= 10000
        or any(type(n) is not int or n < 1 for n in (sheets, envelopes, pages))
        or type(duplex) is not bool
    ):
        raise CompositionError("Incomplete part counts or printing mode for file naming.")
    if spec.mode == "original" or (total == 1 and not spec.single):
        name = original if total == 1 else f"{Path(original).stem}_part{index:06}.pdf"
        from core.variables import validate_filename

        validate_filename(name, extension=".pdf")
        return name
    namespaces = context.to_dict()
    namespaces["namespaces"]["part"] = dict(
        number=f"{index:06}",
        total_number=f"{total:06}",
        sheet_count=sheets,
        envelope_count=envelopes,
        page_count=pages,
        print_mode_code="D" if duplex else "S",
    )
    if first is not None and last is not None and last - first + 1 == envelopes:
        namespaces["namespaces"]["part"].update(first_envelope=first, last_envelope=last)
    if group is not None:
        namespaces["namespaces"]["group"] = {"value": group}
    namespaces["namespaces"].setdefault("job", {}).setdefault("name", Path(original).stem)
    if not namespaces["namespaces"]["job"].get("name"):
        namespaces["namespaces"]["job"]["name"] = Path(original).stem
    template = (SUMMARY_PATTERN if spec.mode == "summary" else spec.pattern) + ".pdf"
    try:
        frozen = VariableContext(**namespaces)
        # Never let generic whole-name shortening remove the protected part number.
        expanded = resolve(template, frozen).value
        if len(expanded.encode("utf-16-le")) // 2 > 160:
            raise VariableError("Filename is too long; shorten the job name or naming structure.")
        return resolve_filename(template, frozen, extension=".pdf").value
    except VariableError as exc:
        raise CompositionError(f"Part naming: {exc}") from exc
