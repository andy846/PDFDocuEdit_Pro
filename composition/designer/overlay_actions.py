"""Object and font editing for the isolated PDF overlay workspace."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict

from PyQt6.QtWidgets import QDialog, QInputDialog

from composition.overlay.model import BarcodeProfile, BarcodeToken, OverlayObject
from composition.pdf_source.planner import SYSTEM_FIELDS, EnvelopePlan, applies
from composition.template.model import Element

from .overlay_dialogs import BarcodeProfileDialog
from .overlay_files import OverlayFiles
from .overlay_usability import OverlayUsability


class OverlayActions(OverlayUsability, OverlayFiles):
    def selection_changed(self, *args):
        ids = self.canvas.selected_ids()
        if self.draft_error:
            previous = getattr(self, "draft_ids", [])
            if set(ids) != set(previous):
                self.canvas.select_ids(previous)
            return
        selected = [obj for obj in (self.spec.objects if self.spec else []) if obj.element.id in ids]
        self.properties.show_selection([obj.element for obj in selected])
        self.properties.rules_group.hide()
        self.properties.repair_button.hide()
        for control in (self.scope, self.control, self.letter_page):
            control.blockSignals(True)
        obj = selected[0] if len(selected) == 1 else None
        if obj:
            self.scope.setCurrentIndex(self.scope.findData(obj.scope))
            self.letter_page.setValue(obj.letter_page)
            self.control.setChecked(obj.control)
        editable = not (self.active_worker or self.font_token or self.preview_only.isChecked())
        self.scope.setEnabled(obj is not None and editable)
        self.letter_page.setEnabled(bool(obj and obj.scope == "letter_page" and editable))
        self.control.setEnabled(bool(obj and obj.profile and editable))
        self.profile_button.setEnabled(bool(obj and obj.profile and editable))
        if obj and obj.profile:
            self.properties.content_group.hide()
        for control in (self.scope, self.control, self.letter_page):
            control.blockSignals(False)
        self.sync_layers()
        self.update_payload_summary(obj)

    def canvas_edit(self, before, after):
        raw = self.spec.to_dict()
        elements = {item["id"]: item for item in after["pages"][0]["elements"]}
        for item in raw["objects"]:
            if item["element"]["id"] in elements:
                item["element"] = elements[item["element"]["id"]]
        self.commit(raw, "Move / resize overlay")

    def property_edit(self, values):
        if not self.spec:
            return
        raw = self.spec.to_dict()
        ids = self.properties.bulk_ids or self.canvas.selected_ids()
        for item in raw["objects"]:
            if item["element"]["id"] in ids:
                for key, value in values.items():
                    if key == "font":
                        item["element"]["font"].update(value)
                    elif key != "value" or not item["profile"]:
                        item["element"][key] = value
        if self.commit(raw, "Edit overlay properties", ids):
            self.draft_error = ""
            self.properties.revert_content.hide()
        else:
            self.draft_ids = list(ids)
            self.draft_error = "Finish or revert the unfinished edit before saving or generating."
            self.preview_generation += 1
            self.timer.stop()
            self.canvas.set_preview(None)
            self.preview_status.setText("Fix unfinished edit")
            self.properties.revert_content.show()
        self.busy()

    def revert_draft(self):
        self.draft_error = ""
        self.selection_changed()
        self.properties.revert_content.hide()
        self.busy()
        self.schedule_preview()

    def scope_edited(self, *args):
        if not self.spec or len(self.canvas.selected_ids()) != 1:
            return
        raw = self.spec.to_dict()
        item = next(item for item in raw["objects"] if item["element"]["id"] == self.canvas.selected_ids()[0])
        item.update(scope=self.scope.currentData(), letter_page=self.letter_page.value(), control=self.control.isChecked())
        self.commit(raw, "Change overlay page scope")

    def required_scope_edited(self, *args):
        if self.spec:
            raw = self.spec.to_dict()
            raw["required_scope"] = self.required_scope.currentData()
            self.commit(raw, "Change required barcode read positions")

    def add_object(self, kind="text", field="EnvelopeSeq", x=20, y=20):
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            return
        element = Element(type=kind, value="{{"+field+"}}", x_mm=x, y_mm=y,
            width_mm=90 if kind in {"code128", "i25"} else 35 if kind == "qr" else 70,
            height_mm=14 if kind in {"code128", "i25"} else 35 if kind == "qr" else 12)
        obj = OverlayObject(element, scope=self.spec.required_scope,
            control=kind != "text" and not any(obj.control for obj in self.spec.objects),
            profile=BarcodeProfile() if kind != "text" else None)
        if self.spec.required_scope == "all_output" and obj.profile:
            obj.profile.tokens = [BarcodeToken(), BarcodeToken(value="PrintPage", width=2), BarcodeToken(value="PrintPageCount", width=2)]
        raw = self.spec.to_dict()
        raw["objects"].append(asdict(obj))
        self.commit(raw, "Add overlay "+kind, [element.id])

    def insert_field(self):
        name, ok = QInputDialog.getItem(self, "Insert system field", "Field", sorted(SYSTEM_FIELDS), 0, False)
        if ok:
            self.properties.content.insertPlainText("{{"+name+"}}")

    def edit_profile(self):
        if len(self.canvas.selected_ids()) != 1:
            return
        obj = next(obj for obj in self.spec.objects if obj.element.id == self.canvas.selected_ids()[0])
        plan = EnvelopePlan(self.spec.source.pages, self.spec.settings)
        fields = plan.page(self.envelope.value(), self.print_page.value()).fields("preview")
        positions = [page for page in range(1, self.spec.settings.output_pages_per_envelope + 1)
                     if applies(obj.scope, plan.page(1, page).fields("preview"), obj.letter_page)]
        samples = [("First applicable mark", plan.page(1, positions[0]).fields("preview")),
                   ("Last applicable mark", plan.page(plan.envelopes, positions[-1]).fields("preview"))]
        dialog = BarcodeProfileDialog(obj.profile, fields, self, symbology=obj.element.type, samples=samples)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            raw = self.spec.to_dict()
            next(item for item in raw["objects"] if item["element"]["id"] == obj.element.id)["profile"] = asdict(dialog.profile)
            self.commit(raw, "Edit barcode payload profile")

    def object_command(self, command):
        if not self.spec:
            return
        ids = self.canvas.selected_ids()
        if command == "select_all":
            self.canvas.select_ids([obj.element.id for obj in self.spec.objects])
            return
        if command == "copy":
            self.clipboard = [copy.deepcopy(item) for item in self.spec.to_dict()["objects"] if item["element"]["id"] in ids]
            return
        if self.active_worker or self.font_token or self.draft_error or self.preview_only.isChecked():
            return
        raw = self.spec.to_dict()
        if command == "delete":
            raw["objects"] = [item for item in raw["objects"] if item["element"]["id"] not in ids]
        elif command in ("duplicate", "paste"):
            copied = self.clipboard if command == "paste" else [item for item in raw["objects"] if item["element"]["id"] in ids]
            ids = []
            for item in copy.deepcopy(copied):
                item["element"]["id"] = uuid.uuid4().hex
                item["element"]["x_mm"] += 5
                item["element"]["y_mm"] += 5
                item["control"] = False
                raw["objects"].append(item)
                ids.append(item["element"]["id"])
        else:
            return
        self.commit(raw, command.title()+" overlay", ids)

    def request_font(self, request):
        ids = request.get("element_ids") or [request["element_id"]]
        if request.get("cancel"):
            self.font_token = None
            self.busy()
            return
        token = uuid.uuid4().hex
        self.font_token = token
        self.busy()
        def ready(result):
            if self.font_token != token or self.close_pending:
                return
            self.font_token = None
            self.properties.file_faces[result["file"]] = result
            raw = self.spec.to_dict()
            for item in raw["objects"]:
                if item["element"]["id"] in ids:
                    item["element"]["font"].update(family=result["family"], file=result["file"], bold=False, italic=False)
            self.commit(raw, "Select exact font face", ids)
            self.busy()
        def failed(message):
            if self.font_token == token:
                self.font_token = None
                self.error(message)
                self.selection_changed()
                self.busy()
        def export(face):
            self.worker({"task": "font_export", "face": face, "directory": str(self.directory/"font-faces")}, ready, failed)
        if "file" in request:
            def inspected(result):
                if self.font_token != token:
                    return
                faces = result["faces"]
                if len(faces) > 1:
                    labels = [face["family"]+" · "+face["style"] for face in faces]
                    choice, ok = QInputDialog.getItem(self, "Exact font face", "Font collection", labels, 0, False)
                    if not ok:
                        failed("Font selection cancelled")
                        return
                    export(faces[labels.index(choice)])
                else:
                    export(faces[0])
            self.worker({"task": "font_info", "file": request["file"]}, inspected, failed)
        else:
            export(request["face"])
