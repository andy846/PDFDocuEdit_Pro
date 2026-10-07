"""Serializable job/result contracts with stable identity and explicit counts."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def new_job_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def validate_output_name(name):
    from composition.template.model import CompositionError
    from core.variables import VariableError, validate_filename
    try:
        validate_filename(name, extension=".pdf")
    except VariableError as exc:
        raise CompositionError("Output needs a valid PDF filename, without folders or reserved characters.") from exc


def validate_output_template(name):
    from composition.template.model import CompositionError
    from core.variables import VariableError, compile_template
    if isinstance(name, str) and "{{" in name:
        try:
            compile_template(name)
            if not name.lower().endswith(".pdf"):
                raise VariableError("Output naming template must end in .pdf.")
        except VariableError as exc:
            raise CompositionError(str(exc)) from exc
    else:
        validate_output_name(name)


def resolve_output_name(name, context):
    from composition.template.model import CompositionError
    from core.variables import VariableContext, VariableError, resolve_filename
    validate_output_template(name)
    try:
        if "{{" not in name:
            return name
        return resolve_filename(name, VariableContext(**context), extension=".pdf").value
    except VariableError as exc:
        raise CompositionError(f"Output naming: {exc}") from exc


@dataclass
class ProductionJob:
    template: dict
    record_store: str
    output_dir: str
    job_id: str = field(default_factory=new_job_id)
    chunk_size: int = 500
    auto_repair: bool = False
    output_name: str = "production.pdf"
    variable_context: dict = field(default_factory=dict)

    def __post_init__(self):
        from core.variables import VariableContext
        if not self.variable_context:
            self.variable_context = VariableContext.for_job(
                input_path=self.template.get("data", {}).get("path", ""),
                job_id=self.job_id, job_name=self.template.get("name", ""),
                production={"template": self.template.get("name", "")},
            ).to_dict()

    def resolved_output_name(self):
        return resolve_output_name(self.output_name, self.variable_context)


@dataclass
class JobResult:
    job_id: str
    status: str = "running"
    started_at: str = field(default_factory=now)
    finished_at: str = ""
    input_records: int = 0
    processed_records: int = 0
    successful_records: int = 0
    failed_records: int = 0
    pages_per_record: int = 1
    expected_pages: int = 0
    printing: str = "simplex"
    sheets: int = 0
    inserted_blanks: int = 0
    generated_pages: int = 0
    generated_files: int = 0
    output_pdf: str = ""
    output_ps: str = ""
    report_dir: str = ""
    output_size: int = 0
    composer_peak_memory_bytes: int = 0
    assembler_peak_memory_bytes: int = 0
    error: str = ""
    error_record: int | None = None
    repaired_glyphs: int = 0
    repaired_records: int = 0
    glyph_repair_report: str = ""
    warnings: list[str] = field(default_factory=list)
    rule_summary: dict = field(default_factory=dict)
    font_scan: dict = field(default_factory=dict)
    auto_repair: bool = False
    media_summary: dict = field(default_factory=dict)
    expected_barcodes: int = 0
    rendered_barcodes: int = 0
    decoded_barcodes: int = 0

    def to_dict(self):
        return asdict(self)
