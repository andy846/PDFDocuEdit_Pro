
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from tests.test_document_windows import editor as editor
from tests.test_quick_extraction import fixture_pdf
from tests.test_workflow_ui import app as app
from tests.test_workflow_ui import integrated as integrated


def wait_until(predicate, timeout=15000):
    from time import monotonic
    until = monotonic()+timeout/1000
    while not predicate() and monotonic() < until:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    assert predicate()


def make_dialog(tmp_path):
    from dialogs.quick_text_extractor import QuickTextExtractorDialog
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    dialog = QuickTextExtractorDialog(source, 0, str(tmp_path/"result.xlsx"), spec=spec.to_dict())
    dialog.show()
    return dialog


def test_shared_editor_multiline_preview_and_export(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        wait_until(lambda: "0000123" in dialog.preview_details.toPlainText())
        assert not dialog.scope.isVisible()
        assert not dialog.policy.isVisible()
        dialog.page_range.setText("1,3")
        dialog.page_mode.setCurrentText("Custom pages")
        dialog.start_scan()
        wait_until(lambda: dialog.result is not None and not dialog.host.workers)
        assert dialog.model.rowCount() == 2
        assert dialog.model.rows[0]["values"] == {"Code": "0000123 Second line"}
        dialog.export_to(tmp_path/"result.xlsx")
        wait_until(lambda: dialog.last_output is not None and not dialog.host.workers)
        from openpyxl import load_workbook
        book = load_workbook(tmp_path/"result.xlsx")
        assert book["Data"]["D2"].value == "0000123 Second line"
        book.close()
        dialog.join.setChecked(False)
        assert not dialog.export_button.isEnabled()
        assert "stale" in dialog.status.text().lower()
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


def test_close_during_preview_and_scan_releases_own_temporary_files(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    directory = dialog.host.directory
    wait_until(lambda: dialog.source_ready)
    dialog.start_scan()
    assert dialog.host.workers
    dialog.reject()
    wait_until(lambda: not dialog.isVisible() and not dialog.host.workers)
    assert not directory.exists()
    assert (tmp_path/"source.pdf").exists()


def test_responsive_keyboard_controls_and_no_profile(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        for width, height in ((1500, 900), (960, 640)):
            dialog.resize(width, height)
            QApplication.processEvents()
            assert dialog.extract_button.isVisible()
            assert dialog.extract_button.geometry().width() > 40
            assert dialog.table.isVisible() and dialog.view.isVisible()
        assert not any("profile" in button.text().lower() for button in dialog.findChildren(
            __import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton))
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


def test_handoff_copy_survives_quick_cleanup_and_remains_unaccepted(qt_application, tmp_path):
    from core.text_extraction import dispatch
    from workflow.engine import execute
    from workflow.model import WorkflowRun, WorkflowSpec
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    target = tmp_path/"workflow-source.pdf"
    result = dispatch({"operation": "handoff", "source": str(source), "target": str(target),
                       "extraction": spec.to_dict(), "pages": [0, 2]})
    source.unlink()
    workflow = WorkflowSpec.from_dict(result["spec"])
    run = execute(workflow, WorkflowRun(), tmp_path/"run", until="extract")
    assert not run.accepted
    with fitz.open(run.source) as pdf:
        assert pdf.page_count == 2
        assert "0000123" in pdf[0].get_text()
        assert "Last page" in pdf[1].get_text()


def test_viewer_entry_captures_unsaved_revision_and_closes_workers(editor, tmp_path, monkeypatch):
    from ui.text_extraction_controller import TextExtractionController  # noqa: F401
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    original = source.read_bytes()
    editor._open_in_new_tab_sync(str(source))
    editor.engine.rotate_pages([0], 90)
    editor._extract_text()
    wait_until(lambda: bool(getattr(editor, "_text_extraction_dialogs", [])))
    dialog = editor._text_extraction_dialogs[0]
    wait_until(lambda: dialog.last_image is not None)
    assert dialog.page.maximum() == 5
    with fitz.open(dialog.source) as captured:
        assert captured[0].rotation == 90
    assert source.read_bytes() == original
    monkeypatch.setattr(editor, "_confirm_discard_changes", lambda: True)
    dialog.apply_regions(spec.to_dict()["regions"])
    dialog.start_scan()
    assert dialog.host.workers
    editor.close()
    wait_until(lambda: not editor.isVisible(), 30000)
    assert not dialog.host.workers


def test_editor_handoff_adopts_regions_and_pages_in_actual_workflow(integrated, tmp_path):
    root, host = integrated
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    root._open_in_new_tab_sync(str(source))
    root._extract_text()
    wait_until(lambda: bool(getattr(root, "_text_extraction_dialogs", [])))
    dialog = root._text_extraction_dialogs[0]
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    dialog.apply_regions(spec.to_dict()["regions"])
    dialog.page_mode.setCurrentText("Custom pages")
    dialog.page_range.setText("1,3")
    dialog.open_workflow()
    wait_until(lambda: not root._text_extraction_dialogs)
    workflow = next(p for p in host.projects if getattr(p, "is_workflow", False))
    assert workflow.spec.node("extract").params == spec.to_dict()
    copied = workflow.spec.node("input").params["paths"][0]
    assert Path(copied).exists()
    assert workflow.spec.node("merge").params["pages"] == {copied: "1,3"}
    assert not workflow.run.accepted


def test_source_revision_change_invalidates_results_without_reading_disk(editor, tmp_path):
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    editor._open_in_new_tab_sync(str(source))
    editor._extract_text()
    wait_until(lambda: bool(getattr(editor, "_text_extraction_dialogs", [])))
    dialog = editor._text_extraction_dialogs[0]
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    dialog.apply_regions(spec.to_dict()["regions"])
    dialog.start_scan()
    wait_until(lambda: dialog.result is not None and not dialog.host.workers)
    assert dialog.export_button.isEnabled()
    editor.engine.rotate_pages([0], 90)
    dialog.export_to(tmp_path/"stale.xlsx")
    assert not (tmp_path/"stale.xlsx").exists()
    assert "source" in dialog.status.text().lower()
    assert not dialog.export_button.isEnabled()


def test_superseded_raster_preview_is_carried_to_latest_request(qt_application, tmp_path):
    dialog = make_dialog(tmp_path)
    try:
        wait_until(lambda: dialog.source_ready and not dialog.host.workers)
        delivered = []
        def request(page, raster):
            return {"operation": "preview", "source": dialog.source, "page": page,
                    "target": str(dialog.host.directory/f"queued-{page}.png"),
                    "raster": raster, "extraction": dialog.config().to_dict()}
        dialog.host.request(request(2, True), lambda result: delivered.append("obsolete"), preview=True)
        dialog.host.request(request(3, False), lambda result: delivered.append(Path(result["image"]).exists()), preview=True)
        assert len(dialog.host.workers) == 1
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        assert delivered == [True]
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


def test_temporary_cleanup_failure_is_visible_and_close_can_retry(qt_application, tmp_path, monkeypatch):
    dialog = make_dialog(tmp_path)
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    cleanup = dialog.host.temporary.cleanup
    def locked():
        raise PermissionError("Test temporary directory is locked")
    monkeypatch.setattr(dialog.host.temporary, "cleanup", locked)
    dialog.reject()
    assert dialog.isVisible()
    assert "temporary" in dialog.status.text().lower()
    monkeypatch.setattr(dialog.host.temporary, "cleanup", cleanup)
    dialog.reject()
    assert not dialog.isVisible()
    assert not dialog.host.directory.exists()


def test_latest_preview_replaces_displayed_page_and_discards_old_text(qt_application, tmp_path):
    from PyQt6.QtWidgets import QGraphicsPixmapItem
    dialog = make_dialog(tmp_path)
    try:
        wait_until(lambda: dialog.source_ready and not dialog.host.workers)
        image = next(item for item in dialog.view.scene().items() if isinstance(item, QGraphicsPixmapItem))
        original = image.pixmap().toImage()
        dialog.preview()  # Start an older field-only request.
        dialog.page.setValue(2)
        dialog.preview()  # Page-change raster is pending.
        dialog.name.setText("Latest_Name")
        dialog.save_controls()
        dialog.preview()  # Latest request would otherwise capture raster=False.
        dialog.timer.stop()
        wait_until(lambda: not dialog.host.workers and dialog.host.pending is None)
        image = next(item for item in dialog.view.scene().items() if isinstance(item, QGraphicsPixmapItem))
        assert image.pixmap().toImage() != original
        assert "Latest_Name" in dialog.preview_details.toPlainText()
        dialog.preview()
        dialog.name.setText("Changed_During_Debounce")
        dialog.save_controls()
        dialog.timer.stop()  # Allow the old result to arrive before the next request.
        wait_until(lambda: not dialog.host.workers)
        assert "Latest_Name" not in dialog.preview_details.toPlainText()
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


def test_draw_region_on_empty_canvas_preserves_shared_editor_behavior(qt_application, tmp_path):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    dialog = make_dialog(tmp_path)
    try:
        wait_until(lambda: dialog.source_ready and not dialog.host.workers)
        view = dialog.view
        dialog.add()
        start, end = view.mapFromScene(QPointF(10, 110)), view.mapFromScene(QPointF(45, 135))
        for kind, point in ((QEvent.Type.MouseButtonPress, start), (QEvent.Type.MouseMove, end),
                            (QEvent.Type.MouseButtonRelease, end)):
            event = QMouseEvent(kind, QPointF(point), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            handler = {QEvent.Type.MouseButtonPress: view.mousePressEvent, QEvent.Type.MouseMove: view.mouseMoveEvent,
                       QEvent.Type.MouseButtonRelease: view.mouseReleaseEvent}[kind]
            handler(event)
        assert 30 < dialog.regions[-1]["width_mm"] < 40
        assert 20 < dialog.regions[-1]["height_mm"] < 30
        assert dialog.regions[0]["width_mm"] == 100
        assert dialog.undo.canUndo()
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


@pytest.mark.parametrize("mode, expected", [("First 10", list(range(11, 21))),
                                          ("First 50", list(range(11, 61))), ("Random 50", None)])
def test_samples_stay_inside_selection_and_cannot_masquerade_as_full_export(qt_application, tmp_path, mode, expected):
    from dialogs.quick_text_extractor import QuickTextExtractorDialog
    from workflow.extraction import ExtractionSpec, Region
    source = tmp_path/"sample.pdf"
    with fitz.open() as pdf:
        for number in range(120):
            pdf.new_page().insert_text((30, 70), f"Page {number+1}")
        pdf.save(source)
    spec = ExtractionSpec([Region(name="Page", x_mm=0, y_mm=0, width_mm=150, height_mm=100)])
    dialog = QuickTextExtractorDialog(source, 0, str(tmp_path/"result.xlsx"), spec=spec.to_dict())
    dialog.show()
    try:
        wait_until(lambda: dialog.source_ready and not dialog.host.workers)
        dialog.page_mode.setCurrentText("Custom pages")
        dialog.page_range.setText("11-110")
        dialog.sample_mode.setCurrentText(mode)
        dialog.start_scan(sample=True)
        wait_until(lambda: dialog.result is not None and not dialog.host.workers)
        pages = [row["page"] for row in dialog.model.rows]
        if expected is not None:
            assert pages == expected
        else:
            assert len(pages) == 50 and pages == sorted(set(pages))
            assert all(11 <= p <= 110 for p in pages)
        assert "Sample" in dialog.status.text()
        assert not dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        wait_until(lambda: not dialog.host.workers)


def test_close_can_stop_a_preview_blocked_inside_native_render(qt_application, tmp_path, monkeypatch):
    from composition.designer.process import Worker
    dialog = make_dialog(tmp_path)
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    # A real child process simulates a native raster call which cannot poll the
    # cancellation file. Only previews may be stopped this way, never exports.
    (tmp_path/"blocked_preview.py").write_text(
        "import json,sys,time\nfrom pathlib import Path\n"
        "request=json.loads(Path(sys.argv[1]).read_text())\n"
        "Path(request['started']).write_text('ready')\nwhile True: time.sleep(.05)\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    started = tmp_path/"started"
    def blocked(directory, request, parent):
        assert request["operation"] == "preview"
        return Worker(directory, {**request, "started": str(started)}, parent, worker_module="blocked_preview")
    monkeypatch.setattr("dialogs.quick_text_extractor.Worker", blocked)
    dialog.preview()
    worker = dialog.host.preview_worker
    try:
        wait_until(started.exists)
        dialog.reject()
        wait_until(lambda: not dialog.host.workers, timeout=2000)
        assert not dialog.isVisible()
        assert not dialog.host.directory.exists()
    finally:
        if dialog.host.workers:
            worker.process.kill()
            wait_until(lambda: not dialog.host.workers)


def test_window_close_wakes_paused_search_before_waiting_for_extraction(editor, tmp_path):
    # The real Search shutdown tests cover pause/wakeup. This dependency models
    # that paused state while exercising the actual window + extraction lifecycle.
    class PausedSearch:
        cancelled = False
        def background_task_count(self):
            return 0 if self.cancelled else 1
        def close(self):
            self.cancelled = True
    source = tmp_path/"source.pdf"
    spec = fixture_pdf(source)
    editor._open_in_new_tab_sync(str(source))
    editor._extract_text()
    wait_until(lambda: bool(getattr(editor, "_text_extraction_dialogs", [])))
    dialog = editor._text_extraction_dialogs[0]
    wait_until(lambda: dialog.source_ready and not dialog.host.workers)
    dialog.apply_regions(spec.to_dict()["regions"])
    paused = PausedSearch()
    editor._deep_search_dialog = paused
    editor._close_lifecycle.warning_after_ms = 0  # Simulate the shutdown deadline having elapsed.
    try:
        dialog.start_scan()
        assert dialog.host.workers
        editor.close()
        wait_until(lambda: not editor.isVisible(), timeout=3000)
    finally:
        paused.close()
