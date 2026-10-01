"""Asynchronous font inventory and face selection, separate from page/job logic."""
from __future__ import annotations

import uuid

from PyQt6.QtWidgets import QInputDialog


class FontOperations:
    def _load_windows_fonts(self):
        if self.close_pending:
            return
        self._worker({"task": "fonts"}, self.properties.set_catalogue,
                     lambda error: self.properties.font_status.setText("Windows fonts unavailable: " + error))

    def _request_font(self, request):
        if self.import_worker or self.production_worker:
            self._error("Finish the active job before changing fonts.")
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
        if "file" in request:
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
                self._export_font(face, object_id, token, epoch)
            self._worker({"task": "font_info", "file": request["file"]}, inspected,
                         lambda error: self._font_failed(object_id, token, error))
        else:
            self._export_font(request["face"], object_id, token, epoch)

    def _export_font(self, face, object_id, token, epoch):
        self._worker({"task": "font_export", "face": face,
                      "directory": str(self.directory / "font-faces")},
                     lambda result: self._font_ready(result, object_id, token, epoch),
                     lambda error: self._font_failed(object_id, token, error))

    def _font_ready(self, result, object_id, token, epoch):
        if self.font_requests.get(object_id) != token:
            return
        self.font_requests.pop(object_id, None)
        if epoch != self.font_epoch or self.close_pending:
            self._busy()
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        target = next((e for e in after["elements"] if e["id"] == object_id), None)
        if target is not None:
            self.properties.file_faces[result["file"]] = result
            target["font"].update(family=result["family"], file=result["file"], bold=False, italic=False)
            self._commit(before, after, "Select exact Windows font face", self.canvas.selected_ids())
            self.message.setText(result.get("note") or
                                 f"{result['family']} · {result['style']} selected for PDF embedding.")
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
