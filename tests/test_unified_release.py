from __future__ import annotations

import json
import zipfile
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.release_signing import load_signing_key, write_update_metadata
from scripts.unified_release import seal, validate_candidates, validate_sealed
from scripts.update_release import create_legacy_auth_bridge, create_packages
from updates import target as targets
from updates import trust
from updates.protocol import Manifest, UpdateError, digest_file
from updates.runtime import Installation
from updates.target import DEFAULT_TARGET, UpdateTarget, resolve_update_route

PRIVATE = UpdateTarget("windows-x64", "private", "qatest")
COMMIT = "a" * 40


@pytest.fixture
def signing(monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw().hex()
    monkeypatch.setattr(trust, "PUBLIC_KEY_HEX", public)
    monkeypatch.setattr("scripts.unified_release.PUBLIC_KEY_HEX", public)
    return key, public


def test_route_requires_known_legacy_launcher_and_keeps_private_project(tmp_path, monkeypatch):
    (tmp_path / "Launcher.exe").write_bytes(b"original")
    monkeypatch.setattr(targets, "LEGACY_WINDOWS_LAUNCHERS", {digest_file(tmp_path / "Launcher.exe")})
    route = resolve_update_route(tmp_path, PRIVATE)
    assert route.transport == DEFAULT_TARGET and route.application == PRIVATE and route.bridge
    (tmp_path / "Launcher.exe").write_bytes(b"unknown")
    with pytest.raises(UpdateError, match="not verified"):
        resolve_update_route(tmp_path, PRIVATE)
    identity = tmp_path / "launcher_runtime/update-target.json"
    identity.parent.mkdir()
    identity.write_text(json.dumps(asdict(PRIVATE)))
    assert not resolve_update_route(tmp_path, PRIVATE).bridge
    identity.write_text(json.dumps(asdict(UpdateTarget("windows-x64", "private", "other"))))
    with pytest.raises(UpdateError, match="another"):
        resolve_update_route(tmp_path, PRIVATE)


def make_windows(folder, key=None):
    folder.mkdir()
    app, bootstrap = folder / "app", folder / "launcher"
    (app / "_internal").mkdir(parents=True)
    (bootstrap / "launcher_runtime").mkdir(parents=True)
    (app / "PDFDocuEdit Pro.exe").write_bytes(b"frozen fixture")
    for path in (app / "_internal/update-target.json", bootstrap / "launcher_runtime/update-target.json"):
        path.write_text(json.dumps(asdict(PRIVATE)))
    (app / "_internal/update_build.json").write_text(json.dumps({
        "version": "3.0.4", "source_commit": COMMIT, "source_fingerprint": "b" * 64,
    }))
    (bootstrap / "Launcher.exe").write_bytes(b"launcher")
    output = folder / "release"
    create_packages(app, bootstrap, output, "3.0.4", key, target=PRIVATE)
    create_legacy_auth_bridge(output, "3.0.4", PRIVATE, key)
    return output


def test_legacy_and_private_are_same_bytes_and_new_clients_reject_wrong_project(tmp_path, signing):
    key, public = signing
    output = make_windows(tmp_path / "windows", key)
    legacy = output / DEFAULT_TARGET.asset("3.0.4")
    assert legacy.read_bytes() == (output / PRIVATE.asset("3.0.4")).read_bytes()
    raw, signature = (output / "update.json").read_bytes(), (output / "update.sig").read_bytes()
    assert Manifest.verify(raw, signature, public).target == DEFAULT_TARGET
    assert Manifest.verify(raw, signature, public, application_target=PRIVATE).application_target == PRIVATE
    wrong = UpdateTarget("windows-x64", "private", "another")
    with pytest.raises(UpdateError, match="required account"):
        Manifest.verify(raw, signature, public, application_target=wrong)
    data = json.loads(raw)
    data.pop("application_target")
    raw = json.dumps(data).encode()
    with pytest.raises(UpdateError, match="required account"):
        Manifest.verify(raw, key.sign(raw), public, application_target=PRIVATE)


def test_unchanged_schema_one_supervisor_can_install_two_account_updates(tmp_path, signing):
    key, public = signing
    output = make_windows(tmp_path / "windows", key)
    installation = Installation(tmp_path / "installed")
    old = installation.root / "versions/3.0.3"
    old.mkdir()
    (old / "PDFDocuEdit Pro.exe").write_bytes(b"original")
    (old / ".managed-update").write_text("3.0.3")
    from updates.protocol import atomic_json
    atomic_json(installation.state_path, {"current": "3.0.3", "previous": None, "phase": "stable"})
    (installation.root / "data/sentinel").write_text("settings and project paths")
    for number in ("3.0.4", "3.0.5"):
        data = json.loads((output / "update.json").read_text())
        data.update(version=number, asset=DEFAULT_TARGET.asset(number))
        raw = json.dumps(data).encode()
        (installation.root / "staging/update.json").write_bytes(raw)
        (installation.root / "staging/update.sig").write_bytes(key.sign(raw))
        import shutil
        shutil.copyfile(output / DEFAULT_TARGET.asset("3.0.4"), installation.root / "staging/package.zip")
        new = installation.prepare(public)
        trial = installation.begin_trial(new)
        installation.commit(trial["token"])
        assert installation.state()["current"] == number
    assert (installation.root / "data/sentinel").read_text() == "settings and project paths"


def test_encrypted_key_password_is_only_requested_in_memory(tmp_path, signing):
    key, _ = signing
    path = tmp_path / "encrypted.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.BestAvailableEncryption(b"fixture-only")))
    prompts = []
    loaded = load_signing_key(path, password_reader=lambda prompt: prompts.append(prompt) or "fixture-only")
    assert loaded.public_key().public_bytes_raw() == key.public_key().public_bytes_raw()
    assert prompts == ["Signing-key password: "]


def candidates(tmp_path):
    output = make_windows(tmp_path / "windows")
    (output / "PDFDocuEdit-Pro-v3.0.4-Setup-Windows-x64.exe").write_bytes(b"installer")
    mac = UpdateTarget("macos-arm64", "private", "qatest")
    package = output / mac.asset("3.0.4")
    entries = {
        "PDFDocuEdit Pro.app/Contents/Resources/update-target.json": json.dumps(asdict(mac)),
        "PDFDocuEdit Pro.app/Contents/Resources/update_build.json": json.dumps({
            "version": "3.0.4", "source_commit": COMMIT, "source_fingerprint": "b" * 64,
        }),
        mac.executable: "native fixture",
    }
    with zipfile.ZipFile(package, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    write_update_metadata(output, {"schema": 2, "product": "PDFDocuEditPro", **asdict(mac),
                          "version": "3.0.4", "min_launcher_version": "1.0.0", "asset": package.name,
                          "size": package.stat().st_size, "expanded_size": sum(len(v) for v in entries.values()),
                          "sha256": digest_file(package), "maturity": "preview"})
    (output / "PDFDocuEdit-Pro-v3.0.4-Managed-macOS-arm64-Private.dmg").write_bytes(b"managed dmg")
    for platform in ("windows-x64", "macos-arm64"):
        marker = "macOS" if platform.startswith("macos") else "Windows"
        files = [p for p in output.iterdir() if marker in p.name or
                 platform == "windows-x64" and p.name == "candidate-update.json"]
        # The platform-specific candidate manifest also belongs to its index.
        metadata = output / ("candidate-update-" + platform + "-private.json")
        if metadata not in files:
            files.append(metadata)
        data = {"version": "3.0.4", "source_commit": COMMIT, "source_fingerprint": "b" * 64,
                "platform": platform, "channel": "private", "auth_project": "qatest",
                "checks": {"native_packaging": True, "frozen_login": {"passed": True},
                           "regression": {"passed": True, "modules": 1, "tests": 1}},
                "files": [{"name": p.name, "size": p.stat().st_size, "sha256": digest_file(p)} for p in files]}
        (output / f"candidate-{platform}.json").write_text(json.dumps(data))
    return output


def test_seal_requires_both_platforms_same_commit_and_unchanged_payload(tmp_path, signing):
    source = candidates(tmp_path)
    output = tmp_path / "sealed"
    index = seal(source, output, "3.0.4", COMMIT, signing[0])
    assert validate_sealed(output)["source_commit"] == COMMIT
    assert {"update.json", "update.sig", "update-macos-arm64-private.sig"} <= {row["name"] for row in index["files"]}
    (output / PRIVATE.asset("3.0.4")).write_bytes(b"changed")
    with pytest.raises(UpdateError, match="differs"):
        validate_sealed(output)
    with pytest.raises(UpdateError, match="same committed"):
        validate_candidates(source, "3.0.4", "c" * 40)
    (source / "candidate-macos-arm64.json").unlink()
    with pytest.raises(FileNotFoundError):
        validate_candidates(source, "3.0.4", COMMIT)
