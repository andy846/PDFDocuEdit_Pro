"""Source inspection, project persistence and production transport for PDF overlays."""
from __future__ import annotations

import copy
from dataclasses import asdict, replace
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

from composition.overlay.model import EnvelopeSpec, OverlayJob
from composition.overlay.serializer import load_project
from composition.pdf_source.model import EnvelopeSettings, SourceInfo

from .overlay_dialogs import GroupingDialog


class OverlayFiles:
    def choose_source(self, checked=False, *, replace=False):
        if self.project_host and self.spec and not replace:
            project = self.project_host.new_overlay()
            if project:
                project.choose_source()
            return
        if self.active_worker or self.font_token:
            return
        if self.spec and not replace:
            self.confirm_discard(lambda: self.select_source(False))
        else:
            self.select_source(replace)

    def select_source(self, preserve):
        path, _ = QFileDialog.getOpenFileName(self, "Select existing production PDF", self.spec.source.path if self.spec else "", "PDF (*.pdf)")
        if not path:
            return
        dialog = GroupingDialog(self.spec.settings if self.spec else None, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.inspect_source(path, dialog.settings, preserve=preserve, detect=dialog.detect.isChecked())

    def edit_grouping(self):
        if not self.spec:
            return
        dialog = GroupingDialog(self.spec.settings, self.spec.source.pages, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.inspect_source(self.spec.source.path, dialog.settings, preserve=True)

    def inspect_source(self, path, settings=None, *, preserve=False, detect=False):
        settings = settings or EnvelopeSettings()
        previous_review = self.spec.detection_review if preserve and self.spec else {}
        pending_detection = bool(previous_review.get("required") and not previous_review.get("accepted"))
        def ready(info):
            if self.close_pending:
                return
            requires_scan = detect or pending_detection
            spec = EnvelopeSpec(SourceInfo(**info), settings)
            self.active_worker = None
            if preserve and self.spec:
                # Reinspection updates the source and grouping, not the production project.
                spec = replace(copy.deepcopy(self.spec), source=SourceInfo(**info), settings=settings,
                               source_link={}, detection_review={})
                if spec.media.get("enabled") and settings.duplex != self.spec.settings.duplex:
                    spec.media["duplex"] = settings.duplex
                same_source = spec.source.sha256 == self.spec.source.sha256
                if same_source:
                    spec.source_link = dict(self.spec.source_link)
                    if spec.source_link and not detect and not settings.groups:
                        spec.source_link["review_required"] = False
                if settings.groups and not same_source:
                    spec.settings = replace(settings, pages_per_envelope=1, groups=[], excluded_pages=[])
                    requires_scan = True
                elif settings.groups:
                    spec.detection_review = self.spec.detection_review
                if requires_scan:
                    spec.detection_review = {"required": True, "accepted": False, "source_sha256": spec.source.sha256}
                spec.objects = self.spec.objects
                spec.required_scope = self.spec.required_scope
                if not self.commit(spec.to_dict(), "Reinspect PDF / change grouping"):
                    return
            else:
                if requires_scan:
                    spec.detection_review = {"required": True, "accepted": False, "source_sha256": spec.source.sha256}
                self.project_path = None
                self.undo.clear()
                self.apply_spec(spec.to_dict())
                self.add_object("text")
            self.fit_canvas()
            self.tabs.setCurrentIndex(0)
            if requires_scan:
                QTimer.singleShot(0, self.detect_mailpieces)
        inspection_settings = replace(settings, pages_per_envelope=1, groups=[], excluded_pages=[]) if settings.groups else settings
        self.worker({"task": "overlay_inspect", "source": str(path), "settings": asdict(inspection_settings),
                     "uniform": detect or pending_detection or bool(settings.groups)}, ready, active=True)

    def detect_mailpieces(self, checked=False):
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            return
        dialog = getattr(self, "detection_dialog", None)
        if (dialog and dialog.context_sha256 == self.spec.source.sha256
                and dialog.context_settings == asdict(self.spec.settings)
                and dialog.context_review == self.spec.detection_review):
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
        if dialog:
            dialog.reject()
        from .mailpiece_dialog import MailpieceDialog
        self.detection_dialog = MailpieceDialog(self)
        self.detection_dialog.show()

    def open_project(self, checked=False, *, path=None):
        if self.project_host:
            return self.project_host.open_project(path)
        if self.active_worker or self.font_token:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open PDF overlay project", "", "Document Designer project (*.pdcx)")
        if path:
            self.confirm_discard(lambda: self.load_path(path))

    def load_path(self, path):
        try:
            spec = load_project(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error(str(exc))
            return
        self.project_path = Path(path)
        self.undo.clear()
        self.apply_spec(spec.to_dict())
        self.undo.setClean()
        self.fit_canvas()

    def save_project(self, checked=False, *, save_as=False, path=None, after=None):
        if hasattr(self, "batch_editor") and not self.batch_editor.resolve():
            return
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            self.error("Finish or revert the unfinished edit and wait for the active task before saving.")
            return
        if not path:
            path = str(self.project_path) if self.project_path and not save_as else ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save overlay project", "", "Document Designer project (*.pdcx)")
        if not path:
            return
        if self.project_host and not self.project_host.allow_save_path(self, path):
            return
        def saved(result):
            self.project_path = Path(result["project"])
            self.apply_spec(result["spec"])
            # Saved asset paths must remain valid when undoing earlier edits.
            self.undo.setClean()
            if after:
                QTimer.singleShot(0, after)
        self.worker({"task": "overlay_save", "project": self.spec.to_dict(), "target": str(path)}, saved, active=True)

    def generate_pdf(self, checked=False, *, output_dir=None):
        if hasattr(self, "batch_editor") and not self.batch_editor.resolve():
            return
        if getattr(self,"media_error",""):
            self.error(self.media_error)
            return
        if self.spec and self.spec.needs_source_review:
            self.error("Confirm grouping / review the updated PDF source before generating.")
            return
        if self.spec and self.spec.needs_detection_review:
            self.error("Scan, review and accept mailpiece boundaries before generating.")
            return
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            return
        if not output_dir:
            output_dir = QFileDialog.getExistingDirectory(self, "Output folder: a new job subfolder will be created")
        if not output_dir:
            return
        self.last_result = None
        import copy
        self._output_spec = copy.deepcopy(self.spec.to_dict())
        self.pdf_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.production_text.setPlainText("Validating source, fonts, page scopes and barcode profiles…")
        self.tabs.setCurrentIndex(1)
        job = OverlayJob(self.spec.to_dict(), str(output_dir), auto_repair=self.auto_repair.isChecked())
        self.worker({"task": "overlay_generate", "job": asdict(job)}, self.production_ready, self.production_failed, active=True)

    def production_ready(self, result):
        self.last_result = result
        labels = [("Job", "job_id"), ("Status", "status"), ("Source pages", "source_pages"), ("Excluded separators", "excluded_source_pages"),
                  ("Input envelopes", "input_envelopes"), ("Composed envelopes", "composed_envelopes"),
                  ("Verified envelopes", "successful_envelopes"), ("Failed envelopes", "failed_envelopes"),
                  ("Unverified envelopes", "unverified_envelopes"), ("Expected output pages", "expected_pages"),
                  ("Generated pages", "generated_pages"), ("Inserted blank backs", "inserted_blanks"),
                  ("Sheets", "sheets"), ("Expected barcodes", "expected_barcodes"), ("Decoded barcodes", "decoded_barcodes"),
                  ("Published PDFs", "generated_files"), ("PDF", "output_pdf"), ("Reports", "report_dir")]
        text = "\n".join(f"{label}: {result[key]:,}" if type(result[key]) is int else f"{label}: {result[key]}" for label, key in labels)
        if result.get("output_ps"):
            text+="\nPostScript: "+result["output_ps"]
        if result["error"]:
            text += (f"\nError envelope: {result['error_envelope']} · source page: {result['error_source_page']} · "
                     f"output page: {result['error_output_page']}\nError: {result['error']}")
        text += "\n\n"+"\n".join(result["warnings"])
        if result.get("media_summary"):
            summary=result["media_summary"]
            text+="\n\nMedia: "+" · ".join(f"{k}: {v:,} sheets" for k,v in summary.get("stock_sheets",{}).items())
            text+=("\nPostScript selection embedded · device validation pending" if summary.get("backend")=="postscript"
                   else "\nOffline default_ticket.jdf · Canon device validation pending")
        self.production_text.setPlainText(text)
        self.pdf_button.setEnabled(result["status"] == "completed")
        self.report_button.setEnabled(bool(result["report_dir"]))

    def production_failed(self, message):
        self.production_text.setPlainText("Job did not publish output.\n"+message)
        self.error(message)

    def open_result(self, key):
        if self.last_result and self.last_result[key]:
            if key == "output_pdf" and self.project_host:
                self.project_host.open_production_output(self, self.last_result)
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_result[key]))

    def cancel_job(self):
        if self.active_worker:
            self.active_worker.cancel()
            self.error("Cancelling at the next safe checkpoint…")

    def confirm_discard(self, callback):
        if hasattr(self, "batch_editor") and not self.batch_editor.resolve():
            return
        if self.undo.isClean() and not self.draft_error:
            callback()
            return
        answer = QMessageBox.question(self, "Unsaved PDF overlay", "Save changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            self.save_project(after=callback)
        elif answer == QMessageBox.StandardButton.Discard:
            callback()

    def closeEvent(self, event):
        if not self.embedded and not self._close_approved and hasattr(self, "batch_editor") and not self.batch_editor.resolve():
            event.ignore()
            return
        if self.embedded and not self._close_approved and not self.close_pending:
            event.ignore()
            QTimer.singleShot(0, lambda: self.project_host.close_project(self))
            return
        if not self.close_pending:
            if not self._close_approved and (not self.undo.isClean() or self.draft_error):
                self.confirm_discard(self.begin_close)
            else:
                self.begin_close()
        if not self.close_pending or self.workers:
            event.ignore()
            return
        self.temp.cleanup()
        event.accept()
        self.projectClosed.emit()

    def begin_close(self):
        self.close_pending = True
        if getattr(self, "detection_dialog", None):
            self.detection_dialog.reject()
        self.timer.stop()
        self.layout_timer.stop()
        for worker in self.workers[:]:
            if worker is self.active_worker:
                worker.cancel()
            else:
                worker.stop_preview()
        if not self.workers and not self.embedded:
            QTimer.singleShot(0, self.close)
