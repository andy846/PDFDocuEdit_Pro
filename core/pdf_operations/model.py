"""Explicit operation plans and audit results; no passwords in persisted models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


class PdfOperationError(ValueError):
    pass


@dataclass(frozen=True)
class PdfOptions:
    operation: str = "flatten"
    mode: str = "safe"
    pages: tuple[int, ...] | None = None
    annotations: bool = True
    forms: bool = False
    rasterise: bool = False
    dpi: int = 300
    remove_javascript: bool = False
    remove_attachments: bool = False
    remove_metadata: bool = False
    normalise_boxes: bool = False
    preflight: bool = False
    allow_preflight_errors: bool = False
    acknowledge_signatures: bool = False
    acknowledge_raster: bool = False
    acknowledge_recovery: bool = False

    def validate(self, page_count=None):
        if self.operation not in ("flatten", "repair") or self.mode not in ("safe", "normalise", "maximum"):
            raise PdfOperationError("Unsupported PDF operation or mode.")
        for key, value in asdict(self).items():
            if key not in ("operation", "mode", "pages", "dpi") and type(value) is not bool:
                raise PdfOperationError(f"{key} must be a boolean.")
        if type(self.dpi) is not int or not 72 <= self.dpi <= 1200:
            raise PdfOperationError("Raster resolution must be between 72 and 1,200 dpi.")
        if self.pages is not None and (not self.pages or len(set(self.pages)) != len(self.pages)
                or any(type(p) is not int or p < 0 or (page_count is not None and p >= page_count) for p in self.pages)):
            raise PdfOperationError("Choose valid, distinct page numbers.")
        if self.operation == "repair" and self.mode == "safe" and (
                self.forms or self.rasterise or self.remove_javascript or self.remove_attachments
                or self.remove_metadata or self.normalise_boxes):
            raise PdfOperationError("Safe Repair cannot apply destructive normalisation options.")
        if self.operation == "repair" and self.mode == "maximum" and self.pages is not None:
            raise PdfOperationError("Maximum Compatibility rebuilds the entire document.")

    @classmethod
    def from_dict(cls, raw):
        values = dict(raw)
        if values.get("pages") is not None:
            values["pages"] = tuple(values["pages"])
        try:
            result = cls(**values)
            result.validate()
            return result
        except (TypeError, KeyError) as exc:
            raise PdfOperationError("Invalid PDF operation options.") from exc


@dataclass(frozen=True)
class PdfOperationPlan:
    source: str
    source_sha256: str
    options: PdfOptions
    page_count: int
    annotations: int = 0
    forms: int = 0
    signed: bool = False
    encrypted: bool = False
    issues: tuple[str, ...] = ()
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        values = dict(raw)
        values["options"] = PdfOptions.from_dict(values["options"])
        values["issues"] = tuple(values.get("issues", ()))
        return cls(**values)


def checked_source(value):
    source = Path(value).expanduser().resolve()
    if not source.is_file():
        raise PdfOperationError("Source PDF does not exist.")
    return source
