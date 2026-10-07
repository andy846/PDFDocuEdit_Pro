"""Visible printing setup, explicit I25 migration and safe front-page placement."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
)

from composition.engine.barcode_profiles import (
    INSERTER_I25,
    BarcodeProfile,
    has_inserter,
    needs_inserter_update,
    updated_inserter,
)
from composition.media.planner import build_print_plan
from composition.template.model import Template
from ui.combo_popup import WideComboBox


def printing_combo(parent=None):
    control = WideComboBox(parent)
    control.addItem("Simplex — one page per physical sheet", False)
    control.addItem("Duplex — front / back, pad odd envelopes", True)
    control.setAccessibleName("Production printing: Simplex or Duplex")
    return control


class ProductionScroll(QScrollArea):
    """Keep printing settings and result actions reachable at small window sizes."""
    def __init__(self, page, actions):
        super().__init__()
        self.actions = actions
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setMinimumSize(0, 0)
        self.setWidget(page)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        needed = sum(self.actions.itemAt(i).widget().minimumSizeHint().width()
                     for i in range(self.actions.count())) + max(0, self.actions.count()-1)*self.actions.spacing() + 24
        direction = QBoxLayout.Direction.TopToBottom if self.viewport().width() < needed else QBoxLayout.Direction.LeftToRight
        if self.actions.direction() != direction:
            self.actions.setDirection(direction)


def plan_summary(template, count):
    plan = build_print_plan(template, max(1, count))
    text = (f"Printing: {'Duplex' if plan.settings.duplex else 'Simplex'}\n"
            f"Records: {count:,} · Template pages per record: {len(template.pages)}\n"
            f"Output pages: {plan.output_pages if count else 0:,} · "
            f"Physical sheets: {plan.sheets if count else 0:,} · "
            f"Inserted blank backs: {plan.inserted_blanks if count else 0:,}")
    if has_inserter(template):
        text += (f"\nRequired control barcodes: {plan.sheets if count else 0:,} — one per sheet front.\n"
                 "Group: first envelope 00, unchanged within an envelope.\n"
                 "Sheet: whole job 00–99, wraps to 00; never resets at an envelope boundary.")
        pattern = [plan.page(1, index) for index in range(1, plan.settings_for(1).output_pages_per_envelope+1)]
        fronts = [p.role+1 for p in pattern if p.source_page is not None and p.fields()["Side"] == "Front"]
        # Inspect only one template pattern; do not scan all records in the GUI.
        missing = [index for index in fronts if not any(e.barcode_profile.get("preset") == INSERTER_I25
                                                       for e in template.pages[index-1].elements)]
        if missing:
            text += ("\nFront template pages without an I25 control barcode: " + ", ".join(map(str, missing)) +
                     ". If these are backs, choose Duplex; otherwise apply barcode to required fronts.")
        text += "\nAll records, visibility rules and barcode dimensions are checked in the background before composition."
    return text


def confirm_i25_update(window, value, *, overlay=False):
    """One atomic Undo operation, only after the user confirms a semantic change."""
    profiles = ([item for item in value["objects"] if item.get("profile")]
                if overlay else [e for p in value["pages"] for e in p["elements"] if e.get("barcode_profile")])
    key = "profile" if overlay else "barcode_profile"
    legacy = [item for item in profiles if needs_inserter_update(item[key])]
    if not legacy:
        return True
    answer = QMessageBox.question(window, "Update I25 sequences",
        f"This project has {len(legacy)} legacy I25 object(s). Their sheet sequence resets at each envelope.\n\n"
        "Update to the current rule?\nGroup: first envelope 00; all sheets in that envelope share its value.\n"
        "Sheet: first physical sheet 00; continues across envelopes and wraps after 99.\n\n"
        "Existing group starts will become 00. Inserts, customer fields and placement are preserved. "
        "Machine verification is reset to pending. One Undo restores the previous settings.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
    if answer != QMessageBox.StandardButton.Yes:
        return False
    after = copy.deepcopy(value)
    targets = after["objects"] if overlay else [e for p in after["pages"] for e in p["elements"]]
    for item in targets:
        if item.get(key) and needs_inserter_update(item[key]):
            item[key] = updated_inserter(BarcodeProfile.from_dict(item[key])).to_dict()
    if overlay:
        window.commit(after, "Update I25 sequences")
    else:
        window._commit(value, after, "Update I25 sequences")
    return True


class ProductionReviewDialog(QDialog):
    def __init__(self, template, count, parent=None):
        super().__init__(parent)
        self.template, self.count = template, count
        self.setWindowTitle("Review production printing")
        screen = self.screen().availableGeometry()
        self.resize(min(640, screen.width()-24), min(480, screen.height()-24))
        layout = QVBoxLayout(self)
        self.printing = printing_combo(self)
        self.printing.setCurrentIndex(int(bool(template.media.get("duplex"))))
        self.printing.setEnabled(not template.media.get("enabled"))
        layout.addWidget(self.printing)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        from ui.responsive import scroll_container
        layout.addWidget(scroll_container(self.summary), 1)
        self.settings_button = QPushButton("Review Media / barcode placement in Production…")
        self.settings_button.clicked.connect(self.reject)
        layout.addWidget(self.settings_button)
        self.footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.footer.button(QDialogButtonBox.StandardButton.Ok).setText("Generate production PDF")
        self.footer.accepted.connect(self.accept)
        self.footer.rejected.connect(self.reject)
        layout.addWidget(self.footer)
        self.printing.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        value = self.template.to_dict()
        value["media"]["duplex"] = bool(self.printing.currentData())
        try:
            self.summary.setText(plan_summary(Template.from_dict(value), self.count) +
                                 ("\nPrinting follows Print Media / Stocks." if self.template.media.get("enabled") else ""))
            self.footer.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        except ValueError as exc:
            self.summary.setText(str(exc))
            self.footer.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)


class ProductionSettings:
    def production_settings_editable(self):
        return not (self.production_worker or self.import_worker or self.content_invalid or self.font_requests
                    or getattr(self, "batch_pending", False)
                    or any(getattr(w, "task", "") == "background" for w in self.workers))

    def build_production_settings(self, layout):
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.production_printing = printing_combo(self)
        self.production_printing.currentIndexChanged.connect(self.change_production_printing)
        form.addRow("Printing", self.production_printing)
        self.production_media_button = QPushButton("Print Media / Stocks…")
        self.production_media_button.clicked.connect(self.edit_print_media)
        form.addRow(self.production_media_button)
        layout.addLayout(form)
        self.production_plan = QLabel()
        self.production_plan.setWordWrap(True)
        self.production_plan.setTextFormat(Qt.TextFormat.PlainText)
        self.production_plan.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        from ui.responsive import scroll_container
        plan_scroll = scroll_container(self.production_plan)
        plan_scroll.setMinimumHeight(self.fontMetrics().lineSpacing()*10+12)
        plan_scroll.setMaximumHeight(self.fontMetrics().lineSpacing()*13+12)
        layout.addWidget(plan_scroll)
        self.production_update_i25 = QPushButton("Update I25 sequences…")
        self.production_update_i25.clicked.connect(lambda: confirm_i25_update(self, self.template.to_dict()))
        layout.addWidget(self.production_update_i25)
        self.production_place_barcode = QPushButton("Apply barcode to required fronts…")
        self.production_place_barcode.clicked.connect(self.place_inserter_fronts)
        layout.addWidget(self.production_place_barcode)

    def refresh_production_settings(self):
        if not hasattr(self, "production_printing"):
            return
        editable = self.production_settings_editable()
        self.production_printing.blockSignals(True)
        self.production_printing.setCurrentIndex(int(bool(self.template.media.get("duplex"))))
        self.production_printing.blockSignals(False)
        self.production_printing.setEnabled(editable and not self.template.media.get("enabled"))
        self.production_media_button.setEnabled(editable)
        inserter = has_inserter(self.template)
        self.production_place_barcode.setVisible(inserter)
        self.production_place_barcode.setEnabled(editable)
        self.production_update_i25.setVisible(any(needs_inserter_update(e.barcode_profile)
            for e in self.template.all_elements() if e.barcode_profile))
        self.production_update_i25.setEnabled(editable)
        try:
            text = plan_summary(self.template, self.record_count)
            if self.template.media.get("enabled"):
                text += "\nPrinting follows Print Media / Stocks."
            if not self.production_update_i25.isHidden():
                text += "\nLegacy I25 requires an explicit sequence update before generation."
            self.production_plan.setText(text)
        except ValueError as exc:
            self.production_plan.setText(str(exc))

    def change_production_printing(self):
        duplex = bool(self.production_printing.currentData())
        if self.template.media.get("enabled") or not self.production_settings_editable():
            self.refresh_production_settings()
            return
        if self.properties.apply() is False:
            self.refresh_production_settings()
            return
        before = self.template.to_dict()
        after = copy.deepcopy(before)
        after["media"]["duplex"] = duplex
        self._commit(before, after, "Change production printing")

    def review_production_printing(self):
        if not self.production_settings_editable():
            return False
        if not has_inserter(self.template):
            return True
        self.tabs.setCurrentIndex(3)
        if not confirm_i25_update(self, self.template.to_dict()):
            return False
        dialog = ProductionReviewDialog(self.template, self.record_count, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            before = self.template.to_dict()
            after = copy.deepcopy(before)
            after["media"]["duplex"] = bool(dialog.printing.currentData())
            self._commit(before, after, "Confirm production printing")
            return True
        finally:
            dialog.deleteLater()

    def place_inserter_fronts(self):
        if not self.production_settings_editable() or self.properties.apply() is False:
            return
        candidates = [(p, e) for p in self.template.pages for e in p.elements
                      if e.barcode_profile.get("preset") == INSERTER_I25]
        if not candidates:
            return
        labels = [f"Page {i+1} · {e.id}" for p, e in candidates for i, page in enumerate(self.template.pages) if page.id == p.id]
        selected = self.canvas.selected_ids()
        default = next((i for i, (_p, e) in enumerate(candidates) if e.id in selected), 0)
        label, ok = QInputDialog.getItem(self, "Sheet-front barcode placement", "Use barcode from:", labels, default, False)
        if not ok:
            return
        page, element = candidates[labels.index(label)]
        if not confirm_i25_update(self, self.template.to_dict()):
            return
        # Resolve after migration so the old dataclass cannot overwrite the upgraded profile.
        element = next(e for e in self.template.all_elements() if e.id == element.id)
        from .barcode_operations import apply_template_profile
        before = self.template.to_dict()
        try:
            after, summary = apply_template_profile(before, page.id, element.id,
                BarcodeProfile.from_dict(element.barcode_profile), bool(self.template.media.get("duplex")), True)
            accepted = QMessageBox.question(self, "Apply barcode to required fronts", summary +
                "\nExisting single control barcodes on target fronts will be replaced with this barcode's settings. Apply?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if accepted == QMessageBox.StandardButton.Yes:
                self._commit(before, after, "Apply barcode to required fronts", element.id)
        except ValueError as exc:
            self._error(str(exc))
