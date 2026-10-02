"""Source inspection, project persistence and production transport for PDF overlays."""
from __future__ import annotations

from dataclasses import asdict
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
            self.inspect_source(path, dialog.settings, preserve=preserve)

    def edit_grouping(self):
        if not self.spec:
            return
        dialog = GroupingDialog(self.spec.settings, self.spec.source.pages, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.inspect_source(self.spec.source.path, dialog.settings, preserve=True)

    def inspect_source(self, path, settings=None, *, preserve=False):
        settings = settings or EnvelopeSettings()
        def ready(info):
            spec = EnvelopeSpec(SourceInfo(**info), settings)
            self.active_worker = None
            if preserve and self.spec:
                spec.objects = self.spec.objects
                spec.required_scope = self.spec.required_scope
                self.commit(spec.to_dict(), "Reinspect PDF / change grouping")
            else:
                self.project_path = None
                self.undo.clear()
                self.apply_spec(spec.to_dict())
                self.add_object("text")
                self.add_object("code128", y=35)
            self.fit_canvas()
            self.tabs.setCurrentIndex(0)
        self.worker({"task": "overlay_inspect", "source": str(path), "settings": asdict(settings)}, ready, active=True)

    def open_project(self, checked=False, *, path=None):
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
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            self.error("Finish or revert the unfinished edit and wait for the active task before saving.")
            return
        if not path:
            path = str(self.project_path) if self.project_path and not save_as else ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save overlay project", "", "Document Designer project (*.pdcx)")
        if not path:
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
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            return
        if not output_dir:
            output_dir = QFileDialog.getExistingDirectory(self, "Output folder: a new job subfolder will be created")
        if not output_dir:
            return
        self.last_result = None
        self.pdf_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.production_text.setPlainText("Validating source, fonts, page scopes and barcode profiles…")
        self.tabs.setCurrentIndex(1)
        job = OverlayJob(self.spec.to_dict(), str(output_dir), auto_repair=self.auto_repair.isChecked())
        self.worker({"task": "overlay_generate", "job": asdict(job)}, self.production_ready, self.production_failed, active=True)

    def production_ready(self, result):
        self.last_result = result
        labels = [("Job", "job_id"), ("Status", "status"), ("Source pages", "source_pages"),
                  ("Input envelopes", "input_envelopes"), ("Composed envelopes", "composed_envelopes"),
                  ("Verified envelopes", "successful_envelopes"), ("Failed envelopes", "failed_envelopes"),
                  ("Unverified envelopes", "unverified_envelopes"), ("Expected output pages", "expected_pages"),
                  ("Generated pages", "generated_pages"), ("Inserted blank backs", "inserted_blanks"),
                  ("Sheets", "sheets"), ("Expected barcodes", "expected_barcodes"), ("Decoded barcodes", "decoded_barcodes"),
                  ("Published PDFs", "generated_files"), ("PDF", "output_pdf"), ("Reports", "report_dir")]
        text = "\n".join(f"{label}: {result[key]:,}" if type(result[key]) is int else f"{label}: {result[key]}" for label, key in labels)
        if result["error"]:
            text += (f"\nError envelope: {result['error_envelope']} · source page: {result['error_source_page']} · "
                     f"output page: {result['error_output_page']}\nError: {result['error']}")
        text += "\n\n"+"\n".join(result["warnings"])
        self.production_text.setPlainText(text)
        self.pdf_button.setEnabled(result["status"] == "completed")
        self.report_button.setEnabled(bool(result["report_dir"]))

    def production_failed(self, message):
        self.production_text.setPlainText("Job did not publish output.\n"+message)
        self.error(message)

    def open_result(self, key):
        if self.last_result and self.last_result[key]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_result[key]))

    def cancel_job(self):
        if self.active_worker:
            self.active_worker.cancel()
            self.error("Cancelling at the next safe checkpoint…")

    def confirm_discard(self, callback):
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
        if not self.close_pending:
            if not self.undo.isClean() or self.draft_error:
                self.confirm_discard(self.begin_close)
            else:
                self.begin_close()
        if not self.close_pending or self.workers:
            event.ignore()
            return
        self.temp.cleanup()
        event.accept()

    def begin_close(self):
        self.close_pending = True
        self.timer.stop()
        self.layout_timer.stop()
        for worker in self.workers[:]:
            if worker is self.active_worker:
                worker.cancel()
            else:
                worker.stop_preview()
        if not self.workers:
            QTimer.singleShot(0, self.close)
