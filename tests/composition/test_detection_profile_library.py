from copy import deepcopy
from dataclasses import asdict

import pytest

from composition.pdf_source.detection import DetectionConfig
from composition.template.model import CompositionError


def api():
    from composition.pdf_source import profile_library

    return profile_library


def config():
    return asdict(
        DetectionConfig(
            version=2, rules=[{"kind": "first_text", "terms": ["Regular Letter"], "region_mm": None}]
        )
    )


def profile():
    m = api()
    result = m.new_profile("eMPF")
    result["rule_sets"] = [m.new_rule("Regular", config(), template_id="REGULAR")]
    return result


def test_create_save_revision_rename_duplicate_and_export(tmp_path):
    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    first = library.save(profile())
    assert first["revision"] == 1
    changed = deepcopy(first)
    changed["description"] = "Recurring letters"
    second = library.save(changed)
    assert second["revision"] == 2 and library.read(first["profile_id"], 1) == first
    assert library.read(first["profile_id"]) == second
    renamed = library.rename(first["profile_id"], "eMPF letters")
    assert renamed["revision"] == 3
    duplicate = library.duplicate(first["profile_id"], "Training copy")
    assert duplicate["profile_id"] != first["profile_id"] and duplicate["revision"] == 1
    path = m.export_profile(tmp_path / "portable", renamed)
    assert path.suffix == ".pdmpx" and m.read_profile(path) == renamed
    assert len(library.list()["entries"]) == 2
    with pytest.raises(CompositionError, match="revision|changed"):
        library.save(first)


def test_import_existing_pdmp_and_reuse_without_previous_source(tmp_path):
    from composition.pdf_source.profiles import load_profile, save_profile

    m = api()
    original = config()
    path = save_profile(tmp_path / "old", DetectionConfig(**original))
    assert load_profile(path) == original
    library = m.ProfileLibrary(tmp_path / "library")
    saved = library.import_profile(path)
    assert saved["rule_sets"][0]["config"] == original
    assert saved["rule_sets"][0]["primary"] == "first_text"
    assert "source" not in saved and "groups" not in saved
    assert library.import_profile(m.export_profile(tmp_path / "new", saved)) == saved


@pytest.mark.parametrize("bad", ["source", "groups", "accepted", "page_text", "member_number", "cache"])
def test_private_or_job_fields_rejected(bad):
    raw = profile()
    raw[bad] = "customer data"
    with pytest.raises(CompositionError):
        api().validate_profile(raw)


@pytest.mark.parametrize("damage", ["schema", "empty_scan", "duplicate_rule", "too_many", "identity_primary"])
def test_strict_rule_validation(damage):
    raw = profile()
    if damage == "schema":
        raw["schema_version"] = 2
    elif damage == "empty_scan":
        raw["rule_sets"] = []
    elif damage == "duplicate_rule":
        raw["rule_sets"] *= 2
    elif damage == "too_many":
        raw["rule_sets"] = [api().new_rule(str(i), config(), template_id="REGULAR") for i in range(17)]
    else:
        raw["rule_sets"][0]["primary"] = "document_id"
    with pytest.raises(CompositionError):
        api().validate_profile(raw, for_scan=True)


def test_oversized_invalid_and_linked_profiles_rejected(tmp_path):
    m = api()
    path = tmp_path / "bad.pdmpx"
    path.write_bytes(b"x" * (m.MAX_BYTES + 1))
    with pytest.raises(CompositionError):
        m.read_profile(path)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(CompositionError):
        m.read_profile(path)


def test_draft_and_malformed_library_entries_do_not_hide_good_profiles(tmp_path):
    m = api()
    lib = m.ProfileLibrary(tmp_path / "library")
    draft = lib.save(m.new_profile("Draft"))
    assert not draft["rule_sets"]
    path = lib.root / "broken"
    path.mkdir()
    (path / "r000001.pdmpx").write_text("{}")
    result = lib.list()
    assert len(result["entries"]) == 1 and result["errors"]


def test_rule_validation_cannot_retain_unknown_extracted_fields():
    raw = profile()
    raw["rule_sets"][0]["samples"] = ["actual account"]
    with pytest.raises(CompositionError):
        api().validate_profile(raw)



def test_import_cannot_bypass_library_capacity(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "MAX_PROFILES", 1)
    lib = m.ProfileLibrary(tmp_path / "library")
    lib.save(profile())
    other = profile()
    portable = m.export_profile(tmp_path / "other.pdmpx", other)
    with pytest.raises(CompositionError, match="limit"):
        lib.import_profile(portable)
    assert len(lib.list()["entries"]) == 1



def test_library_listing_does_not_transfer_all_rule_payloads(tmp_path):
    lib = api().ProfileLibrary(tmp_path / "library")
    saved = lib.save(profile())
    entry = lib.list()["entries"][0]
    assert entry["profile_id"] == saved["profile_id"]
    assert entry["rule_count"] == 1 and "rule_sets" not in entry
    assert lib.read(entry["profile_id"]) == saved
