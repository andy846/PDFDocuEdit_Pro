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
