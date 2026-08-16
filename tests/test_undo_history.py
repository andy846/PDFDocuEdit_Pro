from __future__ import annotations

from pathlib import Path

from core.undo import UndoStack


def make_file(path: Path, content: str = "state") -> Path:
    path.write_text(content)
    return path


def test_descriptions_and_counts(tmp_path: Path) -> None:
    stack = UndoStack()
    source = make_file(tmp_path / "doc.pdf")

    stack.push(str(source), "Rotate Pages")
    stack.push(str(source), "Delete Pages")
    stack.push(str(source), "Insert Pages")

    assert stack.undo_count == 3
    assert stack.redo_count == 0
    assert stack.undo_descriptions() == ["Rotate Pages", "Delete Pages", "Insert Pages"]
    assert stack.redo_descriptions() == []

    stack.push_redo(str(source), "Insert Pages")
    stack.pop_undo()
    assert stack.undo_descriptions() == ["Rotate Pages", "Delete Pages"]
    assert stack.redo_descriptions() == ["Insert Pages"]
    assert stack.undo_count == 2
    assert stack.redo_count == 1

    stack.push_undo(str(source), "Delete Pages")
    stack.pop_redo()
    assert stack.undo_descriptions() == ["Rotate Pages", "Delete Pages", "Delete Pages"]
    assert stack.redo_descriptions() == []
    assert stack.redo_count == 0


def test_push_clears_redo_history(tmp_path: Path) -> None:
    stack = UndoStack()
    source = make_file(tmp_path / "doc.pdf")
    stack.push(str(source), "A")
    stack.push_redo(str(source), "A")
    stack.pop_undo()
    assert stack.redo_count == 1

    stack.push(str(source), "B")
    assert stack.redo_count == 0
    assert stack.redo_descriptions() == []


def test_clear_resets_everything(tmp_path: Path) -> None:
    stack = UndoStack()
    source = make_file(tmp_path / "doc.pdf")
    stack.push(str(source), "A")
    stack.push(str(source), "B")
    stack.clear()
    assert stack.undo_count == 0
    assert stack.redo_count == 0
    assert stack.undo_descriptions() == []
    assert stack.redo_descriptions() == []
