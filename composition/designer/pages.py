"""Fixed template-page navigation and reversible page commands."""
from __future__ import annotations

import copy
import uuid

from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QLabel, QPushButton

from composition.template.model import MAX_TEMPLATE_PAGES, PageSpec


class PageOperations:
    @property
    def page_index(self):
        return next((i for i, page in enumerate(self.template.pages)
                     if page.id == self.active_page_id), 0)

    @property
    def page(self):
        return self.template.pages[self.page_index]

    def _page_dict(self, value, page_id=None):
        target = page_id or self.active_page_id
        return next((page for page in value["pages"] if page["id"] == target), value["pages"][0])

    def _build_page_navigation(self, layout):
        row = QHBoxLayout()
        row.addWidget(QLabel("Template page"))
        self.page_combo = QComboBox()
        self.page_combo.setAccessibleName("Template page")
        self.page_combo.setMinimumWidth(120)
        self.page_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.page_combo.currentIndexChanged.connect(self.select_template_page)
        row.addWidget(self.page_combo, 1)
        self.page_buttons = {}
        for key, label in (("page_add", "+"), ("page_duplicate", "Duplicate"),
                           ("page_delete", "−"), ("page_up", "←"), ("page_down", "→")):
            button = QPushButton(label)
            button.setToolTip(self.actions[key].text())
            button.setAccessibleName(self.actions[key].text())
            if key != "page_duplicate":
                button.setMaximumWidth(55)
            button.clicked.connect(self.actions[key].trigger)
            self.page_buttons[key] = button
            row.addWidget(button)
        layout.addLayout(row)

    def _refresh_pages(self):
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for index, page in enumerate(self.template.pages):
            self.page_combo.addItem(f"{index+1} · {page.name}", page.id)
        self.page_combo.setCurrentIndex(self.page_index)
        self.page_combo.blockSignals(False)
        self.production_heading.setText(
            f"Production: {len(self.template.pages)} fixed page(s) per record · "
            f"{self.record_count * len(self.template.pages):,} expected pages")
        self._update_page_actions()

    def _update_page_actions(self):
        if not hasattr(self, "page_buttons"):
            return
        editable = not (self.import_worker or self.production_worker or self.font_requests)
        count = len(self.template.pages)
        availability = {
            "page_add": editable and count < MAX_TEMPLATE_PAGES,
            "page_duplicate": editable and count < MAX_TEMPLATE_PAGES,
            "page_delete": editable and count > 1,
            "page_up": editable and self.page_index > 0,
            "page_down": editable and self.page_index < count-1,
            "page_rename": editable,
        }
        for key, enabled in availability.items():
            self.actions[key].setEnabled(enabled)
            if key in self.page_buttons:
                self.page_buttons[key].setEnabled(enabled)

    def select_template_page(self, index):
        if not 0 <= index < len(self.template.pages) or index == self.page_index:
            return
        target = self.template.pages[index].id
        self.properties.apply()
        self._apply_template(self.template.to_dict(), page_id=target)
        self.canvas.fit_page()

    def _page_editable(self):
        if self.import_worker or self.production_worker or self.font_requests:
            self._error("Finish the active font or job operation before editing template pages.")
            return False
        self.properties.apply()
        return True

    def add_template_page(self, duplicate=False):
        if not self._page_editable():
            return
        if len(self.template.pages) >= MAX_TEMPLATE_PAGES:
            self._error(f"A template supports at most {MAX_TEMPLATE_PAGES} fixed pages.")
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        if duplicate:
            page = copy.deepcopy(self._page_dict(after))
            page["id"] = uuid.uuid4().hex
            page["name"] = page["name"] + " copy"
            for element in page["elements"]:
                element["id"] = uuid.uuid4().hex
        else:
            from dataclasses import asdict
            page = asdict(PageSpec(name=f"Page {len(after['pages'])+1}",
                                   width_mm=self.page.width_mm, height_mm=self.page.height_mm))
        after["pages"].insert(self.page_index+1, page)
        self._commit(before, after, "Duplicate template page" if duplicate else "Add template page",
                     [], page_id=page["id"])
        self.canvas.fit_page()

    def delete_template_page(self):
        if not self._page_editable():
            return
        if len(self.template.pages) == 1:
            self._error("Keep at least one template page.")
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        after["pages"].pop(self.page_index)
        target = after["pages"][min(self.page_index, len(after["pages"])-1)]["id"]
        self._commit(before, after, "Delete template page", [], page_id=target)
        self.canvas.fit_page()

    def move_template_page(self, direction):
        if not self._page_editable():
            return
        destination = self.page_index + direction
        if not 0 <= destination < len(self.template.pages):
            return
        before, after = self.template.to_dict(), self.template.to_dict()
        page = after["pages"].pop(self.page_index)
        after["pages"].insert(destination, page)
        self._commit(before, after, "Reorder template pages", [])

    def rename_template_page(self):
        if not self._page_editable():
            return
        name, ok = QInputDialog.getText(self, "Page name", "Name", text=self.page.name)
        if ok and name.strip():
            before, after = self.template.to_dict(), self.template.to_dict()
            self._page_dict(after)["name"] = name.strip()
            self._commit(before, after, "Rename template page")
