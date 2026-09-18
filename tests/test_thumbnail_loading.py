from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from ui.thumbnail_panel import ThumbnailPanel


def test_large_list_keeps_widgets_bounded_and_restores_cached_image(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = ThumbnailPanel(animations_enabled=False)
    monkeypatch.setattr(panel._pool, "start", lambda *args: None)
    panel.resize(220, 420)
    panel.show()
    try:
        panel.load_document("unused.pdf", 5000)
        app.processEvents()
        assert panel._list.count() == 5000
        assert len(panel._widget_rows) < 40
        image = QImage(8, 8, QImage.Format.Format_RGB888)
        image.fill(0xFF123456)
        panel._on_thumbnail_rendered(0, image, panel._generation)
        panel.set_current_page(4999)
        app.processEvents()
        assert panel._list.currentRow() == 4999
        assert panel._list.itemWidget(panel._list.item(0)) is None
        assert len(panel._widget_rows) < 40
        panel.set_current_page(0)
        app.processEvents()
        label = panel._list.itemWidget(panel._list.item(0)).image_label
        assert not label.pixmap().isNull()
        assert label.pixmap().toImage().pixelColor(0, 0).name() == "#123456"
        assert len(panel._widget_rows) < 40
    finally:
        panel.clear()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_failed_thumbnail_stops_after_two_attempts(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = ThumbnailPanel(animations_enabled=False)
    panel.show()
    started = []
    monkeypatch.setattr(panel._pool, "start", lambda *args: started.append(args))
    try:
        panel.load_document("unused.pdf", 1)
        panel._on_thumbnail_failed(0, panel._generation)
        panel._schedule_render(0)
        panel._on_thumbnail_failed(0, panel._generation)
        for _ in range(5):
            panel._render_visible_thumbnails()
            panel._schedule_render(0)
        assert len(started) == 2
        assert not panel._pending
    finally:
        panel.clear()
        panel.deleteLater()
        app.processEvents()


def test_fast_scroll_prioritizes_visible_pages_before_prefetch(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = ThumbnailPanel(animations_enabled=False)
    queued = []
    monkeypatch.setattr(panel._pool, "start", lambda task, priority=0: queued.append((task, priority)))
    monkeypatch.setattr(panel._pool, "tryTake", lambda task: True)
    panel.resize(220, 420)
    panel.show()
    try:
        panel.load_document("unused.pdf", 500)
        app.processEvents()
        queued.clear()
        panel.set_current_page(250)
        app.processEvents()
        first, last = panel._visible_range(overscan=0)
        focused = set(range(first, last + 1))
        assert queued[0][0]._page_num in focused
        assert queued[0][1] == 10
        for page in focused:
            label = panel._list.itemWidget(panel._list.item(page)).image_label
            assert "Loading" in label.text()
            assert str(page + 1) in label.text()
        # A late result from the previous viewport must not replace a new row.
        image = QImage(8, 8, QImage.Format.Format_RGB888)
        image.fill(0xFF123456)
        panel._on_thumbnail_rendered(0, image, panel._generation)
        assert "Loading" in panel._list.itemWidget(panel._list.item(first)).image_label.text()
        # Completion updates the current row without another scroll event.
        panel._on_thumbnail_rendered(first, image, panel._generation)
        assert not panel._list.itemWidget(panel._list.item(first)).image_label.pixmap().isNull()
    finally:
        panel.clear()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_scrollbar_jumps_follow_actual_visible_rows_and_restore_images(monkeypatch):
    """Use Qt geometry as the oracle, never the scheduler's own range helper."""
    app = QApplication.instance() or QApplication([])
    panel = ThumbnailPanel(False)
    monkeypatch.setattr(panel._pool, "start", lambda *args: None)
    monkeypatch.setattr(panel._pool, "tryTake", lambda task: True)
    panel.resize(240, 700)
    panel.load_document("unused.pdf", 18000)
    panel.show()
    image = QImage(8, 8, QImage.Format.Format_RGB888)
    image.fill(0xFF123456)
    try:
        app.processEvents()
        scroll = panel._list.verticalScrollBar()
        for fraction in (0, .1, .5, .9, 1, .6, .02, 1, 0):
            scroll.setValue(round(scroll.maximum() * fraction))
            app.processEvents()
            viewport = panel._list.viewport().rect()
            # Independent exhaustive oracle is intentional in this regression;
            # production must use bounded geometry lookups instead.
            visible = {row for row in range(18000)
                       if panel._list.visualRect(panel._list.model().index(row, 0)).intersects(viewport)}
            assert visible
            assert visible <= panel._widget_rows
            assert visible <= panel._pending | panel._cache.keys()
            for row in visible:
                panel._on_thumbnail_rendered(row, image, panel._generation)
                widget = panel._list.itemWidget(panel._list.item(row))
                assert widget is not None
                assert not widget.image_label.pixmap().isNull()
            assert len(panel._widget_rows) < 30
            assert len(panel._pending) <= 12
        # Hide/show must recover the current viewport without another scroll.
        panel.hide()
        scroll.setValue(scroll.maximum())
        panel.show()
        app.processEvents()
        assert 17999 in panel._widget_rows
    finally:
        panel.clear()
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_real_large_pdf_fills_visible_rows_after_drag_stops(tmp_path):
    from time import monotonic

    from PyQt6.QtTest import QTest

    from scripts.benchmark_open import synthetic_pdf

    app = QApplication.instance() or QApplication([])
    source = synthetic_pdf(tmp_path / "large-thumbnails.pdf", 18000)
    panel = ThumbnailPanel(False)
    panel.resize(240, 700)
    panel.load_document(str(source), 18000)
    panel.show()
    try:
        app.processEvents()
        scroll = panel._list.verticalScrollBar()
        # Drag rapidly across distant ranges, then stop without another nudge.
        for fraction in (.1, .8, .3, 1):
            scroll.setValue(round(scroll.maximum() * fraction))
        app.processEvents()
        viewport = panel._list.viewport().rect()
        visible = {row for row in range(17980, 18000)
                   if panel._list.visualRect(panel._list.model().index(row, 0)).intersects(viewport)}
        assert 17999 in visible
        deadline = monotonic() + 15
        while not visible <= panel._cache.keys() and monotonic() < deadline:
            QTest.qWait(20)
        assert visible <= panel._cache.keys()
        for row in visible:
            widget = panel._list.itemWidget(panel._list.item(row))
            assert widget is not None
            assert not widget.image_label.pixmap().isNull()
        assert len(panel._cache) <= 80
        assert len(panel._pending) <= 12
    finally:
        panel.clear()
        panel.quiesce_renders()
        panel.close()
        panel.deleteLater()
        app.processEvents()
