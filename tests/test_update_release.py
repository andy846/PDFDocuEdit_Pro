from __future__ import annotations

import json
import urllib.error
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.update_release import create_packages
from updates import protocol, trust
from updates.protocol import EXECUTABLE, Manifest, UpdateError


def test_release_packages_round_trip_and_exclude_signing_key(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(trust, "PUBLIC_KEY_HEX", key.public_key().public_bytes_raw().hex())
    app, bootstrap = tmp_path / "app", tmp_path / "launcher"
    (app / "_internal").mkdir(parents=True)
    (app / EXECUTABLE).write_bytes(b"test app")
    (app / "_internal" / "install.log").write_text("vendor installation log")
    (app / "_internal" / "runtime.dll").write_bytes(b"runtime")
    bootstrap.mkdir()
    (bootstrap / "Launcher.exe").write_bytes(b"launcher")
    outputs = create_packages(app, bootstrap, tmp_path / "release", "2.5.6", key)
    update, manifest_path, signature_path, deployment = outputs[:4]
    manifest = Manifest.verify(manifest_path.read_bytes(), signature_path.read_bytes(), trust.PUBLIC_KEY_HEX)
    manifest.verify_archive(update)
    with zipfile.ZipFile(deployment) as archive:
        assert "PDFDocuEditPro/Launcher.exe" in archive.namelist()
        assert not any(name.endswith(".log") for name in archive.namelist())
        assert f"PDFDocuEditPro/versions/2.5.6/{EXECUTABLE}" in archive.namelist()
        state = json.loads(archive.read("PDFDocuEditPro/state.json"))
        assert state["current"] == "2.5.6" and state["phase"] == "stable"
        assert not any(name.endswith(".pem") for name in archive.namelist())
    (app / "signing.pem").write_bytes(b"must not ship")
    with pytest.raises(UpdateError, match="Private/local"):
        create_packages(app, bootstrap, tmp_path / "release", "2.5.6", key)


def test_api_quota_uses_direct_public_release_redirect(monkeypatch):
    def exhausted(*_):
        raise urllib.error.HTTPError("https://api.github.com", 403, "rate limit", {}, None)

    class Redirect:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def geturl(self):
            return "https://github.com/owner/repo/releases/tag/v2.5.5"

    monkeypatch.setattr(protocol, "fetch_small", exhausted)
    monkeypatch.setattr(protocol, "_open", lambda _: Redirect())
    assert protocol.check_release("owner/repo", "00" * 32, "2.5.5") is None


def test_api_uses_json_media_type(monkeypatch):
    requests = []

    class Opener:
        def open(self, request, **kwargs):
            requests.append(request)

    monkeypatch.setattr(protocol.urllib.request, "build_opener", lambda *_: Opener())
    protocol._open("https://api.github.com/repos/owner/repo/releases/latest")
    assert requests[0].headers["Accept"] == "application/vnd.github+json"
