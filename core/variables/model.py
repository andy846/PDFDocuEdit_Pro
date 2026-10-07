"""Values and clocks belong to the prepared job, never to the parser."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


class VariableError(ValueError):
    pass


@dataclass(frozen=True)
class Transform:
    name: str
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class Token:
    literal: str = ""
    name: str = ""
    transforms: tuple[Transform, ...] = ()


@dataclass(frozen=True)
class CompiledTemplate:
    text: str
    tokens: tuple[Token, ...]


@dataclass(frozen=True)
class ResolvedValue:
    value: str
    dependencies: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class VariableContext:
    namespaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    legacy: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "namespaces", copy.deepcopy(self.namespaces))
        object.__setattr__(self, "legacy", copy.deepcopy(self.legacy))

    @classmethod
    def for_job(cls, *, input_path="", job_id="", job_name="", batch_id="",
                sequence=None, frozen_at=None, record=None, **namespaces):
        clock = frozen_at if isinstance(frozen_at, datetime) else datetime.fromisoformat(frozen_at) if frozen_at else datetime.now().astimezone()
        if clock.tzinfo is None:
            raise VariableError("The prepared job time needs an explicit timezone.")
        values = {
            "system": {"date": clock.date().isoformat(), "time": clock.strftime("%H-%M-%S"),
                       "datetime": clock.isoformat(timespec="seconds")},
            "job": {"id": job_id, "name": job_name}, "batch": {"id": batch_id},
            "record": record or {}, "workflow": {},
        }
        if input_path:
            source = Path(input_path)
            values["input"] = {"filename": source.name, "stem": source.stem,
                               "extension": source.suffix, "path": str(source)}
        if sequence is not None:
            values["workflow"]["sequence"] = sequence
        for name, fields in namespaces.items():
            values.setdefault(name, {}).update(fields)
        return cls(values, record or {})

    def to_dict(self):
        return {"namespaces": copy.deepcopy(self.namespaces), "legacy": copy.deepcopy(self.legacy)}

    @classmethod
    def for_record(cls, record):
        """Borrow an owned worker record for synchronous resolution only.

        Prepared/persisted contexts still copy their data. Rendering should
        not deepcopy every complete input row for every text object.
        """
        result = object.__new__(cls)
        object.__setattr__(result, "namespaces", {})
        object.__setattr__(result, "legacy", record)
        return result
