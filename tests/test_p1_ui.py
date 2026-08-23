from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from core.settings import SettingsManager
from ui.command_palette import CommandPalette


def make_pdf(path: Path, pages: int = 2) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 96), f"Searchable page {index + 1}")
        document.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
        document.save(path)
    return path


def _window(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication(["pdfdocuedit-p1-test"])
    monkeypatch.setattr(
        viewer_module,
        "SettingsManager",
        lambda: SettingsManager(tmp_path / "settings.json"),
    )
    return viewer_module.PDFViewer(), app


def test_about_identifies_developer(tmp_path: Path, monkeypatch) -> None:
    window, _app = _window(tmp_path, monkeypatch)
    captured: dict[str, str] = {}

    def capture_about(_parent, title: str, text: str) -> None:
        captured.update(title=title, text=text)

    monkeypatch.setattr(viewer_module.QMessageBox, "about", capture_about)
    window.show_about()

    assert captured["title"] == "About PDFDocuEdit Pro"
    assert "<p><b>Developer:</b> Andy Leung</p>" in captured["text"]
    window.close()


def test_nav_panel_outline_search_and_bookmarks(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "nav.pdf")
    window.load_file(str(source))
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    nav = window.workspace.nav_panel

    assert nav.isVisible() is False  # hidden until a tab is requested

    window._show_nav_tab("outline")
    assert nav.active_key() == "outline"
    assert nav.outline._tree.topLevelItemCount() == 2

    window.show_document_info()
    app.processEvents()
    session = window._session
    assert session is not None
    assert session.analysis_panel.isVisible()
    assert session.tab_widget.sizes()[3] >= 300

    window._toggle_thumbnails()
    app.processEvents()
    assert session.nav_panel.isVisible()
    assert session.nav_panel.active_key() == "thumbnails"
    sizes = session.tab_widget.sizes()
    assert sizes[0] >= 200
    assert sizes[2] == 0
    assert sizes[3] == 0

    window._show_nav_tab("search")
    app.processEvents()
    assert not session.search_panel.isHidden()
    assert session.search_panel.isVisible()
    assert not session.analysis_panel.isVisible()
    sizes = session.tab_widget.sizes()
    assert sizes[2] >= 300
    assert sizes[3] == 0
    assert nav.search not in [nav._stack.widget(i) for i in range(nav._stack.count())]
    assert window.context_panel.isHidden()
    window.workspace.nav_panel.search._query.setText("searchable")
    window._run_search("searchable")
    assert nav.search._list.count() == 2
    nav.search._on_activated(nav.search._list.item(1))
    assert window._page == 1

    window._toggle_thumbnails()
    app.processEvents()
    assert session.nav_panel.isVisible()
    assert session.nav_panel.active_key() == "thumbnails"
    sizes = session.tab_widget.sizes()
    assert sizes[0] >= 200
    assert sizes[2] == 0
    assert sizes[3] == 0

    window._toggle_thumbnails()
    app.processEvents()
    assert not session.nav_panel.isVisible()
    assert session.tab_widget.sizes()[0] == 0

    window.goto_page(0)
    # The title prompt cannot be automated offscreen; exercise the bookmark
    # flow through the persisted settings instead.
    items = window.settings.get_bookmarks(str(source))
    items.append({"page": 0, "title": "Start"})
    window.settings.set_bookmarks(str(source), items)
    window._load_navigation()
    assert nav.bookmarks._list.count() == 1
    window._remove_bookmark(0)
    assert window.settings.get_bookmarks(str(source)) == []
    window.close()


def test_command_registry_palette_and_dialogs(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    ids = [command.id for command in window._commands]
    assert len(ids) == len(set(ids))
    assert "undo_history" in ids
    assert "nav_outline" in ids

    palette = CommandPalette(window._commands, window)
    palette._refresh("merge")
    rows = [
        palette._list.topLevelItem(index).text(0)
        for index in range(palette._list.topLevelItemCount())
    ]
    assert any("Merge PDFs" in row for row in rows)

    # Disabled command gating: rotate requires an open document.
    enabled_ids = [c.id for c in window._commands if c.is_enabled()]
    assert "rotate" not in enabled_ids
    assert "open" in enabled_ids
    palette.close()
    window.close()


def test_multi_step_undo_and_redo_preserves_history(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "undo.pdf")
    window.load_file(str(source))
    app.processEvents()

    window._snapshot_before("Rotate Pages")
    window.engine.rotate_pages([0], 90)
    window._snapshot_before("Rotate Pages")
    window.engine.rotate_pages([0], 90)

    assert window._undo_stack.undo_count == 2
    window._undo_to(2)
    assert window._undo_stack.undo_count == 0
    assert window._undo_stack.redo_count == 2
    assert window.engine.is_loaded()
    assert window.engine.page_count == 2

    window._redo_to(2)
    assert window._undo_stack.redo_count == 0
    assert window._undo_stack.undo_count == 2
    window.close()


def test_background_search_for_large_documents(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = tmp_path / "large.pdf"
    with fitz.open() as document:
        for index in range(60):
            page = document.new_page()
            page.insert_text((72, 96), f"unique-needle on page {index + 1}")
        document.save(source)
    window.load_file(str(source))
    app.processEvents()

    panel = window.workspace.nav_panel.search
    window._run_search("unique-needle")
    deadline = time.monotonic() + 30
    while window._tasks and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert not window._tasks
    assert panel._list.count() == 60
    assert panel._hits[0].context
    window.close()
