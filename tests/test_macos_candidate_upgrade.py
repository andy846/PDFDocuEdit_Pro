"""Operator tooling must authenticate candidates and preserve existing state."""
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts import macos_candidate_upgrade as helper
from tests.test_macos_auth_updates import MAC, fixture_app, signed_package
from updates.protocol import UpdateError, atomic_json
from updates.runtime import Installation


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    app = fixture_app(tmp_path / "installed", "3.0.3")
    resources = app / "Contents/Resources"
    resources.mkdir()
    atomic_json(resources / "bootstrap.json", {"target": asdict(MAC)})
    folder = tmp_path / "candidate"
    raw, signature, public, package = signed_package(folder, fixture_app(tmp_path / "new"))
    package.rename(folder / MAC.asset("3.0.4"))
    (folder / (MAC.metadata + ".json")).write_bytes(raw)
    (folder / (MAC.metadata + ".sig")).write_bytes(signature)
    monkeypatch.setattr(helper, "PUBLIC_KEY_HEX", public)
    return app, folder


def test_verifies_signature_and_payload_before_installation(candidate):
    app, folder = candidate
    target, manifest, package, _, _ = helper.verify_candidate(app, folder)
    assert target == MAC and manifest.version == "3.0.4"
    package.write_bytes(b"tampered")
    with pytest.raises(UpdateError, match="checksum"):
        helper.verify_candidate(app, folder)


def test_rejects_changed_project_and_signature(candidate):
    app, folder = candidate
    signature = folder / (MAC.metadata + ".sig")
    signature.write_bytes(b"x" * 64)
    with pytest.raises(UpdateError, match="signature"):
        helper.verify_candidate(app, folder)
    atomic_json(app / "Contents/Resources/bootstrap.json", {"target": asdict(MAC) | {"channel": "public", "auth_project": ""}})
    with pytest.raises(UpdateError, match="account-enabled"):
        helper.verify_candidate(app, folder)


def test_non_mac_guard_runs_before_file_access(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.prepare_macos.platform.system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="Apple Silicon"):
        helper.run(tmp_path / "absent", tmp_path / "candidate", tmp_path / "report.json")
    assert not list(tmp_path.iterdir())


@pytest.fixture
def installed(candidate, tmp_path, monkeypatch):
    app, folder = candidate
    monkeypatch.setattr(helper, "require_arm64", lambda: None)
    monkeypatch.setattr(helper, "validate_app", lambda *_: None)
    # Mac bundle nesting under pytest's long Windows directory exceeds legacy
    # MAX_PATH. A short, owned temporary home keeps this portable test real.
    with tempfile.TemporaryDirectory(prefix="mu-") as temporary:
        monkeypatch.setattr(Path, "home", lambda: Path(temporary))
        root = Path(temporary) / "Library/Application Support/PDFDocuEditPro/managed/private-qatest-arm64"
        installation = Installation(root, target=MAC, validator=lambda *_: None)
        fixture_app(root / "versions/3.0.3", "3.0.3")
        atomic_json(installation.state_path, {"phase": "stable", "current": "3.0.3", "previous": None})
        atomic_json(root / "installation.json", {"launcher": str(app / "Contents/MacOS/PDFDocuEdit Pro")})
        (root / "data/sentinel").write_text("user settings")
        yield app, folder, installation


def test_pending_update_is_left_untouched(installed, tmp_path):
    app, folder, installation = installed
    pending = installation.root / "staging/update.json"
    pending.write_text("existing pending work")
    with pytest.raises(UpdateError, match="left untouched"):
        helper.run(app, folder, tmp_path / "report.json")
    assert pending.read_text() == "existing pending work"
    assert installation.state()["current"] == "3.0.3"
    assert not (installation.root / "versions/3.0.4").exists()


def test_shared_transaction_and_supervisor_without_claiming_real_login(installed, tmp_path, monkeypatch):
    app, folder, installation = installed
    observed = []

    def supervise(instance, arguments, **kwargs):
        state = instance.state()
        observed.append((state["phase"], state["current"], arguments))
        instance.commit(state["token"])
        return 0

    monkeypatch.setattr(helper, "supervise", supervise)
    report = tmp_path / "result.json"
    assert helper.run(app, folder, report) == "3.0.4"
    assert observed == [("trial", "3.0.4", [])]
    evidence = json.loads(report.read_text())
    assert evidence["mac_cross_version_update"] is True
    assert evidence["real_account_login_confirmed"] is False
    assert (installation.root / "data/sentinel").read_text() == "user settings"


def test_report_cannot_replace_managed_state(installed):
    app, folder, installation = installed
    with pytest.raises(UpdateError, match="outside"):
        helper.run(app, folder, installation.state_path)
    assert installation.state()["current"] == "3.0.3"
