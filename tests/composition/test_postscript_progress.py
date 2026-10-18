"""Observable, cancellable PS conversion without pretending an unknown stage is 0%."""
import subprocess

import pytest

import composition.media.postscript as postscript


def converter(monkeypatch, chunks):
    created = []

    class Process:
        returncode = None

        def __init__(self, command, **options):
            self.command = command
            self.log = options["stdout"]
            self.chunks = iter(chunks)
            self.terminated = False
            created.append(self)

        def wait(self, timeout=None):
            if self.returncode is not None:
                return self.returncode
            chunk = next(self.chunks, None)
            if chunk is None:
                self.returncode = 0
                return 0
            self.log.write(chunk)
            self.log.flush()
            raise subprocess.TimeoutExpired(self.command, timeout)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -1

    monkeypatch.setattr(postscript.subprocess, "Popen", Process)
    return created


def test_converter_reports_partial_page_lines_and_keeps_diagnostics(tmp_path, monkeypatch):
    created = converter(monkeypatch, [b"Processing pages 1 through 3.\nPage 1\n", b"Pa", b"ge 2\n", b"Page 3\n"])
    events = []
    try:
        postscript._run("gs", ["-sDEVICE=ps2write"], tmp_path, None,
                        progress=lambda *event: events.append(event), total=3, stage="PostScript conversion")
    except TypeError as exc:
        pytest.fail(f"Converter does not provide progress: {exc}")
    assert "-q" not in created[0].command
    assert any(done == 1 and total == 3 for done, total, _ in events)
    assert any("page 2" in message.lower() for _, _, message in events)
    assert (tmp_path / "ghostscript.log").read_bytes().endswith(b"Page 3\n")


def test_converter_without_page_updates_has_heartbeat_not_fake_percentage(tmp_path, monkeypatch):
    converter(monkeypatch, [b"", b"", b""])
    ticks = iter(range(100))
    monkeypatch.setattr(postscript, "monotonic", lambda: next(ticks), raising=False)
    events = []
    try:
        postscript._run("gs", [], tmp_path, None, progress=lambda *event: events.append(event),
                        total=2388, stage="PostScript conversion")
    except TypeError as exc:
        pytest.fail(f"Converter heartbeat is missing: {exc}")
    assert len(events) >= 3
    assert all(done == total == 0 for done, total, _ in events)
    assert any("elapsed" in message.lower() for _, _, message in events)
    assert len({message for _, _, message in events}) > 1


def test_progress_callback_failure_still_reaps_converter(tmp_path, monkeypatch):
    created = converter(monkeypatch, [b"Page 1\n"])

    def fail(*event):
        raise RuntimeError("observer failed")

    try:
        with pytest.raises(RuntimeError, match="observer failed"):
            postscript._run("gs", [], tmp_path, None, progress=fail, total=1)
    except TypeError as exc:
        pytest.fail(f"Converter progress API is missing: {exc}")
    assert created and created[0].terminated


def test_real_production_reports_each_ps_stage(tmp_path):
    from composition.production.model import ProductionJob
    from tests.composition.test_postscript import model, ps_media
    from tests.production_approval import generate

    events = []
    result = generate(ProductionJob(model(ps_media(), count=1).to_dict(), "", str(tmp_path)),
                      progress=lambda *event: events.append(event))
    assert result.status == "completed", result.error
    assert any("PostScript conversion" in message for _, _, message in events)
    assert any(done > 0 and total == 3 and "PostScript conversion" in message
               for done, total, message in events)
    assert any("PostScript media" in message for _, _, message in events)
    assert any("PostScript validation" in message for _, _, message in events)
    assert result.media_summary["postscript_conversion_seconds"] >= 0
    assert result.media_summary["postscript_validation_seconds"] >= 0


def test_oversize_converter_output_terminates_and_reaps_child(tmp_path,monkeypatch):
    from composition.production.output_policy import OutputPartTooLarge, OutputPolicy
    created=converter(monkeypatch,[b"Page 1\n"])
    target=tmp_path/"converted.ps"
    target.write_bytes(b"x"*101)
    policy=OutputPolicy(pdf_bytes=1000,ps_bytes=100)
    with pytest.raises(OutputPartTooLarge):
        postscript._run("gs",[],tmp_path,None,output_policy=policy,monitored=target)
    assert created[0].terminated and created[0].poll() is not None
