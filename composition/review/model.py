"""Runtime-only contracts. No project schema or persisted approval changes."""
from dataclasses import dataclass, field


@dataclass
class ReviewContext:
    kind: str
    job: dict
    label: str = ""
    identity: str = ""
    external_database: str = ""
    external_data: str = ""
    binding: dict = field(default_factory=dict)
    outputs: list = field(default_factory=list)


@dataclass
class ReviewIssue:
    severity: str
    reason: str
    envelope: int = 0
    output_page: int = 0
    template_page: int = 0
    object_id: str = ""
    field: str = ""
    action: str = "settings"


@dataclass
class ReviewSnapshot:
    snapshot_id: str
    fingerprint: str
    status: str
    summary: dict
    issues: list
    complete: bool = False
