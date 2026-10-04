from __future__ import annotations

import copy
import threading
import time
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QItemSelectionModel, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from tests.composition.test_workspace import wait_until
from tests.composition.test_workspace_modes import app as mode_app
from tests.composition.test_workspace_modes import window as mode_window
from tests.test_merge_workbench_core import source


@pytest.fixture(scope="module")
def app():
    return mode_app.__wrapped__()


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    generator = mode_window.__wrapped__(app, monkeypatch, tmp_path)
    root = next(generator)
    yield root
    page = getattr(root, "_merge_workspace", None)
    if page:
        wait_until(lambda: not page.workers)
        page.undo.setClean()
    try:
        next(generator)
    except StopIteration:
        pass


def ready(page):
    wait_until(lambda: all(e["status"] != "Checking" for e in page.entries) and page.metadata_task is None)


def select(page, rows):
    page.table.clearSelection()
    model = page.table.selectionModel()
    for row in rows:
        model.select(page.model.index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    if rows:
        model.setCurrentIndex(page.model.index(rows[0], 0), QItemSelectionModel.SelectionFlag.NoUpdate)


def test_natural_order_multiselect_page_selection_and_undo(window, tmp_path):
    paths = [source(tmp_path/f"file-{n}.pdf") for n in (10, 2, 1)]
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_paths([str(p) for p in paths])
    ready(page)
    assert [e["label"] for e in page.entries] == ["file-1.pdf", "file-2.pdf", "file-10.pdf"]
    select(page, [0, 1])
    page.range_mode.setCurrentIndex(1)
    page.range_edit.setText("1,5")
    page.apply_selection()
    assert page.total_pages == 9
    assert page.model.output_ranges[page.entries[2]["id"]] == "5–9"
    ids = [e["id"] for e in page.entries[:2]]
    page.reorder(ids, 3)
    assert [e["label"] for e in page.entries] == ["file-10.pdf", "file-1.pdf", "file-2.pdf"]
    assert page.selected_ids() == ids
    page.undo.undo()
    assert page.entries[0]["id"] == ids[0]
    select(page, [0, 1])
    before = copy.deepcopy(page.entries)
    page.range_edit.setText("1-999")
    page.apply_selection()
    assert page.entries == before
    assert "outside" in page.selection_info.text()


def test_merge_tab_identity_modes_shortcuts_and_close_cancel(window, tmp_path, monkeypatch):
    for name in ("one", "two"):
        window._open_in_new_tab_sync(str(source(tmp_path/f"{name}.pdf")))
    sessions = list(window._sessions)
    window._merge_pdfs()
    page = window._merge_workspace
    assert window.workspace.current_tool() is page
    assert not window.save_action.shortcuts()
    assert not window.save_action.isEnabled()
    window.workspace._tabs.tabBar().moveTab(2, 0)
    assert window.workspace.session_at(1) is sessions[0]
    assert window.workspace.session_at(2) is sessions[1]
    page.add_paths([str(tmp_path/"one.pdf")])
    ready(page)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    page.request_close()
    assert window.workspace.current_tool() is page
    window._mode_controller.request_mode("designer")
    window._mode_controller.request_mode("pdf")
    assert window.workspace.current_tool() is page and len(page.entries) == 1
    window.workspace.set_current_session(sessions[0])
    assert window.workspace.current_session() is sessions[0]
    assert window.save_action.shortcuts()
    window.close_document(sessions[1])
    assert window.workspace._tabs.indexOf(page) >= 0


@pytest.mark.parametrize("project_kind", ["mail_merge_template", "overlay"])
def test_snapshot_save_reopen_generate_and_designer(window, tmp_path, monkeypatch, project_kind):
    from ui.designer_handoff_dialog import DesignerHandoffDialog
    def choose(dialog):
        dialog.kind.setCurrentIndex(int(project_kind == "overlay"))
        return dialog.DialogCode.Accepted
    monkeypatch.setattr(DesignerHandoffDialog, "exec", choose)
    path = source(tmp_path/"open.pdf")
    window._open_in_new_tab_sync(str(path))
    session = window._session
    session.engine.delete_pages([4])
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_session(session)
    wait_until(lambda: page.entries[0]["status"] == "Ready" and not page.workers)
    assert page.entries[0]["identity"]["pages"] == 4
    page.undo.undo()
    assert not page.entries
    page.undo.redo()
    ready(page)
    assert page.entries[0]["status"] == "Ready" and page.entries[0]["identity"]["pages"] == 4
    with fitz.open(path) as pdf:
        assert pdf.page_count == 5
    page.output_edit.setText(str(tmp_path/"merged.pdf"))
    assert page.save_list(path=tmp_path/"job.pdmerge")
    wait_until(lambda: not page.saving)
    assert page.undo.isClean()
    page.open_list(path=tmp_path/"job.pdmerge")
    wait_until(lambda: page.entries and ".assets" in page.entries[0]["path"])
    ready(page)
    page.generate()
    wait_until(lambda: not page.busy_state and page.result is not None)
    assert page.result.page_count == 4
    page.send_output()
    wait_until(lambda: window._mode_controller.host is not None and not window._mode_controller.handoff.pending and not window._tasks)
    project = window._mode_controller.host.current_project
    if project_kind == "overlay":
        assert project.spec.source.pages == 4
        assert not project.spec.objects
    else:
        assert len(project.template.pages) == 4 and project.record_count == 0
        assert project.template.source_link["purpose"] == "mail_merge_template"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_narrow_layout_preview_and_keyboard_save(window, tmp_path, theme):
    window._apply_theme(theme)
    window._merge_pdfs()
    page = window._merge_workspace
    window.resize(960, 640)
    page.add_paths([str(source(tmp_path/"one.pdf"))])
    ready(page)
    select(page, [0])
    page.narrow_tabs.setCurrentIndex(1)
    QTest.qWait(150)
    assert page.preview_panel.isVisible()
    assert page.generate_button.geometry().right() < page.width()
    page.preview_mode.setCurrentIndex(1)
    page.page_number.setValue(5)
    wait_until(lambda: page.preview_task is None and not page.preview_timer.isActive()
               and bool(page.preview.scene().items()) and "Source page 5" in page.preview_label.text())
    assert "Source page 5" in page.preview_label.text()


def test_large_offline_drop_has_no_gui_io(window, monkeypatch):
    window._merge_pdfs()
    page = window._merge_workspace
    page.check_timer.stop()
    monkeypatch.setattr(page, "queue_checks", lambda *a, **k: None)
    monkeypatch.setattr(Path, "stat", lambda *a, **k: pytest.fail("GUI stat during add"))
    monkeypatch.setattr(Path, "resolve", lambda *a, **k: pytest.fail("GUI resolve during add"))
    page.add_paths([rf"\\offline\share\file-{i}.pdf" for i in range(18000)])
    assert page.model.rowCount() == 18000
    page.reorder([page.entries[0]["id"]], 18000)
    assert page.entries[-1]["label"] == "file-0.pdf"
    monkeypatch.undo()


def test_source_change_requires_explicit_confirmation_and_invalid_ranges_repair(window, tmp_path, monkeypatch):
    path = source(tmp_path/"changed.pdf")
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_paths([str(path)])
    ready(page)
    select(page, [0])
    page.range_mode.setCurrentIndex(1)
    page.range_edit.setText("1,5")
    page.apply_selection()
    with fitz.open(path) as pdf:
        pdf.delete_page(4)
        pdf.save(tmp_path/"new.pdf")
    (tmp_path/"new.pdf").replace(path)
    page.recheck_selected()
    ready(page)
    assert page.entries[0]["status"] == "Needs review"
    assert not page.generate_button.isEnabled()
    page.recheck_selected()
    ready(page)
    assert page.entries[0]["status"] == "Needs review"
    page.range_mode.setCurrentIndex(0)
    page.apply_selection()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.confirm_sources()
    assert page.generate_button.isEnabled() and page.total_pages == 4


def test_toolbar_undo_and_text_edit_protection_and_save_close(window, tmp_path, monkeypatch):
    path = source(tmp_path/"one.pdf")
    window._open_in_new_tab_sync(str(path))
    session = window._session
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_paths([str(path)])
    ready(page)
    window.command_bar.undoClicked.emit()
    assert not page.entries and session.engine.page_count == 5
    window.command_bar.redoClicked.emit()
    ready(page)
    select(page, [0])
    page.range_mode.setCurrentIndex(1)
    page.range_edit.setFocus()
    page.range_edit.clear()
    QTest.keyClicks(page.range_edit, "1,5")
    undo_index = page.undo.index()
    QTest.keyClick(page.range_edit, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert page.undo.index() == undo_index
    destination = tmp_path/"closed.pdmerge"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)
    page.request_close()
    wait_until(lambda: window._merge_workspace is None)
    assert destination.is_file()
    assert window.workspace.current_session() is session


def test_merge_cancel_keeps_list_modes_and_existing_output(window, tmp_path, monkeypatch):
    import ui.merge_workspace as module
    from core.tools import ToolError
    path = source(tmp_path/"one.pdf")
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_paths([str(path)])
    ready(page)
    output = tmp_path/"out.pdf"
    output.write_bytes(b"old output")
    page.output_edit.setText(str(output))
    started = threading.Event()
    def slow(spec, progress=None, is_cancelled=None):
        started.set()
        while not is_cancelled():
            time.sleep(.005)
        raise ToolError("cancelled")
    monkeypatch.setattr(module, "merge_pdf_items", slow)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page.generate()
    wait_until(started.is_set)
    assert page.busy_state and not page.actions["remove"].isEnabled()
    window._mode_controller.request_mode("designer")
    window._mode_controller.request_mode("pdf")
    page.cancel_job()
    wait_until(lambda: not page.busy_state)
    assert output.read_bytes() == b"old output" and len(page.entries) == 1
    assert "Cancelled" in page.message.text()


def test_preview_retains_each_source_zoom_and_page_position(window, tmp_path):
    window._merge_pdfs()
    page = window._merge_workspace
    page.add_paths([str(source(tmp_path/f"source-{i}.pdf")) for i in range(2)])
    ready(page)
    select(page, [0])
    page.page_number.setValue(3)
    wait_until(lambda: page.shown_entry == page.entries[0]["id"] and not page.preview_timer.isActive() and page.preview_task is None)
    page.preview.zoom(1.25)
    transform = page.preview.transform()
    select(page, [1])
    wait_until(lambda: page.shown_entry == page.entries[1]["id"] and not page.preview_timer.isActive() and page.preview_task is None)
    select(page, [0])
    wait_until(lambda: page.shown_entry == page.entries[0]["id"] and not page.preview_timer.isActive() and page.preview_task is None)
    assert page.page_number.value() == 3
    assert page.preview.transform() == transform


def test_200_pdf_background_merge_keeps_gui_responsive(window, tmp_path):
    paths = []
    for i in range(200):
        path = tmp_path/f"document-{i}.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((30, 50), f"Document {i}")
            pdf.save(path)
        paths.append(str(path))
    window._merge_pdfs()
    page = window._merge_workspace
    start = time.perf_counter()
    page.add_paths(paths)
    add_ms = (time.perf_counter()-start)*1000
    ready(page)
    page.output_edit.setText(str(tmp_path/"out.pdf"))
    beats = []
    timer = QTimer(window)
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start()
    page.generate()
    wait_until(lambda: not page.busy_state and page.result is not None)
    timer.stop()
    assert page.result.page_count == 200 and beats
    with fitz.open(page.result.output_path) as pdf:
        assert pdf[0].get_text().strip() == "Document 0"
        assert pdf[-1].get_text().strip() == "Document 199"
    print(f"200 PDF GUI add: {add_ms:.2f}ms; background merge GUI heartbeats: {len(beats)}")


def test_merge_remains_available_with_designer_flag_off(app, tmp_path, monkeypatch):
    from core.settings import SettingsManager
    from core.viewer import PDFViewer
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_COMPOSITION", "0")
    monkeypatch.setattr("core.viewer.SettingsManager", lambda: SettingsManager(tmp_path/"settings.json"))
    root = PDFViewer()
    root.show()
    try:
        assert not getattr(root, "_mode_controller", None)
        root._open_in_new_tab_sync(str(source(tmp_path/"source.pdf")))
        root._merge_pdfs()
        page = root._merge_workspace
        page.add_paths([str(tmp_path/"source.pdf")])
        ready(page)
        assert root.workspace.current_tool() is page
        assert not root.save_action.shortcuts()
        assert page.result_buttons[1].isHidden()
        assert "merge.save" in {command.id for command in root._commands_for_mode()}
        root.command_bar.undoClicked.emit()
        assert not page.entries
        page.undo.setClean()
    finally:
        root._confirm_discard_changes = lambda: True
        root.close()
        wait_until(lambda: not root.isVisible())
        root.deleteLater()
        app.processEvents()
