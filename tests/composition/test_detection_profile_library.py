from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

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



def region_config():
    return asdict(DetectionConfig(rules=[{"kind": "region_present"}], region_mm=[8, 19, 70, 8], profile_name="Region letters"))


def test_single_rule_library_roundtrip_rename_duplicate_and_export(tmp_path):
    from composition.pdf_source.profiles import load_profile

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    first = library.add_single(region_config())
    assert first["kind"] == "single_mailpiece_detection"
    assert library.read(first["profile_id"])["config"]["region_mm"] == [8, 19, 70, 8]
    assert library.list()["entries"][0]["rule_count"] == 1
    renamed = library.rename(first["profile_id"], "Monthly letters")
    assert renamed["revision"] == 2 and renamed["config"]["profile_name"] == "Monthly letters"
    assert library.read(first["profile_id"], 1)["name"] == "Region letters"
    duplicate = library.duplicate(first["profile_id"], "Another layout")
    assert duplicate["profile_id"] != first["profile_id"] and duplicate["revision"] == 1
    exported = m.export_library_profile(tmp_path / "portable", renamed)
    assert Path(exported).suffix == ".pdmp"
    saved = load_profile(exported)
    assert saved["profile_name"] == "Monthly letters"
    assert set(saved) == {"rules", "combine", "region_mm", "remove_separators", "version", "profile_name"}
    assert not any(key in saved for key in ("groups", "source", "accepted", "page_text"))


def test_single_import_and_manual_save_deduplicate_identical_config(tmp_path):
    from composition.pdf_source.profiles import save_profile

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    path = save_profile(tmp_path / "legacy.pdmp", DetectionConfig(**region_config()))
    saved = library.import_profile(path)
    assert saved["kind"] == "single_mailpiece_detection"
    assert library.import_profile(path) == saved
    assert library.add_single(region_config()) == saved
    assert len(library.list()["entries"]) == 1
    changed = deepcopy(saved["config"])
    changed["region_mm"] = [9, 19, 70, 8]
    newer = library.add_single(changed, profile_id=saved["profile_id"], revision=1)
    assert newer["revision"] == 2
    with pytest.raises(CompositionError, match="revision|changed"):
        library.add_single(changed, profile_id=saved["profile_id"], revision=1)


def test_single_library_does_not_relax_multi_rule_validation(tmp_path):
    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    assert library.list() == {"entries": [], "errors": []}
    existing = library.save(profile())
    single = library.add_single(region_config())
    assert library.read(existing["profile_id"]) == existing
    assert len(library.list()["entries"]) == 2
    with pytest.raises(CompositionError):
        m.validate_profile(single, for_scan=True)
    bad = deepcopy(single)
    bad["groups"] = [[1, 100]]
    with pytest.raises(CompositionError):
        library.save(bad)
    assert len(library.list()["entries"]) == 2



def test_cancelled_registration_does_not_create_a_profile(tmp_path):
    library = api().ProfileLibrary(tmp_path / "library")
    with pytest.raises(CompositionError, match="cancelled"):
        library.add_single(region_config(), is_cancelled=lambda: True)
    assert not library.root.exists()


def test_single_library_capacity_and_mixed_revision_protection(tmp_path, monkeypatch):
    m = api()
    monkeypatch.setattr(m, "MAX_PROFILES", 1)
    library = m.ProfileLibrary(tmp_path / "library")
    saved = library.add_single(region_config())
    other = region_config()
    other["profile_name"] = "Another profile"
    with pytest.raises(CompositionError, match="limit"):
        library.add_single(other)
    folder = library.root / saved["profile_id"]
    (folder / "r000002.pdmpx").write_text("{}")
    with pytest.raises(CompositionError, match="mix"):
        library.read(saved["profile_id"])



def test_cancel_before_selected_profile_update_keeps_previous_revision(tmp_path):
    library = api().ProfileLibrary(tmp_path / "library")
    saved = library.add_single(region_config())
    changed = deepcopy(saved["config"])
    changed["region_mm"] = [10, 19, 70, 8]
    checks = iter([False, True])
    with pytest.raises(CompositionError, match="cancelled"):
        library.add_single(changed, profile_id=saved["profile_id"], revision=1,
                           is_cancelled=lambda: next(checks))
    assert library.read(saved["profile_id"])["revision"] == 1



def test_malformed_single_profile_does_not_hide_other_library_entries(tmp_path):
    library = api().ProfileLibrary(tmp_path / "library")
    saved = library.add_single(region_config())
    bad = library.root / "malformed_single"
    bad.mkdir()
    import sys
    depth = sys.getrecursionlimit() + 100
    (bad / "r000001.pdmp").write_text("[" * depth + "0" + "]" * depth)
    result = library.list()
    assert [entry["profile_id"] for entry in result["entries"]] == [saved["profile_id"]]
    assert result["errors"]


@pytest.mark.parametrize("name", ["eMPF", " EMPF ", "ｅＭＰＦ"])
@pytest.mark.parametrize("operation", ["create", "rename", "duplicate", "import", "single"])
def test_library_rejects_duplicate_names_across_entry_types(tmp_path, name, operation):
    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    original = library.save(profile())
    other = m.new_profile("Another profile")
    if operation == "rename":
        other = library.save(other)
    before = {p.relative_to(library.root): p.read_bytes() for p in library.root.rglob("r*.pdmp*")}
    with pytest.raises(CompositionError, match="name already exists"):
        if operation == "create":
            library.save(m.new_profile(name))
        elif operation == "rename":
            library.rename(other["profile_id"], name)
        elif operation == "duplicate":
            library.duplicate(original["profile_id"], name)
        elif operation == "import":
            other["name"] = name
            library.import_profile(m.export_profile(tmp_path / "imported", other))
        else:
            single = region_config()
            single["profile_name"] = name
            library.add_single(single)
    assert library.read(original["profile_id"]) == original
    assert {p.relative_to(library.root): p.read_bytes() for p in library.root.rglob("r*.pdmp*")} == before


def test_same_name_with_changed_single_rules_requires_selected_identity(tmp_path):
    from composition.pdf_source.profiles import save_profile

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    saved = library.add_single(region_config())
    changed = deepcopy(saved["config"])
    changed["region_mm"][0] += 1
    with pytest.raises(CompositionError, match="name already exists"):
        library.add_single(changed)
    portable = save_profile(tmp_path / "changed", DetectionConfig(**changed))
    with pytest.raises(CompositionError, match="name already exists"):
        library.import_profile(portable)
    changed["profile_name"] = " REGION LETTERS "
    revised = library.add_single(changed, profile_id=saved["profile_id"], revision=1)
    assert revised["profile_id"] == saved["profile_id"] and revised["revision"] == 2
    assert len(library.list()["entries"]) == 1


def legacy_duplicate_library(root):
    """Synthetic historical catalogue; never touch the operator's saved profiles."""
    from composition.pdf_source.profiles import save_profile

    m = api()
    for identity, x in (("old_b", 9), ("old_a", 8)):
        cfg = region_config()
        cfg["region_mm"][0] = x
        save_profile(root / identity / "r000001.pdmp", DetectionConfig(**cfg))
    return m.ProfileLibrary(root)


def test_existing_duplicate_profiles_are_preserved_and_can_be_resolved(tmp_path):
    library = legacy_duplicate_library(tmp_path / "library")
    entries = library.list()["entries"]
    assert [entry["profile_id"] for entry in entries] == ["old_a", "old_b"]
    original = {entry["profile_id"]: library.read(entry["profile_id"]) for entry in entries}
    changed = deepcopy(original["old_b"]["config"])
    changed["region_mm"][0] += 1
    revised = library.add_single(changed, profile_id="old_b", revision=1)
    assert revised["revision"] == 2 and revised["profile_id"] == "old_b"
    assert library.read("old_a") == original["old_a"]
    renamed = library.rename("old_b", "Second layout")
    assert renamed["revision"] == 3
    with pytest.raises(CompositionError, match="name already exists"):
        library.rename("old_b", "Region letters")
    assert library.read("old_a", 1) == original["old_a"]


def test_concurrent_library_writer_cannot_bypass_name_check(tmp_path):
    import subprocess
    import sys

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    with library._writing():
        with pytest.raises(CompositionError, match="busy"):
            m.ProfileLibrary(library.root).save(profile())
        result = subprocess.run([
            sys.executable, "-c",
            "import sys; from composition.pdf_source.profile_library import ProfileLibrary, new_profile; "
            "ProfileLibrary(sys.argv[1]).save(new_profile('eMPF'))", str(library.root),
        ], capture_output=True, text=True, timeout=20)
        assert result.returncode != 0 and "library is busy" in result.stderr
    saved = library.save(profile())
    assert library.read(saved["profile_id"]) == saved
    assert not library.list()["errors"]


def test_v2_portable_import_cannot_create_duplicate_name(tmp_path):
    from composition.pdf_source.profiles import save_profile

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    original = library.save(profile())
    cfg = config()
    cfg["profile_name"] = " EMPF "
    path = save_profile(tmp_path / "portable", DetectionConfig(**cfg))
    with pytest.raises(CompositionError, match="name already exists"):
        library.import_profile(path)
    assert library.list()["entries"][0]["profile_id"] == original["profile_id"]


def test_imported_historical_names_do_not_replace_current_or_bypass_conflicts(tmp_path):
    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    saved = library.save(profile())
    other = m.new_profile("Another profile")
    other["revision"] = 3
    library.import_profile(m.export_profile(tmp_path / "other", other))
    historical = deepcopy(other)
    historical.update(revision=2, name=saved["name"])
    library.import_profile(m.export_profile(tmp_path / "historical", historical))
    assert library.read(other["profile_id"])["name"] == "Another profile"
    future = deepcopy(historical)
    future["revision"] = 4
    with pytest.raises(CompositionError, match="name already exists"):
        library.import_profile(m.export_profile(tmp_path / "future", future))
    assert library.import_profile(m.export_profile(tmp_path / "same", saved)) == saved


def test_ambiguous_identical_legacy_profiles_require_explicit_identity(tmp_path):
    from composition.pdf_source.profiles import save_profile

    m = api()
    library = m.ProfileLibrary(tmp_path / "library")
    cfg = region_config()
    for identity in ("old_a", "old_b"):
        save_profile(library.root / identity / "r000001.pdmp", DetectionConfig(**cfg))
    with pytest.raises(CompositionError, match="name already exists"):
        library.add_single(cfg)
    assert library.add_single(cfg, profile_id="old_b", revision=1)["profile_id"] == "old_b"
