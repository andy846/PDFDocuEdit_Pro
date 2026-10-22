import logging

import fitz
import pytest
from PyQt6.QtWidgets import QApplication

from core.diagnostics import log_failure
from core.pdf_engine import PdfEngine
from core.tasks import FunctionTask
from updates.protocol import UpdateError, atomic_json
from updates.runtime import managed_launcher


def test_diagnostic_retains_trace_but_not_exception_payload(caplog):
    with caplog.at_level(logging.DEBUG):
        try:
            raise ValueError("private PDF text and password")
        except ValueError:
            log_failure("Reading field metadata failed")
    assert "Reading field metadata failed" in caplog.text
    assert "ValueError" in caplog.text
    assert "private PDF text and password" not in caplog.text


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_transaction_restores_and_preserves_process_interrupt(tmp_path, exception):
    path = tmp_path / "input.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    engine = PdfEngine()
    engine.open(path)
    try:
        with pytest.raises(exception), engine.mutation_transaction("Interrupted"):
            engine.rotate_pages([0], 90)
            raise exception()
        assert engine.document[0].rotation == 0
        assert not engine.is_modified
    finally:
        engine.close()


@pytest.mark.parametrize("exception", [ValueError, KeyboardInterrupt, SystemExit])
def test_task_failure_always_signals_completion(exception, monkeypatch):
    app = QApplication.instance() or QApplication([])
    closes = []
    monkeypatch.setattr(QApplication, "closeAllWindows", staticmethod(lambda: closes.append(True)))
    def fail():
        raise exception("hidden details")
    task = FunctionTask(fail)
    events = []
    task.signals.result.connect(lambda _: events.append("result"))
    task.signals.finished.connect(lambda: events.append("finished"))
    task.signals.cancelled.connect(lambda: events.append("cancelled"))
    task.signals.error.connect(lambda _: events.append("error"))
    task.run()
    assert events == (["error", "finished"] if exception is ValueError else ["cancelled", "finished"])
    app.processEvents()
    assert bool(closes) == (exception is SystemExit)


def test_canvas_failed_worker_releases_pending(monkeypatch):
    from ui import pdf_canvas
    app = QApplication.instance() or QApplication([])
    doc = fitz.open()
    doc.new_page()
    canvas = pdf_canvas.PdfCanvas()
    canvas._doc = doc
    canvas._generation = 3
    canvas._pending.add((3, 0))
    task = pdf_canvas._RenderTask(doc, 0, 1, 1, (), 3)
    monkeypatch.setattr(pdf_canvas, "render_page_image", lambda *args: (_ for _ in ()).throw(ValueError()))
    task.signals.finished.connect(canvas._on_render_done)
    task.run()
    app.processEvents()
    assert not canvas._pending
    canvas.clear()
    doc.close()


def test_launcher_detection_and_missing_files(tmp_path):
    folder = tmp_path / "中文 folder" / "versions" / "2.5.7"
    folder.mkdir(parents=True)
    executable = folder / "PDFDocuEdit Pro.exe"
    executable.touch()
    assert managed_launcher(executable) is None
    (folder / ".managed-update").write_text("2.5.7")
    with pytest.raises(UpdateError):
        managed_launcher(executable)
    root = folder.parent.parent
    atomic_json(root / "state.json", {"current": "2.5.7", "phase": "stable"})
    with pytest.raises(UpdateError):
        managed_launcher(executable)
    launcher = root / "Launcher.exe"
    launcher.touch()
    assert managed_launcher(executable) == launcher


def test_entrypoint_reports_launcher_spawn_failure(tmp_path, monkeypatch):
    import launcher
    import main
    import updates.runtime
    notices = []
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.delenv(updates.runtime.TOKEN_ENV, raising=False)
    monkeypatch.setattr(updates.runtime, "managed_launcher", lambda _: tmp_path / "Launcher.exe")
    monkeypatch.setattr(main.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(launcher, "notify", notices.append)
    assert main.main() == 1
    assert len(notices) == 1 and "Launcher.exe" in notices[0]
