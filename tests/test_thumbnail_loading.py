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
