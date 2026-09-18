"""Large Organizer architecture: bounded UI, actual viewport, and safe cancellation."""
from threading import Event, get_ident
from time import monotonic

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from core.page_plan import PlanReader, blank_entry
from dialogs.document_dialogs import VisualOrganizerDialog
from dialogs.virtual_organizer import VirtualOrganizerGrid
from scripts.benchmark_open import synthetic_pdf


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait_for(predicate, timeout=15):
    end = monotonic() + timeout
    while not predicate() and monotonic() < end:
        QTest.qWait(10)
    assert predicate()


def finish(dialog):
    dialog.reject()
    wait_for(lambda: dialog.pages._task is None)
    dialog.release_sources()
    dialog.deleteLater()
    QApplication.processEvents()


def test_18000_pages_open_without_page_widgets_or_gui_pdf_reads(app, tmp_path, monkeypatch):
    path = synthetic_pdf(tmp_path / "large.pdf", 18000)
    with fitz.open(path) as doc:
        original = doc.load_page
        reads = []
        gui = get_ident()
        def load(page):
            reads.append(get_ident())
            return original(page)
        monkeypatch.setattr(doc, "load_page", load)
        # A normal preview must never serialize/copy the complete source PDF.
        monkeypatch.setattr(doc, "tobytes", lambda *a, **k: pytest.fail("whole-document preview copy"))
        dialog = VisualOrganizerDialog(doc)
        try:
            assert isinstance(dialog.pages, VirtualOrganizerGrid)
            assert not reads
            assert len(dialog.findChildren(QWidget)) < 100
            assert not dialog.apply_button.isEnabled()
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 18000)
            wait_for(lambda: bool(dialog.pages._thumb_cache))
            assert reads and gui not in reads
            assert len(dialog.pages.findChildren(QWidget)) < 10
            assert dialog.apply_button.isEnabled()
            assert len(dialog.pages._thumb_cache) < 30
        finally:
            finish(dialog)


def test_preparation_remains_responsive_and_cancel_discards_result(app, tmp_path, monkeypatch):
    path = synthetic_pdf(tmp_path / "cancel.pdf", 1001)
    entered, release = Event(), Event()
    with fitz.open(path) as doc:
        original = doc.load_page
        def blocked(page):
            entered.set()
            assert release.wait(10)
            return original(page)
        monkeypatch.setattr(doc, "load_page", blocked)
        dialog = VisualOrganizerDialog(doc)
        beats = []
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(True))
        timer.start(5)
        try:
            dialog.show()
            wait_for(entered.is_set)
            QTest.qWait(40)
            assert len(beats) >= 3
            dialog.reject()
            assert dialog._pending_result is not None
            assert dialog.isVisible()  # Keep the borrowed document alive until the reader exits.
            release.set()
            wait_for(lambda: dialog.pages._task is None and not dialog.isVisible())
            assert not dialog.pages._widgets
            assert not dialog.pages._thumb_cache
        finally:
            release.set()
            timer.stop()
            finish(dialog)


def test_large_grid_scroll_selection_and_plan_edits(app, tmp_path):
    path = synthetic_pdf(tmp_path / "edit.pdf", 18000)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 18000)
            grid = dialog.pages
            app.processEvents()
            bar = grid.verticalScrollBar()
            for fraction in (.2, .9, .01, 1):
                bar.setValue(round(bar.maximum() * fraction))
            app.processEvents()
            viewport = grid.viewport().rect()
            # Independent actual-geometry oracle, not the production range calculation.
            visible = {row for row in range(18000)
                       if grid.visualRect(grid.model().index(row, 0)).intersects(viewport)}
            assert 17999 in visible
            assert visible <= set(grid._visible_positions())
            wanted = {grid._widgets[row].entry for row in visible}
            wait_for(lambda: wanted <= grid._thumb_cache.keys())
            assert len(grid._thumb_cache) <= 128
            assert len(grid._thumb_queue) < 40
            dialog._select_expression("1,3")
            dialog._reverse()
            assert grid.order()[:4] == [2, 1, 0, 3]
            dialog._select_expression("1")
            dialog._duplicate()
            dialog._rotate_selected(90)
            assert grid.page_plan()[1].final_rotation == 90
            dialog._undo()
            assert grid.page_plan()[1].final_rotation == 0
            dialog._redo()
            assert grid.page_plan()[1].final_rotation == 90
            grid.move_selected(grid.count())
            assert grid.page_plan()[-1].final_rotation == 90
            assert grid.remove_selected()
            assert grid.count() == 18000
            grid.add_external_pages([blank_entry(300, 500)], "beginning")
            assert grid.page_plan()[0].source_kind == "blank"
            grid.restore()
            assert grid.order() == list(range(18000))
            grid.select_positions(range(18000))
            assert len(grid.selected_positions()) == 18000
            assert not grid.remove_selected()
        finally:
            finish(dialog)


def test_closing_during_preview_waits_without_blocking_and_discards_image(app, tmp_path, monkeypatch):
    path = synthetic_pdf(tmp_path / "preview.pdf", 1001)
    entered, release = Event(), Event()
    original = PlanReader.render
    def blocked(reader, entry, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(reader, entry, *args, **kwargs)
    monkeypatch.setattr(PlanReader, "render", blocked)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(entered.is_set)
            dialog.reject()
            assert dialog._pending_result is not None
            beat = []
            QTimer.singleShot(0, lambda: beat.append(True))
            QTest.qWait(30)
            assert beat
            release.set()
            wait_for(lambda: dialog.pages._task is None and not dialog.isVisible())
            assert not dialog.pages._thumb_cache
        finally:
            release.set()
            finish(dialog)


def test_preserves_source_rotation_and_stale_preview_identity(app, tmp_path):
    path = synthetic_pdf(tmp_path / "rotation.pdf", 1001)
    with fitz.open(path) as doc:
        doc[0].set_rotation(90)
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 1001)
            grid = dialog.pages
            assert grid.page_plan()[0].final_rotation == 90
            grid.select_positions([0])
            previous = grid.page_plan()[0]
            grid.rotate_selected(90)
            changed = grid.page_plan()[0]
            assert changed.final_rotation == 180
            wait_for(lambda: changed in grid._thumb_cache)
            assert doc[0].rotation == 90
            # A late old-entry result is keyed by the immutable plan entry and
            # cannot replace the new rotation's cached image.
            from PyQt6.QtGui import QImage
            image = QImage(5, 5, QImage.Format.Format_RGB888)
            cached = grid._thumb_cache[changed]
            grid._rendered((previous, image, 100, 200))
            assert grid._thumb_cache[changed] is cached
        finally:
            finish(dialog)


def test_resizing_and_failed_preparation_have_safe_ui_states(app, tmp_path, monkeypatch):
    path = synthetic_pdf(tmp_path / "resize.pdf", 1001)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 1001)
            grid = dialog.pages
            for width in (1400, 800, 1100):
                dialog.resize(width, 800)
                app.processEvents()
                bar = grid.verticalScrollBar()
                bar.setValue(bar.maximum() // 2)
                app.processEvents()
                area = grid.viewport().rect()
                actual = {row for row in range(1001)
                          if grid.visualRect(grid.model().index(row, 0)).intersects(area)}
                assert actual and actual <= set(grid._visible_positions())
                assert grid._pool.maxThreadCount() == 1
        finally:
            finish(dialog)
    with fitz.open(path) as doc:
        def fail(_page):
            raise ValueError("Synthetic page-tree failure")
        monkeypatch.setattr(doc, "load_page", fail)
        dialog = VisualOrganizerDialog(doc)
        errors = []
        dialog.pages.failed.connect(errors.append)
        try:
            dialog.show()
            wait_for(lambda: bool(errors) and dialog.pages._task is None)
            assert "Synthetic" in errors[0]
            assert not dialog.apply_button.isEnabled()
        finally:
            finish(dialog)


def test_pointer_drag_reorders_group_and_history_without_native_drop(app, tmp_path):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    path = synthetic_pdf(tmp_path / "drag.pdf", 18000)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 18000)
            app.processEvents()
            grid = dialog.pages
            viewport = grid.viewport()

            def move(point):
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(viewport, event)

            first = grid.visualRect(grid.model().index(0, 0)).center()
            fourth = grid.visualRect(grid.model().index(3, 0)).center()
            initial_history = len(dialog._history)
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=first)
            move(fourth)
            assert grid._dragging and grid._drop_slot == 4
            # Only commit the plan on release, keeping hover/auto-scroll cheap.
            assert grid.order()[:4] == [0, 1, 2, 3]
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=fourth)
            assert grid.order()[:4] == [1, 2, 3, 0]
            assert len(dialog._history) == initial_history + 1
            dialog._undo()
            assert grid.order()[:4] == [0, 1, 2, 3]
            dialog._redo()
            assert grid.order()[:4] == [1, 2, 3, 0]
            grid.restore()
            grid.select_positions([0, 1])
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=first)
            move(fourth)
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=fourth)
            assert grid.order()[:4] == [2, 3, 0, 1]
            assert grid.selected_positions() == [2, 3]
            assert len(grid.findChildren(QWidget)) < 10
        finally:
            finish(dialog)


def test_pointer_drag_auto_scroll_and_escape_cancel(app, tmp_path):
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    path = synthetic_pdf(tmp_path / "drag-cancel.pdf", 1001)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        try:
            dialog.show()
            wait_for(lambda: dialog.pages.count() == 1001)
            app.processEvents()
            grid = dialog.pages
            viewport = grid.viewport()
            start = grid.visualRect(grid.model().index(0, 0)).center()
            end = QPoint(start.x(), viewport.height() - 4)
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
            event = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(viewport.mapToGlobal(end)),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(viewport, event)
            assert grid._dragging
            wait_for(lambda: grid.verticalScrollBar().value() > 0)
            QTest.keyClick(grid, Qt.Key.Key_Escape)
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
            assert not grid._dragging and not grid._drag_scroll.isActive()
            assert grid.order() == list(range(1001))
        finally:
            finish(dialog)


@pytest.mark.parametrize("soft", ["#263f60", "rgba(16, 144, 200, 46)"])
def test_large_card_uses_rounded_theme_surface_and_selection_badge(app, monkeypatch, soft):
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

    from core.page_plan import PagePlanEntry
    from dialogs.virtual_organizer import CELL_H, CELL_W
    from styles.theme import get_colors

    colors = dict(get_colors(), primary_soft=soft)
    monkeypatch.setattr("dialogs.virtual_organizer.get_colors", lambda: colors)
    with fitz.open() as doc:
        doc.new_page()
        grid = VirtualOrganizerGrid(doc)
        grid.set_plan([PagePlanEntry("card", "current", 0)])
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, CELL_W, CELL_H)
        option.state = QStyle.StateFlag.State_Enabled
        sentinel = QColor("#fa00fa")
        def paint():
            image = QImage(CELL_W, CELL_H, QImage.Format.Format_ARGB32)
            image.fill(sentinel)
            painter = QPainter(image)
            grid.itemDelegate().paint(painter, option, grid.model().index(0, 0))
            painter.end()
            return image
        try:
            image = paint()
            assert image.pixelColor(5, 5) == sentinel  # Rounded outer corner stays transparent.
            assert image.pixelColor(20, 20) == QColor(get_colors()["bg_surface"])
            option.state |= QStyle.StateFlag.State_Selected
            image = paint()
            if soft.startswith("rgba"):
                base = QColor(colors["bg_surface"])
                expected = QColor(*(round(front * 46 / 255 + back * 209 / 255)
                                    for front, back in zip((16, 144, 200), base.getRgb()[:3], strict=True)))
            else:
                expected = QColor(soft)
            assert image.pixelColor(20, 20) == expected
            assert image.pixelColor(CELL_W - 20, 14) == QColor(get_colors()["primary"])
            assert grid.frameShape() == grid.Shape.NoFrame
        finally:
            grid.shutdown()
            grid.reader.close()
            grid.deleteLater()
            app.processEvents()
