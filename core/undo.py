"""Lightweight undo/redo system based on document snapshots."""

from __future__ import annotations

import os
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

MAX_UNDO_DEPTH = 20


@dataclass
class _Snapshot:
    """A saved document state as a temporary PDF file."""

    path: Path
    description: str

    def cleanup(self) -> None:
        self.path.unlink(missing_ok=True)


class UndoStack(QObject):
    """Manages undo/redo snapshots for a PDF document.

    Each snapshot is a full temp-file copy of the document taken *before*
    a destructive operation. To undo, the viewer re-opens the snapshot.
    """

    changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._undo: deque[_Snapshot] = deque(maxlen=MAX_UNDO_DEPTH)
        self._redo: list[_Snapshot] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def undo_descriptions(self) -> list[str]:
        """Descriptions from oldest to newest (stack bottom to top)."""
        return [snapshot.description for snapshot in self._undo]

    def redo_descriptions(self) -> list[str]:
        """Descriptions in redo order (first undone action first)."""
        return [snapshot.description for snapshot in self._redo]

    @property
    def undo_description(self) -> str:
        return self._undo[-1].description if self._undo else ""

    @property
    def redo_description(self) -> str:
        return self._redo[-1].description if self._redo else ""

    def push(self, source_path: str, description: str) -> None:
        """Copy the current document file as a snapshot before a change."""
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".undo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            return
        snapshot = _Snapshot(path=Path(temp_name), description=description)
        self._undo.append(snapshot)
        self._clear_redo()
        self.changed.emit()

    def pop_undo(self) -> Path | None:
        """Pop the most recent snapshot. Caller must push current state to redo first."""
        if not self._undo:
            return None
        snapshot = self._undo.pop()
        self.changed.emit()
        return snapshot.path

    def pop_redo(self) -> Path | None:
        """Pop the most recent redo snapshot. Caller must push current state to undo first."""
        if not self._redo:
            return None
        snapshot = self._redo.pop()
        self.changed.emit()
        return snapshot.path

    def push_redo(self, source_path: str, description: str) -> None:
        """Save the current document to the redo stack."""
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".redo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            return
        self._redo.append(_Snapshot(path=Path(temp_name), description=description))
        self.changed.emit()

    def push_undo(self, source_path: str, description: str) -> None:
        """Save the current document to the undo stack (used during redo)."""
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".undo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            return
        self._undo.append(_Snapshot(path=Path(temp_name), description=description))
        self.changed.emit()

    def _clear_redo(self) -> None:
        for snapshot in self._redo:
            snapshot.cleanup()
        self._redo.clear()

    def clear(self) -> None:
        for snapshot in self._undo:
            snapshot.cleanup()
        self._undo.clear()
        self._clear_redo()
        self.changed.emit()
