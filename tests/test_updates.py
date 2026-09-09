from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import launcher
from updates import protocol
from updates.protocol import EXECUTABLE, Cancelled, Manifest, Release, UpdateError, atomic_json, digest_file
from updates.runtime import TOKEN_ENV, FileLock, Installation


@pytest.fixture
def signing():
    key = Ed25519PrivateKey.generate()
    return key, key.public_key().public_bytes_raw().hex()


def package(folder, signing, target="2.5.6", entries=None, **overrides):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "package.zip"
    entries = entries or {EXECUTABLE: b"test executable", "_internal/runtime.dll": b"dependency"}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.filename = name
            archive.writestr(info, data)
    data = {
        "schema": 1, "product": "PDFDocuEditPro", "platform": "windows-x64",
        "version": target, "min_launcher_version": "1.0.0",
        "asset": f"PDFDocuEdit-Pro-v{target}-Update-Windows-x64.zip",
        "size": path.stat().st_size, "expanded_size": sum(map(len, entries.values())),
        "sha256": digest_file(path), **overrides,
    }
    raw = json.dumps(data).encode()
    signature = signing[0].sign(raw)
    (folder / "update.json").write_bytes(raw)
    (folder / "update.sig").write_bytes(signature)
    return raw, signature, path


@pytest.fixture
def installation(tmp_path):
    instance = Installation(tmp_path / "installation")
    path = instance.root / "versions" / "2.5.5"
    path.mkdir()
    (path / EXECUTABLE).write_bytes(b"old")
    (path / ".managed-update").write_text("2.5.5")
    atomic_json(instance.state_path, {"current": "2.5.5", "previous": None, "phase": "stable"})
    (instance.root / "data" / "settings.json").write_text('{"theme":"dark"}')
    return instance


@pytest.mark.parametrize("value", ["../1.2.3", "v1.2.3", "1.2.3-beta", "01.2.3", "1.2", None])
def test_invalid_versions(value):
    with pytest.raises(UpdateError):
        protocol.version(value)


def test_numeric_version_order():
    assert protocol.version("2.10.0") > protocol.version("2.9.9")


@pytest.mark.parametrize("change", [
    {"platform": "macos-arm64"}, {"product": "other"}, {"schema": 2},
    {"min_launcher_version": "9.0.0"}, {"size": -1}, {"size": True},
    {"expanded_size": protocol.MAX_EXPANDED_BYTES + 1}, {"asset": "../evil.zip"},
])
def test_reject_incompatible_manifest(tmp_path, signing, change):
    raw, signature, _ = package(tmp_path, signing, **change)
    with pytest.raises(UpdateError):
        Manifest.verify(raw, signature, signing[1])


def test_tampered_metadata_and_wrong_key(tmp_path, signing):
    raw, signature, _ = package(tmp_path, signing)
    for content, key in ((raw + b" ", signing[1]), (raw, "00" * 32)):
        with pytest.raises(UpdateError, match="signature"):
            Manifest.verify(content, signature, key)


def test_tampered_zip_leaves_current_untouched(installation, signing):
    _, _, path = package(installation.root / "staging", signing)
    path.write_bytes(path.read_bytes() + b"corrupted")
    with pytest.raises(UpdateError, match="checksum"):
        installation.prepare(signing[1])
    assert installation.state()["current"] == "2.5.5"
    assert not (installation.root / "versions" / "2.5.6").exists()


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "C:/bad", "a\\bad", "NUL.txt", "a:ads", "a/../b", "a. /b", "a//b"])
def test_unsafe_zip_paths_rejected(tmp_path, signing, unsafe):
    raw, signature, path = package(tmp_path, signing, entries={EXECUTABLE: b"a", "_internal/a.dll": b"b", unsafe: b"bad"})
    manifest = Manifest.verify(raw, signature, signing[1])
    with pytest.raises(UpdateError):
        protocol.extract_archive(path, tmp_path / "extracted", manifest)
    assert not (tmp_path / "extracted").exists()
    assert not (tmp_path.parent / "escape").exists()


def test_zip_symlink_rejected(tmp_path):
    path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    with zipfile.ZipFile(path) as archive, pytest.raises(UpdateError, match="links"):
        protocol.archive_members(archive, 6)


def test_case_colliding_zip_rejected(tmp_path, signing):
    raw, signature, path = package(tmp_path, signing, entries={EXECUTABLE: b"a", EXECUTABLE.upper(): b"b", "_internal/a": b"c"})
    with pytest.raises(UpdateError, match="duplicate"):
        protocol.extract_archive(path, tmp_path / "out", Manifest.verify(raw, signature, signing[1]))


def test_prepare_commit_and_keep_previous(installation, signing):
    package(installation.root / "staging", signing)
    target = installation.prepare(signing[1])
    assert installation.state()["current"] == "2.5.5"
    trial = installation.begin_trial(target)
    with pytest.raises(UpdateError, match="Stale"):
        installation.commit("wrong")
    installation.commit(trial["token"])
    installation.cleanup()
    assert installation.state() == {"current": "2.5.6", "previous": "2.5.5", "phase": "stable"}
    assert installation.executable("2.5.5").exists()
    assert not (installation.root / "staging" / "package.zip").exists()


def test_interrupted_trial_restores_data_and_preserves_pdfs(installation, signing, tmp_path):
    document = tmp_path / "work.pdf"
    document.write_bytes(b"original PDF")
    package(installation.root / "staging", signing)
    installation.begin_trial(installation.prepare(signing[1]))
    (installation.root / "data" / "settings.json").write_text("bad migration")
    (installation.root / "data" / "new-setting").write_text("new")
    fresh = Installation(installation.root)
    assert fresh.recover()
    assert fresh.state()["current"] == "2.5.5"
    assert (fresh.root / "data" / "settings.json").read_text() == '{"theme":"dark"}'
    assert not (fresh.root / "data" / "new-setting").exists()
    assert document.read_bytes() == b"original PDF"
    assert not fresh.recover()
    assert list((fresh.root / "backups").glob("failed-version-*"))
    # Retry does not collide with the failed version directory.
    assert fresh.prepare(signing[1]) == "2.5.6"


def test_interrupted_rollback_is_repeatable(installation, signing, monkeypatch):
    package(installation.root / "staging", signing)
    installation.begin_trial(installation.prepare(signing[1]))
    original = Path.rename

    def interrupt(path, target):
        if path.name.startswith("restore-"):
            raise OSError("simulated power failure")
        return original(path, target)

    with monkeypatch.context() as context:
        context.setattr(Path, "rename", interrupt)
        with pytest.raises(OSError):
            installation.recover()
    assert installation.state()["phase"] == "rollback"
    assert Installation(installation.root).recover()
    assert (installation.root / "data" / "settings.json").read_text() == '{"theme":"dark"}'


def test_insufficient_space_keeps_current(installation, signing, monkeypatch):
    package(installation.root / "staging", signing)
    monkeypatch.setattr(protocol.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(UpdateError, match="free space"):
        installation.prepare(signing[1])
    assert installation.state()["phase"] == "stable"


def test_os_lock_prevents_second_updater(tmp_path):
    one, two = FileLock(tmp_path / "lock"), FileLock(tmp_path / "lock")
    assert one.acquire()
    try:
        assert not two.acquire()
    finally:
        one.release()
    assert two.acquire()
    two.release()


def test_cancelled_download_removes_partial(tmp_path, signing, monkeypatch):
    raw, signature, path = package(tmp_path / "source", signing)
    manifest = Manifest.verify(raw, signature, signing[1])
    release = Release(manifest, raw, signature, "https://github.com/a/b", "notes")
    monkeypatch.setattr(protocol, "_open", lambda _: io.BytesIO(path.read_bytes()))
    stage = tmp_path / "stage"
    with pytest.raises(Cancelled):
        protocol.download(release, stage, lambda *_: None, lambda: True)
    assert not (stage / "package.part").exists()
    assert not (stage / "package.zip").exists()


def test_truncated_download_is_not_staged(tmp_path, signing, monkeypatch):
    raw, signature, path = package(tmp_path / "source", signing)
    release = Release(Manifest.verify(raw, signature, signing[1]), raw, signature, "https://github.com/a/b", "")
    monkeypatch.setattr(protocol, "_open", lambda _: io.BytesIO(path.read_bytes()[:5]))
    with pytest.raises(UpdateError, match="checksum"):
        protocol.download(release, tmp_path / "stage", lambda *_: None, lambda: False)
    assert not (tmp_path / "stage" / "package.zip").exists()


@pytest.mark.parametrize("url", ["http://github.com/a", "https://evil.example/a", "file:///a", "https://github.com:444/a", "https://user@github.com/a"])
def test_insecure_urls_rejected(url):
    with pytest.raises(UpdateError):
        protocol._check_url(url)


def test_release_metadata_pins_assets_and_ignores_old_versions(tmp_path, signing, monkeypatch):
    raw, signature, _ = package(tmp_path, signing)
    base = "https://github.com/owner/repo/releases/download/v2.5.6/"
    metadata = {"tag_name": "v2.5.6", "draft": False, "prerelease": False, "body": "Changes", "assets": [
        {"name": name, "browser_download_url": base + name} for name in ("update.json", "update.sig", json.loads(raw)["asset"])
    ]}
    def fetch(url, _limit):
        if url.endswith("/latest"):
            return json.dumps(metadata).encode()
        return signature if url.endswith("update.sig") else raw
    monkeypatch.setattr(protocol, "fetch_small", fetch)
    release = protocol.check_release("owner/repo", signing[1], "2.5.5")
    assert release.url == base + release.manifest.asset
    assert protocol.check_release("owner/repo", signing[1], "2.5.6") is None
    metadata["prerelease"] = True
    assert protocol.check_release("owner/repo", signing[1], "2.5.5") is None


def test_supervisor_rolls_back_timeout_and_reopens_old(installation, signing, monkeypatch):
    package(installation.root / "staging", signing)
    installation.begin_trial(installation.prepare(signing[1]))
    calls = []
    notices = []
    monkeypatch.setattr(launcher, "notify", notices.append)
    monkeypatch.setattr(launcher.time, "sleep", lambda _: None)

    class Child:
        returncode = None

        def __init__(self, ready, token):
            self.ready, self.token = ready, token

        def poll(self):
            if self.ready:
                if (installation.root / f"accepted-{self.token}.json").exists():
                    self.returncode = 0
                else:
                    atomic_json(installation.root / f"ready-{self.token}.json", {"token": self.token})
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def wait(self, **_kwargs):
            return self.returncode

    def spawn(args, **kwargs):
        calls.append(args[0])
        return Child(len(calls) > 1, kwargs["env"][TOKEN_ENV])

    assert launcher.supervise(installation, [], spawn=spawn, timeout=0) == 0
    assert len(calls) == 2 and "2.5.5" in calls[1]
    assert notices and installation.state()["phase"] == "stable"


def test_unsigned_exit_code_cannot_trigger_update(installation, monkeypatch):
    monkeypatch.setattr(launcher.time, "sleep", lambda _: None)

    class Child:
        returncode = None

        def __init__(self, token):
            self.token = token

        def poll(self):
            if (installation.root / f"accepted-{self.token}.json").exists():
                self.returncode = 75
            else:
                atomic_json(installation.root / f"ready-{self.token}.json", {"token": self.token})
            return self.returncode

    result = launcher.supervise(installation, [], spawn=lambda _args, **kwargs: Child(kwargs["env"][TOKEN_ENV]))
    assert result == 75
    assert installation.state()["current"] == "2.5.5"


def test_real_process_restart_installs_signed_update(installation, signing, monkeypatch):
    import subprocess
    import sys

    package(installation.root / "staging", signing)
    monkeypatch.setattr(launcher, "PUBLIC_KEY_HEX", signing[1])
    notices = []
    monkeypatch.setattr(launcher, "notify", notices.append)
    helper = r"""
import json, os, sys, time
from pathlib import Path
root = Path(os.environ["PDFDOCUEDIT_UPDATE_ROOT"])
token = os.environ["PDFDOCUEDIT_LAUNCH_TOKEN"]
temporary = root / ("ready-" + token + ".tmp")
temporary.write_text(json.dumps({"token": token}))
temporary.replace(root / ("ready-" + token + ".json"))
deadline = time.monotonic() + 10
while not (root / ("accepted-" + token + ".json")).exists():
    if time.monotonic() > deadline:
        sys.exit(2)
    time.sleep(0.02)
if sys.argv[1] == "2.5.5":
    (root / "restart.json").write_text(json.dumps({"token": token}))
    sys.exit(75)
(root / "data" / "new-version-ran").write_text(sys.argv[1])
"""
    launched = []
    def spawn(arguments, **kwargs):
        target = Path(arguments[0]).parent.name
        launched.append(target)
        return subprocess.Popen([sys.executable, "-c", helper, target], **kwargs)

    assert launcher.supervise(installation, [], spawn=spawn, timeout=10) == 0
    assert launched == ["2.5.5", "2.5.6"]
    assert not notices
    assert installation.state()["current"] == "2.5.6"
    assert installation.state()["previous"] == "2.5.5"
    assert (installation.root / "data" / "new-version-ran").read_text() == "2.5.6"
    assert (installation.root / "data" / "settings.json").read_text() == '{"theme":"dark"}'

