"""Cancellable PostScript interpretation and independent Editor working copies."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from time import monotonic

from core.pdf_io import validate_pdf_file
from core.performance import PerformanceTrace
from core.postscript_cache import PreviewCache, check_cancel, converter_identity, source_snapshot

_LOG = logging.getLogger("pdfdocuedit")


def _stop(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Stop this owned process tree, including executable forwarding shims.
        taskkill = Path(os.environ.get("SystemRoot", "C:/Windows"))/"System32/taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            # Failure of the tree helper must not skip owned-process reaping
            # or replace the original cancellation/timeout with a helper error.
            _LOG.warning("PostScript process-tree stop unavailable; using owned-process fallback")
    else:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_process(command, log_path, *, timeout=300, progress=None, is_cancelled=None):
    """Drain into bounded private storage; never publish PS print output as logs."""
    started = reported = monotonic()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = None
    log_path = Path(log_path)
    try:
        check_cancel(is_cancelled)
        with log_path.open("w+b") as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, **options)
            def heartbeat(finished=False):
                nonlocal reported
                now = monotonic()
                if progress and (finished or now-reported >= 1 or reported == started):
                    elapsed = int(now-started)
                    state = "process finished" if finished else "process running"
                    quiet = " · no page notifications available" if elapsed >= 30 and not finished else ""
                    progress(0, 0, f"PostScript conversion · elapsed {elapsed//60:02d}:{elapsed%60:02d} · {state}{quiet}")
                    reported = now
            heartbeat()
            while True:
                check_cancel(is_cancelled)
                if monotonic()-started >= timeout:
                    raise TimeoutError(f"PostScript conversion reached its {int(timeout)}s time limit. No output was installed.")
                try:
                    code = process.wait(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    heartbeat()
                    if os.fstat(stream.fileno()).st_size > 256*1024:
                        # Diagnostic text can include document print operations.
                        # It is not persisted or forwarded to the application log.
                        stream.seek(0)
                        stream.truncate(0)
            check_cancel(is_cancelled)
            if code:
                raise RuntimeError(f"Ghostscript conversion failed (exit {code}). No output was installed.")
            heartbeat(finished=True)
    finally:
        if process is not None:
            _stop(process)
        log_path.unlink(missing_ok=True)


def convert_ps(source, target, executable, *, timeout=300, progress=None, is_cancelled=None, trace=None,
               profile=None):
    target = Path(target).expanduser().resolve()
    source = Path(source).expanduser().resolve()
    if source == target:
        raise ValueError("PostScript conversion cannot overwrite its source.")
    target.parent.mkdir(parents=True, exist_ok=True)
    profile = profile or {"kind": "editor-v1"}
    if profile != {"kind": "editor-v1"}:
        raise ValueError("Unsupported Editor conversion profile.")
    trace = trace or PerformanceTrace("postscript_conversion")
    with tempfile.TemporaryDirectory(prefix=".ps-convert-", dir=target.parent) as directory:
        temporary = Path(directory) / "converted.pdf"
        command = [str(executable), "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                   "-dCompatibilityLevel=1.7", f"-sOutputFile={temporary}", str(source)]
        with trace.span("ps_conversion"):
            run_process(command, Path(directory)/"process.log", timeout=timeout,
                        progress=progress, is_cancelled=is_cancelled)
        check_cancel(is_cancelled)
        if progress:
            progress(0, 0, "Validating converted PDF")
        from core.pdf_engine import DOCUMENT_LOCK
        with trace.span("ps_pdf_validation"), DOCUMENT_LOCK:
            validate_pdf_file(temporary, is_cancelled=is_cancelled, progress=progress)
        check_cancel(is_cancelled)
        os.replace(temporary, target)
    return target


def open_postscript_engine(source, executable, *, cache=None, progress=None, is_cancelled=None):
    from core.pdf_engine import DOCUMENT_LOCK, PdfEngine

    trace = PerformanceTrace("open_document")
    engine = PdfEngine()
    cache = cache or PreviewCache(Path(tempfile.gettempdir())/"unused-ps-cache", enabled=False)
    cache.pdf_lock = DOCUMENT_LOCK
    try:
        check_cancel(is_cancelled)
        identity = None
        cache_epoch = cache.epoch() if cache.active else None
        if cache.active:
            with trace.span("ps_converter_identity"):
                try:
                    identity = converter_identity(executable)
                except (OSError, ValueError, subprocess.SubprocessError):
                    trace.values["ps_cache_status"] = "converter_identity_unavailable"
                    cache = PreviewCache(cache.root, enabled=False)
        if identity is None:
            identity = {}
        with tempfile.TemporaryDirectory(prefix="pdfdocuedit-ps-open-") as scratch:
            snapshot_started = monotonic()
            with source_snapshot(source, scratch, progress=progress, is_cancelled=is_cancelled) as (snapshot, digest):
                trace.values["ps_source_snapshot"] = round((monotonic()-snapshot_started)*1000, 3)
                trace.values["ps_cache_hit"] = False
                if progress:
                    progress(0, 0, "Checking PostScript preview cache")
                lookup_started = monotonic()
                with cache.acquire(digest, identity, is_cancelled=is_cancelled) as hit:
                    trace.values["ps_cache_lookup"] = round((monotonic()-lookup_started)*1000, 3)
                    trace.values.setdefault("ps_cache_status", cache.last_status)
                    if hit is not None:
                        check_cancel(is_cancelled)
                        if progress:
                            progress(0, 0, "Opening verified PostScript preview")
                        engine.open(hit.path)
                        trace.values["ps_cache_hit"] = True
                        trace.values["ps_preview_profile"] = hit.profile["kind"]
                if not engine.is_loaded():
                    output = Path(scratch)/"converted.pdf"
                    convert_ps(snapshot, output, executable, timeout=3600, progress=progress,
                               is_cancelled=is_cancelled, trace=trace)
                    check_cancel(is_cancelled)
                    if progress:
                        progress(0, 0, "Opening converted PDF")
                    engine.open(output)
                    check_cancel(is_cancelled)
                    with trace.span("ps_cache_store"):
                        cache.store(output, digest, identity, {"kind": "editor-v1"}, is_cancelled=is_cancelled, expected_epoch=cache_epoch)
                check_cancel(is_cancelled)
        native = dict(engine.open_trace.values)
        native["pdf_preparation"] = native.pop("preparation", 0)
        trace.values.update(native)
        trace.mark("preparation")
        engine.open_trace = trace
        trace.report("ps_prepared")
        return engine
    except BaseException:
        engine.close()
        raise
