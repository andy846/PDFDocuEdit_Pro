"""Viewer routing, frozen snapshots and ownership transfer for Quick Extraction."""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from dialogs.quick_text_extractor import QuickTextExtractorDialog
from ui.merge_workspace import capture_merge_source


class TextExtractionController:
    def __init__(self, window):
        self.window = window
        self.capturing = False
        if not hasattr(window, "_text_extraction_dialogs"):
            window._text_extraction_dialogs = []

    def open(self):
        window = self.window
        if self.capturing:
            return
        if window._text_extraction_dialogs:
            dialog = window._text_extraction_dialogs[-1]
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
        source, session = window._require_source(), window._session
        if not source or not session or not session.engine.is_loaded():
            return
        if session.form_draft and session.form_draft.changed:
            prompt = QMessageBox(window)
            prompt.setWindowTitle("Unapplied form draft")
            prompt.setText("Apply the form draft before capturing this PDF for text extraction?")
            apply = prompt.addButton("Apply", QMessageBox.ButtonRole.AcceptRole)
            ignore = prompt.addButton("Extract without draft", QMessageBox.ButtonRole.ActionRole)
            prompt.addButton(QMessageBox.StandardButton.Cancel)
            prompt.exec()
            if prompt.clickedButton() is apply:
                if not window._apply_form_draft():
                    return
            elif prompt.clickedButton() is not ignore:
                return
        temporary = tempfile.TemporaryDirectory(prefix="pdfdocuedit-extract-")
        snapshot = Path(temporary.name)/"working-copy.pdf"
        identity = (session.engine.document_id, session.engine.revision)
        page = window._page
        self.capturing = True
        transferred = False

        def ready(info):
            nonlocal transferred
            if info is None or identity != (session.engine.document_id, session.engine.revision):
                window.info_bar.show_message("PDF changed during capture; start text extraction again.", "warning")
                return
            dialog = QuickTextExtractorDialog(snapshot, page, str(source.with_name(source.stem+"_extracted.xlsx")),
                                               window, temporary=temporary, protected=[source],
                                               page_count=info["pages"],
                                               source_guard=lambda: session.engine.is_loaded() and
                                               identity == (session.engine.document_id, session.engine.revision),
                                               handoff=self.handoff if getattr(window, "_mode_controller", None) else None)
            transferred = True
            window._text_extraction_dialogs.append(dialog)
            def closed():
                if dialog in window._text_extraction_dialogs:
                    window._text_extraction_dialogs.remove(dialog)
                dialog.host.deleteLater()
            dialog.finished.connect(closed)
            dialog.show()

        def finished():
            self.capturing = False
            if not transferred:
                temporary.cleanup()

        window._run_task("Capturing PDF for text extraction", capture_merge_source, session.engine, identity, snapshot,
                         cancel_argument="is_cancelled", on_result=ready, on_finished=finished)

    def handoff(self, dialog, spec, pages):
        from workflow.model import WorkflowSpec

        mode = self.window._mode_controller
        host = mode.ensure_host(create_default=False)
        workflow = host.new_workflow()
        if workflow is None:
            raise ValueError("Workflow is closing; finish closing before transferring extraction regions.")
        target = workflow.directory/("extraction-"+uuid.uuid4().hex+".pdf")
        workflow.capture_active = True
        workflow.lock()

        def ready(result):
            WorkflowSpec.from_dict(result["spec"]).validate()
            workflow.capture_active = False
            if not workflow.commit(result["spec"], "Import extraction regions and selected PDF pages"):
                raise ValueError("Workflow did not accept the handoff; the Quick Extraction setup is still available.")
            dialog.reject()
            mode.request_mode("designer")
            workflow.message("PDF snapshot and regions imported. Run, review and approve this Workflow independently.")

        def finished():
            workflow.capture_active = False
            workflow.lock()

        dialog.host.request({"operation": "handoff", "source": dialog.source, "target": str(target),
                             "extraction": spec.to_dict(), "pages": pages}, ready, on_finished=finished)
