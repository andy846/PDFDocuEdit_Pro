"""Merge drop responsiveness, background lifecycle and output fidelity."""
from pathlib import Path
from threading import Event, get_ident
from time import monotonic

import fitz
import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QTableWidget, QWidget

from core.tools import ToolError, merge_pdfs
from dialogs.batch_tools import MergePDFDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(predicate):
    end = monotonic() + 10
    while not predicate() and monotonic() < end:
        QTest.qWait(10)
    assert predicate()


def finish(dialog):
    dialog.reject()
    wait(lambda: dialog._metadata_task is None)
    dialog.deleteLater()
    QApplication.processEvents()


def test_18000_network_paths_add_and_reorder_without_io(app, monkeypatch):
    dialog = MergePDFDialog()
    original_stat, original_resolve = Path.stat, Path.resolve
    def guard(original):
        def checked(path, *args, **kwargs):
            if "offline-server" in str(path):
                pytest.fail("Network I/O during drop or reorder")
            return original(path, *args, **kwargs)
        return checked
    monkeypatch.setattr(Path, "resolve", guard(original_resolve))
    monkeypatch.setattr(Path, "stat", guard(original_stat))
    monkeypatch.setattr(fitz, "open", lambda *a, **k: pytest.fail("PDF open during drop"))
    paths = [rf"\\offline-server\share\file-{i}.pdf" for i in range(18000)]
    dialog.add_paths(paths)
    assert dialog.table.model().rowCount() == 18000
    assert not isinstance(dialog.table, QTableWidget)
    assert len(dialog.table.findChildren(QWidget)) < 25
    dialog.table.selectRow(0)
    dialog._move(1)
    assert dialog.file_paths[1].endswith("file-0.pdf")
    assert dialog.table.model().index(1, 2).data() == "Pending…"
    dialog.add_paths(paths)
    assert len(dialog.file_paths) == 18000
    finish(dialog)


def test_slow_metadata_does_not_block_ui_or_update_closed_dialog(app, monkeypatch):
    import dialogs.batch_tools as module
    entered, release = Event(), Event()
    worker_threads = []
    def slow(path):
        worker_threads.append(get_ident())
        entered.set()
        assert release.wait(10)
        return 25, "1.0", "today", ""
    monkeypatch.setattr(module, "read_pdf_detail", slow)
    dialog = MergePDFDialog()
    timer = QTimer()
    beats = []
    timer.timeout.connect(lambda: beats.append(True))
    timer.start(5)
    try:
        dialog.add_paths(["slow.pdf"])
        wait(entered.is_set)
        QTest.qWait(50)
        assert len(beats) >= 3
        assert worker_threads == [worker_threads[0]] and worker_threads[0] != get_ident()
        dialog.reject()
        assert not dialog.isVisible()
        release.set()
        wait(lambda: dialog._metadata_task is None)
        assert not dialog.table.model().details
    finally:
        release.set()
        timer.stop()
        finish(dialog)


def test_removed_metadata_result_cannot_update_another_row(app, monkeypatch):
    import dialogs.batch_tools as module
    entered, release = Event(), Event()
    def slow(path):
        if path.endswith("first.pdf"):
            entered.set()
            assert release.wait(10)
            return 99, "1", "today", ""
        return 2, "1", "today", ""
    monkeypatch.setattr(module, "read_pdf_detail", slow)
    dialog = MergePDFDialog()
    try:
        dialog.add_paths(["first.pdf", "second.pdf"])
        wait(entered.is_set)
        dialog.table.selectRow(0)
        dialog._remove()
        release.set()
        wait(lambda: dialog._read_count == 1)
        assert dialog.table.model().index(0, 2).data() == "2"
        assert dialog._total_pages == 2
    finally:
        release.set()
        finish(dialog)


def test_missing_pdf_is_inline_and_sort_does_not_reread(app, tmp_path, monkeypatch):
    source = tmp_path / "valid.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(source)
    dialog = MergePDFDialog()
    try:
        dialog.add_paths([str(source), str(tmp_path / "missing.pdf")])
        wait(lambda: dialog._read_count == 2)
        assert dialog.table.model().index(1, 2).data() == "Unavailable"
        assert dialog._total_pages == 1
        monkeypatch.setattr(fitz, "open", lambda *a, **k: pytest.fail("sort opened PDF"))
        dialog.table.selectRow(0)
        dialog._move(1)
        assert dialog.table.model().index(1, 2).data() == "1"
    finally:
        finish(dialog)


@pytest.mark.parametrize("compact", [False, True])
def test_merge_preserves_order_links_rotation_and_metadata(tmp_path, compact):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    with fitz.open() as doc:
        for text in ("First", "Second"):
            doc.new_page().insert_text((40, 50), text)
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(40, 40, 100, 60), "page": 1})
        doc[1].set_rotation(90)
        doc.set_metadata({"title": "Merge regression"})
        doc.save(first)
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 50), "Third")
        doc.save(second)
    progress = []
    target = merge_pdfs([first, second], tmp_path / "out.pdf", progress=lambda *v: progress.append(v), compact=compact)
    with fitz.open(target) as doc:
        assert doc.page_count == 3
        assert [page.get_text().strip() for page in doc] == ["First", "Second", "Third"]
        assert doc[0].get_links()[0]["page"] == 1
        assert doc[1].rotation == 90
        assert doc.metadata["title"] == "Merge regression"
    assert any("Saving" in msg for _, _, msg in progress)
    assert any("Validating" in msg for _, _, msg in progress)


def test_cancel_after_save_preserves_destination_and_cleans_staging(tmp_path, monkeypatch):
    source, target = tmp_path / "source.pdf", tmp_path / "out.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(source)
    target.write_bytes(b"existing destination")
    cancelled = Event()
    original = fitz.Document.save
    def save(doc, *args, **kwargs):
        result = original(doc, *args, **kwargs)
        cancelled.set()
        return result
    monkeypatch.setattr(fitz.Document, "save", save)
    with pytest.raises(ToolError, match="cancelled"):
        merge_pdfs([source], target, is_cancelled=cancelled.is_set)
    assert target.read_bytes() == b"existing destination"
    assert set(tmp_path.iterdir()) == {source, target}


def test_corrupt_source_preserves_existing_output(tmp_path):
    source, target = tmp_path / "broken.pdf", tmp_path / "out.pdf"
    source.write_bytes(b"not a PDF")
    target.write_bytes(b"existing destination")
    with pytest.raises(ToolError, match="Cannot read"):
        merge_pdfs([source], target)
    assert target.read_bytes() == b"existing destination"
    assert set(tmp_path.iterdir()) == {source, target}


def test_merge_table_accepts_actual_viewport_drop(app):
    from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    from dialogs.batch_tools import MergeFileTable
    table = MergeFileTable()
    table.show()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(f"C:/synthetic/{i}.pdf") for i in range(1000)])
    dropped = []
    table.filesDropped.connect(dropped.append)
    for event_type, point in ((QDragEnterEvent, QPoint(10, 10)),
                              (QDragMoveEvent, QPoint(10, 10)),
                              (QDropEvent, QPointF(10, 10))):
        event = event_type(point, Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(table.viewport(), event)
        assert event.isAccepted()
    assert len(dropped) == 1 and len(dropped[0]) == 1000
    table.close()
    table.deleteLater()
