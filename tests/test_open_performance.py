"""Architecture regressions; operation counts matter more than machine timing."""
from pathlib import Path
from threading import Event, get_ident
from time import monotonic

import fitz
import pytest
from PyQt6.QtCore import QAbstractListModel, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import core.viewer as viewer_module
import ui.workspace as workspace_module
from core.reader_lifetime import after_readers
from core.settings import SettingsManager
from scripts.benchmark_open import synthetic_pdf
from ui.page_geometry import PageRows
from ui.pdf_canvas import LayoutMode, PdfCanvas
from ui.thumbnail_panel import MAX_PENDING_RENDERS, ThumbnailPanel


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def window(app, tmp_path, monkeypatch):
    settings = SettingsManager(tmp_path / "settings.json")
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    view = viewer_module.PDFViewer()
    yield view
    view.close()
    app.processEvents()

def wait_until(predicate, timeout=10):
    end = monotonic() + timeout
    while not predicate() and monotonic() < end:
        QTest.qWait(10)
    assert predicate(), "asynchronous operation did not finish"


def test_unc_recents_never_probe_during_window_construction(app, tmp_path, monkeypatch):
    settings = SettingsManager(tmp_path / "settings.json")
    unc = r"\\unavailable-server\disconnected\report.pdf"
    settings.set("recent_files", [unc])
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    original = Path.stat
    def no_network_stat(path, *args, **kwargs):
        assert "unavailable-server" not in str(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", no_network_stat)
    monkeypatch.setattr(fitz, "open", lambda *a, **k: pytest.fail("recent PDF opened during construction"))
    view = viewer_module.PDFViewer()
    try:
        assert view.workspace._empty._recent.count() == 1
        assert view.workspace._empty._availability_started == -1
        assert settings.recent_files() == [str(Path(unc))]
    finally:
        view.close()


def test_welcome_defers_checks_until_visible_and_skips_network_thumbnails(app, monkeypatch):
    probes = []
    monkeypatch.setattr(workspace_module, "check_availability", lambda *args: probes.append(args))
    monkeypatch.setattr(fitz, "open", lambda *a, **k: pytest.fail("welcome opened a PDF"))
    view = workspace_module.EmptyState()
    path = r"\\offline\share\report.pdf"
    try:
        view.set_recent_files([path])
        assert not probes
        assert not hasattr(view, "_recent_pool")
        view.show()
        app.processEvents()
        assert len(probes) == 1
        previous = view._recent_generation
        view.set_recent_files(["new.pdf"])
        view._on_availability(str(Path(path)), previous, False)
        assert "Unavailable" not in view._recent.item(0).text()
    finally:
        view.close()


@pytest.mark.parametrize("pages", [100, 18000])
def test_thumbnail_model_and_initial_work_are_viewport_bounded(app, monkeypatch, pages):
    panel = ThumbnailPanel(False)
    started = []
    monkeypatch.setattr(panel._pool, "start", lambda task, *args: started.append(task))
    monkeypatch.setattr(panel._pool, "tryTake", lambda task: True)
    try:
        panel.resize(220, 420)
        panel.load_document("unused.pdf", pages)
        assert not started  # hidden panels do no render work
        assert isinstance(panel._list.model(), QAbstractListModel)
        assert panel._list.model().rowCount() == pages
        assert not panel._widget_rows
        panel.show()
        app.processEvents()
        assert 0 < len(panel._pending) <= MAX_PENDING_RENDERS
        assert len(panel._widget_rows) < 25
        assert len(panel.findChildren(QWidget)) < 120
    finally:
        panel.clear()
        panel.close()


def test_thumbnail_old_generation_cannot_change_replacement(app, monkeypatch):
    panel = ThumbnailPanel(False)
    monkeypatch.setattr(panel._pool, "start", lambda *a: None)
    monkeypatch.setattr(panel._pool, "tryTake", lambda task: True)
    try:
        panel.load_document("old.pdf", 18000)
        token = panel._generation
        panel.clear()
        panel.load_document("new.pdf", 2)
        image = QImage(8, 8, QImage.Format.Format_RGB888)
        panel._on_thumbnail_rendered(0, image, token)
        panel._on_thumbnail_failed(0, token)
        assert not panel._cache and not panel._failures
        assert panel._list.count() == 2
    finally:
        panel.clear()
        panel.close()


@pytest.mark.parametrize("mode", [LayoutMode.SINGLE, LayoutMode.CONTINUOUS, LayoutMode.FACING])
def test_18000_page_canvas_never_loads_whole_document(app, tmp_path, monkeypatch, mode):
    source = synthetic_pdf(tmp_path / "large.pdf", 18000)
    doc = fitz.open(source)
    loads = []
    real_load = doc.load_page
    def load(page):
        loads.append(page)
        return real_load(page)
    monkeypatch.setattr(doc, "load_page", load)
    canvas = PdfCanvas()
    monkeypatch.setattr(canvas, "_request_render", lambda *a, **k: None)
    try:
        canvas.resize(800, 700)
        canvas.set_layout_mode(mode)
        canvas.load_doc(doc)
        assert len(loads) < 150
        assert len(canvas._page_views) < 20
        if mode != LayoutMode.SINGLE:
            assert isinstance(canvas._rows, PageRows)
            assert len(canvas._rows.heights) < 20
        loads.clear()
        canvas.set_page(17999)
        canvas._sync_views()
        assert len(loads) < 150  # no scan of preceding 17,999 pages
        assert len(canvas._page_views) < 20
    finally:
        canvas.clear()
        canvas.close()
        doc.close()


def test_large_open_defers_optional_analysis_and_emits_timings(window, tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path / "large.pdf", 18000)
    monkeypatch.setattr(viewer_module, "list_document_annotations", lambda *a: pytest.fail("eager scan"))
    monkeypatch.setattr(viewer_module.PdfEngine, "get_toc", lambda *a: pytest.fail("eager outline"))
    monkeypatch.setattr(viewer_module, "_perform_document_analysis", lambda *a: pytest.fail("eager analysis"))
    window.show()
    window.load_file(str(source))
    wait_until(lambda: not window._open_queue_scheduled)
    session = window._session
    wait_until(lambda: "time_to_first_page" in session._open_trace.values)
    assert session.large_document
    assert not session.nav_panel.thumbnails._pending
    assert not getattr(session, "_annotation_records", None)
    trace = session._open_trace.values
    assert trace["page_analysis"] == "on_demand"
    assert all(key in trace for key in ("fitz_open", "working_copy", "metadata", "page_count", "page_model", "thumbnail_panel", "inspector", "search_text", "first_page_render", "time_to_first_page", "time_to_interactive"))


def test_slow_preparation_does_not_block_event_loop_and_closed_result_is_ignored(window, tmp_path, monkeypatch):
    source = synthetic_pdf(tmp_path / "small.pdf", 3)
    entered, release = Event(), Event()
    gui_thread = get_ident()
    real_prepare = viewer_module._prepare_pdf_engine
    prepared = []
    def slow(*args):
        assert get_ident() != gui_thread
        entered.set()
        assert release.wait(5)
        result = real_prepare(*args)
        prepared.append(result[1])
        return result
    monkeypatch.setattr(viewer_module, "_prepare_pdf_engine", slow)
    session = window.open_in_new_tab(str(source))
    try:
        wait_until(entered.is_set)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait_until(lambda: ticks)
        window.close_document(session)
        release.set()
        wait_until(lambda: not window._open_queue_scheduled)
        assert window.workspace.session_count() == 0
        assert prepared and not prepared[0].is_loaded()
    finally:
        release.set()


def test_reader_retirement_does_not_wait_on_gui_thread():
    reader, released = Event(), Event()
    after_readers([reader], released.set)
    assert not released.is_set()
    reader.set()
    assert released.wait(2)


def test_small_document_public_open_and_explicit_annotation_scan(window, tmp_path):
    source = tmp_path / "small.pdf"
    with fitz.open() as doc:
        for index in range(3):
            page = doc.new_page()
            page.add_text_annot((50, 50), f"Note {index}")
        doc.save(source)
    window.show()
    window.load_file(str(source))
    wait_until(lambda: not window._open_queue_scheduled)
    assert window.engine.page_count == 3
    assert not window._session.large_document
    assert not getattr(window._session, "_annotation_records", None)
    window._scan_annotations()
    wait_until(lambda: not window._tasks)
    assert window.context_panel._annot_list.count() == 3
    window.goto_page(2)
    wait_until(lambda: window._page == 2)
    assert window.engine.page_count == 3


def test_cancelled_preparation_disposes_native_document(app, tmp_path):
    from core.tasks import FunctionTask
    source = synthetic_pdf(tmp_path / "cancelled.pdf", 2)
    prepared = []
    def prepare():
        result = viewer_module._prepare_pdf_engine(str(source))
        prepared.append(result[1])
        task.cancel()
        return result
    task = FunctionTask(prepare, discard_result=viewer_module._dispose_prepared_pdf)
    task.run()
    assert prepared and not prepared[0].is_loaded()


def test_cached_recent_preview_requires_no_file_access(app, monkeypatch):
    import base64

    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    image = QImage(32, 44, QImage.Format.Format_RGB888)
    image.fill(0xff123456)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    path = str(Path(r"\\offline\share\cached.pdf"))
    info = {path: {"thumbnail": base64.b64encode(bytes(data)).decode("ascii"),
                   "last_opened": "2026-09-17T10:30"}}
    monkeypatch.setattr(fitz, "open", lambda *a, **k: pytest.fail("cached thumbnail opened a PDF"))
    monkeypatch.setattr(Path, "is_file", lambda *a: pytest.fail("cached thumbnail checked its source"))
    view = workspace_module.EmptyState()
    try:
        view.set_recent_files([path], info)
        assert path in view._thumb_done
        assert "2026-09-17 10:30" in view._recent.item(0).text()
    finally:
        view.close()


def test_window_destroyed_before_startup_timers_does_not_run_stale_callbacks(app, tmp_path, monkeypatch):
    import sys

    from PyQt6.QtCore import QCoreApplication, QEvent
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: SettingsManager(tmp_path / "settings.json"))
    view = viewer_module.PDFViewer()
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not errors


@pytest.mark.parametrize("operation", ["thumbnail", "open"])
def test_background_native_reads_respect_document_lock(app, tmp_path, monkeypatch, operation):
    from threading import Thread

    from core.pdf_engine import DOCUMENT_LOCK, PdfEngine
    from ui.thumbnail_panel import _RenderTask

    source = tmp_path / "native-reader.pdf"
    synthetic_pdf(source, 1)
    entered = Event()
    started = Event()
    original_open = fitz.open

    def tracked_open(*args, **kwargs):
        entered.set()
        return original_open(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", tracked_open)
    engine = PdfEngine()
    task = _RenderTask(str(source), 0, 0.1, None, 0)
    errors = []

    def run():
        started.set()
        try:
            if operation == "thumbnail":
                task.run()
            else:
                engine.open(source)
        except Exception as exc:
            errors.append(exc)

    worker = Thread(target=run)
    with DOCUMENT_LOCK:
        worker.start()
        assert started.wait(2)
        assert not entered.wait(0.1), "native reader bypassed the shared lock"
    worker.join(10)
    assert not worker.is_alive()
    assert entered.is_set()
    assert not errors
    engine.close()


def test_sidebar_layout_timer_does_not_retain_destroyed_receiver(app):
    import gc
    import weakref

    from ui.side_panel import CollapsibleSection

    for _ in range(12):
        parent = QWidget()
        section = CollapsibleSection("lifetime-test", "Tools", False, parent)
        reference = weakref.ref(section)
        del section, parent
        gc.collect()
        app.processEvents()
        assert reference() is None
