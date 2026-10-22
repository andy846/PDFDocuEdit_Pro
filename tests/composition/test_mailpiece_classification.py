import copy
from dataclasses import asdict

import pytest

from composition.pdf_source.model import EnvelopeSettings, SourceInfo
from composition.template.model import CompositionError
from tests.composition.test_multi_rule_detection import api as detect
from tests.composition.test_multi_rule_detection import index, profile


def api():
    from composition.pdf_source import classification

    return classification


def report():
    value = detect().detect_index(index("Regular", "continued", "Reminder"), profile())
    value["source_sha256"] = "a" * 64
    return value


def source():
    return SourceInfo(
        "source.pdf",
        "a" * 64,
        100,
        1,
        3,
        [{"width_pt": 595, "height_pt": 842, "rotation": 0}],
        geometry_mode="uniform",
    )


def test_accept_uses_compact_content_bound_descriptor_and_no_old_approval(tmp_path):
    m = api()
    value = report()
    descriptor = m.accept_report(value, tmp_path)
    assert descriptor["accepted"] and "classifications" not in descriptor and "profile" not in descriptor
    assert m.load_report(descriptor)["classifications"] == value["classifications"]
    assert m.validate_descriptor(descriptor, source(), [[1, 2], [3, 3]], []) is None
    assert "authorization" not in descriptor
    assert len(str(descriptor)) < 3000


def test_unknown_requires_explicit_classification_before_acceptance(tmp_path):
    m = api()
    value = detect().detect_index(index("Other", "continued", "Reminder"), profile())
    value["source_sha256"] = "a" * 64
    with pytest.raises(CompositionError):
        m.accept_report(value, tmp_path)
    corrected = m.classify(value, 0, "REGULAR")
    assert corrected["classifications"][0]["classification_status"] == "manual"
    assert not corrected["accepted"] and corrected["edits"][-1]["action"] == "classify"
    assert m.accept_report(corrected, tmp_path)["accepted"]


def test_split_requires_new_first_page_classification_and_merge_conflict():
    m = api()
    value = report()
    split = m.edit_report(value, 0, split_page=2)
    assert split["groups"] == [[1, 1], [2, 2], [3, 3]]
    assert split["classifications"][1]["classification_status"] == "unknown"
    assert value["groups"] == [[1, 2], [3, 3]]
    merged = m.edit_report(value, 1, merge_previous=True)
    assert merged["groups"] == [[1, 3]]
    assert merged["classifications"][0]["classification_status"] == "ambiguous"
    assert m.classify(merged, 0, "REGULAR")["classifications"][0]["template_id"] == "REGULAR"


@pytest.mark.parametrize("damage", ["source", "groups", "profile", "asset"])
def test_stale_descriptor_or_asset_rejected(tmp_path, damage):
    m = api()
    descriptor = m.accept_report(report(), tmp_path)
    if damage == "asset":
        from pathlib import Path

        Path(descriptor["classification_asset"]["path"]).write_text("{}")
    elif damage == "source":
        descriptor["source_sha256"] = "b" * 64
    elif damage == "groups":
        descriptor["groups"] = [[1, 3]]
    else:
        descriptor["profile_sha256"] = "b" * 64
    with pytest.raises(CompositionError):
        m.load_report(descriptor)


@pytest.mark.parametrize("damage", ["overlap", "missing", "template", "rules", "rows"])
def test_report_validation_rejects_inconsistent_mapping(damage):
    value = report()
    if damage == "overlap":
        value["groups"] = [[1, 2], [2, 3]]
    elif damage == "missing":
        value["groups"] = [[1, 1], [3, 3]]
    elif damage == "template":
        value["classifications"][0]["template_id"] = "NOT_CONFIGURED"
    elif damage == "rules":
        value["classifications"][0]["rule_ids"] = ["invented"]
    else:
        value["classifications"][0]["start_page"] = 2
    with pytest.raises(CompositionError):
        api().validate_report(value)


def test_descriptor_is_source_specific_not_a_reusable_profile(tmp_path):
    m = api()
    descriptor = m.accept_report(report(), tmp_path)
    from composition.pdf_source.profile_library import validate_profile

    with pytest.raises(CompositionError):
        validate_profile(descriptor)
    changed = source()
    changed.sha256 = "b" * 64
    with pytest.raises(CompositionError):
        m.validate_descriptor(descriptor, changed, [[1, 2], [3, 3]], [])


def test_manual_conflict_resolution_is_recorded():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"].append({"kind": "page_number", "auto": True})
    value = detect().detect_index(index("Regular Page 1 of 2", "Regular Page 2 of 2"), value)
    assert not detect().can_accept(value)
    changed = api().classify(value, 0, "REGULAR")
    assert detect().can_accept(changed)
    assert any(f.get("resolution") == "operator_review" for f in changed["findings"])


def classified_spec(tmp_path):
    from composition.overlay.model import EnvelopeSpec
    from composition.pdf_source.source import inspect_source
    from core.pdf_backend import fitz

    path = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for _ in range(3):
            pdf.new_page()
        pdf.save(path)
    info = inspect_source(path, EnvelopeSettings(pages_per_envelope=1), uniform=True)
    value = report()
    value["source_sha256"] = info.sha256
    raw = EnvelopeSpec(info, EnvelopeSettings(groups=value["groups"])).to_dict()
    raw.update(overlay_version=9, detection_review=api().accept_report(value, tmp_path / "audit"))
    return EnvelopeSpec.from_dict(raw)


def test_versioned_project_roundtrip_copies_classification_asset(tmp_path):
    import json
    from pathlib import Path

    from composition.overlay.serializer import load_project, save_project

    spec = classified_spec(tmp_path)
    saved = save_project(spec, tmp_path / "saved" / "customer.pdcx")
    raw = json.loads(saved.read_text(encoding="utf-8"))
    path = raw["detection_review"]["classification_asset"]["path"]
    assert not Path(path).is_absolute() and ".assets/" in path
    restored = load_project(saved)
    assert restored.overlay_version == 9
    assert api().load_report(restored.detection_review)["groups"] == spec.settings.groups


def test_asset_is_part_of_production_fingerprint(tmp_path):
    from pathlib import Path

    from composition.overlay.model import OverlayJob
    from composition.review.service import fingerprint

    spec = classified_spec(tmp_path)
    raw = {"kind": "overlay", "job": asdict(OverlayJob(spec.to_dict(), str(tmp_path / "out")))}
    hashes = {}
    fingerprint(raw, resource_hashes=hashes)
    asset = Path(spec.detection_review["classification_asset"]["path"])
    assert str(asset.resolve()) in hashes


def test_edit_does_not_reuse_old_conflict_approval():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"].append({"kind": "page_number", "auto": True})
    value = detect().detect_index(index("Regular Page 1 of 2", "Regular Page 2 of 2"), value)
    confirmed = api().classify(value, 0, "REGULAR")
    changed = api().edit_report(confirmed, 0, split_page=2)
    assert not any(f.get("resolution") for f in changed["findings"] if f["blocking"])


def test_workflow_roundtrip_owns_group_classification_asset(tmp_path):
    import json
    from pathlib import Path

    from tests.test_workflow_core import configured
    from workflow.serializer import load_workflow, save_workflow

    spec = classified_spec(tmp_path)
    workflow = configured(Path(spec.source.path), tmp_path / "output")
    workflow.node("group").params = {
        "method": "reviewed_detection",
        "detection_review": copy.deepcopy(spec.detection_review),
    }
    saved = Path(save_workflow(workflow, tmp_path / "saved" / "customer.pdflow"))
    raw = json.loads(saved.read_text(encoding="utf-8"))
    group = next(n for n in raw["nodes"] if n["kind"] == "group")
    asset = group["params"]["detection_review"]["classification_asset"]["path"]
    assert not Path(asset).is_absolute()
    Path(spec.detection_review["classification_asset"]["path"]).unlink()
    restored = load_workflow(saved)
    assert api().load_report(restored.node("group").params["detection_review"])["groups"] == [[1, 2], [3, 3]]


def test_workflow_mapping_uses_original_envelope_not_new_ordinal(tmp_path):
    m = api()
    descriptor = m.accept_report(report(), tmp_path / "old")
    mapped_source = source()
    mapped_source.pages = 1
    mapped_source.sha256 = "b" * 64
    remapped = m.remap_report(
        descriptor, mapped_source, [[1, 1]], [2], tmp_path / "new", original_groups=descriptor["groups"]
    )
    loaded = m.load_report(remapped)
    assert loaded["classifications"][0]["template_id"] == "REMINDER"
    assert loaded["source_sha256"] == "b" * 64
    assert loaded["edits"][-1]["original_source_sha256"] == "a" * 64
    assert loaded["edits"][-1]["selected"] == [2]
    with pytest.raises(CompositionError):
        m.remap_report(
            descriptor, mapped_source, [[1, 1]], [1], tmp_path / "bad", original_groups=descriptor["groups"]
        )


def test_large_boundary_edit_does_not_rescan_every_classification_per_row():
    class CountedRows(list):
        iterations = 0

        def __iter__(self):
            type(self).iterations += 1
            return super().__iter__()

    value = detect().detect_index(index(*(["Regular"] * 300)), profile())
    value["classifications"] = CountedRows(value["classifications"])
    CountedRows.iterations = 0
    changed = api().edit_report(value, 1, merge_previous=True)
    assert len(changed["groups"]) == 299 and changed["groups"][0] == [1, 2]
    assert CountedRows.iterations <= 10, "Boundary editing repeatedly scanned all mailpieces"


def test_remap_rejects_missing_original_range_proof_after_workflow_edits(tmp_path):
    m = api()
    value = detect().detect_index(
        index("Regular", "Reminder", "Third", "continued"), profile("Regular", "Reminder", "Third")
    )
    value["source_sha256"] = "a" * 64
    accepted = m.accept_report(value, tmp_path / "accepted")
    derived = source()
    derived.sha256 = "b" * 64
    derived.pages = 1
    # Current Review merge/split: [1-2], [3], [4]. Retained current ordinal 2
    # comes from old THIRD, while old ordinal 2 was REMINDER (both one page).
    with pytest.raises(CompositionError, match="original|boundar|classif"):
        m.remap_report(accepted, derived, [[1, 1]], [2], tmp_path / "wrong-map")


def test_remap_rejects_changed_original_ranges_even_when_lengths_match(tmp_path):
    m = api()
    value = detect().detect_index(
        index("Regular", "Reminder", "Third", "continued"), profile("Regular", "Reminder", "Third")
    )
    value["source_sha256"] = "a" * 64
    accepted = m.accept_report(value, tmp_path / "accepted")
    derived = source()
    derived.sha256 = "b" * 64
    derived.pages = 1
    with pytest.raises(CompositionError, match="original|boundar|classif"):
        m.remap_report(
            accepted, derived, [[1, 1]], [2], tmp_path / "wrong-map", original_groups=[[1, 2], [3, 3], [4, 4]]
        )



def test_original_range_proof_is_required_even_if_derived_snapshot_matches(tmp_path):
    from composition.overlay.model import EnvelopeSpec
    from workflow.engine import detection_audit
    descriptor = api().accept_report(report(), tmp_path / "accepted")
    spec = EnvelopeSpec(source(), EnvelopeSettings(groups=descriptor["groups"]), overlay_version=9, detection_review=descriptor)
    with pytest.raises(CompositionError, match="original|boundar|classif"):
        detection_audit(spec, descriptor, selected=[1, 2], directory=tmp_path / "mapped", original_groups=[[1, 1], [2, 3]])
