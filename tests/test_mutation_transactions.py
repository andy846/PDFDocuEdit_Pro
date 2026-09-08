from pathlib import Path

import fitz
import pytest

from core.pdf_engine import PdfEngine, PdfEngineError
from core.undo import UndoStack


@pytest.fixture
def document(tmp_path):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for number in range(3):
            doc.new_page().insert_text((72, 72), f"Page {number}")
        doc.save(source)
    stack = UndoStack()
    engine = PdfEngine(on_commit=stack.push_bytes)
    engine.open(source)
    yield engine, stack, source
    engine.close()
    stack.clear()


def test_nested_action_commits_once_with_live_unsaved_state(document):
    engine, stack, _ = document
    engine.rotate_pages([0], 90)
    revision = engine.revision
    with engine.mutation_transaction("Combined"):
        engine.rotate_pages([1], 90)
        with engine.mutation_transaction("Inner"):
            engine.delete_pages([2])
    assert engine.page_count == 2
    assert engine.revision == revision + 1
    assert stack.undo_descriptions() == ["Combined"]
    path = stack.pop_undo()
    try:
        with fitz.open(path) as before:
            assert before.page_count == 3
            assert [page.rotation for page in before] == [90, 0, 0]
        assert stack.restored_modified
    finally:
        path.unlink()


@pytest.mark.parametrize("swallow", [False, True])
def test_failure_restores_content_context_and_history(document, swallow):
    engine, stack, source = document
    stack.push_redo(str(source), "Existing redo")
    engine.rotate_pages([0], 90)
    state = (engine.revision, engine.document_id, engine.original_path,
             engine.temp_path, engine.is_modified, engine._requires_full_save)
    with pytest.raises(PdfEngineError, match="restored"):
        with engine.mutation_transaction("Failed"):
            engine.delete_pages([2])
            try:
                with engine.mutation_transaction("Nested"):
                    engine.rotate_pages([1], 90)
                    raise ValueError("injected")
            except ValueError:
                if not swallow:
                    raise
    assert engine.page_count == 3
    assert [page.rotation for page in engine.document] == [90, 0, 0]
    assert state == (engine.revision, engine.document_id, engine.original_path,
                     engine.temp_path, engine.is_modified, engine._requires_full_save)
    assert stack.undo_count == 0
    assert stack.redo_descriptions() == ["Existing redo"]
    with engine.mutation_transaction("Retry"):
        engine.rotate_pages([1], 90)
    assert stack.undo_descriptions() == ["Retry"]
    assert not stack.can_redo


def test_caught_engine_failure_poisons_transaction(document):
    engine, stack, _ = document
    with pytest.raises(PdfEngineError, match="restored"):
        with engine.mutation_transaction("Failed"):
            engine.rotate_pages([0], 90)
            try:
                engine.delete_pages([0, 1, 2])
            except PdfEngineError:
                pass
    assert engine.document[0].rotation == 0
    assert not engine.is_modified
    assert not stack.can_undo


def test_snapshot_storage_failure_rolls_back_and_keeps_redo(document, monkeypatch):
    engine, stack, source = document
    stack.push_redo(str(source), "Existing")
    write = Path.write_bytes
    def fail(path, data):
        if path.name.startswith(".undo-"):
            raise OSError("disk full")
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(PdfEngineError, match="restored"):
        with engine.mutation_transaction("Rotate"):
            engine.rotate_pages([0], 90)
    assert engine.document[0].rotation == 0
    assert not engine.is_modified
    assert engine.revision == 0
    assert not stack.can_undo
    assert stack.redo_descriptions() == ["Existing"]


def test_noop_keeps_history_and_revision(document):
    engine, stack, source = document
    stack.push_redo(str(source), "Existing")
    with engine.mutation_transaction("No change"):
        engine.rotate_pages([0], 360)
        engine.delete_pages([])
        engine.reorder_pages([0, 1, 2])
    assert not stack.can_undo
    assert stack.can_redo
    assert not engine.is_modified
    assert engine.revision == 0


@pytest.mark.parametrize("operation", ["save", "open", "close"])
def test_document_lifecycle_is_excluded(document, operation):
    engine, stack, source = document
    with pytest.raises(PdfEngineError, match="restored"):
        with engine.mutation_transaction("Invalid"):
            engine.rotate_pages([0], 90)
            if operation == "open":
                engine.open(source)
            else:
                getattr(engine, operation)()
    assert engine.document[0].rotation == 0
    assert not stack.can_undo
    with fitz.open(source) as disk:
        assert disk[0].rotation == 0


def test_repeat_insert_partial_failure_rolls_back(document, monkeypatch):
    engine, stack, source = document
    insert = fitz.Document.insert_pdf
    calls = 0
    def fail(doc, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("insert failed")
        return insert(doc, *args, **kwargs)
    monkeypatch.setattr(fitz.Document, "insert_pdf", fail)
    with pytest.raises(PdfEngineError, match="restored"):
        with engine.mutation_transaction("Repeat"):
            engine.repeat_insert_pages(str(source), [0], 1)
    assert engine.page_count == 3
    assert not stack.can_undo
    assert not engine.is_modified
