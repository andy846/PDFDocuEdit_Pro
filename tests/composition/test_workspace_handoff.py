"""Focused integration checks for the two workspace handoff loop."""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox

from composition.designer.overlay_workspace import OverlayWindow
from composition.designer.workspace import CompositionWindow
from composition.overlay.serializer import load_project
from core.pdf_engine import DOCUMENT_LOCK, SearchHit
from tests.composition.test_pdf_overlay_models import make_source
from tests.composition.test_workspace import wait_until
from tests.composition.test_workspace_modes import app as mode_app
from tests.composition.test_workspace_modes import window as mode_window


@pytest.fixture(scope="module")
def app():
    return mode_app.__wrapped__()


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    yield from mode_window.__wrapped__(app, monkeypatch, tmp_path)


def opened(window, tmp_path):
    path = make_source(tmp_path / "input.pdf", 6)
    window._open_in_new_tab_sync(str(path))
    return window._session, window._mode_controller.handoff


def finish_transfer(window, service):
    wait_until(lambda: not service.pending and not window._tasks)
    return window._mode_controller.host.current_project


def test_one_click_transfers_unsaved_revision_and_deduplicates(window, tmp_path):
    session, service = opened(window, tmp_path)
    session.engine.rotate_pages([0], 90)
    # A uniformly rotated source satisfies overlay's existing geometry requirements.
    session.engine.rotate_pages([1, 2, 3, 4, 5], 90)
    service.send_pdf(session)
    service.send_pdf(session)  # Repeated clicks do not launch a second capture.
    project = finish_transfer(window, service)
    assert isinstance(project, OverlayWindow)
    assert len(window._mode_controller.host.projects) == 1
    assert project.spec.source.pages == 6 and project.spec.source.geometries[0]["rotation"] == 90
    assert not project.spec.objects and not project.actions["generate"].isEnabled()
    assert not project.undo.isClean()
    assert project.link_panel.isVisible()
    assert "Up to date" in project.link_status.text()
    service.send_pdf(session)
    assert not service.pending and len(window._mode_controller.host.projects) == 1
    assert session.engine.is_modified


def test_current_page_background_and_search_checked_pages(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, "template_background", [2])
    template = finish_transfer(window, service)
    assert isinstance(template, CompositionWindow)
    with fitz.open(template.page.background) as pdf:
        assert "Original Source Page 3" in pdf[0].get_text()
    assert template.template.source_link["page_map"] == [2]
    identity = (session.engine.document_id, session.engine.revision)
    hits = [SearchHit(page, rects, "Original") for page, rects in session.engine.search_text("Original")]
    session.search_panel.set_results(hits, 6, identity)
    for row in (1, 4):
        session.search_panel._list.item(row).setCheckState(Qt.CheckState.Checked)
    from ui.designer_handoff_dialog import DesignerHandoffDialog
    def choose_overlay(dialog):
        assert dialog.request() == ("mail_merge_template", [1, 4])
        dialog.kind.setCurrentIndex(1)
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(DesignerHandoffDialog, "exec", choose_overlay)
    session.search_panel._request_pages_action("designer")
    overlay = finish_transfer(window, service)
    assert overlay.spec.source_link["page_map"] == [1, 4]
    assert overlay.spec.source.pages == 2
    session.engine.delete_pages([0])
    window._search_pages_action("designer", [1], session)
    assert not service.pending
    assert session.search_panel.result_identity() is None


def test_source_update_preserves_objects_cancels_and_undoes(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session)
    project = finish_transfer(window, service)
    project.add_object("text", x=25, y=30)
    project.add_object("i25", y=55)
    project.inspect_source(project.spec.source.path, project.spec.settings, preserve=True)
    wait_until(lambda: project.active_worker is None)
    assert not project.spec.needs_source_review
    objects, source = copy.deepcopy(project.spec.to_dict()["objects"]), project.spec.source.path
    session.engine.delete_pages([5])
    service.refresh()
    assert "Source changed" in project.link_status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    service.update_source(project)
    finish_transfer(window, service)
    assert project.spec.source.path == source
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    finish_transfer(window, service)
    assert project.spec.source.pages == 5
    assert project.spec.to_dict()["objects"] == objects
    assert project.spec.needs_source_review
    assert not project.actions["generate"].isEnabled()
    project.undo.undo()
    assert project.spec.source.path == source and not project.spec.needs_source_review
    assert Path(source).exists()


def test_save_and_reopen_copied_source_and_close_cancel(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session)
    project = finish_transfer(window, service)
    host = window._mode_controller.host
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    assert not host.close_project(project)
    project.save_project(path=str(tmp_path / "overlay.pdcx"))
    wait_until(lambda: project.active_worker is None)
    saved = load_project(tmp_path / "overlay.pdcx")
    assert Path(saved.source.path).parent == tmp_path / "overlay.assets"
    old_temp = service.source_dirs[project][0].name
    assert host.close_project(project)
    wait_until(lambda: project not in host.projects)
    assert not Path(old_temp).exists()
    reopened = host.open_project(str(tmp_path / "overlay.pdcx"))
    assert reopened.spec.source.pages == 6
    assert Path(reopened.spec.source.path).is_file()
    service.refresh()
    assert "Source disconnected" in reopened.link_status.text()


def test_output_return_source_mapping_blank_and_edited_qc(window, tmp_path):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, pages=[1, 3])
    project = finish_transfer(window, service)
    raw = project.spec.to_dict()
    raw["source_link"]["review_required"] = False
    raw["settings"]["duplex"] = True
    project.commit(raw, "Confirm grouping")
    project.generate_pdf(output_dir=str(tmp_path / "output"))
    wait_until(lambda: project.active_worker is None)
    assert project.last_result["status"] == "completed", project.last_result
    project.open_result("output_pdf")
    wait_until(lambda: window._session in service.outputs)
    output = window._session
    assert service.back_button.isVisible()
    output.page = 1
    service.open_output_source()
    assert window._session is output
    output.page = 2
    service.open_output_source()
    assert window._session is session and session.page == 3
    window.workspace.set_current_session(output)
    output.engine.delete_pages([0])
    service.refresh()
    assert "Edited" in service.back_button.text()
    service.open_output_source()
    assert window._session is output
    service.back_to_project()
    assert window._mode_controller.host.current_project is project
    assert window._mode_controller.modes.mode.value == "designer"


def test_update_invalidates_dynamic_grouping_and_retains_zoom(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session)
    project = finish_transfer(window, service)
    # Declare a reviewed grouping using the same structured report shape as the detector.
    from composition.pdf_source.detection import DetectionConfig, scan_pdf
    report = scan_pdf(project.spec.source.path, DetectionConfig(rules=[{"kind": "first_text", "terms": ["Original Source Page"]}]))["detection"]
    raw = project.spec.to_dict()
    raw["settings"]["groups"] = report["groups"]
    raw["detection_review"] = {**report, "accepted": True, "required": True}
    raw["source_link"]["review_required"] = False
    assert project.commit(raw, "Accept detection")
    project.canvas.set_zoom(1.6)
    transform = project.canvas.transform()
    session.engine.delete_pages([5])
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    finish_transfer(window, service)
    assert not project.spec.settings.groups and project.spec.needs_detection_review
    assert project.spec.needs_source_review
    assert project.canvas.transform() == transform


def test_shrunken_source_keeps_objects_and_blocks_production(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session)
    project = finish_transfer(window, service)
    project.add_object("text", x=120, y=30)
    obj = copy.deepcopy(project.spec.to_dict()["objects"])
    with DOCUMENT_LOCK:
        for page in session.engine.document:
            page.set_cropbox(fitz.Rect(0, 0, 200, 500))
        session.engine.mark_modified()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    finish_transfer(window, service)
    assert project.spec.to_dict()["objects"] == obj
    assert "outside" in project.link_status.text()
    assert not project.actions["generate"].isEnabled()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(760, 580), (960, 640)])
def test_handoff_controls_and_source_panel_fit_narrow_windows(window, tmp_path, theme, size):
    session, service = opened(window, tmp_path)
    window.resize(*size)
    window._apply_theme(theme)
    service.refresh()
    assert service.send_button.isVisible()
    assert service.send_button.geometry().right() < window.command_bar.width()
    assert service.send_button.height() <= 40
    service.send_pdf(session)
    project = finish_transfer(window, service)
    assert project.link_open.isVisible()
    assert project.link_update.isVisible()
    assert project.source_scroll.horizontalScrollBar().maximum() == 0
    assert project.link_update.width() > 0


def test_cancel_handoff_keeps_modes_and_cleans_source(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    import ui.workspace_handoff as handoff_module
    started = threading.Event()
    def slow_capture(engine, directory, identity, **kwargs):
        from composition.production.generator import check_cancel
        started.set()
        while not kwargs["is_cancelled"]():
            time.sleep(.01)
        check_cancel(kwargs["is_cancelled"])
    monkeypatch.setattr(handoff_module, "capture_pdf", slow_capture)
    service.send_pdf(session)
    wait_until(started.is_set)
    window._mode_controller.request_mode("designer")
    assert window._mode_controller.modes.mode.value == "designer"
    assert not window._mode_controller.prepare_exit()
    window._cancel_tasks()
    wait_until(lambda: not service.pending and not window._tasks)
    assert not service.source_dirs
    assert session.tab_widget.isEnabled()
    assert window._mode_controller.modes.pages["pdf"].isEnabled()


def test_3000_page_background_handoff_keeps_gui_events_running(window, tmp_path):
    path = make_source(tmp_path / "large.pdf", 3000)
    window._open_in_new_tab_sync(str(path))
    service = window._mode_controller.handoff
    ticks = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    start = time.monotonic()
    service.send_pdf(window._session)
    project = finish_transfer(window, service)
    timer.stop()
    assert project.spec.source.pages == 3000
    assert ticks
    print(f"3000-page handoff: {time.monotonic()-start:.3f}s; GUI ticks: {len(ticks)}")


def test_reopened_source_reconnect_requires_explicit_update(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session)
    project = finish_transfer(window, service)
    project.save_project(path=str(tmp_path / "linked.pdcx"))
    wait_until(lambda: project.active_worker is None)
    host = window._mode_controller.host
    assert host.close_project(project)
    wait_until(lambda: project not in host.projects)
    project = host.open_project(str(tmp_path / "linked.pdcx"))
    original_snapshot = project.spec.source.path
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.open_linked_source(project)
    wait_until(lambda: project in service.links)
    wait_until(lambda: not window._tasks and not service.project_busy(project))
    service.refresh()
    assert "Source changed" in project.link_status.text()
    assert project.spec.source.path == original_snapshot
    service.update_source(project)
    finish_transfer(window, service)
    assert project.spec.source.path != original_snapshot
    assert project.spec.needs_source_review


def test_background_update_retains_text_and_is_undoable(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, "template_background", [2])
    project = finish_transfer(window, service)
    project.add_element("text")
    elements = copy.deepcopy(project.template.to_dict()["pages"][0]["elements"])
    previous = project.page.background
    session.engine.rotate_pages([2], 90)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    finish_transfer(window, service)
    assert project.template.to_dict()["pages"][0]["elements"] == elements
    assert project.page.background != previous
    project.undo.undo()
    assert project.page.background == previous and Path(previous).exists()
