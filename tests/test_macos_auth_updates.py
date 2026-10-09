from __future__ import annotations

import json
import plistlib
import stat
import sys
import zipfile
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auth.controller import AuthController
from auth.store import ApprovalStore, StorageError
from tests.test_private_auth import MemoryBackend, approval, pump
from updates.macos_archive import APP, bundle_members, write_bundle
from updates.protocol import Manifest, UpdateError, atomic_json, digest_file, extract_archive
from updates.runtime import Installation
from updates.target import UpdateTarget

MAC = UpdateTarget("macos-arm64", "private", "qatest")


def fixture_app(folder, value="3.0.4"):
    app = folder / APP
    (app / "Contents/MacOS").mkdir(parents=True)
    exe = app / "Contents/MacOS/PDFDocuEdit Pro"
    exe.write_bytes(b"fixture executable")
    exe.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": value}))
    return app


def signed_package(folder, source, target=MAC, value="3.0.4"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "package.zip"
    expanded = write_bundle(source, path)
    key = Ed25519PrivateKey.generate()
    data = {"schema": 2, "product": "PDFDocuEditPro", "platform": target.platform,
            "channel": target.channel, "auth_project": target.auth_project, "version": value,
            "min_launcher_version": "1.0.0", "asset": target.asset(value), "size": path.stat().st_size,
            "expanded_size": expanded, "sha256": digest_file(path)}
    raw = json.dumps(data).encode()
    signature = key.sign(raw)
    (folder / "update.json").write_bytes(raw)
    (folder / "update.sig").write_bytes(signature)
    return raw, signature, key.public_key().public_bytes_raw().hex(), path


def test_mac_backend_is_explicit_and_keychain_failure_never_falls_back(monkeypatch, tmp_path):
    backend = MemoryBackend()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("auth.store.Path.home", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "keyring.backends.macOS", SimpleNamespace(Keyring=lambda: backend))
    store = ApprovalStore("qatest")
    assert store.backend is backend and store.storage_name == "macOS Keychain"
    assert store.blocked_path.is_relative_to(tmp_path / "Library/Application Support")
    store.save(approval(project_ref="qatest"))
    assert store.load() is not None
    backend.get_password = lambda *_: (_ for _ in ()).throw(RuntimeError("denied"))
    with pytest.raises(StorageError, match="macOS Keychain"):
        store.load()
    assert not any(p.suffix == ".json" for p in tmp_path.rglob("*"))


def test_background_cache_admits_offline_without_writing_keychain(qt_application):
    import threading

    from auth.model import AuthResult, Outcome
    waiting = threading.Event()
    store = ApprovalStore("qatest", backend=MemoryBackend())
    store.save(approval(project_ref="qatest"))
    original = store.load
    store.load = lambda: (waiting.wait(2), original())[1]
    store.save = lambda *_: pytest.fail("Cache admission must not rewrite Keychain")
    controller = AuthController(SimpleNamespace(verify=lambda *_: AuthResult(Outcome.UNAVAILABLE, "Offline")), store)
    admitted = []
    controller.approved.connect(admitted.append)
    controller.start(asynchronous=True)
    assert controller.busy and not admitted
    waiting.set()
    pump(qt_application, lambda: bool(admitted) and not controller.busy)
    assert admitted[0].user_id == approval().user_id
    controller.stop()


def test_signed_platform_channel_and_project_are_bound(tmp_path):
    raw, sig, public, _ = signed_package(tmp_path / "stage", fixture_app(tmp_path / "source"))
    assert Manifest.verify(raw, sig, public, target=MAC).target == MAC
    for target in (UpdateTarget(), UpdateTarget("macos-arm64"), UpdateTarget("macos-arm64", "private", "other")):
        with pytest.raises(UpdateError):
            Manifest.verify(raw, sig, public, target=target)


def test_mac_transaction_uses_existing_settings_backup_and_rollback(tmp_path):
    root = tmp_path / "managed"
    instance = Installation(root, target=MAC, validator=lambda *_: None)
    old = fixture_app(root / "versions/3.0.3", "3.0.3")
    (old.parent / ".managed-update").write_text("3.0.3")
    atomic_json(instance.state_path, {"current": "3.0.3", "previous": None, "phase": "stable"})
    settings = root / "data/settings.json"
    settings.write_text("original")
    _, _, public, _ = signed_package(root / "staging", fixture_app(tmp_path / "source"))
    target = instance.prepare(public)
    instance.begin_trial(target)
    settings.write_text("new settings")
    assert instance.recover()
    assert settings.read_text() == "original" and instance.state()["current"] == "3.0.3"


def test_invalid_bundle_is_not_published(tmp_path):
    instance = Installation(tmp_path / "managed", target=MAC,
                            validator=lambda *_: (_ for _ in ()).throw(UpdateError("Invalid signature")))
    atomic_json(instance.state_path, {"current": "3.0.3", "previous": None, "phase": "stable"})
    _, _, public, _ = signed_package(instance.root / "staging", fixture_app(tmp_path / "source"))
    with pytest.raises(UpdateError, match="Invalid signature"):
        instance.prepare(public)
    assert not (instance.root / "versions/3.0.4").exists()
    assert not list((instance.root / "versions").glob(".staging-*"))


@pytest.mark.parametrize("name,target", [
    (f"{APP}/Contents/link", "/outside"),
    (f"{APP}/Contents/link", "../../outside"),
    (f"{APP}/Contents/link", "link"),
])
def test_unsafe_mac_links_rejected(tmp_path, name, target):
    app = fixture_app(tmp_path / "source")
    path = tmp_path / "package.zip"
    expanded = write_bundle(app, path)
    with zipfile.ZipFile(path, "a") as archive:
        info = zipfile.ZipInfo(name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        value = target.encode()
        archive.writestr(info, value)
    with zipfile.ZipFile(path) as archive, pytest.raises(UpdateError):
        bundle_members(archive, expanded + len(value))


@pytest.mark.skipif(sys.platform != "darwin", reason="Native Mac symlinks and executable permissions")
def test_native_bundle_links_and_permissions_roundtrip(tmp_path):
    app = fixture_app(tmp_path / "source")
    resources = app / "Contents/Resources"
    resources.mkdir()
    (resources / "real").write_text("owned")
    (resources / "link").symlink_to("real")
    raw, sig, public, package = signed_package(tmp_path / "stage", app)
    manifest = Manifest.verify(raw, sig, public, target=MAC)
    destination = tmp_path / "new"
    extract_archive(package, destination, manifest)
    assert (destination / APP / "Contents/Resources/link").read_text() == "owned"
    assert (destination / MAC.executable).stat().st_mode & 0o111
