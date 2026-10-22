"""Live Deep Search pause, GUI responsiveness and owned task cleanup."""
import time
from threading import Event, get_ident

import fitz
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QTimer

from core.search_results_store import SearchResultsStore
from ui.deep_search_dialog import DeepSearchDialog


def wait(app, predicate, seconds=8):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    assert predicate(), "Deep Search did not reach the expected state"


@pytest.fixture
def search(qt_application, tmp_path, monkeypatch):
    for name, pages in (("a.pdf", 2), ("b.pdf", 12)):
        with fitz.open() as pdf:
            for _ in range(pages):
                pdf.new_page().insert_text((20, 30), "needle " * 8)
            pdf.save(tmp_path / name)
    entered, release = Event(), Event()
    visited = []
    original = fitz.Page.get_text

    def controlled(page, *args, **kwargs):
        visited.append((page.parent.name, page.number))
        if page.parent.name.endswith("b.pdf") and page.number == 0:
            entered.set()
            assert release.wait(8)
        return original(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_text", controlled)
    dialog = DeepSearchDialog(str(tmp_path))
    dialog.query.setText("needle")
    yield dialog, qt_application, entered, release, visited
    release.set()
    if not sip.isdeleted(dialog):
        dialog._cancel_search()
        wait(qt_application, lambda: dialog._task is None)
        temporary = dialog._store.path.parent
        dialog.close()
        wait(qt_application, lambda: not temporary.exists())


def test_pause_resume_does_not_restart_or_change_search_snapshot(search):
    dialog, app, entered, release, visited = search
    assert hasattr(dialog, "pause_button"), "Deep Search needs Pause / Resume"
    assert not dialog.pause_button.isEnabled()
    dialog._search()
    wait(app, entered.is_set)
    task = dialog._task
    dialog.pause_button.click()
    release.set()
    wait(app, lambda: dialog.pause_button.text() == "Resume")
    count = len(visited)
    end = time.monotonic() + .15
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    assert len(visited) == count and dialog._task is task
    assert dialog.cancel_button.isEnabled()
    dialog.query.setText("a different query")
    dialog.pause_button.click()
    wait(app, lambda: dialog._task is None)
    assert len(visited) == 14 and len(set(visited)) == 14
    assert dialog._run_query == "needle"
    assert "Completed" in dialog.status.text()
    assert dialog._store.hit_count() == 112
    assert not dialog.pause_button.isEnabled()


def test_cancel_wakes_paused_search_and_retains_completed_files(search):
    dialog, app, entered, release, _ = search
    assert hasattr(dialog, "pause_button"), "Deep Search needs Pause / Resume"
    dialog._search()
    wait(app, entered.is_set)
    dialog.pause_button.click()
    release.set()
    wait(app, lambda: dialog.pause_button.text() == "Resume")
    dialog._cancel_search()
    wait(app, lambda: dialog._task is None)
    assert "cancelled" in dialog.status.text()
    assert [r["filename"] for r in dialog._results] == ["a.pdf"]
    assert dialog._store.hit_count() == 16
    assert dialog.export_button.isEnabled()


def test_live_sql_runs_off_gui_thread_and_slow_queries_do_not_block(search, monkeypatch):
    dialog, app, entered, release, _ = search
    gui = get_ident()
    calls = []
    for name in ("add", "hit_count", "hit_page", "counts", "remove_incomplete_files"):
        original = getattr(SearchResultsStore, name)

        def observed(self, *args, _name=name, _original=original, **kwargs):
            calls.append((_name, get_ident()))
            if _name == "hit_page":
                time.sleep(.06)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(SearchResultsStore, name, observed)
    heartbeat = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(time.monotonic()))
    timer.start()
    try:
        dialog._search()
        wait(app, entered.is_set)
        release.set()
        wait(app, lambda: dialog._task is None)
        wait(app, lambda: dialog._hits_model.total == 112)
        assert calls and all(thread != gui for _, thread in calls), calls
        assert len(heartbeat) >= 5
        assert max(b-a for a, b in zip(heartbeat, heartbeat[1:], strict=False)) < .15
    finally:
        timer.stop()


def test_close_paused_search_cleans_only_after_worker_exit(search):
    dialog, app, entered, release, _ = search
    assert hasattr(dialog, "pause_button"), "Deep Search needs Pause / Resume"
    dialog._search()
    wait(app, entered.is_set)
    dialog.pause_button.click()
    release.set()
    wait(app, lambda: dialog.pause_button.text() == "Resume")
    temporary = dialog._store.path.parent
    dialog.close()
    wait(app, lambda: not temporary.exists())


def test_clear_completed_async_results_does_not_keep_old_store(search):
    dialog, app, entered, release, _ = search
    dialog._search()
    wait(app, entered.is_set)
    release.set()
    wait(app, lambda: dialog._task is None and dialog._queries.task is None)
    old = dialog._store.path
    dialog._clear_results()
    assert dialog._hits_model.total == 0
    assert dialog.table.rowCount() == 0 and not old.exists()
    assert dialog._queries is None
    dialog._search()
    wait(app, lambda: dialog._task is None)
    wait(app, lambda: dialog._hits_model.total == 112)


def test_live_model_sorted_paging_uses_one_cutoff_and_rejects_old_query(qt_application, tmp_path):
    from core.deep_search import SearchBatch, SearchFile, SearchHit
    from core.deep_search_runtime import read_search_query
    from ui.search_hits_model import SearchHitsModel
    store = SearchResultsStore()
    try:
        store.add(SearchBatch(hits=tuple(SearchHit("a.pdf", "a.pdf", i+1, "needle", "text", "needle", i)
                                        for i in range(450)),
                              file=SearchFile("a.pdf", "a.pdf", 450, 450, 450, False)))
        requests = []
        model = SearchHitsModel(store)
        model.set_async_loader(requests.append)
        model.configure()
        header = read_search_query(store.path, requests.pop())
        model.apply_query(header)
        assert model.rowCount() == 450 and model.hit(0).page == 1
        store.add(SearchBatch(hits=(SearchHit("0.pdf", "0.pdf", 1, "needle", "text", "new", 0),)))
        assert model.hit(249) is None
        page = read_search_query(store.path, requests.pop())
        model.apply_query(page)
        assert model.hit(249).page == 250
        model.configure(keyword="absent")
        model.apply_query(header)
        model.apply_query(read_search_query(store.path, requests.pop()))
        assert model.total == 0
    finally:
        store.close()


def test_empty_file_filter_returns_zero_with_snapshot_cutoff(qt_application):
    from core.deep_search_runtime import read_search_query
    from ui.search_hits_model import SearchHitsModel
    store = SearchResultsStore()
    try:
        requests = []
        model = SearchHitsModel(store)
        model.set_async_loader(requests.append)
        model.configure(())
        model.apply_query(read_search_query(store.path, requests.pop()))
        assert model.total == 0 and model.rowCount() == 0
    finally:
        store.close()


def test_scroll_during_refresh_waits_for_new_snapshot(qt_application):
    from core.deep_search import SearchBatch, SearchHit
    from core.deep_search_runtime import read_search_query
    from ui.search_hits_model import SearchHitsModel
    store = SearchResultsStore()
    try:
        store.add(SearchBatch(hits=tuple(SearchHit("b.pdf", "b.pdf", i+1, "needle", "text", "needle", i)
                                        for i in range(450))))
        requests = []
        model = SearchHitsModel(store)
        model.set_async_loader(requests.append)
        model.configure()
        model.apply_query(read_search_query(store.path, requests.pop()))
        store.add(SearchBatch(hits=(SearchHit("a.pdf", "a.pdf", 1, "needle", "text", "new", 0),)))
        model.refresh()
        header_request = requests.pop()
        assert model.hit(249) is None
        assert not requests, "Page must not use the old cutoff while a new header is pending"
        model.apply_query(read_search_query(store.path, header_request))
        assert model.hit(249) is None
        model.apply_query(read_search_query(store.path, requests.pop()))
        assert model.hit(249).page == 249
    finally:
        store.close()


def test_invalid_folder_finishes_with_actionable_error(qt_application, tmp_path):
    dialog = DeepSearchDialog(str(tmp_path / "missing"))
    dialog.query.setText("needle")
    try:
        dialog._search()
        wait(qt_application, lambda: dialog._task is None)
        assert dialog.status.text().startswith("Search failed:"), dialog.status.text()
        assert "valid folder" in dialog.status.text()
        assert not dialog.pause_button.isEnabled()
    finally:
        temporary = dialog._store.path.parent
        dialog.close()
        wait(qt_application, lambda: not temporary.exists())


def test_pause_after_text_waits_before_barcode_decode(search, monkeypatch):
    dialog, app, entered, release, visited = search
    decoded = []
    monkeypatch.setattr("core.deep_search._barcode_values",
                        lambda page: decoded.append((page.parent.name, page.number)) or ())
    dialog.barcodes.setChecked(True)
    dialog._search()
    wait(app, entered.is_set)
    dialog.pause_button.click()
    release.set()
    wait(app, lambda: dialog.pause_button.text() == "Resume")
    assert all(not name.endswith("b.pdf") for name, _ in decoded)
    dialog.pause_button.click()
    wait(app, lambda: dialog._task is None)
    assert len(visited) == 14 and len(decoded) == 14


def test_new_selection_is_not_replaced_by_older_header(qt_application):
    from core.deep_search import SearchBatch, SearchHit
    from core.deep_search_runtime import read_search_query
    from ui.search_hits_model import SearchHitsModel
    store = SearchResultsStore()
    try:
        first = SearchHit("a.pdf", "a.pdf", 1, "needle", "text", "first", 0)
        second = SearchHit("a.pdf", "a.pdf", 2, "needle", "text", "second", 0)
        store.add(SearchBatch(hits=(first, second)))
        requests, restored = [], []
        model = SearchHitsModel(store)
        model.set_async_loader(requests.append)
        model.viewRestored.connect(restored.append)
        model.configure()
        model.apply_query(read_search_query(store.path, requests.pop()))
        restored.clear()
        model.selected_hit = first
        model.refresh()
        result = read_search_query(store.path, requests.pop())
        model.selected_hit = second
        model.apply_query(result)
        assert not restored, "Old selection must not replace the newer user choice"
        model.apply_query(read_search_query(store.path, requests.pop()))
        assert restored == [1]
    finally:
        store.close()


def test_result_query_queue_prioritises_visible_pages_and_discards_dropped(qt_application, monkeypatch):
    from core.deep_search_runtime import read_search_query
    from ui.search_queries import SearchQueries
    store = SearchResultsStore()
    entered, release = Event(), Event()

    def slow(path, request):
        entered.set()
        assert release.wait(8)
        return read_search_query(path, request)

    monkeypatch.setattr("ui.search_queries.read_search_query", slow)
    service = SearchQueries(store.path, None)
    dropped = []
    if hasattr(service, "discarded"):
        service.discarded.connect(dropped.append)
    base = {"kind":"page", "generation":1, "paths":None, "keyword":"", "source":"",
            "order":"id", "cutoff":0}
    try:
        service.request({**base, "offset":0})
        wait(qt_application, entered.is_set)
        for page in range(1, 31):
            service.request({**base, "offset":page*200})
        assert len(service.queue) <= 4
        assert service.queue[0]["offset"] == 6000
        assert len(dropped) == 26
    finally:
        service.close()
        release.set()
        wait(qt_application, lambda: service.task is None)
        service.deleteLater()
        store.close()


def test_export_filtered_scope_uses_latest_debounced_input(search):
    dialog, app, entered, release, _ = search
    dialog._search()
    wait(app, entered.is_set)
    release.set()
    wait(app, lambda: dialog._task is None and dialog._queries.task is None)
    dialog.export_scope.setCurrentIndex(1)
    dialog.file_filter.setText("no-such-file")
    assert dialog._export_selection()[0] == ()


def test_unloaded_selection_during_refresh_keeps_record_identity(qt_application):
    from core.deep_search import SearchBatch, SearchHit
    from core.deep_search_runtime import read_search_query
    from ui.search_hits_model import SearchHitsModel
    store = SearchResultsStore()
    try:
        store.add(SearchBatch(hits=tuple(SearchHit("b.pdf", "b.pdf", i+1, "needle", "text", "needle", i)
                                        for i in range(450))))
        requests, restored = [], []
        model = SearchHitsModel(store)
        model.set_async_loader(requests.append)
        model.viewRestored.connect(restored.append)
        model.configure()
        model.apply_query(read_search_query(store.path, requests.pop()))
        restored.clear()
        assert hasattr(model, "choose_row"), "Selection tracking must include unloaded rows"
        model.choose_row(0)
        model.refresh()
        old_header = read_search_query(store.path, requests.pop())
        model.choose_row(249)
        store.add(SearchBatch(hits=(SearchHit("a.pdf", "a.pdf", 1, "needle", "text", "new", 0),)))
        model.apply_query(old_header)
        assert not restored
        model.apply_query(read_search_query(store.path, requests.pop()))
        assert restored == [250]
        assert model.selected_hit.path == "b.pdf" and model.selected_hit.page == 250
    finally:
        store.close()


@pytest.mark.parametrize("font_size", [12, 24])
def test_pause_resume_control_remains_visible_with_large_fonts(search, font_size):
    from PyQt6.QtCore import QPoint, QRect
    dialog, app, entered, release, _ = search
    font = dialog.font()
    font.setPointSize(font_size)
    dialog.setFont(font)
    dialog.resize(960, 640)
    dialog.show()
    app.processEvents()
    dialog._search()
    wait(app, entered.is_set)
    dialog.pause_button.click()
    release.set()
    wait(app, lambda: dialog.pause_button.text() == "Resume")
    app.processEvents()
    viewport = dialog._responsive_scroll.viewport()
    rect = QRect(dialog.pause_button.mapTo(viewport, QPoint()), dialog.pause_button.size())
    assert viewport.rect().contains(rect), (viewport.rect(), rect)


@pytest.mark.parametrize("size", [(960, 640), (1160, 760)])
def test_first_show_preserves_compact_search_rows_and_results(qt_application, monkeypatch, tmp_path, size):
    from PyQt6.QtCore import QPoint, QRect

    monkeypatch.setattr("ui.responsive.available_area", lambda _: QRect(0, 0, 1920, 1080))
    dialog = DeepSearchDialog(str(tmp_path))
    dialog._animations_enabled = False
    dialog.resize(*size)
    try:
        dialog.show()
        for _ in range(12):
            qt_application.processEvents()
        viewport = dialog._responsive_scroll.viewport()
        query = dialog.query.geometry()
        search = dialog.search_button.geometry()
        pause = dialog.pause_button.geometry()
        assert abs(query.center().y() - search.center().y()) <= 2
        assert abs(query.center().y() - pause.center().y()) <= 2
        assert dialog.tabs.height() >= dialog.height() * .45
        for control in (dialog.query, dialog.pause_button, dialog.open_option,
                        dialog.export_button, dialog.export_scope):
            rect = QRect(control.mapTo(viewport, QPoint()), control.size())
            assert viewport.rect().contains(rect), (viewport.rect(), rect)
    finally:
        dialog.close()
        qt_application.processEvents()
