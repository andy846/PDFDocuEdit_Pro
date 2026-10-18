"""Headless, byte-based production limits; system bounds cannot be disabled."""

from dataclasses import asdict, dataclass, field

from composition.template.model import CompositionError

SYSTEM_MAX_BYTES = 2_000_000_000
MAX_PART_PAGES = 20_000
MAX_PARTS = 10_000
POLICY_REVISION = 1


class OutputPartTooLarge(CompositionError):
    def __init__(self, kind, actual, limit):
        self.kind, self.actual, self.limit = kind, actual, limit
        super().__init__(f"{kind} size {actual:,} bytes exceeds {limit:,} bytes.")


@dataclass(frozen=True)
class OutputPolicy:
    pdf_bytes: int = SYSTEM_MAX_BYTES
    ps_bytes: int = SYSTEM_MAX_BYTES
    envelopes: int = 0
    naming: dict = field(default_factory=dict)
    version: int = POLICY_REVISION

    @classmethod
    def recommended(cls):
        return cls(250_000_000, 500_000_000, 1000, {"mode": "summary", "single": True})

    @classmethod
    def from_dict(cls, raw=None):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict) or set(raw) - {
            "pdf_bytes",
            "ps_bytes",
            "envelopes",
            "naming",
            "version",
        }:
            raise CompositionError("Invalid output policy fields.")
        values = dict(raw)
        for key in ("pdf_bytes", "ps_bytes"):
            value = values.get(key)
            if value is None:
                values[key] = SYSTEM_MAX_BYTES
            elif type(value) is not int or not 1_000_000 <= value <= SYSTEM_MAX_BYTES:
                raise CompositionError("Output size must be 1–2,000 MB or system-only.")
        if type(values.get("version", 1)) is not int or values.get("version", 1) != POLICY_REVISION:
            raise CompositionError("Unsupported output policy revision.")
        count = values.get("envelopes", 0)
        if type(count) is not int or not 0 <= count <= 1_000_000:
            raise CompositionError("Envelopes per part must be 0 (automatic) or 1–1,000,000.")
        from .output_naming import NamingSpec

        NamingSpec.from_dict(values.get("naming", {}))
        return cls(**values)

    def to_dict(self):
        return asdict(self)

    def check_size(self, path, kind):
        limit = min(SYSTEM_MAX_BYTES, self.ps_bytes if kind in ("PostScript", "PS") else self.pdf_bytes)
        actual = path.stat().st_size
        if actual > limit:
            raise OutputPartTooLarge(kind, actual, limit)
        return actual


def check_scratch_space(directory, estimated_pdf=0, *, postscript=False, ps_limit=SYSTEM_MAX_BYTES):
    """Conservative scratch estimate, not a promise about native converter size."""
    import shutil
    from pathlib import Path

    folder = Path(directory).resolve()
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    estimate = max(
        16 * 1024 * 1024, estimated_pdf * 3 + (min(ps_limit, estimated_pdf * 20) * 3 if postscript else 0)
    )
    free = shutil.disk_usage(folder).free
    if free < estimate:
        raise CompositionError(
            f"Insufficient temporary disk space: {free:,} bytes free; estimated scratch budget {estimate:,} bytes. Reduce envelopes per part or choose another output volume."
        )
    return {"scratch_estimate_bytes": estimate, "free_disk_bytes": free}
