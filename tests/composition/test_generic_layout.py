import copy

import pytest

from composition.engine.barcode_profiles import BarcodeProfile, BarcodeToken
from composition.engine.generic_layout import BarcodeContext, BarcodeSegment, SegmentError
from composition.template.model import CompositionError, Element, Template, required_fields


def profile(*segments, total=None):
    return BarcodeProfile.fixed_layout(sum(s.length for s in segments) if total is None else total, list(segments))


def test_numeric_padding_and_text_identity():
    number = BarcodeSegment(name="Envelope", source="system", value="EnvelopeSeq", format="numeric", length=2)
    p = profile(number)
    assert p.payload(BarcodeContext(system={"EnvelopeSeq": "000000000000000001"})) == "01"
    assert p.payload(BarcodeContext(system={"EnvelopeSeq": "000000"})) == "00"
    account = BarcodeSegment(name="Account", source="data", value="Account", length=6)
    assert profile(account).payload(BarcodeContext(data={"Account": "000123"})) == "000123"
    with pytest.raises(SegmentError, match="exactly 6"):
        profile(account).payload(BarcodeContext(data={"Account": "123"}))


def test_namespaced_collision_and_existing_sequence():
    p = profile(BarcodeSegment(name="Imported", source="data", value="EnvelopeSeq", length=2),
                BarcodeSegment(name="System", source="system", value="EnvelopeSeq", format="numeric", length=2),
                BarcodeSegment(name="Existing", source="sequence", value="Seq", format="numeric", length=2))
    context = BarcodeContext(data={"EnvelopeSeq": "AB"}, system={"EnvelopeSeq": "000001"}, sequences={"Seq": "000004"})
    assert p.payload(context) == "AB0104"
    assert p.required_fields() == {"EnvelopeSeq", "Seq"}
    template = Template(elements=[Element(type="code128", barcode_profile=p.to_dict())])
    assert required_fields(template) == {"EnvelopeSeq", "Seq"}


@pytest.mark.parametrize("scope,key", [("record", "EnvelopeIndex"), ("page", "OutputPage"), ("sheet", "SheetNo")])
def test_stateless_cycles(scope, key):
    p = profile(BarcodeSegment(name="Counter", source="sequence", format="numeric", length=2, scope=scope, overflow="cycle"))
    results = [p.evaluate(BarcodeContext(system={key: str(n)})) for n in (99, 100, 101, 102, 1001)]
    assert [r.payload for r in results] == ["98", "99", "00", "01", "00"]
    assert [r.segments[0].cycled for r in results] == [False, False, True, True, True]
    assert results[-1].segments[0].raw == "1000"
    assert p.payload(BarcodeContext(system={key: "101"})) == "00"


@pytest.mark.parametrize("source", ["data", "fixed", "system"])
def test_only_running_sequences_can_cycle(source):
    p = profile(BarcodeSegment(source=source, value="EnvelopeSeq" if source == "system" else "123", format="numeric", overflow="cycle"))
    with pytest.raises(CompositionError, match="only for Numeric running"):
        p.validate(p.fields())


@pytest.mark.parametrize("value", ["", "-1", "1.2", "１２", "A001", " 1"])
def test_invalid_numeric_values_are_located(value):
    p = profile(BarcodeSegment(name="Customer number", source="data", value="Account", format="numeric", length=2))
    with pytest.raises(SegmentError, match="Customer number"):
        p.payload(BarcodeContext(data={"Account": value}))


def test_overflow_missing_total_positions_and_roundtrip():
    p = profile(BarcodeSegment(name="Counter", source="sequence", format="numeric", length=2),
                BarcodeSegment(name="Fixed", value="001", length=3))
    p.validate([])
    assert [s.position for s in p.evaluate(BarcodeContext(system={"EnvelopeIndex": "2"})).segments] == [1, 3]
    with pytest.raises(SegmentError, match="needs 3 digits"):
        p.payload(BarcodeContext(system={"EnvelopeIndex": "101"}))
    with pytest.raises(SegmentError, match="unavailable"):
        p.payload(BarcodeContext())
    bad = copy.deepcopy(p)
    bad.total_length = 6
    with pytest.raises(CompositionError, match="Configured length 5"):
        bad.validate([])
    reopened = BarcodeProfile.from_dict(p.to_dict())
    assert reopened.to_dict() == p.to_dict() and reopened.version == 3
    assert reopened.payload(BarcodeContext(system={"EnvelopeIndex": "2"})) == "01001"


def test_legacy_contract_and_profile_version_security():
    p = BarcodeProfile(tokens=[BarcodeToken(value="EnvelopeSeq", width=2)])
    assert p.payload({"EnvelopeSeq": "01"}) == "01"
    with pytest.raises(CompositionError, match="cannot fit"):
        p.payload({"EnvelopeSeq": "000001"})
    assert BarcodeProfile.from_dict(p.to_dict()).payload({"EnvelopeSeq": "01"}) == "01"
    raw = profile(BarcodeSegment(value="00", length=2)).to_dict()
    raw["version"] = 2
    with pytest.raises(CompositionError, match="version 3"):
        BarcodeProfile.from_dict(raw)
    assert BarcodeProfile.from_dict({"version": 1, "tokens": [{"kind": "literal", "value": "0001", "width": 0}]}).payload({}) == "0001"


def test_context_preserves_imported_system_names_in_rendering():
    from composition.data.sequences import sequence_record
    from composition.engine.rules import ElementPlan
    from composition.template.model import SequenceSpec
    p = profile(BarcodeSegment(name="Data", source="data", value="EnvelopeSeq", length=2),
                BarcodeSegment(name="Physical sheet", source="system", value="SheetNo", length=2, format="numeric"),
                BarcodeSegment(name="Sequence", source="sequence", value="Seq", length=2, format="numeric"))
    element = Element(type="code128", barcode_profile=p.to_dict())
    template = Template(elements=[element], sequences=[SequenceSpec(name="Seq", padding=4)])
    record = sequence_record(template, {"EnvelopeSeq": "AB"}, 2)
    assert ElementPlan(element).resolve(record).value == "AB0102"
    assert record["EnvelopeSeq"] == "AB"
