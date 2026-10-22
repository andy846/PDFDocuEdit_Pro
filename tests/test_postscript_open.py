"""Opening conversion cancellation, quality and cache integration."""
import hashlib
import sys
from pathlib import Path
from time import monotonic

import fitz
import pytest

from tests.test_postscript_cache import IDENTITY, pdf


def module():
    from core import postscript_open
    return postscript_open


def test_process_heartbeat_and_timeout_reap_child(tmp_path):
    m = module()
    progress = []
    start = monotonic()
    with pytest.raises(TimeoutError):
        m.run_process([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path / "process.log", timeout=.25,
                      progress=lambda *args: progress.append(args))
    assert monotonic() - start < 5
    assert progress and all(p[0] == p[1] == 0 for p in progress)
    assert "running" in progress[0][2]


def test_process_cancel_is_real_and_no_raw_document_logging(tmp_path):
    from core.tasks import TaskCancelled
    m = module()
    start = monotonic()
    with pytest.raises(TaskCancelled):
        m.run_process([sys.executable, "-c", "import time;print('CLIENT SECRET',flush=True);time.sleep(30)"],
                      tmp_path / "process.log", timeout=30, is_cancelled=lambda: monotonic() - start > .15)
    assert monotonic() - start < 5


def test_converter_compatibility_and_validation(tmp_path, monkeypatch):
    m = module()
    commands = []
    def run(command, log, **kwargs):
        commands.append(command)
        target = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("-sOutputFile=")))
        pdf(target)
    monkeypatch.setattr(m, "run_process", run)
    output = tmp_path / "output.pdf"
    assert m.convert_ps(tmp_path / "input.ps", output, "gs", timeout=300) == output
    assert "-dCompatibilityLevel=1.7" in commands[0]
    assert "-dSAFER" in commands[0]
    assert not any("PDFSETTINGS" in arg or "Downsample" in arg or "DetectDuplicateImages" in arg for arg in commands[0])
    with fitz.open(output) as doc:
        assert doc.page_count == 2


def test_failed_conversion_never_replaces_output(tmp_path, monkeypatch):
    m = module()
    target = pdf(tmp_path / "existing.pdf")
    before = target.read_bytes()
    monkeypatch.setattr(m, "run_process", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("failed")))
    with pytest.raises(RuntimeError):
        m.convert_ps(tmp_path / "a.ps", target, "gs")
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".existing-*.pdf"))


def setup_open(tmp_path, monkeypatch):
    m = module()
    from core.postscript_cache import PreviewCache
    source = tmp_path / "source.ps"
    source.write_bytes(b"%!PS source")
    cache = PreviewCache(tmp_path / "cache")
    calls = []
    def convert(src, out, exe, **kwargs):
        calls.append(Path(src).read_bytes())
        kwargs["trace"].values["ps_conversion"] = 1
        kwargs["trace"].values["ps_pdf_validation"] = 1
        return pdf(out)
    monkeypatch.setattr(m, "convert_ps", convert)
    monkeypatch.setattr(m, "converter_identity", lambda executable: IDENTITY)
    return m, source, cache, calls


def test_cold_open_then_cache_hit_and_save_is_independent(tmp_path, monkeypatch):
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    engine = m.open_postscript_engine(source, "gs", cache=cache)
    assert engine.page_count == 2 and calls == [source.read_bytes()]
    assert engine.open_trace.values["ps_cache_hit"] is False
    assert "ps_conversion" in engine.open_trace.values
    engine.close()
    engine = m.open_postscript_engine(source, "gs", cache=cache)
    try:
        assert len(calls) == 1 and engine.open_trace.values["ps_cache_hit"] is True
        engine.rotate_pages([0], 90)
        assert engine.is_modified
    finally:
        engine.close()
    with cache.acquire(hashlib.sha256(source.read_bytes()).hexdigest(), IDENTITY) as entry:
        with fitz.open(entry.path) as doc:
            assert doc[0].rotation == 0


def test_same_length_time_changed_content_misses(tmp_path, monkeypatch):
    import os
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    e = m.open_postscript_engine(source, "gs", cache=cache)
    e.close()
    old = source.stat()
    source.write_bytes(b"%!PS CHANGE")
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    e = m.open_postscript_engine(source, "gs", cache=cache)
    e.close()
    assert len(calls) == 2


def test_production_preview_first_open_does_not_convert(tmp_path, monkeypatch):
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    cache.store(pdf(tmp_path / "validated.pdf"), hashlib.sha256(source.read_bytes()).hexdigest(), IDENTITY,
                {"kind": "production-v1", "resolution_dpi": 600})
    e = m.open_postscript_engine(source, "gs", cache=cache)
    try:
        assert not calls and e.open_trace.values["ps_cache_hit"]
    finally:
        e.close()


def test_cancel_before_conversion_no_cache_or_engine(tmp_path, monkeypatch):
    from core.tasks import TaskCancelled
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    with pytest.raises(TaskCancelled):
        m.open_postscript_engine(source, "gs", cache=cache, is_cancelled=lambda: True)
    assert not calls


def test_cache_failure_still_opens_pdf(tmp_path, monkeypatch):
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    monkeypatch.setattr(cache, "store", lambda *a, **k: False)
    e = m.open_postscript_engine(source, "gs", cache=cache)
    try:
        assert calls and e.page_count == 2
    finally:
        e.close()


@pytest.mark.parametrize("enabled", [True, False])
def test_optional_fingerprint_failure_does_not_block_conversion(tmp_path, monkeypatch, enabled):
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    cache.enabled = enabled
    monkeypatch.setattr(m, "converter_identity", lambda *args: (_ for _ in ()).throw(PermissionError("identity unavailable")))
    engine = m.open_postscript_engine(source, "gs", cache=cache)
    try:
        assert engine.page_count == 2 and len(calls) == 1
    finally:
        engine.close()


def test_clear_during_cold_conversion_prevents_late_cache_repopulation(tmp_path, monkeypatch):
    m, source, cache, calls = setup_open(tmp_path, monkeypatch)
    original = m.convert_ps
    def convert(*args, **kwargs):
        result = original(*args, **kwargs)
        assert not cache.clear()["busy"]
        return result
    monkeypatch.setattr(m, "convert_ps", convert)
    e = m.open_postscript_engine(source, "gs", cache=cache)
    e.close()
    with cache.acquire(hashlib.sha256(source.read_bytes()).hexdigest(), IDENTITY) as hit:
        assert hit is None


@pytest.mark.parametrize("failure", ["timeout", "missing"])
def test_cancel_reaps_owned_process_when_windows_tree_stop_fails(tmp_path, monkeypatch, failure):
    import os
    import subprocess
    from types import SimpleNamespace

    from core.cancellation import TaskCancelled

    m = module()
    class Process:
        pid = 123456
        killed = False
        waits = 0
        def poll(self):
            return None if not self.killed else 0
        def wait(self, timeout):
            self.waits += 1
            if not self.killed:
                raise subprocess.TimeoutExpired("owned converter", timeout)
            return 0
        def kill(self):
            self.killed = True
    process = Process()
    def failed_tree_stop(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("taskkill", 5)
        raise FileNotFoundError("taskkill unavailable")
    monkeypatch.setattr(m, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(m.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(m.subprocess, "run", failed_tree_stop)
    checks = iter([False, True])
    log = tmp_path / "private.log"
    with pytest.raises(TaskCancelled):
        m.run_process(["owned-converter"], log, is_cancelled=lambda: next(checks))
    assert process.killed and process.waits == 2
    assert not log.exists()
