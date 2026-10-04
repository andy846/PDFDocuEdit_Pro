"""Serializable job/result contracts with stable identity and explicit counts."""

from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def new_job_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def validate_output_name(name):
    from composition.template.model import CompositionError
    if (not isinstance(name,str) or len(name)>160 or not name.lower().endswith(".pdf")
            or name!=Path(name).name or re.search(r'[<>:"/\\|?*\x00-\x1f]',name)
            or name.rstrip(" .")!=name or name in (".pdf","..pdf")
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",name)):
        raise CompositionError("Output needs a valid PDF filename, without folders or reserved characters.")


@dataclass
class ProductionJob:
    template: dict
    record_store: str
    output_dir: str
    job_id: str = field(default_factory=new_job_id)
    chunk_size: int = 500
    auto_repair: bool = False
    output_name: str = "production.pdf"


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
    generated_pages: int = 0
    generated_files: int = 0
    output_pdf: str = ""
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

    def to_dict(self):
        return asdict(self)
