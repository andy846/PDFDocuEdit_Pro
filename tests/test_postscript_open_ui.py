"""Existing Editor queue and Preferences integrations."""
from threading import Event

import pytest

from tests.test_document_windows import editor as editor
from tests.test_open_performance import wait_until


def test_ps_queue_reports_and_cancel_keeps_task_until_finished(editor, tmp_path, monkeypatch):
    from core import viewer
    from core.tasks import TaskCancelled
    source = tmp_path / "input.ps"
    source.write_bytes(b"%!PS")
    entered, release = Event(), Event()
    received = {}
    def prepare(path, password=None, **kwargs):
        received.update(kwargs)
        kwargs["progress"](0, 0, "PostScript conversion · process running")
        entered.set()
        release.wait(5)
        if kwargs["is_cancelled"]():
            raise TaskCancelled
        raise AssertionError("expected cancellation")
    monkeypatch.setattr(viewer, "_prepare_pdf_engine", prepare)
    try:
        editor.load_file(str(source))
        wait_until(entered.is_set)
        wait_until(lambda: "PostScript" in editor.task_bar._detail.text())
        assert editor.task_bar._cancel.isVisible()
        editor.task_bar._cancel.click()
        assert editor._tasks  # cooperative cancellation is not completion
        release.set()
        wait_until(lambda: not editor._tasks and not editor._open_queue_scheduled)
        assert editor.bottom_bar._status.text() == "Cancelled"
        assert received["cache_config"]["enabled"]
    finally:
        release.set()


def test_prepare_ps_passes_cancel_without_error_status(tmp_path, monkeypatch):
    from core import postscript_open, viewer
    from core.tasks import TaskCancelled
    monkeypatch.setattr(postscript_open, "open_postscript_engine", lambda *a, **k: (_ for _ in ()).throw(TaskCancelled()))
    with pytest.raises(TaskCancelled):
        viewer._prepare_pdf_engine(str(tmp_path / "a.ps"), is_cancelled=lambda: True)


def test_preferences_cache_toggle_and_background_clear(qt_application, tmp_path, monkeypatch):
    from core import resources
    from core.postscript_cache import PreviewCache
    from core.settings import SettingsManager
    from tests.test_postscript_cache import IDENTITY, PROFILE, SOURCE, pdf
    from ui.diagnostics_dialog import PreferencesDialog
    monkeypatch.setattr(resources, "cache_dir", lambda: tmp_path / "application-cache")
    settings = SettingsManager(tmp_path / "settings.json")
    cache = PreviewCache(resources.cache_dir() / "postscript-previews-v1")
    cache.store(pdf(tmp_path / "a.pdf"), SOURCE, IDENTITY, PROFILE)
    dialog = PreferencesDialog(settings)
    try:
        dialog.show()
        assert dialog.ps_cache_enabled.isChecked()
        dialog.ps_cache_clear.click()
        wait_until(lambda: dialog._ps_cache_task is None)
        with cache.acquire(SOURCE, IDENTITY) as hit:
            assert hit is None
        dialog.ps_cache_enabled.setChecked(False)
        dialog.accept()
        assert settings.get("ps_preview_cache_enabled") is False
    finally:
        dialog.close()


def test_clear_task_can_finish_after_preferences_destroyed(qt_application, tmp_path, monkeypatch):
    from PyQt6 import sip

    from core import resources
    from core.postscript_cache import PreviewCache
    from core.settings import SettingsManager
    from ui import diagnostics_dialog
    from ui.diagnostics_dialog import PreferencesDialog
    monkeypatch.setattr(resources, "cache_dir", lambda: tmp_path / "cache")
    entered, release = Event(), Event()
    def clear(self):
        entered.set()
        assert release.wait(5)
        return {"removed": 0, "busy": False}
    monkeypatch.setattr(PreviewCache, "clear", clear)
    dialog = PreferencesDialog(SettingsManager(tmp_path / "settings.json"))
    try:
        dialog._clear_ps_cache()
        wait_until(entered.is_set)
        sip.delete(dialog)
        release.set()
        wait_until(lambda: not diagnostics_dialog._PS_CACHE_CLEAR_TASKS)
    finally:
        release.set()
        if not sip.isdeleted(dialog):
            dialog.close()


@pytest.mark.parametrize("width", [960, 760])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_long_ps_progress_keeps_cancel_reachable(editor, qt_application, width, theme):
    from PyQt6.QtCore import QPoint

    from styles.theme import apply_theme
    apply_theme(qt_application, theme)
    editor.resize(width, 640)
    editor.task_bar.start("Opening document", cancellable=True)
    message = "PostScript conversion · elapsed 45:20 · process running · no page notifications available"
    editor.task_bar.update_progress(0, 0, message)
    qt_application.processEvents()
    cancel = editor.task_bar._cancel
    right = cancel.mapTo(editor, QPoint(cancel.width(), 0)).x()
    assert editor.width() <= width
    assert right <= editor.width()


def test_isolated_production_worker_receives_cache_via_private_stdin(qt_application, tmp_path, monkeypatch):
    from dataclasses import asdict

    from composition.designer.process import Worker, approval_session
    from composition.media.postscript import ghostscript_executable
    from composition.production.model import ProductionJob
    from core import postscript_cache, postscript_open
    from tests.composition.test_postscript import model, ps_media
    from tests.production_approval import review_contexts
    cache = postscript_cache.PreviewCache(tmp_path / "cache")
    monkeypatch.setattr(postscript_cache, "application_cache_config", lambda settings=None: {"root": str(cache.root), "enabled": True})
    job = ProductionJob(model(ps_media(), count=1).to_dict(), "", str(tmp_path / "output"))
    receipts = review_contexts(tmp_path / "review", [{"kind": "template", "job": asdict(job)}], approval_session())
    worker = Worker(tmp_path / "ipc", {"task": "generate", "job": asdict(job), "production_review": receipts[0]})
    results, errors, ended = [], [], []
    worker.resultReady.connect(results.append)
    worker.failed.connect(errors.append)
    worker.ended.connect(lambda: ended.append(True))
    wait_until(lambda: bool(results or errors))
    assert not errors, errors
    assert results[0]["status"] == "completed"
    wait_until(lambda: bool(ended))
    monkeypatch.setattr(postscript_open, "convert_ps", lambda *a, **k: pytest.fail("worker preview was not cached"))
    e = postscript_open.open_postscript_engine(results[0]["output_ps"], ghostscript_executable(), cache=cache)
    try:
        assert e.open_trace.values["ps_cache_hit"]
    finally:
        e.close()
