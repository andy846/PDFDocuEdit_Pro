"""Lightweight undo/redo system based on document snapshots."""

from __future__ import annotations

import logging
import os
import tempfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.diagnostics import log_failure

MAX_UNDO_DEPTH = 20


@dataclass
class _Snapshot:
    """A saved document state as a temporary PDF file."""

    path: Path
    description: str
    modified: bool = False

    def cleanup(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).warning("Cannot remove undo snapshot %s", self.path, exc_info=True)


class UndoStack(QObject):
    """Manages undo/redo snapshots for a PDF document.

    Each snapshot is a full temp-file copy of the document taken *before*
    a destructive operation. To undo, the viewer re-opens the snapshot.
    """

    changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._undo: deque[_Snapshot] = deque()
        self._redo: list[_Snapshot] = []
        self._restored_modified = False
        self._restoring = False

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

    @property
    def restored_modified(self) -> bool:
        """Whether the state returned by the latest pop was unsaved."""
        return self._restored_modified

    def _require_idle(self) -> None:
        if self._restoring:
            raise RuntimeError("History cannot change during a restore.")

    def restore(
        self,
        direction: str,
        current_data: bytes,
        *,
        modified: bool,
        apply: Callable[[Path, bool], bool],
    ) -> bool:
        """Stage the inverse snapshot, apply the target, then commit both stacks.

        The callback must retain the current document when it fails or returns
        False. Target history stays owned by this stack until success.
        """
        self._require_idle()
        if direction not in {"undo", "redo"}:
            raise ValueError("History direction must be undo or redo.")
        source = self._undo if direction == "undo" else self._redo
        if not source:
            return False
        target = source[-1]
        handle, temp_name = tempfile.mkstemp(prefix=".history-", suffix=".pdf")
        os.close(handle)
        inverse = _Snapshot(Path(temp_name), target.description, modified)
        committed = False
        self._restoring = True
        try:
            inverse.path.write_bytes(current_data)
            if not apply(target.path, target.modified):
                return False
            source.pop()
            if direction == "undo":
                self._redo.append(inverse)
            else:
                self._append_undo(inverse)
            self._restored_modified = target.modified
            committed = True
            target.cleanup()
        finally:
            self._restoring = False
            if not committed:
                inverse.cleanup()
        self.changed.emit()
        return True

    def push_bytes(self, data: bytes, description: str, modified: bool = False) -> None:
        """Commit a transaction snapshot; storage failure leaves history intact.

        Unlike the legacy file-copy API, failure propagates to the transaction
        so the document can roll back instead of losing its undo point.
        """
        self._require_idle()
        handle, temp_name = tempfile.mkstemp(prefix=".undo-", suffix=".pdf")
        os.close(handle)
        snapshot = _Snapshot(Path(temp_name), description, modified)
        try:
            snapshot.path.write_bytes(data)
        # Preserve cancellation/exit: restore ownership/history, then re-raise.
        except BaseException:
            snapshot.cleanup()
            raise
        self._append_undo(snapshot)
        self._clear_redo()
        self.changed.emit()

    def push(
        self, source_path: str, description: str, *, modified: bool = False
    ) -> None:
        """Copy the current document file as a snapshot before a change."""
        self._require_idle()
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".undo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            log_failure('undo.push: fallback after failure', 10)
            Path(temp_name).unlink(missing_ok=True)
            return
        snapshot = _Snapshot(
            path=Path(temp_name), description=description, modified=modified
        )
        self._append_undo(snapshot)
        self._clear_redo()
        self.changed.emit()

    def pop_undo(self) -> Path | None:
        """Pop the most recent snapshot. Caller must push current state to redo first."""
        self._require_idle()
        if not self._undo:
            return None
        snapshot = self._undo.pop()
        self._restored_modified = snapshot.modified
        self.changed.emit()
        return snapshot.path

    def pop_redo(self) -> Path | None:
        """Pop the most recent redo snapshot. Caller must push current state to undo first."""
        self._require_idle()
        if not self._redo:
            return None
        snapshot = self._redo.pop()
        self._restored_modified = snapshot.modified
        self.changed.emit()
        return snapshot.path

    def push_redo(
        self, source_path: str, description: str, *, modified: bool = True
    ) -> None:
        """Save the current document to the redo stack."""
        self._require_idle()
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".redo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            log_failure('undo.push_redo: fallback after failure', 10)
            Path(temp_name).unlink(missing_ok=True)
            return
        self._redo.append(
            _Snapshot(
                path=Path(temp_name), description=description, modified=modified
            )
        )
        self.changed.emit()

    def push_undo(
        self, source_path: str, description: str, *, modified: bool = True
    ) -> None:
        """Save the current document to the undo stack (used during redo)."""
        self._require_idle()
        source = Path(source_path)
        if not source.is_file():
            return
        handle, temp_name = tempfile.mkstemp(prefix=".undo-", suffix=".pdf")
        os.close(handle)
        try:
            target = Path(temp_name)
            target.write_bytes(source.read_bytes())
        except Exception:
            log_failure('undo.push_undo: fallback after failure', 10)
            Path(temp_name).unlink(missing_ok=True)
            return
        self._append_undo(
            _Snapshot(
                path=Path(temp_name), description=description, modified=modified
            )
        )
        self.changed.emit()

    def _append_undo(self, snapshot: _Snapshot) -> None:
        """Append without leaking the temp file evicted at the depth limit."""
        if len(self._undo) >= MAX_UNDO_DEPTH:
            self._undo.popleft().cleanup()
        self._undo.append(snapshot)

    def _clear_redo(self) -> None:
        for snapshot in self._redo:
            snapshot.cleanup()
        self._redo.clear()

    def clear(self) -> None:
        self._require_idle()
        for snapshot in self._undo:
            snapshot.cleanup()
        self._undo.clear()
        self._clear_redo()
        self._restored_modified = False
        self.changed.emit()
