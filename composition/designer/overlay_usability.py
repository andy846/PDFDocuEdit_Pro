"""Object discovery and immediate barcode feedback for the PDF overlay workspace."""
from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem, QMessageBox

from composition.engine.barcodes import validate_payload
from composition.pdf_source.planner import EnvelopePlan, applies

from .overlay_dialogs import SCOPE_LABELS


class OverlayUsability:
    def filter_system_fields(self, text):
        query = text.casefold()
        for row in range(self.fields.count()):
            item = self.fields.item(row)
            item.setHidden(query not in item.text().casefold())

    def filter_layers(self, *args):
        query = self.object_filter.text().casefold()
        for row in range(self.layers.count()):
            item = self.layers.item(row)
            item.setHidden(query not in (item.text() + item.toolTip()).casefold())
        if hasattr(self, "layer_type"):
            from .selection_tools import filter_types
            filter_types(self)

    def sync_layers(self):
        objects = self.spec.objects if self.spec else []
        signature = [(obj.element.id, obj.element.type, obj.element.value, obj.scope,
                      obj.letter_page, obj.control, obj.profile.name if obj.profile else "") for obj in objects]
        self.layers.blockSignals(True)
        try:
            if signature != getattr(self, "layer_signature", None):
                scroll = self.layers.verticalScrollBar().value()
                self.layers.clear()
                scopes = {value: label for label, value in SCOPE_LABELS}
                for obj in objects:
                    content = obj.profile.name if obj.profile else obj.element.value.replace("\n", " ")
                    suffix = " [Control]" if obj.control else ""
                    item = QListWidgetItem(f"{obj.element.type.upper()}{suffix} · {content[:70]}")
                    item.setData(Qt.ItemDataRole.UserRole, obj.element.id)
                    item.setToolTip(f"{content}\n{scopes[obj.scope]}\nObject: {obj.element.id}")
                    self.layers.addItem(item)
                self.layers.verticalScrollBar().setValue(scroll)
                self.layer_signature = signature
            selected = set(self.canvas.selected_ids())
            for row in range(self.layers.count()):
                item = self.layers.item(row)
                item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selected)
            self.filter_layers()
        finally:
            self.layers.blockSignals(False)

    def select_layer_objects(self, ids=None):
        if hasattr(self, "batch_editor") and not self.batch_editor.resolve():
            self.sync_layers()
            return
        if not self.spec or self.active_worker or self.font_token or self.draft_error:
            return
        ids = ids if ids is not None else [item.data(Qt.ItemDataRole.UserRole) for item in self.layers.selectedItems()]
        chosen = [obj for obj in self.spec.objects if obj.element.id in ids]
        if not chosen:
            self.canvas.select_ids([])
            return
        plan = EnvelopePlan(self.spec.source.pages, self.spec.settings)
        current = self.print_page.value()
        candidates = [current, *[page for page in range(1, plan.settings_for(self.envelope.value()).output_pages_per_envelope + 1) if page != current]]
        for page in candidates:
            fields = plan.page(self.envelope.value(), page).fields("preview")
            if all(applies(obj.scope, fields, obj.letter_page) for obj in chosen):
                if self.preview_only.isChecked():
                    self.preview_only.setChecked(False)
                self.print_page.setValue(page)
                self.canvas.select_ids([obj.element.id for obj in chosen])
                return
        if self.spec.needs_source_review and len(chosen) == 1:
            answer = QMessageBox.question(self, "Review object page scope",
                "This object's page scope is unavailable in the updated PDF.\n"
                "Change it to all source pages so you can review and repair the object?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                raw = self.spec.to_dict()
                next(item for item in raw["objects"] if item["element"]["id"] == chosen[0].element.id)["scope"] = "all_source"
                self.commit(raw, "Review unavailable object scope", [chosen[0].element.id])
                return
        self.sync_layers()
        self.error("These objects use different pages. Select objects sharing a page to edit together.")

    def update_payload_summary(self, obj):
        self.payload_summary.setVisible(bool(obj and obj.profile))
        if not obj or not obj.profile:
            return
        try:
            fields = EnvelopePlan(self.spec.source.pages, self.spec.settings).page(
                self.envelope.value(), self.print_page.value()).fields("preview")
            payload = obj.profile.payload(fields)
            validate_payload(obj.element.type, payload)
            text = f"Payload: {payload}\n{len(payload)} characters · {obj.profile.name}"
        except ValueError as exc:
            text = "Payload needs attention: " + str(exc)
        self.payload_summary.setText(text)
        self.payload_summary.setToolTip(text)

    def focus_overlay_properties(self):
        self.inspector.show()
        self.inspector.raise_()
        if self.properties.bulk_ids:
            target = self.properties.numbers["font_size"]
        elif self.profile_button.isEnabled():
            target = self.profile_button
        else:
            target = self.properties.content
        self.inspector_scroll.ensureWidgetVisible(target)
        target.setFocus()

    def preview_failed(self, message, generation):
        if generation != self.preview_generation or self.close_pending or self.draft_error:
            return
        match = re.search(r"object ([a-f0-9]{32})", message)
        self.preview_error_object = match.group(1) if match else None
        self.canvas.set_preview(None)
        self.preview_status.setText('<a href="review">Preview failed · Review object</a>' if match else "Preview failed")
        self.preview_status.setToolTip(message)
        self.error(message)

    def review_preview_error(self, *args):
        if self.preview_error_object:
            self.select_layer_objects([self.preview_error_object])
            self.focus_overlay_properties()
