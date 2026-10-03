"""Document Designer interaction state: compact inspector, content drafts and canvas views."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTransform

from composition.template.model import CompositionError, Template

from .rule_controls import rules_summary


class DesignerUsability:
    def _init_usability(self):
        self.content_invalid = False
        self.page_views = {}
        self.compact_inspector = False
        self.inspector_selection = None
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.setInterval(70)
        self.layout_timer.timeout.connect(self._adjust_inspector)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "layout_timer"):
            self.layout_timer.start()

    def _adjust_inspector(self):
        compact = self.width() < 1100
        if compact != self.compact_inspector:
            self.compact_inspector = compact
            if compact:
                self.left_panel.addTab(self.properties_scroll, "Properties")
                self.left_panel.setMinimumWidth(270)
                self.splitter.setSizes([290, max(250, self.width()-330)])
                if self.canvas.selected_ids() and self.actions["properties"].isChecked():
                    self.left_panel.setCurrentWidget(self.properties_scroll)
            else:
                index = self.left_panel.indexOf(self.properties_scroll)
                if index >= 0:
                    self.left_panel.removeTab(index)
                self.splitter.addWidget(self.properties_scroll)
                self.left_panel.setMinimumWidth(150)
                self.splitter.setSizes([200, max(260, self.width()-500), 280])
        self.description.hide()
        self._show_properties(self.actions["properties"].isChecked())
        button = self.project_toolbar.widgetForAction(self.actions["properties"])
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                                  if self.width() >= 900 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._update_actions()

    def _show_properties(self, visible):
        visible = visible and self.tabs.currentIndex() != 2
        if self.compact_inspector:
            index = self.left_panel.indexOf(self.properties_scroll)
            if index >= 0:
                if not visible and self.left_panel.currentIndex() == index:
                    self.left_panel.setCurrentIndex(0)
                self.left_panel.setTabVisible(index, visible)
            # QTabWidget controls the visibility of inactive pages.
            if visible:
                self.properties_scroll.setVisible(self.left_panel.currentWidget() is self.properties_scroll)
        else:
            self.properties_scroll.setVisible(visible)

    def reveal_properties(self):
        """Expose the inspector without taking keyboard focus away from the canvas."""
        self.actions["properties"].setChecked(True)
        self.actions["data_panel"].setChecked(True)
        self.left_panel.show()
        self._show_properties(True)
        if self.compact_inspector:
            self.left_panel.setCurrentWidget(self.properties_scroll)

    def toggle_properties_panel(self, visible):
        if visible or not self.properties_scroll.isVisible():
            if self.tabs.currentIndex() != 1:
                self.tabs.setCurrentIndex(1)
            self.reveal_properties()
        else:
            self._show_properties(False)

    def _filter_layers(self, *args):
        query = self.layer_filter.text().casefold()
        for index in range(self.layers.count()):
            item = self.layers.item(index)
            item.setHidden(query not in (item.text() + item.toolTip()).casefold())

    def focus_properties(self):
        self.reveal_properties()
        self.properties_scroll.ensureWidgetVisible(self.properties.content)
        if self.properties.element and self.properties.element.type in {"text", "qr", "code128", "i25"}:
            self.properties.content.setFocus()
        else:
            self.properties.numbers["x_mm"].setFocus()

    def _remember_canvas_view(self):
        if not self.canvas.template:
            return
        centre = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.page_views[self.active_page_id] = (
            QTransform(self.canvas.transform()), centre, self.canvas.selected_ids())

    def _restore_canvas_view(self):
        view = self.page_views.get(self.active_page_id)
        if view:
            self.canvas.setTransform(view[0])
            self.canvas.centerOn(view[1])
        else:
            self.canvas.fit_page()
        self.canvas.zoomChanged.emit(self.canvas.transform().m11()/(96/25.4))

    def _set_content_error(self, message):
        was_invalid = self.content_invalid
        self.content_invalid = bool(message)
        self.properties.draft_status.setText(message)
        self.properties.draft_status.setVisible(bool(message))
        self.properties.revert_content.setVisible(bool(message))
        if message:
            self.preview_generation += 1
            self.preview_timer.stop()
            self.preview_review.hide()
            self.canvas.set_preview(None)
            self.preview_state.setText("Edit needs attention; correct the value or revert the draft.")
        self._busy()
        if was_invalid and not message:
            self._schedule_preview()

    def revert_content_draft(self):
        element = self.properties.element
        self._set_content_error("")
        if element:
            self.properties.show_element(element)
        self._schedule_preview()

    def _edit_property_values(self, values):
        if not self.properties.element:
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        object_id = self.properties.element.id
        target = next(e for e in self._page_dict(after)["elements"] if e["id"] == object_id)
        original = dict(target)
        target.update(values)
        try:
            Template.from_dict(after)
        except CompositionError as exc:
            # Retain an incomplete field reference in the editor, never produce the old value.
            self._set_content_error(str(exc))
            return
        self._set_content_error("")
        text_only = {key: value for key, value in target.items() if key != "value"} == {
            key: value for key, value in original.items() if key != "value"}
        self._commit(before, after, "Edit text content" if text_only else "Edit object properties",
                     object_id, content_only=object_id if text_only else None)

    def _apply_text_update(self, template, selected):
        self.template = template
        self.canvas.template = template
        elements = {e.id: e for e in self.page.elements}
        for item in self.canvas.element_items:
            item.element = elements[item.element.id]
            item.setToolTip(item.element.type + ": " + item.element.value + "\n" + rules_summary(item.element.rules))
        element = elements.get(selected)
        self.properties.element = element
        if element and self.properties.content.toPlainText() != element.value:
            self.properties.loading = True
            self.properties.content.setPlainText(element.value)
            self.properties.loading = False
        for index in range(self.layers.count()):
            item = self.layers.item(index)
            element = elements.get(item.data(256))
            if element:
                value = element.value.replace("\n", " ")[:45] or element.type.title()
                badge = "[Rule] " if element.rules.visible_when or element.rules.alternative else ""
                item.setText(f"{badge}{element.type.title()} · {value}")
                item.setToolTip(value + "\n" + element.id)
        self._filter_layers()
        self._title()
        self._schedule_preview()

    def _restrict_editing(self):
        busy = bool(self.import_worker or self.production_worker)
        pending = bool(self.font_requests or any(getattr(worker, "task", "") == "background"
                                               for worker in self.workers))
        editable = not (busy or self.content_invalid)
        for key, action in self.actions.items():
            if not editable and (key.startswith(("insert_", "arrange_")) or
                                 key in {"variable", "cut", "paste", "duplicate", "delete", "cjk", "repair_glyph", "edit_rules", "clear_rules"}):
                action.setEnabled(False)
        self.actions["preview"].setEnabled(not self.content_invalid)
        self.remap_button.setEnabled(not (busy or self.content_invalid))
        self.canvas.set_editable(editable)
        self.properties.setEnabled(not (busy or self.font_requests))
        self.properties.rules_button.setEnabled(self.actions["edit_rules"].isEnabled() and not pending)
        self.properties.rules_clear.setEnabled(self.actions["clear_rules"].isEnabled() and not pending)
        if pending:
            self.actions["edit_rules"].setEnabled(False)
            self.actions["clear_rules"].setEnabled(False)
        self.import_button.setEnabled(not busy and not self.content_invalid)
        for key in ("save", "save_as", "generate"):
            self.actions[key].setEnabled(self.actions[key].isEnabled()
                                         and not self.content_invalid and not pending)
        self.generate_button.setEnabled(self.generate_button.isEnabled()
                                         and not self.content_invalid and not pending)
        self.actions["undo"].setEnabled(self.undo.canUndo() and editable)
        self.actions["redo"].setEnabled(self.undo.canRedo() and editable)
        for key in ("background", "remove_background", "rename", "import", "page_size",
                    "page_add", "page_duplicate", "page_delete", "page_up", "page_down",
                    "page_rename", "page_previous", "page_next", "preview"):
            if self.content_invalid:
                self.actions[key].setEnabled(False)
        self.page_combo.setEnabled(not self.content_invalid)
        self.font_size_tool.setEnabled(self.font_size_tool.isEnabled() and editable and not pending)
        for key, button in self.page_buttons.items():
            button.setEnabled(self.actions[key].isEnabled())
        for index in (0, 2, 3):
            self.tabs.setTabEnabled(index, not self.content_invalid)
        self._update_navigation()
        self.record.setEnabled(not self.content_invalid and self.record_count > 0)
        if self.content_invalid:
            for button in (self.first, self.previous, self.next, self.last):
                button.setEnabled(False)

