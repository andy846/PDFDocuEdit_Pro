"""One resolver for naming and legacy Designer field references."""
from __future__ import annotations

from .model import CompiledTemplate, ResolvedValue, VariableContext, VariableError
from .parser import compile_template
from .transforms import apply_transform

ALIASES = {"InputName": "input.filename", "InputStem": "input.stem", "Date": "system.date",
           "Time": "system.time", "JobID": "job.id", "BatchID": "batch.id",
           "WorkflowSeq": "workflow.sequence", "EnvelopeSeq": "envelope.sequence",
           "PageCount": "input.pages", "RecordCount": "job.records"}


def _value(name, context):
    if "." not in name:
        if name in context.legacy:
            return context.legacy[name]
        if name in context.namespaces.get("record", {}):
            return context.namespaces["record"][name]
        name = ALIASES.get(name, "record." + name)
    namespace, field = name.split(".", 1)
    return context.namespaces.get(namespace, {}).get(field)


def resolve(template, context, policy="strict"):
    if policy not in ("strict", "preview"):
        raise VariableError("Variable policy must be strict or preview.")
    compiled = template if isinstance(template, CompiledTemplate) else compile_template(template)
    if not isinstance(context, VariableContext):
        raise VariableError("Resolution requires a prepared VariableContext.")
    parts, dependencies, issues, size = [], [], [], 0
    for token in compiled.tokens:
        if not token.name:
            text = token.literal
        else:
            dependencies.append(token.name)
            value = _value(token.name, context)
            for transformation in token.transforms:
                value = apply_transform(value, transformation)
                if isinstance(value, str) and len(value) > 100_000:
                    raise VariableError(f"Variable {token.name} exceeds the output limit.")
            if value is None:
                message = f"Missing field: {token.name}"
                if policy == "strict":
                    raise VariableError(message)
                issues.append(message)
                text = "[Missing: " + token.name + "]"
            elif isinstance(value, (str, int, float, bool)):
                text = str(value)
            else:
                raise VariableError(f"Variable {token.name} must contain a scalar value.")
        size += len(text)
        if size > 100_000:
            raise VariableError("Resolved output exceeds 100,000 characters.")
        parts.append(text)
    return ResolvedValue("".join(parts), tuple(dict.fromkeys(dependencies)), tuple(issues))


def validate_dependencies(template, context):
    return resolve(template, context).dependencies
