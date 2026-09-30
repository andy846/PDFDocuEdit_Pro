"""Serializable job/result contracts with stable identity and explicit counts."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


def new_job_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ProductionJob:
    template: dict
    record_store: str
    output_dir: str
    job_id: str = field(default_factory=new_job_id)
    chunk_size: int = 500


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
    generated_pages: int = 0
    generated_files: int = 0
    output_pdf: str = ""
    report_dir: str = ""
    output_size: int = 0
    error: str = ""
    error_record: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
