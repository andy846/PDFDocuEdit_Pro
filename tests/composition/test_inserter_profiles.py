from dataclasses import asdict

import pytest

from composition.engine.barcode_profiles import BarcodeProfile, InsertSpec, check_digit
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.template.model import (
    CompositionError,
    ConditionGroup,
    Element,
    RuleCondition,
    Template,
    required_fields,
)


def values(envelope=1, sheet=1, total=2):
    return {"EnvelopeIndex": str(envelope), "SheetNo": str(sheet), "SheetCount": str(total), "JobSheetNo": str((envelope-1)*total+sheet)}


def test_golden_payloads_and_zero_checksum():
    profile = BarcodeProfile.inserter()
    assert profile.payload(values()) == "000000000000000000"
    assert profile.payload(values(sheet=2)) == "000100100000000006"
    assert check_digit("0"*17) == "0"
    assert len(profile.payload(values())) == 18
    assert profile.group_start == 0
    assert profile.inserter_parts(values())["group"] == "00"
    assert profile.inserter_parts(values())["sheet"] == "00"
    assert profile.inserter_parts(values(envelope=2))["group"] == "01"


@pytest.mark.parametrize("mask", range(8))
@pytest.mark.parametrize("offset", [0, 3])
def test_all_insert_combinations(mask, offset):
    profile = BarcodeProfile.inserter()
    for index in range(3):
        profile.inserts[offset+index].mode = "always" if mask & (1 << index) else "never"
    payload = profile.payload(values())
    assert payload[4+offset//3] == str(mask)
    assert payload[-1] == check_digit(payload[:17])


def test_rollover_leading_zeros_conditional_and_overflow():
    profile = BarcodeProfile.inserter()
    assert [profile.payload(values(index))[:2] for index in (98, 99, 100, 101)] == ["97", "98", "99", "00"]
    profile.customer_field = "Customer"
    profile.inserts[4] = InsertSpec("conditional", ConditionGroup(conditions=[RuleCondition("Scheme", value="A")]))
    profile.validate({"Customer", "Scheme"})
    payload = profile.payload({**values(), "Customer": "000000007", "Scheme": "A"})
    assert payload[8:17] == "000000007" and payload[5] == "2"
    with pytest.raises(CompositionError, match="nine ASCII"):
        profile.payload({**values(), "Customer": "7", "Scheme": "A"})
    with pytest.raises(CompositionError, match="99 physical"):
        profile.payload({**values(total=100), "Customer": "000000007", "Scheme": "A"})


def test_versioned_migration_and_template_profile_roundtrip():
    raw = {"name": "Generic", "version": 1, "tokens": [{"kind": "literal", "value": "000012", "width": 0}]}
    migrated = BarcodeProfile.from_dict(raw)
    assert migrated.version == 2 and migrated.payload({}) == "000012"
    assert raw["version"] == 1
    element = Element(type="i25", width_mm=100, barcode_profile=asdict(BarcodeProfile.inserter()))
    template = Template(elements=[element])
    reopened = Template.from_dict(template.to_dict())
    assert reopened.template_version == 12 and reopened.elements[0].barcode_profile == element.barcode_profile
    assert required_fields(reopened) == set()
    legacy = template.to_dict()
    legacy["template_version"] = 10
    with pytest.raises(CompositionError, match="version 11"):
        Template.from_dict(legacy)


def test_duplex_sheet_context_has_same_payload_both_sides():
    profile = BarcodeProfile.inserter()
    plan = EnvelopePlan(4, EnvelopeSettings(pages_per_envelope=4, duplex=True))
    payloads = [profile.payload(page.fields()) for page in plan.pages()]
    assert payloads[0] == payloads[1] == "000000000000000000"
    assert payloads[2] == payloads[3] == "000100100000000006"


def test_job_sequence_crosses_envelopes_and_legacy_requires_explicit_update():
    from composition.engine.barcode_profiles import require_current_inserters, updated_inserter
    profile = BarcodeProfile.inserter()
    plan = EnvelopePlan(5, EnvelopeSettings(groups=[[1, 3], [4, 5]]))
    parts = [profile.inserter_parts(p.fields()) for p in plan.pages()]
    assert [p["group"] for p in parts] == ["00", "00", "00", "01", "01"]
    assert [p["sheet"] for p in parts] == ["00", "01", "02", "03", "04"]
    assert [p["eog"] for p in parts] == ["0", "0", "1", "0", "1"]
    legacy = BarcodeProfile.from_dict({"version": 2, "preset": profile.preset, "group_start": 5})
    assert legacy.inserter_parts(plan.page(2, 1).fields())["sheet"] == "00"
    with pytest.raises(CompositionError, match="confirm Update I25"):
        require_current_inserters([("old", legacy)])
    upgraded = updated_inserter(legacy)
    require_current_inserters([("old", upgraded)])
    assert upgraded.group_start == 0 and upgraded.sheet_sequence_scope == "job"
    assert legacy.group_start == 5 and legacy.version == 2
    assert BarcodeProfile.from_dict(upgraded.to_dict()).payload(plan.page(2, 1).fields()) == profile.payload(plan.page(2, 1).fields())


def test_job_sheet_context_missing_is_not_guessed():
    with pytest.raises(CompositionError, match="physical sheet number"):
        BarcodeProfile.inserter().payload({"EnvelopeIndex": "2", "SheetNo": "1", "SheetCount": "1"})
