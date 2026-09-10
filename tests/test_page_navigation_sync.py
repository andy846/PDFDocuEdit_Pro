import fitz
import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ui.pdf_canvas import CAPTION_H, LayoutMode, PdfCanvas


@pytest.fixture
def canvas(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PdfCanvas, "_request_render", lambda *args, **kwargs: None)
    document = fitz.open()
    for _ in range(5):
        document.new_page(width=240, height=300)
    view = PdfCanvas()
    view.resize(900, 850)
    view.show()
    view.load_doc(document)
    QTest.qWait(150)
    yield view, app
    view.clear()
    view.close()
    document.close()


@pytest.mark.parametrize("mode", [LayoutMode.CONTINUOUS, LayoutMode.FACING])
def test_jump_keeps_requested_page_and_signals_in_sync(canvas, mode):
    view, app = canvas
    view.set_layout_mode(mode)
    QTest.qWait(150)
    events = []
    view.pageChanged.connect(events.append)
    for target in (2, 4, 0, 3):
        events.clear()
        view.set_page(target)
        QTest.qWait(150)
        assert view.current_page == target
        assert events == [target]
        rect = view._page_rect_in_layout(target)
        assert rect.bottom() > view.verticalScrollBar().value()
        assert rect.top() < view.verticalScrollBar().value() + view.viewport().height()


def test_small_page_centers_and_stays_centered_on_resize_and_zoom(canvas):
    view, app = canvas
    for width, height, zoom in ((900, 850, 1), (720, 1000, .75), (950, 750, 1.2)):
        view.resize(width, height)
        view.set_zoom(zoom)
        QTest.qWait(150)
        rect = view._page_rect_in_layout(0)
        assert abs(rect.center().x() - view.viewport().width() / 2) <= 1
        assert abs(rect.center().y() + CAPTION_H / 2 - view.viewport().height() / 2) <= 1
        assert view.verticalScrollBar().maximum() == 0


def test_scroll_updates_current_page_and_retains_facing_side_on_tie(canvas):
    view, app = canvas
    view.resize(700, 380)
    view.set_layout_mode(LayoutMode.FACING)
    QTest.qWait(150)
    view.set_page(2)
    view._update_current_from_scroll()
    assert view.current_page == 2
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    QTest.qWait(150)
    assert view.current_page in (3, 4)


def test_viewer_thumbnail_status_and_counts_follow_primary_and_history(tmp_path, monkeypatch):
    import sys
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    import core.viewer as viewer_module
    from core.settings import SettingsManager

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    monkeypatch.setattr(PdfCanvas, "_request_render", lambda *args, **kwargs: None)
    source = tmp_path / "pages.pdf"
    with fitz.open() as document:
        for _ in range(5):
            document.new_page(width=240, height=300)
        document.save(source)
    window = viewer_module.PDFViewer()
    window.show()
    window.load_file(str(source))
    session = window._session
    thumbnails = session.nav_panel.thumbnails

    def check(page, count):
        QTest.qWait(180)
        assert session.canvas.current_page == session.page == window.bottom_bar._current_page == page
        assert thumbnails._list.currentRow() == page
        assert thumbnails._list.count() == window.bottom_bar._page_count == session.engine.page_count == count

    try:
        session.canvas.set_layout_mode(LayoutMode.FACING)
        thumbnails._list.setCurrentRow(2)
        check(2, 5)
        session.set_split(True)
        window._wire_canvas(session, session.split_canvas)
        session.set_split_sync(page=False)
        session.split_canvas.set_page(4)
        check(2, 5)
        session.set_split_sync(page=True)
        session.split_canvas.set_page(3)
        check(3, 5)
        with window._page_transaction("Delete last pages") as allowed:
            assert allowed
            session.engine.delete_pages([3, 4])
        window._after_page_count_change()
        check(2, 3)
        window._undo()
        check(2, 5)
        window._redo()
        check(2, 3)
        assert not errors, errors
    finally:
        session.engine._is_modified = False
        window.close_document()
        window.close()
        app.processEvents()


def test_loading_document_resets_scroll_to_its_first_page(canvas):
    view, app = canvas
    view.resize(600, 380)
    view.set_layout_mode(LayoutMode.CONTINUOUS)
    QTest.qWait(150)
    view.set_page(4)
    assert view.verticalScrollBar().value() > 0
    view.load_doc(view._doc)
    QTest.qWait(150)
    assert view.current_page == 0
    assert view._page_rect_in_layout(0).top() >= view.verticalScrollBar().value()


def test_large_single_page_remains_scrollable_and_next_page_starts_at_top(canvas):
    view, app = canvas
    view.resize(350, 300)
    view.set_zoom(2)
    QTest.qWait(150)
    assert view.verticalScrollBar().maximum() > 0
    assert view.horizontalScrollBar().maximum() > 0
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    view.set_page(1)
    assert view.verticalScrollBar().value() == 0
    assert view.current_page == 1
