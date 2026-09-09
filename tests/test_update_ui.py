from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QApplication, QWidget

from core.resources import config_dir_path, data_dir
from ui.update_dialog import UpdateDialog, UpdateWorker
from updates.protocol import read_json
from updates.runtime import ROOT_ENV, TOKEN_ENV


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


class Viewer(QWidget):
    def __init__(self, allow_close):
        super().__init__()
        self.allow_close = allow_close

    def closeEvent(self, event):
        event.setAccepted(self.allow_close)


def test_cancelled_unsaved_document_does_not_request_restart(app, tmp_path, monkeypatch):
    monkeypatch.delenv(ROOT_ENV, raising=False)
    viewer = Viewer(False)
    dialog = UpdateDialog(viewer)
    dialog.root = tmp_path
    dialog.restart()
    assert not (tmp_path / "restart.json").exists()
    assert not getattr(viewer, "_update_restart", False)
    assert "postponed" in dialog.status.text()
    viewer.allow_close = True
    dialog.close()
    viewer.close()


def test_successful_close_requests_supervised_restart(app, tmp_path, monkeypatch):
    monkeypatch.delenv(ROOT_ENV, raising=False)
    monkeypatch.setenv(TOKEN_ENV, "test-launch-token")
    viewer = Viewer(True)
    dialog = UpdateDialog(viewer)
    dialog.root = tmp_path
    dialog.restart()
    assert viewer._update_restart
    assert read_json(tmp_path / "restart.json")["token"] == "test-launch-token"
    dialog.close()


def test_unmanaged_build_explains_bootstrap(app, monkeypatch):
    monkeypatch.delenv(ROOT_ENV, raising=False)
    viewer = Viewer(True)
    dialog = UpdateDialog(viewer)
    assert not dialog.action.isEnabled()
    assert "Launcher.exe" in dialog.status.text()
    dialog.close()
    viewer.close()


def test_settings_and_associations_use_stable_root(app, tmp_path, monkeypatch):
    from core.file_association import _executable

    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    assert config_dir_path() == tmp_path / "data" / "config"
    assert data_dir() == tmp_path / "data"
    assert _executable() == str(tmp_path / "Launcher.exe")


def test_update_worker_error_returns_signal_without_ui_block(app, tmp_path, monkeypatch):
    import ui.update_dialog as module

    def offline(*_):
        raise OSError("network unavailable")

    monkeypatch.setattr(module, "check_release", offline)
    errors = []
    worker = UpdateWorker(tmp_path)
    worker.failed.connect(errors.append)
    worker.start()
    assert worker.wait(2000)
    QCoreApplication.processEvents()
    assert errors == ["network unavailable"]


def test_qt_startup_disables_editor_until_matching_acceptance(app, tmp_path, monkeypatch):
    from updates.app_session import activate
    from updates.protocol import atomic_json
    from updates.runtime import queue_launch

    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(TOKEN_ENV, "unique-token")
    viewer = Viewer(True)
    calls = []
    activate(viewer, calls.append)
    assert not viewer.isEnabled()
    assert read_json(tmp_path / "ready-unique-token.json")["token"] == "unique-token"
    atomic_json(tmp_path / "accepted-unique-token.json", {"token": "wrong"})
    viewer._update_handshake_timer.timeout.emit()
    assert not viewer.isEnabled()
    atomic_json(tmp_path / "accepted-unique-token.json", {"token": os.environ[TOKEN_ENV]})
    viewer._update_handshake_timer.timeout.emit()
    assert viewer.isEnabled()
    queue_launch(tmp_path, ["document.pdf"])
    viewer._update_requests_timer.timeout.emit()
    assert calls == [[], ["document.pdf"]]
    assert not list((tmp_path / "requests").glob("*.json"))
    viewer._update_requests_timer.stop()
    viewer.close()
