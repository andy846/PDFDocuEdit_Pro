"""Content-bound PS preview cache; no customer fixtures."""
import hashlib
import sqlite3

import pytest

from core.pdf_backend import fitz

IDENTITY = {"sha256": "a" * 64, "version": "test-1"}
PROFILE = {"kind": "editor-v1"}
SOURCE = hashlib.sha256(b"source").hexdigest()


def api():
    from core import postscript_cache
    return postscript_cache


def pdf(path, pages=2):
    with fitz.open() as doc:
        for i in range(pages):
            doc.new_page().insert_text((40, 40), f"Page {i}")
        doc.save(path)
    return path


def test_store_lookup_and_content_identity(tmp_path):
    cache = api().PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "a.pdf")
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is not None and hit.pages == 2
        assert hit.profile == PROFILE
        assert hit.path.read_bytes() == source.read_bytes()
    with cache.acquire(hashlib.sha256(b"changed").hexdigest(), IDENTITY) as hit:
        assert hit is None
    with cache.acquire(SOURCE, {**IDENTITY, "version": "changed"}) as hit:
        assert hit is None


@pytest.mark.parametrize("damage", ["bytes", "missing", "metadata"])
def test_invalid_cache_is_miss(tmp_path, damage):
    cache = api().PreviewCache(tmp_path / "cache")
    cache.store(pdf(tmp_path / "a.pdf"), SOURCE, IDENTITY, PROFILE)
    with cache.acquire(SOURCE, IDENTITY) as hit:
        path = hit.path
    if damage == "bytes":
        path.write_bytes(b"not a pdf")
    elif damage == "missing":
        path.unlink()
    else:
        with sqlite3.connect(cache.database) as db:
            db.execute("UPDATE entries SET pages=999")
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is None
    assert cache.last_status == "invalid_entry"


def test_profile_is_part_of_key_and_unknown_profile_rejected(tmp_path):
    cache = api().PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "a.pdf")
    assert not cache.store(source, SOURCE, IDENTITY, {"kind": "unknown"})
    assert cache.store(source, SOURCE, IDENTITY, {"kind": "production-v1", "resolution_dpi": 600})
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit.profile == PROFILE


def test_disabled_oversize_and_unwritable_cache_do_not_change_source(tmp_path):
    source = pdf(tmp_path / "a.pdf")
    before = source.read_bytes()
    assert not api().PreviewCache(tmp_path / "off", enabled=False).store(source, SOURCE, IDENTITY, PROFILE)
    assert not api().PreviewCache(tmp_path / "small", max_entry=1).store(source, SOURCE, IDENTITY, PROFILE)
    blocker = tmp_path / "blocked"
    blocker.write_text("file")
    assert not api().PreviewCache(blocker).store(source, SOURCE, IDENTITY, PROFILE)
    assert source.read_bytes() == before


def test_expiry_capacity_and_clear_respect_active_reader(tmp_path):
    cache = api().PreviewCache(tmp_path / "cache", max_bytes=15000)
    source = pdf(tmp_path / "a.pdf")
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is not None
        assert api().PreviewCache(cache.root).clear()["busy"]
        assert hit.path.is_file()
    assert cache.clear()["removed"] == 1
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)
    with sqlite3.connect(cache.database) as db:
        db.execute("UPDATE entries SET used=0")
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is None
    limited = api().PreviewCache(tmp_path / "limited", max_bytes=source.stat().st_size + 10)
    assert limited.store(source, SOURCE, IDENTITY, PROFILE)
    other = hashlib.sha256(b"other").hexdigest()
    assert limited.store(source, other, IDENTITY, PROFILE)
    with limited.acquire(SOURCE, IDENTITY) as hit:
        assert hit is None
    with limited.acquire(other, IDENTITY) as hit:
        assert hit is not None


def test_clear_does_not_touch_unowned_files_or_follow_links(tmp_path):
    cache = api().PreviewCache(tmp_path / "cache")
    cache.store(pdf(tmp_path / "a.pdf"), SOURCE, IDENTITY, PROFILE)
    unrelated = cache.root / "keep.pdf"
    unrelated.write_bytes(b"unowned")
    cache.clear()
    assert unrelated.read_bytes() == b"unowned"


def test_stable_snapshot_hashes_content_and_checks_cancellation(tmp_path):
    module = api()
    source = tmp_path / "input.ps"
    source.write_bytes(b"original" * 200000)
    with module.source_snapshot(source, tmp_path / "snapshots") as value:
        snapshot, digest = value
        assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
        assert snapshot.read_bytes() == source.read_bytes()
        snapshot_path = snapshot
    assert not snapshot_path.exists()
    from core.tasks import TaskCancelled
    with pytest.raises(TaskCancelled):
        with module.source_snapshot(source, tmp_path / "snapshots", is_cancelled=lambda: True):
            pytest.fail("cancelled snapshot yielded")


def test_production_preview_only_activated_after_commit(tmp_path):
    module = api()
    cache = module.PreviewCache(tmp_path / "cache")
    interpreted = pdf(tmp_path / "checked.pdf")
    ps = tmp_path / "production.ps"
    ps.write_bytes(b"postscript")
    digest = hashlib.sha256(ps.read_bytes()).hexdigest()
    with module.production_previews(cache):
        module.stage_production_preview(interpreted, digest, IDENTITY, {"kind": "production-v1", "resolution_dpi": 600})
        with cache.acquire(digest, IDENTITY) as hit:
            assert hit is None
        module.commit_production_previews({"output_ps": str(ps)})
        with cache.acquire(digest, IDENTITY) as hit:
            assert hit is not None and hit.profile["kind"] == "production-v1"
    assert not list((cache.root / "pending").glob("*.pdf"))


def test_aborted_or_mismatched_production_never_activates(tmp_path):
    module = api()
    cache = module.PreviewCache(tmp_path / "cache")
    interpreted = pdf(tmp_path / "checked.pdf")
    with module.production_previews(cache):
        module.stage_production_preview(interpreted, SOURCE, IDENTITY, PROFILE)
        module.commit_production_previews({"output_ps": str(tmp_path / "missing.ps")})
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is None
    assert not list((cache.root / "pending").glob("*.pdf"))


def test_headless_cache_does_not_import_qt():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "import core.postscript_cache,sys;assert not any(x.startswith('PyQt') for x in sys.modules)"], capture_output=True, timeout=20)
    assert result.returncode == 0


def test_clearing_during_production_invalidates_pending_entries(tmp_path):
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    ps = tmp_path / "a.ps"
    ps.write_bytes(b"PS")
    digest = hashlib.sha256(ps.read_bytes()).hexdigest()
    with m.production_previews(cache):
        m.stage_production_preview(pdf(tmp_path / "a.pdf"), digest, IDENTITY, PROFILE)
        assert not cache.clear()["busy"]
        m.commit_production_previews({"output_ps": str(ps)})
    with cache.acquire(digest, IDENTITY) as hit:
        assert hit is None


def test_pending_previews_are_bounded_by_total_cache_budget(tmp_path):
    m = api()
    source = pdf(tmp_path / "a.pdf")
    cache = m.PreviewCache(tmp_path / "cache", max_bytes=source.stat().st_size + 10)
    with m.production_previews(cache):
        for n in range(5):
            m.stage_production_preview(source, hashlib.sha256(str(n).encode()).hexdigest(), IDENTITY, PROFILE)
        assert sum(p.stat().st_size for p in cache.root.rglob("*.pdf")) <= cache.max_bytes


def test_cache_cleanup_failure_does_not_fail_committed_production(tmp_path, monkeypatch):
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    with m.production_previews(cache) as sink:
        monkeypatch.setattr(sink, "close", lambda: (_ for _ in ()).throw(PermissionError("busy")))


def test_cancel_during_cache_store_is_not_suppressed(tmp_path):
    from core.tasks import TaskCancelled
    cache = api().PreviewCache(tmp_path / "cache")
    with pytest.raises(TaskCancelled):
        cache.store(pdf(tmp_path / "a.pdf"), SOURCE, IDENTITY, PROFILE, is_cancelled=lambda: True)


def test_cancel_during_lookup_releases_cache_lease(tmp_path):
    from core.tasks import TaskCancelled
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    cache.store(pdf(tmp_path / "a.pdf"), SOURCE, IDENTITY, PROFILE)
    with pytest.raises(TaskCancelled):
        with cache.acquire(SOURCE, IDENTITY, is_cancelled=lambda: True):
            pytest.fail("cancelled lookup yielded")
    assert not m.PreviewCache(cache.root).clear()["busy"]


def test_cache_configuration_failure_is_optional(tmp_path, monkeypatch):
    from core import resources
    from core.settings import SettingsManager
    monkeypatch.setattr(resources, "cache_dir", lambda: (_ for _ in ()).throw(PermissionError("unavailable")))
    config = api().application_cache_config(SettingsManager(tmp_path / "settings.json"))
    assert not config["enabled"]


def test_clear_removes_abandoned_owned_content_and_keeps_active_pending(tmp_path):
    import uuid
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "a.pdf")
    with m.production_previews(cache):
        m.stage_production_preview(source, SOURCE, IDENTITY, PROFILE)
        active = list((cache.root / "pending").glob("*.pdf"))[0]
        abandoned = cache.root / "pending" / (uuid.uuid4().hex + ".pdf")
        abandoned.write_bytes(source.read_bytes())
        unindexed = cache.root / "entries" / ("f"*64 + ".pdf")
        unindexed.write_bytes(source.read_bytes())
        assert not cache.clear()["busy"]
        assert not abandoned.exists() and not unindexed.exists()
        assert active.exists()
    assert not active.exists()


def test_disable_blocks_existing_worker_cache_instances(tmp_path):
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "a.pdf")
    with m.production_previews(cache):
        m.stage_production_preview(source, SOURCE, IDENTITY, PROFILE)
        assert cache.set_enabled(False)
        assert not m.PreviewCache(cache.root).store(source, SOURCE, IDENTITY, PROFILE)
        with m.PreviewCache(cache.root).acquire(SOURCE, IDENTITY) as hit:
            assert hit is None
    assert cache.set_enabled(True)
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)


def test_editor_cache_validation_uses_supplied_native_lock(tmp_path, monkeypatch):
    m = api()
    source = pdf(tmp_path / "a.pdf")
    state = {"held": False, "checks": 0}
    class Lock:
        def __enter__(self):
            state["held"] = True
        def __exit__(self, *args):
            state["held"] = False
    validate = m.validate_pdf_file
    def checked(*args, **kwargs):
        assert state["held"]
        state["checks"] += 1
        return validate(*args, **kwargs)
    monkeypatch.setattr(m, "validate_pdf_file", checked)
    cache = m.PreviewCache(tmp_path / "cache", pdf_lock=Lock())
    assert cache.store(source, SOURCE, IDENTITY, PROFILE)
    with cache.acquire(SOURCE, IDENTITY) as hit:
        assert hit is not None
    assert state["checks"] == 2


def test_pending_cleanup_releases_every_lease_after_one_file_is_busy(tmp_path, monkeypatch):
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "checked.pdf")
    sink = m.ProductionPreviewSink(cache)
    sink.stage(source, SOURCE, IDENTITY, PROFILE)
    sink.stage(source, hashlib.sha256(b"second").hexdigest(), IDENTITY, PROFILE)
    paths = list(sink.leases)
    handles = list(sink.leases.values())
    original_unlink = type(paths[0]).unlink
    def busy_first(path, *args, **kwargs):
        if path == paths[0]:
            raise PermissionError("busy preview")
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(type(paths[0]), "unlink", busy_first)
        try:
            sink.close()
        except OSError:
            pass
        assert all(handle.closed for handle in handles)
        assert not paths[1].exists()
        assert not sink.leases
    assert paths[0].exists()
    assert cache.clear()["removed"] == 1


def test_staging_copy_failure_releases_lease_even_when_cleanup_fails(tmp_path, monkeypatch):
    m = api()
    cache = m.PreviewCache(tmp_path / "cache")
    source = pdf(tmp_path / "checked.pdf")
    sink = m.ProductionPreviewSink(cache)
    handles = []
    original_lease = m._pending_lease
    def lease(path):
        handle = original_lease(path)
        handles.append(handle)
        return handle
    def failed_copy(src, dst):
        dst.write_bytes(b"partial")
        raise OSError("copy failed")
    original_unlink = type(source).unlink
    def busy_pending(path, *args, **kwargs):
        if path.parent == cache.root / "pending" and path.suffix == ".pdf":
            raise PermissionError("busy partial preview")
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(m, "_pending_lease", lease)
        patch.setattr(m.shutil, "copyfile", failed_copy)
        patch.setattr(type(source), "unlink", busy_pending)
        with pytest.raises(OSError, match="copy failed"):
            sink.stage(source, SOURCE, IDENTITY, PROFILE)
        assert handles and all(handle.closed for handle in handles)
        assert not sink.leases
    assert cache.clear()["removed"] == 1
