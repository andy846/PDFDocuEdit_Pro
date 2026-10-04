"""Atomic selected-object drafts and session-local text format clipboard."""
from __future__ import annotations

import copy
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtCore import QEventLoop
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

from .arrange import commit_elements, current_elements, report


class FormatClipboard:
    """Own copied font assets until application shutdown, independent of projects."""

    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pdc-format-")
        self.value = None
        QApplication.instance().aboutToQuit.connect(self.temp.cleanup)


class BatchEditor:
    def __init__(self, window):
        self.window = window
        self.properties = window.properties
        self.committing = False
        self.resolving = False
        self.restoring_selection = False
        self.pending = False
        self.defer_discard = False
        self.deferred_discard = False
        self.last_selection = []
        self.last_page = None
        self.properties.batch_resolver = self.resolve
        self.properties.batchApplyRequested.connect(self.apply)
        self.properties.batchRevertRequested.connect(self.revert)
        self.properties.bulkChanged.connect(self.changed)
        window.canvas.before_edit = self.resolve
        window.batch_editor = self
        app = QApplication.instance()
        if not hasattr(app, "designer_format_clipboard"):
            app.designer_format_clipboard = FormatClipboard()
        self.clipboard = app.designer_format_clipboard
        for key, title, callback in (
            ("copy_format", "Copy text formatting", self.copy_format),
            ("paste_format", "Paste text formatting…", self.paste_format),
            ("apply_batch", "Apply changed settings", self.apply),
            ("revert_batch", "Revert unapplied settings", self.revert),
        ):
            action = QAction(title, window)
            action.triggered.connect(callback)
            window.actions[key] = action
        window.undo.indexChanged.connect(self.update_actions)

    def changed(self):
        self.update_actions()
        if hasattr(self.window, "selection_status"):
            ids = self.window.canvas.selected_ids()
            self.window.selection_status.setText(f"{len(ids)} selected · {len(self.targets())} text targets" if ids else "No selection")
        host = getattr(self.window, "project_host", None)
        if host:
            host.update_project(self.window)

    def update_actions(self, *args):
        w = self.window
        if w.close_pending or sip.isdeleted(w) or sip.isdeleted(w.undo):
            return
        editable = w.canvas.editable and not w.canvas.mode_preview and not self.pending
        targets = self.targets()
        for key in ("copy_format", "paste_format"):
            w.actions[key].setEnabled(editable and bool(targets) and (key == "copy_format" or bool(self.clipboard.value)))
        for key in ("apply_batch", "revert_batch"):
            w.actions[key].setEnabled(editable and self.properties.has_batch_draft())
        draft = self.properties.has_batch_draft() or self.pending
        for key, available in (("undo", w.undo.canUndo()), ("redo", w.undo.canRedo())):
            if key in w.actions:
                w.actions[key].setEnabled(bool(available and editable and not draft))

    def targets(self):
        ids = set(self.window.canvas.selected_ids())
        return [e for e in current_elements(self.window) if e.id in ids and (
            e.type == "text" or self.properties.include_barcode.isChecked() and
            e.type in {"code128", "i25"} and e.show_barcode_text)]

    def selection(self, ids):
        """Keep an untouched draft on redundant refresh; prompt on actual selection changes."""
        if self.restoring_selection:
            return False
        if self.committing:
            return True
        if self.properties.has_batch_draft():
            if set(ids) == set(self.last_selection):
                self.update_actions()
                return False
            if not self.resolve():
                self.restoring_selection = True
                try:
                    self.window.canvas.select_ids(self.last_selection)
                finally:
                    self.restoring_selection = False
                return False
        self.last_selection = list(ids)
        self.update_actions()
        return True

    def resolve(self, *args):
        if self.committing:
            return True
        if self.deferred_discard:
            return True
        if self.pending or self.resolving:
            return False
        if not self.properties.has_batch_draft():
            return True
        self.resolving = True
        try:
            dialog = QMessageBox(self.window)
            dialog.setWindowTitle("Unapplied selected-object settings")
            dialog.setText("Apply the changed settings before continuing?")
            apply = dialog.addButton("Apply", QMessageBox.ButtonRole.AcceptRole)
            discard = dialog.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.exec()
            if dialog.clickedButton() is apply:
                return self.apply(wait=True)
            if dialog.clickedButton() is discard:
                if self.defer_discard:
                    self.deferred_discard = True
                else:
                    self.revert()
                return True
            return False
        finally:
            self.resolving = False

    def revert(self):
        if self.pending:
            return
        selected = [e for e in current_elements(self.window) if e.id in set(self.last_selection)]
        self.properties.show_selection(selected)
        self.changed()

    def apply(self, *args, wait=False):
        p, w = self.properties, self.window
        if self.pending or not p.has_batch_draft() or not w.canvas.editable or w.canvas.mode_preview:
            return not p.has_batch_draft()
        selected = [asdict(e) for e in current_elements(w) if e.id in set(self.last_selection)]
        if set(e["id"] for e in selected) != set(p.geometry_ids):
            report(w, "Selection changed; review the pending settings before applying.")
            return False
        typography, geometry = p.batch_values()
        targets = set(p.bulk_ids)
        request = copy.deepcopy(p.bulk_font_request)
        snapshot = copy.deepcopy(selected)
        outcome = []
        loop = QEventLoop(w)

        def done(error=None, font=None):
            self.pending = False
            w.batch_pending = False
            success = False
            try:
                if getattr(w, "close_pending", False):
                    return
                if error:
                    raise ValueError(error)
                current = [asdict(e) for e in current_elements(w) if e.id in set(self.last_selection)]
                if current != snapshot:
                    raise ValueError("Selected objects changed while preparing the font. Draft retained; review and apply again.")
                for e in selected:
                    e.update(geometry)
                    if e["id"] in targets:
                        for key, value in typography.items():
                            if key == "font":
                                e["font"].update(value)
                            else:
                                e[key] = value
                        if font:
                            e["font"].update(font)
                self.committing = True
                try:
                    success = commit_elements(w, selected, f"Apply settings to {len(selected)} selected objects")
                finally:
                    self.committing = False
                if success:
                    self.revert()
            except (ValueError, OSError) as exc:
                report(w, str(exc))
            finally:
                outcome.append(success)
                if not w.close_pending:
                    (w._busy if hasattr(w, "template") else w.busy)()
                    self.update_actions()
                loop.quit()

        if request:
            self.pending = True
            w.batch_pending = True
            (w._busy if hasattr(w, "template") else w.busy)()
            worker = w._worker if hasattr(w, "template") else w.worker

            def exported(result):
                done(font={"family": result["family"], "file": result["file"], "bold": False, "italic": False})

            def export(face):
                if w.close_pending:
                    done()
                    return
                worker({"task": "font_export", "validate_pdf": True, "face": face, "directory": str(w.directory / "font-faces")}, exported, done)

            def inspected(result):
                if w.close_pending:
                    done()
                    return
                faces = result["faces"]
                if not faces:
                    done("No usable font face found. Draft retained.")
                    return
                if len(faces) > 1:
                    labels = [f"{f['family']} / {f['style']}" for f in faces]
                    label, ok = QInputDialog.getItem(w, "Choose exact font face", "Font collection / style", labels, 0, False)
                    if not ok:
                        done("Font selection cancelled. Draft retained.")
                        return
                    export(faces[labels.index(label)])
                else:
                    export(faces[0])

            if "file" in request:
                worker({"task": "font_info", "file": request["file"]}, inspected, done)
            else:
                export(request["face"])
            if wait and not outcome:
                loop.exec()
        else:
            done()
        return bool(outcome and outcome[0])

    def copy_format(self, *args):
        if not self.window.canvas.editable or self.window.canvas.mode_preview or not self.resolve():
            return
        targets = self.targets()
        if not targets:
            return
        values = [dict(font=asdict(e.font), colour=e.colour, align=e.align, vertical_align=e.vertical_align, line_spacing=e.line_spacing) for e in targets]
        if any(v != values[0] for v in values[1:]):
            report(self.window, "Select one text object or objects with identical formatting to copy.")
            return
        value = copy.deepcopy(values[0])
        path = value["font"]["file"]
        if path:
            # Prepare a licensed exact font in a clipboard-owned directory asynchronously.
            self.pending = True
            self.window.batch_pending = True
            worker = self.window._worker if hasattr(self.window, "template") else self.window.worker
            (self.window._busy if hasattr(self.window, "template") else self.window.busy)()

            def finish(error=None, result=None):
                self.pending = False
                self.window.batch_pending = False
                if self.window.close_pending:
                    return
                if error:
                    report(self.window, error)
                else:
                    value["font"]["file"] = result["file"]
                    self.clipboard.value = value
                (self.window._busy if hasattr(self.window, "template") else self.window.busy)()
                self.refresh_clipboard_actions()

            def inspected(result):
                if self.window.close_pending:
                    finish()
                    return
                if len(result["faces"]) != 1:
                    finish("Copy requires a saved exact font face. Choose a face first.")
                    return
                worker({"task": "font_export", "validate_pdf": True, "face": result["faces"][0], "directory": self.clipboard.temp.name},
                       lambda result: finish(result=result), finish)

            worker({"task": "font_info", "file": path}, inspected, finish)
        else:
            self.clipboard.value = value
            self.refresh_clipboard_actions()

    def refresh_clipboard_actions(self):
        for widget in QApplication.instance().allWidgets():
            editor = getattr(widget, "batch_editor", None)
            if editor:
                editor.update_actions()

    def paste_format(self, *args):
        if not self.window.canvas.editable or self.window.canvas.mode_preview or not self.clipboard.value or not self.resolve():
            return
        targets = self.targets()
        if not targets:
            return
        answer = QMessageBox.question(self.window, "Paste text formatting", f"Apply copied text formatting to {len(targets)} selected text object(s)?",
                                      QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Apply:
            return
        value = copy.deepcopy(self.clipboard.value)
        if value["font"]["file"]:
            # Copy from session ownership into target project ownership for save/Undo.
            try:
                source = Path(value["font"]["file"])
                target = self.window.directory / "font-faces" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                value["font"]["file"] = str(target)
            except OSError as exc:
                report(self.window, str(exc))
                return
        changed = []
        for element in targets:
            raw = asdict(element)
            raw.update(copy.deepcopy(value))
            changed.append(raw)
        try:
            self.committing = True
            commit_elements(self.window, changed, f"Paste formatting to {len(changed)} text objects")
        except ValueError as exc:
            report(self.window, str(exc))
        finally:
            self.committing = False
        self.changed()
