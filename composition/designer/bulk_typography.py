"""Selected-text formatting with one Undo command and one exact-face preparation."""
from __future__ import annotations

import uuid
from dataclasses import asdict

from PyQt6.QtWidgets import QInputDialog


class BulkTypography:
    def _selected_text(self):
        ids = set(self.canvas.selected_ids())
        return [e for e in self.page.elements if e.id in ids and
                (e.type == "text" or (self.properties.include_barcode.isChecked() and e.type in {"code128", "i25"} and e.show_barcode_text))]

    def _bulk_editable(self):
        return not (self.content_invalid or self.import_worker or self.production_worker
                    or self.canvas.mode_preview or self.close_pending
                    or any(getattr(w, "task", "") == "background" for w in self.workers))

    def _edit_bulk_properties(self, values):
        if not self._bulk_editable() or self.font_requests:
            return
        ids = self.properties.bulk_ids
        if set(ids) != {e.id for e in self._selected_text()} or not ids:
            return
        if set(values) - {"font", "align", "vertical_align", "line_spacing", "colour"}:
            return
        if "font" in values and (not isinstance(values["font"], dict) or
                                set(values["font"]) - {"family", "file", "bold", "italic", "size_pt"}):
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        for target in self._page_dict(after)["elements"]:
            if target["id"] in ids:
                for key, value in values.items():
                    if key == "font":
                        target["font"].update(value)
                    else:
                        target[key] = value
        self._commit(before, after, f"Format {len(ids)} selected text objects", self.canvas.selected_ids())

    def _request_bulk_font(self, request):
        ids = list(request["element_ids"])
        if request.get("cancel"):
            for object_id in ids:
                self.font_requests.pop(object_id, None)
            self._busy()
            return
        if not self._bulk_editable() or self.font_requests:
            return
        text = self._selected_text()
        if not ids or set(ids) != {e.id for e in text}:
            return
        token, epoch = uuid.uuid4().hex, self.font_epoch
        expected = {e.id: asdict(e.font) for e in text}
        self.font_requests.update({object_id: token for object_id in ids})
        self.message.setText(f"Preparing one exact font face for {len(ids)} text objects...")
        self._busy()

        def active():
            return (epoch == self.font_epoch and not self.close_pending and
                    all(self.font_requests.get(i) == token for i in ids))

        def finish(error=None):
            matched = any(self.font_requests.get(i) == token for i in ids)
            for object_id in ids:
                if self.font_requests.get(object_id) == token:
                    self.font_requests.pop(object_id, None)
            if self.close_pending or not matched:
                return
            current = self.canvas.selected_ids()
            self._selection(current[0] if len(current) == 1 else "")
            self._busy()
            if error:
                self._error(error)

        def ready(result):
            if not active():
                finish()
                return
            targets = {e.id: e for e in self.template.all_elements() if e.id in ids}
            if len(targets) != len(ids) or any(asdict(targets[i].font) != expected[i] for i in ids):
                finish("Selected font settings changed while loading. No batch font change applied.")
                return
            before, after = self.template.to_dict(), self.template.to_dict()
            if result["file"]:
                self.properties.file_faces[result["file"]] = result
            for target in (e for p in after["pages"] for e in p["elements"] if e["id"] in ids):
                target["font"].update(family=result["family"], file=result["file"], bold=False, italic=False)
            for object_id in ids:
                self.font_requests.pop(object_id, None)
            self._commit(before, after, f"Select exact font for {len(ids)} text objects",
                         self.canvas.selected_ids())
            self.message.setText(f"{result['family']} / {result['style']} applied to {len(ids)} text objects; individual sizes and glyph repairs retained.")
            self._busy()

        def export(face):
            if not active():
                finish()
                return
            self._worker({"task": "font_export", "face": face,
                          "directory": str(self.directory / "font-faces")}, ready, finish)

        def inspected(result):
            if not active():
                finish()
                return
            faces = result["faces"]
            if len(faces) > 1:
                labels = [face["family"] + " / " + face["style"] for face in faces]
                label, ok = QInputDialog.getItem(self, "Choose exact font face",
                                                "Font collection / variable style", labels, 0, False)
                if not ok:
                    finish("Font selection cancelled. No batch change applied.")
                    return
                face = faces[labels.index(label)]
            else:
                face = faces[0]
            export(face)

        if "file" in request:
            self._worker({"task": "font_info", "file": request["file"]}, inspected, finish)
        else:
            export(request["face"])
