import os
import sys
from dataclasses import replace
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
)

from core.io_atomic import atomic_output
from core.page_plan import PagePlanEntry, PlanReader, apply_plan_to_document, duplicate_entries, export_plan
from core.pdf_engine import PdfEngine
from core.undo import UndoStack
from dialogs.document_dialogs import VisualOrganizerDialog
from dialogs.organizer_tools import (
    BlankPagesDialog,
    InterleaveDialog,
    JobDialog,
    OrganizerWorker,
    SplitPlanDialog,
)


def make_pdf(path, layers=False, password=None):
    with fitz.open() as doc:
        for i in range(3):
            doc.new_page().insert_text((72, 80), f"Page {i + 1}")
        if layers:
            for visible in (True, False):
                layer = doc.add_ocg("Same name", on=visible)
                doc[0].insert_text((72, 160 if visible else 220), "Visible" if visible else "Hidden", oc=layer)
        options = {"encryption": fitz.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": password} if password else {}
        doc.save(path, **options)
    return path


@pytest.mark.parametrize("external", [False, True])
def test_layered_sources_duplicate_import_and_exports_match_preview(tmp_path, external):
    source = make_pdf(tmp_path / "layers.pdf", layers=True)
    with fitz.open(source) as original:
        original_bytes = original.tobytes(no_new_id=True)
        with fitz.open(stream=original_bytes, filetype="pdf") as current, PlanReader(original) as reader:
            entry = PagePlanEntry("source", "external" if external else "current", 0,
                                  str(source) if external else "")
            duplicate = replace(duplicate_entries([entry])[0], final_rotation=90)
            plan = [entry, duplicate]
            expected = [reader.render(p, 600).samples for p in plan]
            with fitz.open() as copy:
                reader.append(copy, entry)
            assert original.tobytes(no_new_id=True) == original_bytes
            apply_plan_to_document(current, plan)
            for page, pixels in zip(current, expected, strict=True):
                scale = 600 / max(page.rect.width, page.rect.height)
                assert page.get_pixmap(matrix=fitz.Matrix(scale, scale)).samples == pixels
            assert sorted(g["on"] for g in current.get_ocgs().values()).count(False) >= 1
            result = export_plan(original_bytes, [(tmp_path / "export.pdf", plan)])
            assert not result.error
            with fitz.open(tmp_path / "export.pdf") as output:
                for page, pixels in zip(output, expected, strict=True):
                    scale = 600 / max(page.rect.width, page.rect.height)
                    assert page.get_pixmap(matrix=fitz.Matrix(scale, scale)).samples == pixels
                tags = [output.xref_get_key(i, "OrganizerOCG")[1] for i in output.get_ocgs()
                            if output.xref_get_key(i, "OrganizerOCG")[0] == "string"]
                assert len(tags) == len(set(tags))


def test_noop_apply_preserves_modified_flag_revision_and_history(tmp_path):
    path = make_pdf(tmp_path / "source.pdf")
    stack = UndoStack()
    engine = PdfEngine(on_commit=stack.push_bytes)
    engine.open(path)
    try:
        plan = [PagePlanEntry(str(i), "current", i) for i in range(3)]
        with engine.mutation_transaction("No change"):
            engine.apply_page_plan(plan)
        assert not engine.is_modified and engine.revision == 0 and stack.undo_count == 0
    finally:
        engine.close()
        stack.clear()


def test_atomic_export_does_not_overwrite_file_created_at_commit(tmp_path, monkeypatch):
    target = tmp_path / "race.pdf"
    name = "rename" if os.name == "nt" else "link"
    commit = getattr(os, name)

    def race(source, destination):
        target.write_bytes(b"Other writer")
        return commit(source, destination)

    monkeypatch.setattr(os, name, race)
    with pytest.raises(FileExistsError), atomic_output(target, overwrite=False) as staged:
        staged.write_bytes(b"Export")
    assert target.read_bytes() == b"Other writer"
    assert list(tmp_path.iterdir()) == [target]


def test_custom_blank_numbers_are_the_actual_output_dimensions():
    app = QApplication.instance() or QApplication([])
    dialog = BlankPagesDialog((300, 500))
    dialog.paper.setCurrentIndex(3)
    dialog.width_mm.setValue(100)
    dialog.height_mm.setValue(140)
    dialog.orientation.setCurrentIndex(1)
    assert (dialog.width_mm.value(), dialog.height_mm.value()) == (140, 100)
    dialog.width_mm.setValue(90)
    assert dialog.orientation.currentIndex() == 0
    assert dialog.page_size() == pytest.approx((90 * 72 / 25.4, 100 * 72 / 25.4))
    dialog.close()
    app.processEvents()


def test_large_progress_and_invalid_split_state():
    app = QApplication.instance() or QApplication([])
    worker = OrganizerWorker(lambda **kwargs: None)
    progress = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.progress.emit(2**32, 2**33)
    assert progress == [(2**32, 2**33)]
    job = JobDialog("Large import", lambda **kwargs: None, None)
    job._progress(*progress[0])
    assert job.bar.value() == 500
    job.close()
    split = SplitPlanDialog([PagePlanEntry("one", "current", 0)])
    assert split.groups and split._validation.isHidden()
    split.prefix.setText("bad\x01name")
    assert not split.ok.isEnabled() and split.groups == [] and split.model.rowCount() == 0
    split.close()
    app.processEvents()


@pytest.mark.parametrize("action", ["Insert", "Replace", "Interleave", "Extract", "Split"])
def test_real_organizer_buttons_and_option_dialogs(tmp_path, monkeypatch, action):
    app = QApplication.instance() or QApplication([])
    errors, messages = [], []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    current_path = make_pdf(tmp_path / "current.pdf")
    external = make_pdf(tmp_path / "external.pdf", password="secret")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kw: (str(external), ""))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kw: ("secret" if args[1] == "Encrypted source PDF" else "1-2", True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kw: (str(tmp_path / "extract.pdf"), ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kw: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    with fitz.open(current_path) as doc:
        organizer = VisualOrganizerDialog(doc)
        organizer.show()
        app.processEvents()
        organizer._select_expression("1")
        before = organizer.pages.page_plan()

        def complete_options():
            modal = app.activeModalWidget()
            if not isinstance(modal, (InterleaveDialog, SplitPlanDialog)):
                return
            try:
                if isinstance(modal, InterleaveDialog):
                    modal.first.setCurrentIndex(1)
                    modal.reverse_b.setChecked(True)
                    modal.remainder.setCurrentIndex(1)
                else:
                    modal.mode.setCurrentIndex(1)
                    modal.interval.setValue(2)
                    assert modal.model.rowCount() == 2
                QTest.mouseClick(modal.ok, Qt.MouseButton.LeftButton)
            except Exception as exc:
                errors.append(exc)
                modal.reject()

        timer = QTimer()
        timer.timeout.connect(complete_options)
        timer.start(20)
        try:
            button = next(b for b in organizer.findChildren(QPushButton) if b.text() == action)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        finally:
            timer.stop()
        assert not errors, errors
        assert organizer._validation.isHidden(), organizer._validation.text()
        if action in {"Extract", "Split"}:
            assert messages and "Completed" in messages[-1]
            assert organizer.pages.page_plan() == before
        else:
            assert organizer.pages.count() == {"Insert": 5, "Replace": 4, "Interleave": 6}[action]
            organizer._undo()
            assert organizer.pages.page_plan() == before
            organizer._redo()
        assert doc.page_count == 3
        organizer.reject()


def test_cancelled_source_selection_discards_snapshot(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = make_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kw: ("", False))
    with fitz.open(path) as doc:
        organizer = VisualOrganizerDialog(doc)
        assert organizer._source_entries() == []
        assert list(Path(organizer.sources.temporary.name).iterdir()) == []
        organizer.reject()
    app.processEvents()


def test_button_failure_shows_error_instead_of_escaping_qt(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: errors.append(args))
    path = make_pdf(tmp_path / "source.pdf")
    with fitz.open(path) as doc:
        organizer = VisualOrganizerDialog(doc)
        organizer._select_expression("1")
        before = organizer.pages.page_plan()

        def failed(*args):
            raise RuntimeError("Cannot render source")

        monkeypatch.setattr(organizer.pages.reader, "render", failed)
        button = next(b for b in organizer.findChildren(QPushButton) if b.text() == "Crop")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert not errors and "Cannot render source" in organizer._validation.text()
        assert organizer.pages.page_plan() == before
        organizer.reject()
    app.processEvents()
