"""Process isolation, single document ownership and raster parity checks."""
import io
import json
import sys
import threading

import fitz
import pytest

from core.pdf_engine import DOCUMENT_LOCK
from core.printing import (
    PrintJob,
    PrintRenderSettings,
    prepare_print_job,
    render_page_image,
    render_print_page,
)
from tests.test_printing import app, pdf, printer_factory, settings, wait_for
from ui.print_controller import PrintController


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("mode", [0, 1, 2])
def test_process_raster_matches_existing_rendering(tmp_path, rotation, mode):
    app()
    source = pdf(tmp_path / "source.pdf", 1)
    with fitz.open(source) as document:
        page = document[0]
        page.set_cropbox(fitz.Rect(10, 15, 190, 285))
        page.set_rotation(rotation)
        snapshot = document.tobytes()
        cfg = PrintRenderSettings(72, 250, 300, 4, 7, mode, 85, True, 2, -3)
        expected = render_page_image(page, cfg)
    prepared = prepare_print_job(PrintJob(snapshot, "test", "test"))
    directory = prepared.session.directory
    try:
        actual = render_print_page(prepared, 0, cfg)
        assert actual[1:] == expected[1:]
        assert actual[0] == expected[0]
        assert not (directory / "page.rgb").exists()
    finally:
        prepared.session.close()
    assert not directory.exists()


def test_windowed_worker_binds_missing_python_streams(tmp_path, monkeypatch):
    from core import print_worker

    source = pdf(tmp_path / "source.pdf", 2)
    directory = tmp_path / "worker"
    directory.mkdir()
    requests = [{"id": 1, "command": "prepare", "source": str(source), "pages": None},
                {"id": 2, "command": "render_page", "index": 1, "dpi": 72},
                {"id": 3, "command": "close_document"}, {"id": 4, "command": "shutdown"}]

    class RetainedStream(io.StringIO):
        def close(self):
            self.final_value = self.getvalue()
            super().close()

    stdin = RetainedStream("".join(json.dumps(value) + "\n" for value in requests))
    stdout = RetainedStream()
    bindings = []

    def bind(number, mode):
        bindings.append((number, mode))
        return stdin if mode == "r" else stdout

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", None)
        patch.setattr(sys, "stdout", None)
        patch.setattr(print_worker, "_windows_pipe_stream", bind)
        assert print_worker.main([str(directory)]) == 0
    responses = [json.loads(line) for line in stdout.final_value.splitlines()]
    assert bindings == [(-10, "r"), (-11, "w")]
    assert stdin.closed and stdout.closed
    assert responses[0]["event"] == "ready"
    assert [item["id"] for item in responses[1:]] == [1, 2, 3]
    assert responses[1]["result"]["pages"] == [0, 1]
    assert responses[2]["result"]["width"] > 0
    assert not (directory / "input.pdf").exists()
    assert not (directory / "page.rgb").exists()


def test_parent_document_lock_does_not_block_print_worker(tmp_path):
    prepared = prepare_print_job(PrintJob(str(pdf(tmp_path / "source.pdf")), "test", "test"))
    outcome = []

    def render():
        outcome.append(render_print_page(prepared, 0, settings(None)))

    try:
        with DOCUMENT_LOCK:
            thread = threading.Thread(target=render)
            thread.start()
            thread.join(timeout=5)
            assert not thread.is_alive(), "Print rendering waited for the editor's global lock"
        assert outcome
    finally:
        prepared.session.close()


def test_document_is_not_reopened_between_pages(tmp_path, monkeypatch):
    from core import print_worker

    source = pdf(tmp_path / "source.pdf", 100)
    directory = tmp_path / "worker"
    directory.mkdir()
    requests = [{"id": 1, "command": "prepare", "source": str(source), "pages": None}]
    requests += [{"id": i + 2, "command": "render_page", "index": page, "dpi": 72}
                 for i, page in enumerate((0, 20, 99, 0))]
    requests += [{"id": 6, "command": "close_document"}, {"id": 7, "command": "shutdown"}]
    calls = []
    original = fitz.open

    def open_document(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    output = io.StringIO()
    monkeypatch.setattr(print_worker.fitz, "open", open_document)
    monkeypatch.setattr(print_worker.sys, "stdin", io.StringIO("\n".join(map(json.dumps, requests))))
    monkeypatch.setattr(print_worker.sys, "stdout", output)
    assert print_worker.main([str(directory)]) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()
                 if "ready" not in line]
    assert len(calls) == 1
    assert len(responses) == 6 and all("error" not in value for value in responses)
    assert not (directory / "input.pdf").exists()


def test_worker_crash_isolated_and_next_file_can_print(tmp_path, monkeypatch):
    import ui.print_controller as module

    app()
    original = module.render_print_page
    killed = False

    def render(prepared, *args, **kwargs):
        nonlocal killed
        if not killed:
            killed = True
            prepared.session.kill()
            prepared.session.process.wait(timeout=5)
        return original(prepared, *args, **kwargs)

    monkeypatch.setattr(module, "render_print_page", render)
    jobs = [PrintJob(str(pdf(tmp_path / f"{i}.pdf")), f"{i}.pdf", str(i)) for i in range(2)]
    done, states = [], []
    controller = PrintController(jobs, printer_factory(tmp_path, []), settings)
    controller.finished.connect(lambda *value: done.append(value))
    controller.file_finished.connect(lambda *value: states.append(value))
    controller.start()
    wait_for(lambda: bool(done), timeout=15)
    assert done == [(1, 1, 0, False)]
    assert [value[1] for value in states] == ["failed", "sent"]
    assert controller._render_session is None
    controller.deleteLater()


def test_cancel_terminates_unresponsive_renderer_and_cleans_temp(tmp_path, monkeypatch):
    import core.printing as module

    app()
    original = module.subprocess.Popen
    script = (
        "import json,os,sys,time; from pathlib import Path; "
        "folder=Path(sys.argv[1]); print(json.dumps({'event':'ready','pid':os.getpid()}),flush=True)\n"
        "for line in sys.stdin:\n"
        " r=json.loads(line)\n"
        " if r['command']=='prepare':\n"
        "  print(json.dumps({'id':r['id'],'result':{'pages':[0],'first_size':[200,300]}}),flush=True)\n"
        " elif r['command']=='render_page':\n"
        "  (folder/'busy').touch(); time.sleep(30)\n"
        " else: break\n"
    )

    def launch(args, **kwargs):
        return original([sys.executable, "-c", script, args[-1]], **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    done = []
    controller = PrintController([PrintJob("unused.pdf", "cancel.pdf", "cancel")],
                                 printer_factory(tmp_path, []), settings)
    controller.finished.connect(lambda *value: done.append(value))
    controller.start()
    wait_for(lambda: controller._render_session is not None
             and (controller._render_session.directory / "busy").exists())
    directory = controller._render_session.directory
    controller.cancel()
    wait_for(lambda: bool(done), timeout=9)
    assert done == [(0, 0, 0, True)]
    assert not directory.exists()
    assert not (tmp_path / "printed-cancel.pdf").exists()
    controller.deleteLater()
