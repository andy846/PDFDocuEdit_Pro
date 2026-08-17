from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox, QTabBar

import core.viewer as viewer_module
from core.settings import SettingsManager


def make_pdf(path: Path, pages: int = 3, prefix: str = "Doc") -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), f"{prefix} content page {index + 1}")
        document.save(path)
    return path


def _window(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication(["pdfdocuedit-p4-test"])
    monkeypatch.setattr(
        viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json")
    )
    window = viewer_module.PDFViewer()
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    return window, app


def _wait_renders(app, canvas, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while canvas._pending and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_open_multiple_tabs_and_switch(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf", prefix="Alpha")
    second = make_pdf(tmp_path / "second.pdf", prefix="Beta")

    window.load_file(str(first))
    _wait_renders(app, window.workspace.canvas)
    assert window.workspace.session_count() == 1

    window.open_in_new_tab(str(second))
    _wait_renders(app, window.workspace.canvas)
    assert window.workspace.session_count() == 2
    assert window._session is window.workspace.current_session()
    assert window.bottom_bar._file_full == "second.pdf"  # label may be elided

    # Switch back to the first tab via the workspace.
    first_session = next(
        session for session in window._sessions if session.document_name == "first.pdf"
    )
    window.workspace.set_current_session(first_session)
    app.processEvents()
    assert window._session is first_session
    assert window.bottom_bar._file_full == "first.pdf"
    assert window.bottom_bar._total.text() == "/ 3"
    assert "first.pdf" in window.windowTitle()

    window._next_tab()
    app.processEvents()
    assert window._session.document_name == "second.pdf"
    window._previous_tab()
    app.processEvents()
    assert window._session.document_name == "first.pdf"
    window.close()


def test_close_tab_and_last_tab_returns_empty_state(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.load_file(str(first))
    window.open_in_new_tab(str(second))
    _wait_renders(app, window.workspace.canvas)
    assert window.workspace.session_count() == 2

    window.close_document()
    app.processEvents()
    assert window.workspace.session_count() == 1
    assert window._session.document_name == "first.pdf"

    window.close_document()
    app.processEvents()
    assert window.workspace.session_count() == 0
    assert window._session is None
    assert not window.engine.is_loaded()
    assert not window.bottom_bar._zoom_in.isEnabled()
    window.close()


def test_clicking_tab_x_closes_document_in_real_viewer(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )
    window.load_file(str(first))
    window.open_in_new_tab(str(second))
    _wait_renders(app, window.workspace.canvas)
    assert window.workspace.session_count() == 2

    bar = window.workspace._tabs.tabBar()
    button = bar.tabButton(1, QTabBar.ButtonPosition.RightSide)
    assert button is not None and not button.icon().isNull()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert window.workspace.session_count() == 1
    assert not button.isVisible()
    assert window._session is not None
    assert window._session.document_name == "first.pdf"
    window.close()


def test_per_session_undo_isolation(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf", pages=4, prefix="Alpha")
    second = make_pdf(tmp_path / "second.pdf", pages=2, prefix="Beta")

    window.load_file(str(first))
    window.open_in_new_tab(str(second))
    _wait_renders(app, window.workspace.canvas)

    second_session = window._session
    window._snapshot_before("Delete Pages")
    second_session.engine.delete_pages([0])
    window._after_page_count_change()
    assert second_session.engine.page_count == 1
    assert second_session.undo_stack.can_undo

    first_session = next(s for s in window._sessions if s is not second_session)
    window.workspace.set_current_session(first_session)
    app.processEvents()
    assert first_session.engine.page_count == 4
    assert not window._undo_stack.can_undo  # per-session stack, untouched

    window._undo()
    app.processEvents()
    assert first_session.engine.page_count == 4  # undo targets... nothing on this stack

    window.workspace.set_current_session(second_session)
    app.processEvents()
    assert window._undo_stack.can_undo
    window._undo()
    app.processEvents()
    assert second_session.engine.page_count == 2
    window.close()


def test_split_view_same_document(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "split.pdf")
    window.load_file(str(source))
    _wait_renders(app, window.workspace.canvas)

    session = window._session
    assert not session.has_split
    window._toggle_split_view()
    app.processEvents()
    assert session.has_split
    assert session.split_canvas is not None
    _wait_renders(app, session.split_canvas)
    assert session.split_canvas._doc is session.canvas._doc  # same document

    session.split_canvas.set_page(1)
    assert session.canvas.current_page == 0  # independent pages

    window._set_split_orientation("vertical")
    assert session.canvas_area.orientation() == Qt.Orientation.Vertical
    assert session.split_orientation == "vertical"
    assert window.settings.get("split_orientation") == "vertical"

    window._set_split_sync_page(True)
    session.split_canvas.set_page(2)
    assert session.canvas.current_page == 2
    assert window.settings.get("split_sync_page") is True

    window._set_split_sync_zoom(True)
    session.split_canvas.set_zoom(1.5)
    assert session.canvas.zoom_ratio == 1.5
    assert window.settings.get("split_sync_zoom") is True

    window._reset_split_sizes()
    sizes = session.canvas_area.sizes()
    assert len(sizes) == 2
    assert abs(sizes[0] - sizes[1]) <= 1

    window._toggle_split_view()
    assert not session.has_split
    window.close()


def test_compat_properties_track_current_session(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")

    window.load_file(str(first))
    window.open_in_new_tab(str(second))
    _wait_renders(app, window.workspace.canvas)

    second_session = window._session
    assert window.engine is second_session.engine
    assert window.workspace.canvas is second_session.canvas
    assert window.workspace.nav_panel is second_session.nav_panel
    assert window._undo_stack is second_session.undo_stack
    assert window._page == 0

    first_session = next(s for s in window._sessions if s is not second_session)
    window.workspace.set_current_session(first_session)
    app.processEvents()
    assert window.engine is first_session.engine
    assert window.workspace.canvas is first_session.canvas
    window.close()


def test_tab_commands_registered(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    ids = [command.id for command in window._commands]
    for wanted in ("tab_next", "tab_prev", "view_split"):
        assert wanted in ids, wanted
    window.close()
