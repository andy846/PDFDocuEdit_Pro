from __future__ import annotations

from pathlib import Path

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from core.settings import SettingsManager
from ui.infobar import InfoBar

_APP = None


def window_for(tmp_path: Path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication(["search-page-actions-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    window = viewer_module.PDFViewer()
    window._set_motion_enabled(False)
    monkeypatch.setattr(window, "_confirm_discard_changes", lambda: True)
    return window


def make_pdf(path: Path) -> Path:
    with fitz.open() as document:
        for page in range(3):
            sheet = document.new_page()
            sheet.insert_text((72, 96), f"find this on page {page + 1}")
        document.save(path)
    return path


def test_search_result_pages_can_be_selected_and_extracted(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    panel = window._session.search_panel
    window._run_search("find")
    assert panel._list.count() == 3
    assert not panel._extract_pages.isEnabled()
    panel._list.item(0).setCheckState(Qt.CheckState.Checked)
    panel._list.item(2).setCheckState(Qt.CheckState.Checked)
    assert panel._selected_pages() == [0, 2]
    target = tmp_path / "selected.pdf"
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "PDF (*.pdf)"),
    )
    panel._extract_pages.click()
    with fitz.open(target) as document:
        assert document.page_count == 2
        assert "page 1" in document[0].get_text()
        assert "page 3" in document[1].get_text()
    assert window.engine.page_count == 3
    window.close()


def test_search_result_delete_invalidates_old_page_numbers(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    panel = window._session.search_panel
    window._run_search("find")
    panel._list.item(1).setCheckState(Qt.CheckState.Checked)
    prompts = []
    monkeypatch.setattr(
        viewer_module.QMessageBox,
        "question",
        lambda *args, **kwargs: prompts.append(args[2]) or viewer_module.QMessageBox.StandardButton.Yes,
    )
    panel._delete_pages.click()
    assert window.engine.page_count == 2
    assert "2" in prompts[0]
    assert panel._list.count() == 0
    assert not panel._delete_pages.isEnabled()
    assert "search again" in panel._status.text()
    window.close()


def test_search_select_all_and_stale_revision_guard(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    panel = window._session.search_panel
    window._run_search("find")
    panel._select_all.click()
    assert panel._selected_pages() == [0, 1, 2]
    assert not panel._delete_pages.isEnabled()
    assert panel._extract_pages.isEnabled()
    panel._clear_selection.click()
    assert panel._selected_pages() == []
    panel._list.item(0).setCheckState(Qt.CheckState.Checked)
    window.engine.delete_pages([2])
    window._search_pages_action("delete", [0], window._session)
    assert window.engine.page_count == 2
    assert panel._list.count() == 0
    window.close()


def test_notification_queue_can_be_advanced_without_discarding():
    global _APP
    _APP = QApplication.instance() or QApplication(["notification-queue-test"])
    bar = InfoBar()
    bar.set_animations_enabled(False)
    bar.show_message("First", timeout=0)
    bar.show_message("Second", timeout=0)
    bar.show_message("Third", timeout=0)
    assert bar._queue_badge.text() == "+2"
    bar._queue_badge.click()
    assert bar._message.text() == "Second"
    bar.hide_bar()
    assert bar._message.text() == "Third"
    bar.hide_bar()
    assert bar.isHidden()


def test_sidebar_search_matches_group_and_shortcut(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    panel = window.side_panel
    panel._search.setText("Page Operations")
    assert panel._buttons["insert"].isVisible() or not panel._buttons["insert"].isHidden()
    assert panel._buttons["highlight"].isHidden()
    panel._search.setText("F7")
    assert not panel._buttons["insert"].isHidden()
    assert panel._buttons["delete"].isHidden()
    panel._search.setText("no-such-tool")
    assert panel._tool_count.text() == "No matching tools"
    window.close()


def test_unavailable_recent_routes_to_recovery(tmp_path, monkeypatch):
    missing = str(tmp_path / "missing.pdf")
    window = window_for(tmp_path, monkeypatch)
    window.settings.add_recent_file(missing)
    window.workspace.set_recent_files(window.settings.recent_files())
    empty = window.workspace._empty
    item = empty._recent.item(0)
    empty._on_availability(missing, empty._recent_generation, False)
    assert "Unavailable" in item.text()
    requested = []
    window.workspace.missingRecentRequested.disconnect(window._recover_recent_file)
    window.workspace.missingRecentRequested.connect(requested.append)
    empty._activate_recent(item)
    assert requested == [missing]
    window.close()


def test_recent_relink_replaces_old_entry_only_after_open(tmp_path, monkeypatch):
    old = str(tmp_path / "old.pdf")
    replacement = str(tmp_path / "new.pdf")
    window = window_for(tmp_path, monkeypatch)
    window.settings.add_recent_file(old)

    def choose_locate(box):
        box._chosen = next(button for button in box.buttons() if button.text() == "Locate…")
        return 0

    monkeypatch.setattr(viewer_module.QMessageBox, "exec", choose_locate)
    monkeypatch.setattr(viewer_module.QMessageBox, "clickedButton", lambda box: box._chosen)
    monkeypatch.setattr(
        viewer_module.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (replacement, "PDF (*.pdf)")
    )
    opened = []
    monkeypatch.setattr(window, "open_in_new_tab", lambda path, *, on_open: opened.append((path, on_open)))
    window._recover_recent_file(old)
    assert window.settings.recent_files() == [old]
    assert opened[0][0] == replacement
    window.settings.add_recent_file(replacement)
    opened[0][1](None)
    assert window.settings.recent_files() == [replacement]
    window.close()


def test_search_page_action_targets_own_document_across_tabs(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    window._load_file_sync(str(first))
    first_session = window._session
    window._run_search("find", first_session)
    first_session.search_panel._list.item(0).setCheckState(Qt.CheckState.Checked)
    second_session = window._open_in_new_tab_sync(str(second))
    assert second_session is not first_session
    target = tmp_path / "from-first.pdf"
    monkeypatch.setattr(
        viewer_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "PDF (*.pdf)"),
    )
    first_session.search_panel._extract_pages.click()
    assert window._session is first_session
    with fitz.open(target) as document:
        assert document.page_count == 1
    window.close()


def test_search_delete_cancel_keeps_selection(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    panel = window._session.search_panel
    window._run_search("find")
    panel._list.item(0).setCheckState(Qt.CheckState.Checked)
    monkeypatch.setattr(
        viewer_module.QMessageBox,
        "question",
        lambda *args, **kwargs: viewer_module.QMessageBox.StandardButton.Cancel,
    )
    panel._delete_pages.click()
    assert window.engine.page_count == 3
    assert panel._selected_pages() == [0]
    window.close()


def test_changed_query_does_not_restore_old_search_results(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    panel = window._session.search_panel
    identity = (window.engine.document_id, window.engine.revision)
    hits = window.engine.search_text_detailed("find")
    panel._query.setText("find")
    panel.show_searching()
    panel._query.setText("other")
    window._finish_search(hits, window._session, "find", None, identity)
    assert panel._list.count() == 0
    assert not panel._extract_pages.isEnabled()
    window.close()


def test_search_actions_fit_narrow_window(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    window._load_file_sync(str(make_pdf(tmp_path / "source.pdf")))
    window.resize(640, 440)
    window.show()
    _APP.processEvents()
    window.search_document()
    _APP.processEvents()
    panel = window._session.search_panel
    assert panel.width() >= 300
    assert panel._delete_pages.geometry().right() < panel.width()
    assert panel._extract_pages.geometry().right() < panel.width()
    window.close()


def test_recent_missing_entry_can_be_removed(tmp_path, monkeypatch):
    old = str(tmp_path / "old.pdf")
    window = window_for(tmp_path, monkeypatch)
    window.settings.add_recent_file(old)

    def choose_remove(box):
        box._chosen = next(button for button in box.buttons() if button.text() == "Remove from recent")
        return 0

    monkeypatch.setattr(viewer_module.QMessageBox, "exec", choose_remove)
    monkeypatch.setattr(viewer_module.QMessageBox, "clickedButton", lambda box: box._chosen)
    window._recover_recent_file(old)
    assert window.settings.recent_files() == []
    assert old not in window.settings.get("recent_file_info", {})
    window.close()
