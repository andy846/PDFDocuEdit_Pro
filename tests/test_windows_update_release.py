"""Explicit Windows update-only scope retains signing and provenance gates."""
import json

import pytest

from scripts.unified_release import seal, validate_candidates, validate_sealed
from scripts.update_release import create_packages
from tests.test_unified_release import COMMIT, PRIVATE, candidates, make_windows, signing  # noqa: F401
from updates.protocol import UpdateError


def windows_candidate(tmp_path):
    source = candidates(tmp_path)
    index = source / "candidate-windows-x64.json"
    data = json.loads(index.read_text())
    data["release_scope"] = "windows-update"
    data["files"] = [row for row in data["files"] if "Managed-Portable" not in row["name"] and "Setup-" not in row["name"]]
    index.write_text(json.dumps(data))
    (source / "candidate-macos-arm64.json").unlink()
    return source


def test_windows_only_requires_explicit_scope_and_seals_no_other_platform(tmp_path, signing):  # noqa: F811
    source = windows_candidate(tmp_path)
    with pytest.raises((UpdateError, FileNotFoundError)):
        validate_candidates(source, "3.0.4", COMMIT)
    try:
        index = seal(source, tmp_path / "signed", "3.0.4", COMMIT, signing[0], scope="windows-update")
    except TypeError as exc:
        pytest.fail(f"Explicit Windows update-only release is not supported: {exc}")
    assert index["release_scope"] == "windows-update"
    assert index["platforms"] == ["windows-x64"]
    assert validate_sealed(tmp_path / "signed")["source_commit"] == COMMIT
    names = {row["name"] for row in index["files"]}
    assert {"update.json", "update.sig", "update-windows-x64-private.json", "update-windows-x64-private.sig"} <= names
    assert not any("macos" in name.lower() or "Setup-" in name or "Managed-Portable" in name for name in names)


def test_update_only_does_not_build_managed_portable(tmp_path, monkeypatch):
    source = make_windows(tmp_path / "fixture")
    app, launcher = source.parent / "app", source.parent / "launcher"
    import scripts.update_release as module

    monkeypatch.setattr(module.shutil, "make_archive", lambda *args, **kwargs: pytest.fail("Portable ZIP must not be built"))
    try:
        outputs = create_packages(app, launcher, tmp_path / "updates", "3.0.4", None,
                                  target=PRIVATE, updates_only=True)
    except TypeError as exc:
        pytest.fail(f"Update-only packaging is missing: {exc}")
    assert any(path and path.name == PRIVATE.asset("3.0.4") for path in outputs)
    assert not any(path and "Managed-Portable" in path.name for path in outputs)


def test_windows_scope_still_rejects_failed_regression(tmp_path, signing):  # noqa: F811
    source = windows_candidate(tmp_path)
    path = source / "candidate-windows-x64.json"
    data = json.loads(path.read_text())
    data["checks"]["regression"]["passed"] = False
    path.write_text(json.dumps(data))
    try:
        with pytest.raises(UpdateError, match="gates must pass"):
            seal(source, tmp_path / "signed", "3.0.4", COMMIT, signing[0], scope="windows-update")
    except TypeError as exc:
        pytest.fail(f"Scoped signing validation is missing: {exc}")


def test_native_update_build_skips_both_distribution_archives(monkeypatch):
    from scripts import build

    monkeypatch.setattr(build, "validate_tesseract_bundle", lambda: None)
    monkeypatch.setattr(build, "validate_verapdf_bundle", lambda: None)
    monkeypatch.setattr(build, "run", lambda *args: None)
    monkeypatch.setattr(build, "_windows_signing_settings", lambda: None)
    monkeypatch.setattr(build, "build_portable_zip", lambda: pytest.fail("Portable build is out of scope"))
    monkeypatch.setattr(build, "_find_inno_setup_compiler", lambda: pytest.fail("Installer build is out of scope"))
    try:
        assert build.build_windows(updates_only=True) == (None, None)
    except TypeError as exc:
        pytest.fail(f"Native update-only build is missing: {exc}")
