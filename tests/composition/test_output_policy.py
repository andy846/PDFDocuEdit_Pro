"""Strict production limits and sortable, physical-count output naming."""

from datetime import datetime

import pytest

from composition.template.model import CompositionError
from core.variables import VariableContext


def context():
    return VariableContext.for_job(
        job_id="stable", job_name="Statement", frozen_at=datetime.fromisoformat("2026-10-17T09:00:00+08:00")
    )


def test_system_limits_apply_to_legacy_and_recommended_jobs():
    from composition.production.output_policy import OutputPolicy

    legacy = OutputPolicy.from_dict({})
    assert legacy.pdf_bytes == legacy.ps_bytes == 2_000_000_000
    policy = OutputPolicy.recommended()
    assert (policy.pdf_bytes, policy.ps_bytes, policy.envelopes) == (250_000_000, 500_000_000, 1000)
    assert OutputPolicy.from_dict(policy.to_dict()) == policy


@pytest.mark.parametrize(
    "key,value",
    [
        ("pdf_bytes", 0),
        ("pdf_bytes", True),
        ("ps_bytes", -1),
        ("ps_bytes", 2_000_000_001),
        ("envelopes", True),
        ("envelopes", -1),
        ("version", 2),
        ("code", "eval"),
    ],
)
def test_invalid_limits_cannot_disable_or_raise_system_safety(key, value):
    from composition.production.output_policy import OutputPolicy

    with pytest.raises(CompositionError):
        OutputPolicy.from_dict({key: value})


def test_summary_names_use_part_counts_mode_and_frozen_clock():
    from composition.production.output_naming import NamingSpec, part_filename

    spec = NamingSpec(mode="summary", single=True)
    name = part_filename(
        spec,
        context(),
        "production.pdf",
        index=1,
        total=12,
        sheets=2000,
        envelopes=1000,
        pages=4000,
        duplex=True,
        first=1,
        last=1000,
    )
    assert name == "Statement_20261017_part000001_2000SHT_1000ENV_D.pdf"
    assert part_filename(
        spec,
        context(),
        "production.pdf",
        index=2,
        total=12,
        sheets=30,
        envelopes=10,
        pages=30,
        duplex=False,
        first=1001,
        last=1010,
    ).endswith("part000002_30SHT_10ENV_S.pdf")


@pytest.mark.parametrize(
    "pattern",
    [
        "same",
        "{{part.number|truncate:2}}",
        "{{group.value}}_{{part.number}}",
        "../{{part.number}}",
        "{{record.Name}}_{{part.number}}",
    ],
)
def test_patterns_must_preserve_order_and_cannot_embed_routes_or_customer_rows(pattern):
    from composition.production.output_naming import NamingSpec

    with pytest.raises(CompositionError):
        NamingSpec(mode="custom", pattern=pattern).validate()


def test_totals_and_original_name_compatibility():
    from composition.production.output_naming import NamingSpec, part_filename

    kwargs = dict(index=1, total=12, sheets=4, envelopes=2, pages=8, duplex=True, first=1, last=2)
    assert part_filename(NamingSpec(), context(), "letters.pdf", **kwargs) == "letters_part000001.pdf"
    assert part_filename(NamingSpec(), context(), "letters.pdf", **{**kwargs, "total": 1}) == "letters.pdf"
    spec = NamingSpec(
        mode="custom", pattern="{{job.name}}_{{part.number}}_of{{part.total_number}}", single=True
    )
    assert part_filename(spec, context(), "letters.pdf", **kwargs) == "Statement_000001_of000012.pdf"


def test_long_names_are_rejected_instead_of_truncating_part_identity():
    from composition.production.output_naming import NamingSpec, part_filename

    with pytest.raises(CompositionError, match="long"):
        part_filename(
            NamingSpec(mode="custom", pattern="X" * 155 + "{{part.number}}", single=True),
            context(),
            "a.pdf",
            index=1,
            total=2,
            sheets=1,
            envelopes=1,
            pages=1,
            duplex=False,
            first=1,
            last=1,
        )
