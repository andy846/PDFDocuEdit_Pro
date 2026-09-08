import time
from threading import Event

import fitz
import pytest
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import ui.print_controller as controller_module
from core.printing import PrintJob, PrintRenderSettings, prepare_print_job
from core.tasks import TaskCancelled
from ui.print_controller import PrintController

_app = None


def app():
    global _app
    _app = QApplication.instance() or QApplication(["print-controller-tests"])
    return _app


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert predicate(), "Timed out waiting for print controller"


def pdf(path, pages=2):
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page(width=200, height=300)
            page.insert_text((20, 30), f"Page {index}")
        doc.save(path)
    return path


def settings(_printer):
    return PrintRenderSettings(72, 200, 300, 0, 0, 0, 100, True, 0, 0)


def printer_factory(tmp_path, seen):
    def create(job, _prepared):
        assert QThread.currentThread() == app().thread()
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(72)
        printer.setDocName(job.name)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(tmp_path / f"printed-{job.name}"))
        seen.append(job.key)
        return printer
    return create


def test_prepare_preserves_snapshot_order_and_duplicates(tmp_path):
    source = pdf(tmp_path / "source.pdf", 3)
    with fitz.open(source) as doc:
        doc[0].insert_text((20, 60), "unsaved edit")
        snapshot = doc.tobytes()
    prepared = prepare_print_job(PrintJob(snapshot, "job", "job", (2, 0, 2)))
    assert prepared.pages == (2, 0, 2)
    with fitz.open(stream=prepared.data, filetype="pdf") as result:
        assert "unsaved edit" in result[0].get_text()
    cancelled = Event()
    cancelled.set()
    with pytest.raises(TaskCancelled):
        prepare_print_job(PrintJob(snapshot, "job", "job"), is_cancelled=cancelled.is_set)


def test_render_worker_cancel_keeps_gui_responsive_and_does_not_spool(tmp_path, monkeypatch):
    application = app()
    entered, release = Event(), Event()
    ticks = []
    timer = QTimer()
    timer.setInterval(2)
    timer.timeout.connect(lambda: ticks.append(1))
    real_render = controller_module.render_print_page

    def slow_render(*args, **kwargs):
        assert QThread.currentThread() != application.thread()
        entered.set()
        assert release.wait(5)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(controller_module, "render_print_page", slow_render)
    seen, finished, statuses = [], [], []
    controller = PrintController([PrintJob(str(pdf(tmp_path / "source.pdf")), "job.pdf", "job")],
                                 printer_factory(tmp_path, seen), settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.file_finished.connect(lambda *value: statuses.append(value))
    timer.start()
    controller.start()
    try:
        wait_for(lambda: entered.is_set() and len(ticks) >= 3)
        controller.cancel()
        assert not finished  # cleanup waits for the in-flight worker
        release.set()
        wait_for(lambda: bool(finished))
        assert finished == [(0, 0, 0, True)]
        assert statuses == [("job", "cancelled", "")]
        assert not (tmp_path / "printed-job.pdf").exists()
        assert controller._task is None and controller._prepared is None
    finally:
        release.set()
        timer.stop()
        controller.cancel()
        wait_for(lambda: bool(finished))
        controller.deleteLater()
        QTest.qWait(1)


def test_render_failure_skips_bad_input_then_continues_next_file(tmp_path, monkeypatch):
    app()
    first = pdf(tmp_path / "first.pdf")
    second = pdf(tmp_path / "second.pdf", 1)
    real_render = controller_module.render_print_page
    worker_threads = []

    def fail_second_page(prepared, index, config, **kwargs):
        worker_threads.append(QThread.currentThread() != app().thread())
        if index == 1:
            raise RuntimeError("injected raster failure")
        return real_render(prepared, index, config, **kwargs)

    monkeypatch.setattr(controller_module, "render_print_page", fail_second_page)
    seen, finished, statuses = [], [], []
    jobs = [PrintJob(str(tmp_path / "missing.pdf"), "missing.pdf", "missing"),
            PrintJob(str(first), "first.pdf", "first"),
            PrintJob(str(second), "second.pdf", "second")]
    controller = PrintController(jobs, printer_factory(tmp_path, seen), settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.file_finished.connect(lambda *value: statuses.append(value))
    controller.start()
    wait_for(lambda: bool(finished))
    assert finished == [(1, 1, 1, False)]
    assert [value[1] for value in statuses] == ["skipped", "failed", "sent"]
    assert all(worker_threads)
    assert seen == ["first", "second"]
    with fitz.open(tmp_path / "printed-second.pdf") as output:
        assert output.page_count == 1
    assert controller._painter is None and controller._prepared is None
    controller.deleteLater()
    QTest.qWait(1)


def test_cancel_during_preparation_marks_file_and_releases_worker(tmp_path, monkeypatch):
    app()
    entered, release = Event(), Event()
    real_prepare = controller_module.prepare_print_job

    def slow_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(controller_module, "prepare_print_job", slow_prepare)
    finished, statuses, seen = [], [], []
    controller = PrintController([PrintJob(str(pdf(tmp_path / "source.pdf")), "job.pdf", "job")],
                                 printer_factory(tmp_path, seen), settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.file_finished.connect(lambda *value: statuses.append(value))
    controller.start()
    try:
        wait_for(entered.is_set)
        controller.cancel()
        release.set()
        wait_for(lambda: bool(finished))
        assert statuses == [("job", "cancelled", "")]
        assert not seen
        assert finished == [(0, 0, 0, True)]
    finally:
        release.set()
        controller.cancel()
        wait_for(lambda: bool(finished))
        controller.deleteLater()
        QTest.qWait(1)


def test_native_dialog_cancel_does_not_start_a_printer_job(tmp_path):
    app()
    finished = []
    def cancelled_dialog(*_):
        raise TaskCancelled
    controller = PrintController([PrintJob(str(pdf(tmp_path / "source.pdf")), "job", "job")],
                                 cancelled_dialog, settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.start()
    wait_for(lambda: bool(finished))
    assert finished == [(0, 0, 0, True)]
    assert controller._painter is None
    controller.deleteLater()
    QTest.qWait(1)


def test_printer_page_failure_releases_painter(tmp_path):
    app()
    class FailingPrinter(QPrinter):
        def newPage(self):
            return False
    def create(job, _prepared):
        assert QThread.currentThread() == app().thread()
        printer = FailingPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(72)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(tmp_path / "partial.pdf"))
        return printer
    finished, statuses = [], []
    controller = PrintController([PrintJob(str(pdf(tmp_path / "source.pdf")), "job", "job")],
                                 create, settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.file_finished.connect(lambda *value: statuses.append(value))
    controller.start()
    wait_for(lambda: bool(finished))
    assert finished == [(0, 1, 0, False)]
    assert statuses[0][1] == "failed"
    assert "next page" in statuses[0][2]
    assert controller._painter is None
    with fitz.open(tmp_path / "partial.pdf") as output:
        assert output.page_count == 1
    controller.deleteLater()
    QTest.qWait(1)


def test_cancel_before_start_does_not_prepare_or_create_printer(tmp_path):
    app()
    def must_not_run(*_):
        pytest.fail("A cancelled job must not create a printer")
    finished = []
    controller = PrintController([PrintJob("missing.pdf", "job", "job")], must_not_run, settings)
    controller.finished.connect(lambda *value: finished.append(value))
    controller.cancel()
    controller.start()
    wait_for(lambda: bool(finished))
    assert finished == [(0, 0, 0, True)]
    assert controller._task is None
    with pytest.raises(RuntimeError, match="already started"):
        controller.start()
    controller.deleteLater()
    QTest.qWait(1)
