"""Coordinate live mutations and history without owning PDF rendering widgets."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from core.diagnostics import log_failure, log_lifecycle
from core.pdf_engine import DOCUMENT_LOCK, PdfEngine, PdfEngineError
from core.reader_lifetime import after_readers, pause_readers

if TYPE_CHECKING:
    from core.viewer import PDFViewer

    from .document_session import DocumentSession


class MutationController:
    """Keep transaction/history lifecycle out of the main window's tool handlers."""

    def __init__(self, viewer: PDFViewer):
        self.viewer = viewer
        self.active = False

    @contextmanager
    def transaction(self, description: str):
        """Authorize once and rebind every document reader after rollback."""
        viewer = self.viewer
        session = viewer._session
        if (self.active or viewer._closing or session is None or not session.engine.is_loaded()
                or viewer._printing or viewer._tasks
                or not viewer._confirm_signature_invalidation()):
            yield False
            return
        canvases = viewer._document_canvases(session)
        states = [(canvas, viewer._capture_canvas_view_state(canvas)) for canvas in canvases]
        thumbnails = session.nav_panel.thumbnails
        self.active = True
        stage = "reader_drain"
        log_lifecycle("mutation.reader_drain", canvases=len(canvases))
        try:
            with viewer._close_lifecycle.lock_ui(), pause_readers((*canvases, thumbnails)):
                for canvas in canvases:
                    canvas.wait_for_renders()
                thumbnails.quiesce_renders()
                original = session.engine.document
                stage = "mutation"
                try:
                    with session.engine.mutation_transaction(description):
                        yield True
                except BaseException:
                    stage = "rollback_rebind"
                    if session.engine.document is not original:
                        for canvas, state in states:
                            canvas.clear(wait=False)
                            if session.engine.is_loaded():
                                canvas.load_doc(session.engine.document, float(state["zoom"]))
                                viewer._restore_canvas_view_state(canvas, state)
                        if session.engine.is_loaded():
                            viewer._reload_thumbnails(session)
                        viewer._sync_modified_state()
                        viewer._refresh_annotate_list()
                    stage = "mutation_rolled_back"
                    raise
        except BaseException:
            log_failure("Mutation failed at " + stage)
            raise
        finally:
            self.active = False
            if not viewer._closing:
                for canvas in canvases:
                    canvas._fill_render_queue(set(canvas._page_views))
                thumbnails._render_visible_thumbnails()
            viewer._update_undo_actions()
            log_lifecycle("mutation.finished", tasks=len(viewer._tasks))

    def move_history(self, direction: str) -> bool:
        viewer = self.viewer
        session = viewer._session
        if (self.active or viewer._closing or session is None or not session.engine.is_loaded()
                or viewer._printing or viewer._tasks):
            return False
        stack = session.undo_stack
        if not (stack.can_undo if direction == "undo" else stack.can_redo):
            return False
        try:
            with DOCUMENT_LOCK:
                current = session.engine.document.tobytes(garbage=0, deflate=False, clean=False, no_new_id=True)
            changed = stack.restore(
                direction, current, modified=session.engine.is_modified,
                apply=lambda path, modified: viewer._restore_history_snapshot(
                    session, path, modified=modified
                ),
            )
        except Exception as exc:
            log_failure('mutation_controller.move_history: fallback after failure', 10)
            viewer._error(f"{direction.title()} failed", str(exc))
            return False
        if changed:
            viewer.info_bar.show_message(f"{direction.title()} applied.", "success")
        return changed

    def restore_history_snapshot(
        self, session: DocumentSession, snapshot_path: Path, *, modified: bool
    ) -> bool:
        """Prepare a replacement before touching live readers; retain the old engine.

        The history stack still owns snapshot_path. It removes that file only
        after this method has successfully installed and displayed its contents.
        """
        viewer = self.viewer
        if self.active:
            raise PdfEngineError("Another document operation is still active.")
        canvases = viewer._document_canvases(session)
        thumbnails = session.nav_panel.thumbnails
        self.active = True
        try:
            with viewer._close_lifecycle.lock_ui(), pause_readers((*canvases, thumbnails)):
                return self._restore_history_snapshot_paused(session, snapshot_path, modified=modified)
        finally:
            self.active = False
            if not viewer._closing:
                for canvas in canvases:
                    canvas._fill_render_queue(set(canvas._page_views))
                thumbnails._render_visible_thumbnails()
            viewer._update_undo_actions()

    def _restore_history_snapshot_paused(self, session, snapshot_path, *, modified):
        viewer = self.viewer
        previous = session.engine
        opened = PdfEngine()
        view_state = viewer._capture_session_view_state(session)
        canvas_states = [
            (canvas, viewer._capture_canvas_view_state(canvas))
            for canvas in viewer._document_canvases(session)
        ]
        display_path = session.display_path or previous.original_path or snapshot_path
        installing = False
        try:
            opened.open(snapshot_path)
            if opened.page_count < 1:
                raise PdfEngineError("History snapshot contains no pages.")
            with DOCUMENT_LOCK:
                for page in opened.document:
                    _ = page.rect
            opened.inherit_save_context(previous, modified=modified)
            installing = True
            viewer._replace_session_engine(session, opened, close_previous=False)
            if not viewer._complete_pdf_open(
                session, display_path, reset_history=False, announce=False
            ):
                raise PdfEngineError("Could not display the history snapshot.")
            viewer._restore_session_view_state(session, view_state)
            for canvas, state in canvas_states:
                viewer._restore_canvas_view_state(canvas, state)
        # Preserve cancellation/exit: restore ownership/history, then re-raise.
        except BaseException:
            # UI installation can already have scheduled replacement readers.
            # Detach without waiting; retain leases before restoring ownership.
            readers = session.nav_panel.thumbnails.reader_events()
            for canvas, _state in canvas_states:
                readers.extend(canvas.reader_events())
            try:
                if installing:
                    # Keep the original engine alive throughout UI installation.
                    # Restore readers even if failure happened before assignment.
                    session.nav_panel.thumbnails.quiesce_renders(wait=False)
                    for canvas, _state in canvas_states:
                        canvas.clear(wait=False)
                    session.engine = previous
                    for canvas, state in canvas_states:
                        canvas.load_doc(previous.document, float(state["zoom"]))
                        viewer._restore_canvas_view_state(canvas, state)
                    viewer._load_navigation()
                    viewer._after_page_count_change()
                    viewer._restore_session_view_state(session, view_state)
            finally:
                after_readers(readers, opened.close)
            raise
        # Cleanup cannot turn a completed replacement into a failed history move.
        try:
            previous.close()
        except Exception:
            log_failure("Could not clean up replaced history engine", logging.WARNING)
        return True
