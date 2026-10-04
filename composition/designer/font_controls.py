"""Asynchronous font inventory and face selection, separate from page/job logic."""
from __future__ import annotations

import uuid

from PyQt6.QtWidgets import QInputDialog

from composition.template.model import FontSpec


class FontOperations:
    def _load_windows_fonts(self):
        if self.close_pending:
            return
        self._worker({"task": "fonts"}, self.properties.set_catalogue,
                     lambda error: self.properties.font_status.setText("Windows fonts unavailable: " + error))

    def _request_font(self, request):
        if request.get("element_ids"):
            self._request_bulk_font(request)
            return
        if self.content_invalid or self.import_worker or self.production_worker:
            self._error("Finish or revert the unfinished edit, and finish the active job before changing fonts.")
            return
        object_id = request["element_id"]
        if request.get("cancel"):
            self.font_requests.pop(object_id, None)
            self._busy()
            return
        token = uuid.uuid4().hex
        self.font_requests[object_id] = token
        epoch = self.font_epoch
        self._busy()
        repair = request.get("codepoint")
        if "spec" in request:
            self._worker({"task": "glyph_repair_font", "spec": request["spec"], "codepoint": repair},
                         lambda result: self._font_ready(result, object_id, token, epoch, repair),
                         lambda error: self._font_failed(object_id, token, error))
        elif "file" in request:
            def inspected(result):
                if self.font_requests.get(object_id) != token or epoch != self.font_epoch:
                    return
                faces = result["faces"]
                if len(faces) > 1:
                    labels = [face["family"] + " · " + face["style"] for face in faces]
                    label, ok = QInputDialog.getItem(self, "Choose exact font face",
                                                     "Font collection / variable style", labels, 0, False)
                    if not ok:
                        self._font_failed(object_id, token, "Font selection cancelled.")
                        return
                    face = faces[labels.index(label)]
                else:
                    face = faces[0]
                self._export_font(face, object_id, token, epoch, repair)
            self._worker({"task": "font_info", "file": request["file"]}, inspected,
                         lambda error: self._font_failed(object_id, token, error))
        else:
            self._export_font(request["face"], object_id, token, epoch, repair)

    def _export_font(self, face, object_id, token, epoch, repair=None):
        self._worker({"task": "font_export", "face": face, "codepoint": repair,
                      "directory": str(self.directory / "font-faces")},
                     lambda result: self._font_ready(result, object_id, token, epoch, repair),
                     lambda error: self._font_failed(object_id, token, error))

    def _font_ready(self, result, object_id, token, epoch, repair=None):
        if self.font_requests.get(object_id) != token:
            return
        self.font_requests.pop(object_id, None)
        if epoch != self.font_epoch or self.close_pending:
            self._busy()
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        target = next((e for page in after["pages"] for e in page["elements"] if e["id"] == object_id), None)
        if target is not None:
            if result["file"]:
                self.properties.file_faces[result["file"]] = result
            if repair:
                from dataclasses import asdict
                spec = result.get("spec") or asdict(FontSpec(family=result["family"], file=result["file"]))
                spec["size_pt"] = target["font"]["size_pt"]
                target["glyph_repairs"][repair] = spec
                label = f"Configure repair for {repair}; primary font retained"
                message = f"{repair}: {result['family']} configured only for missing glyphs; primary font retained."
            else:
                target["font"].update(family=result["family"], file=result["file"], bold=False, italic=False)
                label = "Select exact Windows font face"
                message = result.get("note") or f"{result['family']} · {result['style']} selected for PDF embedding."
            self._commit(before, after, label, self.canvas.selected_ids())
            self.message.setText(message)
        self._busy()

    def _font_failed(self, object_id, token, error):
        if self.font_requests.get(object_id) == token:
            self.font_requests.pop(object_id, None)
            if self.properties.element and self.properties.element.id == object_id:
                self.properties.show_element(self.properties.element)
            self._error(error)
            self._busy()

    def _inspect_selected_font(self, element):
        if not element or not element.font.file:
            return
        path = element.font.file
        if path in self.properties.file_faces or path in self.font_inspections:
            return
        self.font_inspections.add(path)
        def inspected(result):
            face = result["faces"][0]
            self.properties.file_faces[path] = face
            if self.properties.element and self.properties.element.font.file == path:
                self.properties.font_style.setItemText(0, face["style"] + " (saved exact face)")
                self.properties.font_status.setToolTip(path + ("\n" + face["note"] if face["note"] else ""))
        self._worker({"task": "font_info", "file": path}, inspected, lambda error: None)
