"""Bounded declarative conditions shared by preview, glyph preflight and production."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from composition.template.model import (
    AlternativeContent,
    CompositionError,
    ConditionGroup,
    ElementRules,
    RuleCondition,
    parse_value,
    resolve_value,
)

TEXT_OPERATORS = ("eq", "ne", "contains", "starts_with", "ends_with", "is_empty", "not_empty")
NUMBER_OPERATORS = ("eq", "ne", "gt", "ge", "lt", "le")
EMPTY_OPERATORS = ("is_empty", "not_empty")


class RuleValueError(CompositionError):
    def __init__(self, field, reason):
        self.field = field
        super().__init__(f"Field {field}: {reason}")


class RecordRuleError(CompositionError):
    def __init__(self, ordinal, element, page, reason):
        self.record_ordinal = ordinal
        field = getattr(reason, "field", "")
        super().__init__(
            f"Rule preflight: Record {ordinal}, template page {page}, object {element.id}"
            + (f", field {field}" if field else "")
            + f": {reason}"
        )


def decimal_value(value, field):
    if (
        not isinstance(value, str)
        or len(value.strip()) > 128
        or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value.strip())
    ):
        raise RuleValueError(
            field, "Expected a finite decimal number using a dot; no currency, commas or exponent."
        )
    return Decimal(value.strip())


def validate_group(group):
    if not isinstance(group, ConditionGroup) or group.mode not in ("all", "any"):
        raise CompositionError("Conditions use All or Any.")
    if not isinstance(group.conditions, list) or not 1 <= len(group.conditions) <= 20:
        raise CompositionError("An enabled condition group needs 1 to 20 conditions.")
    for condition in group.conditions:
        if not isinstance(condition, RuleCondition):
            raise CompositionError("Invalid condition.")
        if not isinstance(condition.field, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", condition.field
        ):
            raise CompositionError("Choose a mapped field name for each condition.")
        if condition.data_type not in ("text", "number"):
            raise CompositionError("Condition data type must be text or number.")
        operators = TEXT_OPERATORS if condition.data_type == "text" else NUMBER_OPERATORS
        if condition.operator not in operators:
            raise CompositionError("Unsupported comparison for this condition type.")
        if not isinstance(condition.value, str) or len(condition.value) > 10_000:
            raise CompositionError("Condition values must be text of at most 10,000 characters.")
        if condition.operator in EMPTY_OPERATORS and condition.value:
            raise CompositionError("Empty checks do not take a comparison value.")
        if condition.data_type == "number":
            decimal_value(condition.value, condition.field)


def validate_rules(element, check_assets=False):
    from pathlib import Path

    rules = element.rules
    if not isinstance(rules, ElementRules):
        raise CompositionError("Invalid object rules.")
    if rules.visible_when is not None:
        validate_group(rules.visible_when)
    if rules.alternative is not None:
        alternative = rules.alternative
        if not isinstance(alternative, AlternativeContent):
            raise CompositionError("Invalid alternative content.")
        validate_group(alternative.when)
        if element.type not in ("text", "qr", "code128", "i25", "image"):
            raise CompositionError("Alternative content requires text, barcode or image.")
        if not isinstance(alternative.image, str) or not isinstance(alternative.value, str):
            raise CompositionError("Alternative content must use static text/image references.")
        if element.type == "image":
            if alternative.value or not alternative.image:
                raise CompositionError("Select a static alternative image.")
            if check_assets and not Path(alternative.image).is_file():
                raise CompositionError(f"Alternative image not found: {alternative.image}")
        else:
            if alternative.image:
                raise CompositionError("Text alternatives cannot contain an image path.")
            parse_value(alternative.value)


def rule_fields(rules):
    groups = [rules.visible_when]
    if rules.alternative is not None:
        groups.append(rules.alternative.when)
    return {condition.field for group in groups if group is not None for condition in group.conditions}


class CompiledGroup:
    def __init__(self, group):
        validate_group(group)
        self.mode = group.mode
        self.conditions = tuple(
            (c, decimal_value(c.value, c.field) if c.data_type == "number" else c.value)
            for c in group.conditions
        )

    def matches(self, record):
        results = []
        for condition, expected in self.conditions:
            if condition.field not in record:
                raise RuleValueError(condition.field, "Missing field. Check the mapped field name.")
            value = record[condition.field]
            if not isinstance(value, str):
                raise RuleValueError(condition.field, "Imported field values must be text.")
            if condition.data_type == "number":
                value = decimal_value(value, condition.field)
            op = condition.operator
            if op == "eq":
                result = value == expected
            elif op == "ne":
                result = value != expected
            elif op == "gt":
                result = value > expected
            elif op == "ge":
                result = value >= expected
            elif op == "lt":
                result = value < expected
            elif op == "le":
                result = value <= expected
            elif op == "contains":
                result = expected in value
            elif op == "starts_with":
                result = value.startswith(expected)
            elif op == "ends_with":
                result = value.endswith(expected)
            elif op == "is_empty":
                result = value == ""
            else:
                result = value != ""
            results.append(result)
        # Evaluate every enabled condition: short-circuiting must not hide invalid numeric data.
        return all(results) if self.mode == "all" else any(results)


@dataclass(frozen=True)
class Selection:
    visible: bool
    alternative: bool = False
    value: str = ""
    image: str = ""


class ElementPlan:
    def __init__(self, element):
        validate_rules(element)
        self.element = element
        self.tokens = parse_value(element.value) if element.type in ("text", "qr", "code128", "i25") else ()
        self.alternative_tokens = (
            parse_value(element.rules.alternative.value)
            if element.rules.alternative and element.type != "image"
            else ()
        )
        self.visibility = CompiledGroup(element.rules.visible_when) if element.rules.visible_when else None
        self.alternative = (
            CompiledGroup(element.rules.alternative.when) if element.rules.alternative else None
        )
        self.fields = rule_fields(element.rules) | {
            value for kind, value in self.tokens + self.alternative_tokens if kind == "field"
        }
        self.has_rules = self.visibility is not None or self.alternative is not None

    def resolve(self, record, *, design=False):
        if not design:
            for field in self.fields:
                if field not in record:
                    raise RuleValueError(field, "Missing field. Check the mapped field name.")
            if self.visibility and not self.visibility.matches(record):
                return Selection(False)
        alternate = bool(not design and self.alternative and self.alternative.matches(record))
        image = self.element.rules.alternative.image if alternate else self.element.image
        tokens = self.alternative_tokens if alternate else self.tokens
        return Selection(True, alternate, resolve_value(tokens, record) if tokens else "", image)

    def selected_fields(self, alternate):
        return [
            value
            for kind, value in (self.alternative_tokens if alternate else self.tokens)
            if kind == "field"
        ]
