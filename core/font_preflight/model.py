"""Versioned metadata contracts. Reports never contain font binaries or text."""

from dataclasses import asdict, dataclass, field


class FontPreflightError(ValueError):
    pass


@dataclass
class FontResource:
    xref: int
    name: str
    subtype: str
    descriptor: int = 0
    encoding: str = ""
    to_unicode: bool = False
    streams: list[int] = field(default_factory=list)
    descendants: list[int] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    status: str = "NON_EMBEDDED"
    reason: str = ""
    resource_keys: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    usage: str = "Referenced resource; text invocation not verified"


@dataclass
class FontInventory:
    source_sha256: str
    page_count: int
    resources: list[FontResource]
    complete: bool = True
    issues: list[str] = field(default_factory=list)
    protected: bool = False
    policy: str = "print"
    schema_version: int = 1

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class FontSource:
    path: str
    sha256: str
    postscript_name: str
    version: str
    fs_type: int
    authorized: bool
    face_index: int = 0

    def report(self):
        value = asdict(self)
        value.pop("path")
        return value


@dataclass(frozen=True)
class MatchDecision:
    font_xref: int
    status: str
    reason: str
    source: FontSource | None = None

    def to_dict(self):
        return {
            "font_xref": self.font_xref,
            "status": self.status,
            "reason": self.reason,
            "source": self.source.report() if self.source else None,
        }


@dataclass(frozen=True)
class FontRepairPlan:
    source_sha256: str
    reference_sha256: str
    matches: tuple[MatchDecision, ...]
    schema_version: int = 1
