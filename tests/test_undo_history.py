from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize("direction", ["undo", "redo"])
@pytest.mark.parametrize("failure", ["write", "return", "raise"])
def test_failed_restore_preserves_both_stacks(tmp_path, monkeypatch, direction, failure):
    stack = UndoStack()
    source = make_file(tmp_path / "state.pdf")
    stack.push(str(source), "Undo action", modified=False)
    stack.push_redo(str(source), "Redo action", modified=True)
    before = (stack.undo_descriptions(), stack.redo_descriptions(), stack.restored_modified)
    targets = [snapshot.path for snapshot in [*stack._undo, *stack._redo]]
    staged = []
    write = Path.write_bytes
    calls = []
    def save(path, data):
        if path.name.startswith(".history-"):
            staged.append(path)
            if failure == "write":
                raise OSError("disk full")
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", save)
    def apply(path, modified):
        calls.append(path)
        assert path.exists()
        assert before == (stack.undo_descriptions(), stack.redo_descriptions(), stack.restored_modified)
        if failure == "raise":
            raise RuntimeError("open failed")
        return False
    try:
        if failure == "return":
            assert not stack.restore(direction, b"live", modified=True, apply=apply)
        else:
            with pytest.raises((OSError, RuntimeError)):
                stack.restore(direction, b"live", modified=True, apply=apply)
        assert before == (stack.undo_descriptions(), stack.redo_descriptions(), stack.restored_modified)
        assert all(path.exists() for path in targets)
        assert staged and not any(path.exists() for path in staged)
        assert len(calls) == (0 if failure == "write" else 1)
    finally:
        stack.clear()


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_successful_restore_commits_once_and_rejects_reentrant_changes(tmp_path, direction):
    stack = UndoStack()
    source = make_file(tmp_path / "state.pdf", "target")
    if direction == "undo":
        stack.push(str(source), "Action", modified=False)
    else:
        stack.push_redo(str(source), "Action", modified=False)
    events = []
    stack.changed.connect(lambda: events.append(True))
    consumed = []
    def apply(path, modified):
        assert path.read_text() == "target"
        assert not modified
        consumed.append(path)
        with pytest.raises(RuntimeError, match="during a restore"):
            stack.clear()
        return True
    try:
        assert stack.restore(direction, b"unsaved live", modified=True, apply=apply)
        assert events == [True]
        assert not consumed[0].exists()
        opposite = stack._redo if direction == "undo" else stack._undo
        assert opposite[-1].path.read_bytes() == b"unsaved live"
        assert opposite[-1].modified
        assert not stack.restored_modified
    finally:
        stack.clear()
