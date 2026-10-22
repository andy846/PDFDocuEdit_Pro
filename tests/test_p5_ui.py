from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

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
    app = QApplication.instance() or QApplication(["pdfdocuedit-p5-test"])
    monkeypatch.setattr(
        viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json")
    )
    window = viewer_module.PDFViewer()
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    return window, app


def _wait(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def test_thumbnail_reorder_flow(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "reorder.pdf", pages=3)
    window._load_file_sync(str(source))
    assert _wait(app, lambda: not window.workspace.canvas._pending)

    session = window._session
    window._show_nav_tab("thumbnails")
    app.processEvents()
    assert session.nav_panel.thumbnails._list.count() == 3

    window._handle_thumbnail_reorder(session, [2, 0, 1])
    app.processEvents()
    assert session.engine.page_count == 3
    assert "content page 3" in session.engine.document.load_page(0).get_text()
    assert session.nav_panel.thumbnails._list.count() == 3
    assert window._undo_stack.can_undo

    window._undo()
    app.processEvents()
    assert "content page 1" in session.engine.document.load_page(0).get_text()
    window.close()


def test_recent_previews_reuse_opened_page_cache(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    first = make_pdf(tmp_path / "recent-a.pdf", pages=1)
    second = make_pdf(tmp_path / "recent-b.pdf", pages=1)
    window.load_file(str(first))
    assert _wait(app, lambda: str(first) in window.workspace._empty._thumb_done)
    window.open_in_new_tab(str(second))
    assert _wait(app, lambda: window.workspace._empty._thumb_done == {str(first), str(second)})
    assert window.workspace._empty._recent.count() == 2
    assert window.settings.get("recent_file_info")[str(first)]["thumbnail"]
    for item_index in range(2):
        item = window.workspace._empty._recent.item(item_index)
        assert not item.icon().isNull()

    # Stale results for replaced lists must be ignored silently.
    from PyQt6.QtGui import QImage

    window.workspace.set_recent_files([str(first)])
    window.workspace._empty._on_recent_thumb(str(second), QImage(8, 8, QImage.Format.Format_RGB888))
    assert str(second) not in window.workspace._empty._thumb_done
    window.close()


def test_zoom_coalescing(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "zoom.pdf", pages=5)
    window._load_file_sync(str(source))
    assert _wait(app, lambda: not window.workspace.canvas._pending)

    canvas = window.workspace.canvas
    calls: list[float] = []
    base = canvas.zoom_ratio
    monkeypatch.setattr(canvas, "set_zoom", lambda ratio: calls.append(ratio))

    for _ in range(5):
        canvas._queue_zoom(canvas.zoom_ratio * 1.2)
    assert calls == []  # coalesced, nothing applied yet
    canvas._apply_queued_zoom()
    assert len(calls) == 1
    assert abs(calls[0] - base * 1.2) < 1e-9  # last queued target wins
    canvas._apply_queued_zoom()
    assert len(calls) == 1  # pending cleared, no double apply
    window.close()


def test_scroll_sync_coalescing(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "scroll.pdf", pages=8)
    window._load_file_sync(str(source))
    assert _wait(app, lambda: not window.workspace.canvas._pending)

    canvas = window.workspace.canvas
    canvas.set_layout_mode("continuous")
    assert _wait(app, lambda: not canvas._pending)

    sync_calls: list[int] = []
    monkeypatch.setattr(canvas, "_sync_views", lambda: sync_calls.append(1))
    for _ in range(4):
        canvas._schedule_scroll_sync()
    assert sync_calls == []
    canvas._apply_scroll_sync()
    assert len(sync_calls) == 1
    window.close()
