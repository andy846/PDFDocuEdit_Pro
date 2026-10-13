"""Small typed results. Credentials are excluded from repr and diagnostics."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class Outcome(StrEnum):
    APPROVED = "approved"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"
    RELOGIN = "relogin"
    DENIED = "denied"


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Approval:
    project_ref: str
    user_id: str
    email: str
    refresh_token: str = field(repr=False)
    approved_at: str = ""
    last_verified: str = ""
    cache_version: int = 1

    def validate(self, project_ref: str) -> None:
        UUID(self.user_id)
        if self.project_ref != project_ref or self.cache_version != 1:
            raise ValueError("Approval belongs to another project or cache version.")
        if not self.refresh_token or len(self.refresh_token) > 1024 or len(self.email) > 320:
            raise ValueError("Invalid stored approval.")
        for value in (self.approved_at, self.last_verified):
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError("Approval timestamp must include a timezone.")


@dataclass(frozen=True)
class AuthResult:
    outcome: Outcome
    message: str
    approval: Approval | None = field(default=None, repr=False)
