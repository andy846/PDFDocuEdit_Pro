"""Applied unsaved watermarks must not leave a hidden IPC-owning viewer."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from core import viewer as viewer_module
from core.pdf_backend import fitz
from core.settings import SettingsManager
from core.watermarks import list_watermarks
from dialogs.annotation_dialogs import WatermarkDialog
from tests.test_open_performance import wait_until
from tests.test_private_auth_ui import approved
from tests.test_private_auth_ui import private as private
from updates.protocol import digest_file


@pytest.fixture
def live_private(private, monkeypatch, tmp_path):
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION", "0")
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    private.viewer_factory = viewer_module.PDFViewer
    private.controller.commit_approval(approved())
    private.managed_ready()
    yield private
    # The shared auth fixture uses lightweight windows. This fixture owns real
    # dirty PDFs, so retire them without a second operator prompt on failure.
    if private.viewer is not None:
        private.viewer._confirm_discard_changes = lambda: True
        private.viewer._close_lifecycle.stateChanged.disconnect(private._viewer_close_state_changed)


def source_pdf(path, rotation=0, image_only=False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.draw_rect(fitz.Rect(60, 60, 220, 200), color=(1, 0, 0), fill=(0, .5, 1))
        if not image_only:
            page.insert_text((72, 240), "Synthetic lifecycle test")
        else:
            image = page.get_pixmap().tobytes("png")
            doc.delete_page(0)
            page = doc.new_page()
            page.insert_image(page.rect, stream=image)
        page.set_rotation(rotation)
        doc.save(path)
    return path


def apply_watermark(viewer, monkeypatch):

    class AutoApply(WatermarkDialog):
        def exec(self):
            QTimer.singleShot(220, self._validate)
            return super().exec()

    monkeypatch.setattr(viewer_module, "WatermarkDialog", AutoApply)
    viewer._show_watermark_dialog()


def choose_unsaved(monkeypatch, answer, during_prompt=None):
    original_question = QMessageBox.question
    prompts = []

    def discard(*args, **kwargs):
        def choose():
            modal = QApplication.activeModalWidget()
            if isinstance(modal, QMessageBox):
                prompts.append(True)
                if during_prompt:
                    during_prompt()
                modal.button(answer).click()
        QTimer.singleShot(40, choose)
        return original_question(*args, **kwargs)

    monkeypatch.setattr(QMessageBox, "question", discard)
    return prompts


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("image_only", [False, True])
def test_applied_watermark_discard_exits_after_real_unsaved_prompt(
    live_private, qt_application, monkeypatch, tmp_path, rotation, image_only,
):
    private = live_private
    viewer = private.viewer
    exits = []
    monkeypatch.setattr(private, "_exit_app", lambda: exits.append(True))
    source = source_pdf(tmp_path / "source.pdf", rotation, image_only)
    before = digest_file(source)
    viewer.queue_open_files([str(source)])
    wait_until(lambda: not viewer._tasks and not viewer._open_queue_scheduled)
    session = viewer._session
    apply_watermark(viewer, monkeypatch)
    assert session.engine.is_modified
    assert len(list_watermarks(session.engine.document[0])) == 1
    prompts = choose_unsaved(monkeypatch, QMessageBox.StandardButton.Discard)
    viewer.close()
    wait_until(lambda: viewer._window_closed)
    qt_application.processEvents()
    qt_application.processEvents()
    assert prompts == [True]
    assert digest_file(source) == before
    assert private.exiting and private.viewer is None
    assert exits == [True]


def test_open_during_canceled_close_waits_then_renders(live_private, monkeypatch, tmp_path):
    private = live_private
    viewer = private.viewer
    original = viewer._open_in_new_tab_sync(str(source_pdf(tmp_path / "edited.pdf")))
    apply_watermark(viewer, monkeypatch)
    next_path = source_pdf(tmp_path / "other.pdf")
    def forwarded():
        private.accept_paths([str(next_path)])
        assert private.pending_paths == [str(next_path)]
        assert len(viewer._sessions) == 1
    choose_unsaved(monkeypatch, QMessageBox.StandardButton.Cancel, forwarded)
    assert not viewer.close()
    wait_until(lambda: len(viewer._sessions) == 2 and not viewer._tasks)
    second = viewer._session
    wait_until(lambda: second.canvas._page_views[0].overlay._pixmap is not None)
    assert original.engine.is_modified and not private.exiting
    assert not private.pending_paths


def test_open_during_discard_uses_fresh_viewer(live_private, monkeypatch, tmp_path):
    private = live_private
    old = private.viewer
    old._open_in_new_tab_sync(str(source_pdf(tmp_path / "edited.pdf")))
    apply_watermark(old, monkeypatch)
    incoming = source_pdf(tmp_path / "new.pdf")
    exits = []
    monkeypatch.setattr(private, "_exit_app", lambda: exits.append(True))
    choose_unsaved(monkeypatch, QMessageBox.StandardButton.Discard,
                   lambda: private.accept_paths([str(incoming)]))
    old.close()
    wait_until(lambda: private.viewer is not old)
    assert private.viewer is not None and not private.exiting
    viewer = private.viewer
    wait_until(lambda: viewer._session is not None and viewer.engine.is_loaded() and not viewer._tasks)
    wait_until(lambda: viewer._session.canvas._page_views[0].overlay._pixmap is not None)
    assert viewer._session.display_path == incoming
    assert not exits and not private.pending_paths


def test_save_from_unsaved_prompt_preserves_watermark_and_exits(live_private, monkeypatch, tmp_path):
    private = live_private
    viewer = private.viewer
    exits = []
    monkeypatch.setattr(private, "_exit_app", lambda: exits.append(True))
    source = source_pdf(tmp_path / "saved.pdf")
    before = digest_file(source)
    viewer._open_in_new_tab_sync(str(source))
    apply_watermark(viewer, monkeypatch)
    choose_unsaved(monkeypatch, QMessageBox.StandardButton.Save)
    viewer.close()
    wait_until(lambda: private.exiting)
    assert exits == [True] and digest_file(source) != before
    with fitz.open(source) as doc:
        assert len(list_watermarks(doc[0])) == 1


def test_canceled_failed_preview_does_not_block_exit(live_private, monkeypatch, tmp_path):
    from ui import watermark_preview
    private = live_private
    viewer = private.viewer
    exits = []
    monkeypatch.setattr(private, "_exit_app", lambda: exits.append(True))
    source = source_pdf(tmp_path / "preview-failure.pdf")
    before = digest_file(source)
    session = viewer._open_in_new_tab_sync(str(source))
    def fail(*args, **kwargs):
        raise ValueError("PRIVATE_PREVIEW_VALUE")
    monkeypatch.setattr(watermark_preview, "add_watermark", fail)
    class CancelAfterFailure(WatermarkDialog):
        def exec(self):
            self._start_preview()
            wait_until(lambda: all(task.done.is_set() for task in self._preview_jobs))
            self.reject()
            return QDialog.DialogCode.Rejected
    monkeypatch.setattr(viewer_module, "WatermarkDialog", CancelAfterFailure)
    viewer._show_watermark_dialog()
    assert not session.engine.is_modified
    viewer.close()
    wait_until(lambda: private.exiting)
    assert exits == [True] and digest_file(source) == before


def test_canceled_preview_reader_finishes_before_exit(live_private, monkeypatch, tmp_path):
    from threading import Event

    from ui import watermark_preview
    private = live_private
    viewer = private.viewer
    monkeypatch.setattr(private, "_exit_app", lambda: None)
    source = source_pdf(tmp_path / "reader.pdf")
    session = viewer._open_in_new_tab_sync(str(source))
    doc = session.engine.document
    started, release = Event(), Event()
    run = watermark_preview.WatermarkPreviewTask.run
    def held(task):
        started.set()
        release.wait(5)
        run(task)
    monkeypatch.setattr(watermark_preview.WatermarkPreviewTask, "run", held)
    class CancelWithReader(WatermarkDialog):
        def exec(self):
            self._start_preview()
            wait_until(started.is_set)
            self.reject()
            return QDialog.DialogCode.Rejected
    monkeypatch.setattr(viewer_module, "WatermarkDialog", CancelWithReader)
    try:
        viewer._show_watermark_dialog()
        assert not viewer.close()
        assert not doc.is_closed and not private.exiting
        assert not viewer.can_accept_open_requests()
    finally:
        release.set()
    wait_until(lambda: private.exiting)
    assert doc.is_closed and private.viewer is None


@pytest.mark.parametrize("entry", ["queue_open_files", "open_in_new_tab", "load_file"])
def test_retired_viewer_cannot_create_ghost_tabs(live_private, tmp_path, entry):
    viewer = live_private.viewer
    source = source_pdf(tmp_path / "ignored.pdf")
    count = len(viewer._sessions)
    viewer._window_closed = True
    try:
        getattr(viewer, entry)([str(source)] if entry == "queue_open_files" else str(source))
        assert len(viewer._sessions) == count
        assert not viewer._queued_open_paths and not viewer._tasks
    finally:
        viewer._window_closed = False


def test_locked_cancel_keeps_access_revoked_and_paths_pending(live_private, monkeypatch, tmp_path):
    from auth import guard
    private = live_private
    viewer = private.viewer
    session = viewer._open_in_new_tab_sync(str(source_pdf(tmp_path / "locked.pdf")))
    apply_watermark(viewer, monkeypatch)
    private.lock("Synthetic revocation")
    incoming = str(source_pdf(tmp_path / "must-wait.pdf"))
    choose_unsaved(monkeypatch, QMessageBox.StandardButton.Cancel,
                   lambda: private.accept_paths([incoming]))
    private.quit()
    QApplication.processEvents()
    QApplication.processEvents()
    assert private.viewer is viewer and session.engine.is_modified
    assert private.locked and not guard.runtime_access
    assert not viewer.isEnabled() and private.pending_paths == [incoming]
    assert len(viewer._sessions) == 1 and not viewer._queued_open_paths


def test_account_switch_cancel_retains_original_account(live_private, monkeypatch, tmp_path):
    private = live_private
    viewer = private.viewer
    viewer._open_in_new_tab_sync(str(source_pdf(tmp_path / "account.pdf")))
    apply_watermark(viewer, monkeypatch)
    old = private.controller.approval
    choose_unsaved(monkeypatch, QMessageBox.StandardButton.Cancel)
    private.prepare_account(approved("0a308a5f-b50d-4caa-9dbe-0c145f5782eb"))
    QApplication.processEvents()
    QApplication.processEvents()
    assert private.viewer is viewer and private.controller.approval == old
    assert private.viewer_account == old.user_id and private.pending_approval is None


def test_discard_then_other_pdf_in_actual_new_process(tmp_path):
    directory = tmp_path / "restart"
    subprocess.run([sys.executable, "-m", "tests.qa_watermark_restart", "--directory", str(directory)],
                   cwd=Path(__file__).resolve().parent.parent,
                   env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                   capture_output=True, text=True, check=True, timeout=90)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert result["passed"] and result["separate_processes"]
    assert all(row["exiting"] and row["viewer_released"] and row["source_unchanged"]
               and row["non_white_samples"] > 0 for row in result["reports"])


@pytest.mark.parametrize("deleted", ["application", "viewer"])
def test_deferred_close_observer_ignores_deleted_qobjects(qt_application, deleted):
    from PyQt6 import sip
    from PyQt6.QtCore import QObject

    from auth.application import PrivateApplication
    owner = QObject()
    session = QObject()
    calls = []
    session.viewer = owner
    session._closed = lambda: calls.append(True)
    PrivateApplication._schedule_closed_check(session)
    sip.delete(session if deleted == "application" else owner)
    qt_application.processEvents()
    assert calls == []
    if not sip.isdeleted(session):
        sip.delete(session)
    if not sip.isdeleted(owner):
        sip.delete(owner)
