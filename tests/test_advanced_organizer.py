from dataclasses import replace
from pathlib import Path

import fitz
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from core.page_plan import (
    POINTS_PER_MM,
    PagePlanEntry,
    PlanReader,
    SourceStore,
    apply_plan_to_document,
    blank_entry,
    crop_entries,
    duplicate_entries,
    export_plan,
    interleave_entries,
    parse_page_selection,
    reverse_selected,
)
from dialogs.document_dialogs import VisualOrganizerDialog
from dialogs.organizer_tools import CropDialog, SplitPlanDialog


def document(count=4):
    doc = fitz.open()
    for i in range(count):
        page = doc.new_page(width=400 + i * 10, height=600)
        page.insert_text((100, 200), f"Page {i + 1}")
        page.draw_rect(fitz.Rect(60, 80, 160, 130), fill=(1, 0, 0))
    return doc


def entries(doc):
    return [PagePlanEntry(str(i), "current", i, final_rotation=p.rotation) for i, p in enumerate(doc)]


@pytest.mark.parametrize("expression,count,expected", [
    ("1-3,5,2", 6, [0, 1, 2, 4]), (" ODD , even", 5, list(range(5))),
    ("every 4th page", 10, [3, 7]), ("EVERY 2 pages,1", 5, [0, 1, 3]),
    ("last 10 pages", 3, [0, 1, 2]), ("last 2 pages", 5, [3, 4]),
    ("all", 0, []), ("even", 1, []), ("", 4, []),
    ("1-10,15,20-30", 30, list(range(10)) + [14] + list(range(19, 30))),
])
def test_selection(expression, count, expected):
    assert parse_page_selection(expression, count) == expected


@pytest.mark.parametrize("expression", ["0", "6", "1-6", "every 0 pages", "last 0 pages", "odd,", "foo", "1,,2", "1.5"])
def test_invalid_selection(expression):
    with pytest.raises(ValueError):
        parse_page_selection(expression, 5)


@pytest.mark.parametrize("first,reverse,pad", [(f, r, p) for f in (False, True) for r in (False, True) for p in (False, True)])
def test_interleave(first, reverse, pad):
    with document(5) as doc, PlanReader(doc) as reader:
        a, b = entries(doc)[:3], entries(doc)[3:]
        plan = interleave_entries(a, b, b_first=first, reverse_b=reverse, pad=pad, size_of=reader.size)
        expected_b = list(reversed(b)) if reverse else b
        assert plan[:2] == ([expected_b[0], a[0]] if first else [a[0], expected_b[0]])
        assert len(plan) == (6 if pad else 5)
        assert len({p.entry_id for p in plan}) == len(plan)
        if pad:
            blank = next(p for p in plan if p.source_kind == "blank")
            assert reader.size(blank) == reader.size(a[-1])


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_rotation_offset_and_export_parity(tmp_path, rotation):
    with document(2) as doc:
        doc[0].set_cropbox(fitz.Rect(20, 30, 380, 560))
        doc[0].set_rotation(rotation)
        original = doc.tobytes()
        with PlanReader(doc) as reader:
            plan = entries(doc)
            copy = duplicate_entries(plan[:1])[0]
            plan.append(copy)
            cropped = crop_entries(plan, [0], (2, 3, 4, 5), reader)
            assert cropped[2] == copy and copy.crop_box is None
            w, h = reader.size(plan[0])
            cw, ch = reader.size(cropped[0])
            assert cw == pytest.approx(w - 6 * POINTS_PER_MM)
            assert ch == pytest.approx(h - 8 * POINTS_PER_MM)
            preview = reader.render(cropped[0], 400)
            cropped.append(blank_entry(220, 330))
        full = tmp_path / "extract.pdf"
        parts = [(tmp_path / f"part{i}.pdf", [entry]) for i, entry in enumerate(cropped)]
        result = export_plan(original, [(full, cropped)] + parts)
        assert not result.error
        apply_plan_to_document(doc, cropped)
        with fitz.open(full) as extracted:
            for i, page in enumerate(doc):
                with fitz.open(parts[i][0]) as split:
                    assert page.get_pixmap().samples == extracted[i].get_pixmap().samples == split[0].get_pixmap().samples
            scale = 400 / max(doc[0].rect.width, doc[0].rect.height)
            assert preview.samples == doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale)).samples
        assert doc[2].cropbox == fitz.Rect(20, 30, 380, 560)


def test_crop_batch_rejects_all_problem_pages():
    with document(3) as doc, PlanReader(doc) as reader:
        plan = entries(doc)
        with pytest.raises(ValueError, match="1, 2, 3"):
            crop_entries(plan, range(3), (1000, 0, 0, 0), reader)
        assert all(p.crop_box is None for p in plan)


def test_encrypted_snapshot_stable_and_cancelled(tmp_path):
    source = tmp_path / "encrypted.pdf"
    with document(2) as doc:
        doc.save(source, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    store = SourceStore()
    try:
        with pytest.raises(ValueError):
            store.snapshot(str(source), "wrong")
        snap, rotations = store.snapshot(str(source), "secret")
        source.write_bytes(b"changed after import")
        with document(1) as current, PlanReader(current) as reader:
            entry = PagePlanEntry("external", "external", 1, snap, rotations[1], "secret")
            assert reader.source(entry)[1].get_text().strip() == "Page 2"
        with pytest.raises(InterruptedError):
            store.snapshot(snap, "secret", cancelled=lambda: True)
        assert len(list(Path(store.temporary.name).iterdir())) == 1
    finally:
        store.close()
    assert not Path(snap).exists()


def test_export_protection_cancel_and_partial_failure(tmp_path):
    with document(2) as doc:
        plan, data = entries(doc), doc.tobytes()
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    result = export_plan(data, [(first, plan)], protected=[first])
    assert result.error and not first.exists()
    result = export_plan(data, [(first, plan), (second, [replace(plan[0], source_page=100)])])
    assert result.completed == [first] and result.error and not second.exists()
    old = first.read_bytes()
    assert export_plan(data, [(first, plan)]).error
    assert first.read_bytes() == old
    cancelled = False

    def progress(done, total):
        nonlocal cancelled
        cancelled = done == 1000

    first.unlink()
    result = export_plan(data, [(first, plan), (second, plan)], cancelled=lambda: cancelled, progress=progress)
    # Cancellation at an assembly checkpoint commits no incomplete PDF.
    assert result.cancelled and not second.exists()


def test_organizer_history_selection_cancel_and_lazy_thumbnails():
    app = QApplication.instance() or QApplication([])
    with document(80) as doc:
        before = doc.tobytes(no_new_id=True)
        dialog = VisualOrganizerDialog(doc)
        dialog.show()
        app.processEvents()
        assert len(dialog.pages._thumb_queue) < 30
        dialog._select_expression("1,3")
        dialog._reverse()
        assert dialog.pages.order()[:4] == [2, 1, 0, 3]
        dialog._select_expression("1")
        assert dialog.pages.selected_widgets()[0].entry.source_page == 2
        dialog._select_expression("1000")
        assert dialog.pages.selected_positions() == [0]
        dialog._duplicate()
        dialog._rotate_selected(90)
        assert dialog.pages.page_plan()[0].final_rotation == 0
        dialog._undo()
        assert dialog.pages.page_plan()[1].final_rotation == 0
        dialog._redo()
        assert dialog.pages.page_plan()[1].final_rotation == 90
        dialog.reject()
        assert doc.tobytes(no_new_id=True) == before


def test_crop_drag_and_split_preview():
    app = QApplication.instance() or QApplication([])
    with document(5) as doc, PlanReader(doc) as reader:
        plan = entries(doc)
        dialog = CropDialog(plan, [0, 1], reader)
        dialog.show()
        app.processEvents()
        rect = dialog.canvas.image_rect()
        start = rect.topLeft() + (rect.bottomRight() - rect.topLeft()) * 0.1
        end = rect.topLeft() + (rect.bottomRight() - rect.topLeft()) * 0.9
        QTest.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseRelease(dialog.canvas, Qt.MouseButton.LeftButton, pos=end.toPoint())
        assert dialog.inputs[0].value() == pytest.approx(400 / POINTS_PER_MM * .1, abs=.5)
        dialog.inputs[0].setValue(5)
        assert dialog.canvas.margins[0] == 5
        dialog._apply()
        assert dialog.plan[0].crop_box is not None
        split = SplitPlanDialog(plan)
        split.mode.setCurrentIndex(1)
        split.interval.setValue(2)
        assert [len(p) for _, p in split.groups] == [2, 2, 1]
        split.mode.setCurrentIndex(2)
        split.points.setText("1,4")
        assert [len(p) for _, p in split.groups] == [1, 3, 1]
        split.points.setText("6")
        assert not split.ok.isEnabled()
        split.close()


def test_reverse_selected_slots():
    with document(5) as doc:
        plan = entries(doc)
        result = reverse_selected(plan, [0, 2, 4])
        assert [p.source_page for p in result] == [4, 1, 2, 3, 0]


def test_bookmarks_annotations_and_transaction_rollback(tmp_path):
    from core.pdf_engine import PdfEngine, PdfEngineError
    from core.undo import UndoStack

    source = tmp_path / "original.pdf"
    with document(3) as doc:
        doc.set_toc([[1, "First", 1], [1, "Third", 3]])
        doc[0].add_text_annot((100, 100), "Keep annotation")
        doc.save(source)
    stack = UndoStack()
    engine = PdfEngine(on_commit=stack.push_bytes)
    engine.open(source)
    try:
        plan = entries(engine.document)
        plan = [plan[2], plan[0], duplicate_entries(plan[:1])[0], blank_entry(200, 300)]
        with engine.mutation_transaction("Organize Pages"):
            engine.apply_page_plan(plan)
        assert stack.undo_descriptions() == ["Organize Pages"]
        assert engine.document.get_toc() == [[1, "First", 2], [1, "Third", 1]]
        assert [len(list(p.annots() or [])) for p in engine.document] == [0, 1, 1, 0]
        before = [(p.get_text(), tuple(p.cropbox), p.rotation) for p in engine.document]
        bad = entries(engine.document)
        bad[-1] = replace(bad[-1], crop_box=(0, 0, 9999, 9999))
        with pytest.raises(PdfEngineError, match="restored"):
            with engine.mutation_transaction("Bad crop"):
                engine.apply_page_plan(bad)
        assert [(p.get_text(), tuple(p.cropbox), p.rotation) for p in engine.document] == before
        assert stack.undo_count == 1
    finally:
        engine.close()
        stack.clear()


def test_cancel_after_first_split_keeps_completed_file(tmp_path):
    with document(2) as doc:
        data, plan = doc.tobytes(), entries(doc)
    first, second = tmp_path / "one.pdf", tmp_path / "two.pdf"
    result = export_plan(data, [(first, plan[:1]), (second, plan[1:])], cancelled=first.exists)
    assert result.cancelled and result.completed == [first]
    assert first.exists() and not second.exists()
