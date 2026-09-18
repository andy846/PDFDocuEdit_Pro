from __future__ import annotations

import time
from pathlib import Path

import fitz
from PyQt6.QtCore import QPoint, QRectF
from PyQt6.QtWidgets import QApplication

import core.viewer as viewer_module
from core.settings import SettingsManager
from ui.pdf_canvas import LayoutMode, ToolMode


def make_pdf(path: Path, pages: int = 6) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), f"Page {index + 1} searchable content")
        document.save(path)
    return path


def _window(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication(["pdfdocuedit-p2-test"])
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
    while (canvas._pending or canvas._magnifier_task is not None) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_layout_modes_and_page_sync(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "p2.pdf")
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)

    canvas = window.workspace.canvas
    assert canvas.layout_mode == LayoutMode.SINGLE

    window._set_layout_mode("continuous")
    _wait_renders(app, canvas)
    assert canvas.layout_mode == LayoutMode.CONTINUOUS
    assert len(canvas._rows) == 6
    assert window.bottom_bar._layout.currentData() == "continuous"

    canvas.set_page(3)
    _wait_renders(app, canvas)
    assert canvas.current_page == 3
    assert window.bottom_bar._page.text() == "4"

    window._set_layout_mode("facing")
    assert canvas.layout_mode == LayoutMode.FACING
    assert canvas._rows[0][1] == [0, 1]
    assert canvas._rows[1][1] == [2, 3]
    assert canvas._rows[2][1] == [4, 5]
    window.close()

def test_horizontal_scroll_at_400_percent_all_layouts_and_split(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "wide-scroll.pdf", pages=4)
    window._load_file_sync(str(source))
    canvas = window.workspace.canvas
    _wait_renders(app, canvas)

    for mode in ("single", "continuous", "facing"):
        window._set_layout_mode(mode)
        canvas.set_zoom(4.0)
        _wait_renders(app, canvas)
        app.processEvents()
        assert canvas.horizontalScrollBar().maximum() > 0, mode

    window._toggle_split_view()
    session = window._session
    assert session is not None and session.split_canvas is not None
    session.split_canvas.set_zoom(4.0)
    _wait_renders(app, session.split_canvas)
    app.processEvents()
    assert session.split_canvas.horizontalScrollBar().maximum() > 0
    window.close()


def test_fit_and_actual_size(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "fit.pdf")
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)

    canvas = window.workspace.canvas
    canvas.fit_page()
    app.processEvents()
    zoom = canvas.zoom_ratio
    assert 0.25 <= zoom <= 4.0
    assert int(window.bottom_bar._zoom.text().rstrip("%")) == round(zoom * 100)

    canvas.actual_size()
    assert canvas.zoom_ratio == 1.0
    window.close()


def test_selection_and_search_highlight(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "select.pdf")
    window._load_file_sync(str(source))
    _wait_renders(app, window.workspace.canvas)

    canvas = window.workspace.canvas
    canvas.set_tool_mode(ToolMode.SELECT)
    assert canvas.tool_mode == ToolMode.SELECT

    page = window.engine.document.load_page(0)
    words = [word for word in page.get_text("words") if "searchable" in str(word[4])]
    assert words
    pdf_rect = fitz.Rect(words[0][:4])
    scale = 1.0 / canvas.zoom_ratio
    widget_rect = QRectF(
        pdf_rect.x0 / scale,
        pdf_rect.y0 / scale,
        pdf_rect.width / scale,
        pdf_rect.height / scale,
    )
    canvas._on_selection(0, widget_rect)
    assert canvas._selection is not None
    assert "searchable" in canvas._selection[1]

    copied: list[str] = []
    canvas.textCopied.connect(copied.append)
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    ctrl_c = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier
    )
    assert canvas._viewport_key_press(ctrl_c)
    assert copied == ["searchable"]

    # Search-hit highlighting is stored and applied to the page overlay.
    canvas.show_search_hits(0, [pdf_rect])
    assert canvas._search_hits == (0, [pdf_rect])
    view = canvas._page_views.get(0)
    assert view is not None
    assert view.overlay._search_rects == [pdf_rect]
    window.close()


def test_magnifier_tracks_cursor_and_keeps_edge_sample_centered(
    tmp_path: Path, monkeypatch
) -> None:
    window, app = _window(tmp_path, monkeypatch)
    source = make_pdf(tmp_path / "magnifier.pdf")
    window._load_file_sync(str(source))
    canvas = window.workspace.canvas
    _wait_renders(app, canvas)

    canvas.set_tool_mode(ToolMode.MAGNIFIER)
    overlay = canvas._page_views[0].overlay
    local = QPoint(overlay.width() // 2, overlay.height() // 2)
    viewport_position = overlay.mapTo(canvas.viewport(), local)
    target = canvas._magnifier_target(viewport_position)
    assert target is not None
    page_num, _pager_position, pdf_point = target
    expected = overlay.widget_to_pdf(local)
    assert page_num == 0
    assert abs(pdf_point.x - expected.x) < 0.01
    assert abs(pdf_point.y - expected.y) < 0.01

    canvas._update_magnifier(viewport_position)
    _wait_renders(app, canvas)
    assert canvas._magnifier_popup is not None
    pixmap = canvas._magnifier_popup.pixmap()
    assert pixmap is not None
    assert abs(pixmap.deviceIndependentSize().width() - 200) <= 1
    assert abs(pixmap.deviceIndependentSize().height() - 200) <= 1

    # A sample next to the page edge remains the same size instead of being
    # stretched, which keeps its target under the popup centre crosshair.
    canvas._update_magnifier(
        overlay.mapTo(canvas.viewport(), QPoint(1, 1))
    )
    _wait_renders(app, canvas)
    edge_pixmap = canvas._magnifier_popup.pixmap()
    assert edge_pixmap is not None
    assert abs(edge_pixmap.deviceIndependentSize().width() - 200) <= 1
    assert abs(edge_pixmap.deviceIndependentSize().height() - 200) <= 1
    window.close()


def test_command_bar_canvas_buttons_switch_and_sync_modes(
    tmp_path: Path, monkeypatch
) -> None:
    from PyQt6.QtCore import Qt

    window, app = _window(tmp_path, monkeypatch)
    buttons = window.command_bar._canvas_buttons
    assert list(buttons) == ["browse", "hand", "select", "magnifier"]
    assert all(not button.isEnabled() for button in buttons.values())

    source = make_pdf(tmp_path / "canvas-buttons.pdf")
    window._load_file_sync(str(source))
    app.processEvents()
    assert all(button.isEnabled() for button in buttons.values())
    assert buttons["browse"].isChecked()

    buttons["hand"].click()
    assert window.workspace.canvas.tool_mode == ToolMode.HAND
    assert buttons["hand"].isChecked()
    overlay = window.workspace.canvas._page_views[0].overlay
    assert overlay.cursor().shape() == Qt.CursorShape.OpenHandCursor
    assert overlay.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    window.workspace.canvas._hand_anchor = QPoint(10, 10)
    window.workspace.canvas._refresh_cursors()
    assert overlay.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    window.workspace.canvas._hand_anchor = None
    window.workspace.canvas._refresh_cursors()
    hand_action = next(
        action for action in window._tool_actions if action.data() == "hand"
    )
    assert hand_action.isChecked()

    window._set_canvas_tool("magnifier")
    assert window.workspace.canvas.tool_mode == ToolMode.MAGNIFIER
    assert buttons["magnifier"].isChecked()
    assert sum(button.isChecked() for button in buttons.values()) == 1
    assert not overlay.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
    window.close()


def test_p2_commands_registered(tmp_path: Path, monkeypatch) -> None:
    window, app = _window(tmp_path, monkeypatch)
    ids = [command.id for command in window._commands]
    for wanted in (
        "view_single",
        "view_continuous",
        "view_facing",
        "fit_page",
        "actual_size",
        "tool_hand",
        "tool_select",
        "tool_magnifier",
        "toggle_page_labels",
    ):
        assert wanted in ids, wanted
    window.close()
