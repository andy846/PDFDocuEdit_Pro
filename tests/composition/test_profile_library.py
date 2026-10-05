"""Validated local imports, bounded reads, cancellation and compatibility."""
import json
from dataclasses import asdict

import pytest

from composition.media.model import PrinterProfile, default_media
from composition.media.profile_library import (
    MAX_BYTES,
    MAX_IMPORT,
    identity,
    import_profiles,
    list_profiles,
    read_profile,
    validate_profile,
)


def profile(kind="media", family="vp6000"):
    media = default_media()
    media["printer_profile"] = asdict(PrinterProfile(profile_version=2, backend="postscript", family=family,
        profile_name="Letterhead setup", mappings={s["id"]: {"media_type": s["id"]} for s in media["stocks"]}))
    return {"kind": kind, "profile_version": 2,
            "settings": media if kind == "media" else media["printer_profile"]}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_import_deduplicates_without_overwriting_source_or_local_files(tmp_path):
    source = write(tmp_path / "source.json", profile())
    before = source.read_bytes()
    library = tmp_path / "library"
    result = import_profiles(library, [source, source])
    assert result["imported"] == result["duplicates"] == 1
    target = next(library.glob("*.json"))
    target_before = target.read_bytes()
    assert import_profiles(library, [source])["duplicates"] == 1
    assert source.read_bytes() == before and target.read_bytes() == target_before
    assert len(list_profiles(library)["entries"]) == 1
    assert not list(library.glob(".*"))


def test_folder_import_retains_valid_profiles_and_reports_invalid_files(tmp_path):
    source = tmp_path / "source"
    write(source / "first" / "media.json", profile())
    write(source / "second" / "printer.json", profile("printer", "ix"))
    write(source / "bad.json", {"commands": "quit"})
    result = import_profiles(tmp_path / "library", folder=source)
    assert result["imported"] == 2 and len(result["import_errors"]) == 1
    assert {e["family"] for e in result["entries"]} == {"vp6000", "ix"}


@pytest.mark.parametrize("raw", [None, [], {"kind": "printer", "profile_version": True, "settings": {}},
    {"kind": "printer", "profile_version": 9, "settings": {}},
    {**profile(), "commands": "quit"}, {**profile(), "profile_version": 1},
    {**profile("printer"), "settings": {**profile("printer")["settings"], "python": "eval"}}])
def test_untrusted_or_inconsistent_profiles_rejected(raw):
    with pytest.raises(ValueError):
        validate_profile(raw)


def test_oversized_read_and_import_limit_are_explicit(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError, match="1 MB"):
        read_profile(path)
    with pytest.raises(ValueError, match="at most"):
        import_profiles(tmp_path / "library", [path] * (MAX_IMPORT + 1))


def test_cancel_import_retains_only_completed_atomic_profiles(tmp_path):
    sources = [write(tmp_path / f"{i}.json", profile("media", family)) for i, family in enumerate(("vp6000", "i300", "ix"))]
    progress = []
    result = import_profiles(tmp_path / "library", sources, is_cancelled=lambda: bool(progress),
                             progress=lambda *args: progress.append(args))
    assert result["imported"] == 1 and result["cancelled"]
    entries = list_profiles(tmp_path / "library")["entries"]
    assert len(entries) == 1 and entries[0]["family"] == "vp6000"


def test_legacy_defaults_normalize_and_invalid_local_file_is_preserved(tmp_path):
    legacy = {"kind": "printer", "profile_version": 1, "settings": {"mappings": {}}}
    assert validate_profile(legacy)["settings"]["family"] == "vp6000"
    source = write(tmp_path / "source.json", profile())
    library = tmp_path / "library"
    target = write(library / ("profile-" + identity(validate_profile(profile())) + ".json"), {"broken": True})
    before = target.read_bytes()
    result = import_profiles(library, [source])
    assert result["imported"] == 0 and result["import_errors"] and result["errors"]
    assert target.read_bytes() == before


def test_omitted_mapping_defaults_deduplicate_against_designer_saved_profile(tmp_path):
    minimal = profile()
    expanded = validate_profile(minimal)
    result = import_profiles(tmp_path / "library", [write(tmp_path / "minimal.json", minimal),
                                                   write(tmp_path / "saved.json", expanded)])
    assert result["imported"] == 1 and result["duplicates"] == 1
