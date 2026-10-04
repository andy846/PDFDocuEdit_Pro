"""Focused choice dialog and multi-page Designer handoff integration."""
import copy
import threading
import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox

from composition.designer.workspace import CompositionWindow
from composition.engine.renderer import render_preview
from composition.template.model import SequenceSpec
from core.pdf_engine import DOCUMENT_LOCK, SearchHit
from tests.composition.test_workspace import wait_until
from tests.composition.test_workspace_handoff import (
    app as handoff_app,
)
from tests.composition.test_workspace_handoff import (
    finish_transfer,
    opened,
)
from tests.composition.test_workspace_handoff import (
    window as handoff_window,
)
from ui.designer_handoff_dialog import DesignerHandoffDialog


@pytest.fixture(scope="module")
def app(qt_application):
    return handoff_app.__wrapped__(qt_application)


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    yield from handoff_window.__wrapped__(app, monkeypatch, tmp_path)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_choice_dialog_default_ranges_limits_and_narrow_fit(window, theme):
    window._apply_theme(theme)
    dialog = DesignerHandoffDialog(window, label="Word template.pdf", page_count=150, current_page=4)
    dialog.show()
    app_instance = dialog.window().windowHandle()
    assert app_instance is not None
    assert dialog.kind.currentData() == "mail_merge_template"
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled() and "100" in dialog.summary.text()
    dialog.selection.setCurrentIndex(2)
    dialog.range.setText("1-3, 5")
    assert ok.isEnabled() and dialog.request() == ("mail_merge_template", [0, 1, 2, 4])
    assert "Each customer produces 4" in dialog.summary.text()
    dialog.range.setText("1, 999")
    assert not ok.isEnabled()
    dialog.selection.setCurrentIndex(1)
    assert dialog.request() == ("mail_merge_template", [4])
    dialog.kind.setCurrentIndex(1)
    dialog.selection.setCurrentIndex(0)
    assert ok.isEnabled() and dialog.request() == ("overlay", None)
    dialog.resize(450, 360)
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    assert dialog.buttons.geometry().bottom() < dialog.height()
    assert dialog.summary.geometry().right() < dialog.width()
    dialog.close()


def test_toolbar_choice_creates_normal_project_with_unsaved_pages(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    session.engine.rotate_pages([1], 90)
    def choose(dialog):
        assert dialog.kind.currentData() == "mail_merge_template"
        dialog.selection.setCurrentIndex(2)
        dialog.range.setText("1-3")
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(DesignerHandoffDialog, "exec", choose)
    service.refresh()
    assert service.send_button.isEnabled()
    service.send_button.click()
    project = finish_transfer(window, service)
    assert isinstance(project, CompositionWindow)
    assert len(project.template.pages) == 3 and project.record_count == 0
    assert not project.undo.isClean()
    assert project.template.source_link["version"] == 2
    assert "3 template page(s) per customer" in project.link_status.text()
    assert session.engine.is_modified and window._mode_controller.modes.mode.value == "designer"
    service.send_pdf(session, "mail_merge_template", [0, 1, 2])
    assert not service.pending and len(window._mode_controller.host.projects) == 1
    service.send_pdf(session, "mail_merge_template", [0, 1, 2], force_new=True)
    assert finish_transfer(window, service) is not project
    assert len(window._mode_controller.host.projects) == 2


def test_search_handoff_can_select_normal_template(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    hits = [SearchHit(page, rects, "Original") for page, rects in session.engine.search_text("Original")]
    session.search_panel.set_results(hits, 6, (session.engine.document_id, session.engine.revision))
    for row in (1, 4):
        session.search_panel._list.item(row).setCheckState(Qt.CheckState.Checked)
    def choose(dialog):
        assert dialog.request() == ("mail_merge_template", [1, 4])
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(DesignerHandoffDialog, "exec", choose)
    session.search_panel._request_pages_action("designer")
    project = finish_transfer(window, service)
    assert isinstance(project, CompositionWindow) and len(project.template.pages) == 2
    assert project.template.source_link["page_map"] == [1, 4]


def test_update_retains_fields_sequences_page_order_view_and_undo(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, "mail_merge_template", [0, 1, 2])
    project = finish_transfer(window, service)
    project.add_element("text", "{{Name}} / {{Seq}}")
    assert project.apply_sequences([SequenceSpec("Seq")], "generated", 2)
    project.move_template_page(1)
    before = copy.deepcopy(project.template.to_dict())
    project.canvas.zoom_by(1.15)
    transform = project.canvas.transform()
    selected = project.canvas.selected_ids()
    session.engine.rotate_pages([1], 90)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    assert finish_transfer(window, service) is project
    assert [p.id for p in project.template.pages] == [p["id"] for p in before["pages"]]
    assert [p["elements"] for p in project.template.to_dict()["pages"]] == [p["elements"] for p in before["pages"]]
    assert project.template.to_dict()["sequences"] == before["sequences"]
    assert project.template.source_link["template_page_map"] == before["source_link"]["template_page_map"]
    assert project.canvas.transform() == transform and project.canvas.selected_ids() == selected
    assert all(p.background != old["background"] for p, old in zip(project.template.pages, before["pages"], strict=True))
    project.undo.undo()
    assert project.template.to_dict() == before
    assert all(Path(p.background).exists() for p in project.template.pages)
    project.undo.redo()
    assert project.template.source_link["transfer_id"] != before["source_link"]["transfer_id"]


def test_count_change_cancel_or_new_project_and_shrink_blocks_update(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, "mail_merge_template")
    project = finish_transfer(window, service)
    project.add_element("text", "Customer {{Name}}")
    before = project.template.to_dict()
    session.engine.delete_pages([5])
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    service.update_source(project)
    finish_transfer(window, service)
    assert len(window._mode_controller.host.projects) == 1 and project.template.to_dict() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    service.update_source(project)
    new = finish_transfer(window, service)
    assert new is not project and len(new.template.pages) == 5 and project.template.to_dict() == before
    new.add_element("text", "Still here")
    saved = new.template.to_dict()
    with DOCUMENT_LOCK:
        session.engine.document[0].set_cropbox(fitz.Rect(0, 0, 100, 500))
        session.engine.mark_modified()
    service.update_source(new)
    finish_transfer(window, service)
    assert new.template.to_dict() == saved


def test_background_removal_deletion_and_output_source_mapping(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.send_pdf(session, "mail_merge_template", [0, 2, 5])
    project = finish_transfer(window, service)
    project.move_template_page(1)
    snapshot = project.template.to_dict()
    output = tmp_path / "production.pdf"
    output.write_bytes(render_preview(project.template, {}))
    project._output_template = snapshot
    service.open_production_output(project, {"output_pdf": str(output)})
    wait_until(lambda: window._session in service.outputs)
    output_session = window._session
    window.goto_page(0)
    traced = []
    monkeypatch.setattr(service, "open_linked_source", lambda target, page=None: traced.append(page))
    service.open_output_source()
    assert traced == [2]
    window.goto_page(1)
    service.open_output_source()
    assert traced == [2, 0]
    project.remove_background()
    assert len(project.template.source_link["template_page_map"]) == 2
    project.undo.undo()
    assert project.template.to_dict() == snapshot
    project.delete_template_page()
    assert len(project.template.source_link["template_page_map"]) == 2
    project.undo.undo()
    assert project.template.to_dict() == snapshot
    assert not output_session.engine.is_modified


def test_choice_cancel_leaves_pdf_and_designer_tabs_untouched(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    monkeypatch.setattr(DesignerHandoffDialog, "exec", lambda dialog: dialog.DialogCode.Rejected)
    service.refresh()
    assert service.send_button.isEnabled()
    service.send_button.click()
    assert not service.pending and window._mode_controller.host is None
    assert window._mode_controller.modes.mode.value == "pdf"
    assert window._session is session


def test_command_palette_uses_the_same_project_choice(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    service.refresh()
    requests = []
    monkeypatch.setattr(service, "choose_project", lambda chosen: requests.append(chosen))
    command = next(item for item in window._mode_controller.commands() if item.id == "send_to_designer")
    assert command.is_enabled()
    command.handler()
    assert requests == [session]


def test_background_capture_cancellation_cleans_files_and_creates_no_tab(window, tmp_path, monkeypatch):
    session, service = opened(window, tmp_path)
    import ui.workspace_handoff as module
    started = threading.Event()
    folders = []
    def slow_capture(engine, directory, identity, **options):
        from composition.production.generator import check_cancel
        folder = Path(directory)
        folders.append(folder)
        (folder / "partial-background.pdf").write_bytes(b"partial")
        started.set()
        while not options["is_cancelled"]():
            time.sleep(.01)
        check_cancel(options["is_cancelled"])
    monkeypatch.setattr(module, "capture_template_pdf", slow_capture)
    service.send_pdf(session, "mail_merge_template")
    wait_until(started.is_set)
    window._cancel_tasks()
    wait_until(lambda: not service.pending and not window._tasks)
    assert all(not folder.exists() for folder in folders)
    assert window._mode_controller.host is None and not service.source_dirs
    assert session.tab_widget.isEnabled() and window._mode_controller.modes.pages["pdf"].isEnabled()
