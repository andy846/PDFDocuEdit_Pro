"""Visible printing setup, explicit I25 migration and safe front-page placement."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
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


def stock_summary_rows(template, plan, count):
    """Display existing planned stock assignments without scanning records."""
    media = template.media
    if not media.get("enabled"):
        return []
    profile = media.get("printer_profile", {})
    stocks = {stock["id"]: stock for stock in media.get("stocks", [])}
    rows = []
    for stock, sheets in plan.stock_sheets.items():
        mapping = profile.get("mappings", {}).get(stock, {})
        if profile.get("backend") == "postscript":
            from composition.media.model import PrinterProfile
            from composition.media.postscript import selection_request
            effective = selection_request(PrinterProfile.from_dict(profile), stocks[stock])
            request = " · ".join(f"{key} {value}" for key, value in effective.items()
                                 if key != "PageSize" and value is not None)
        else:
            request = mapping.get("catalog_id") or mapping.get("name") or ""
        rows.append((stocks[stock]["name"], sheets if count else 0, request))
    return rows


def plan_summary(template, count, *, plan=None):
    if plan is None:
        plan = build_print_plan(template, max(1, count))
    text = (f"Printing: {'Duplex' if plan.settings.duplex else 'Simplex'}\n"
            f"Records: {count:,} · Template pages per record: {len(template.pages)}\n"
            f"Output pages: {plan.output_pages if count else 0:,} · "
            f"Physical sheets: {plan.sheets if count else 0:,} · "
            f"Inserted blank backs: {plan.inserted_blanks if count else 0:,}")
    media = template.media
    profile = media.get("printer_profile", {})
    backend = profile.get("backend", "pdf") if media.get("enabled") else "pdf"
    text += "\nOutput: " + {"pdf": "PDF", "postscript": "PDF + PostScript", "canon_prismasync": "PDF + JDF"}.get(backend, backend)
    if media.get("enabled"):
        text += "\nPrinter profile: " + (profile.get("profile_name") or "Unnamed profile")
        for name, sheets, request in stock_summary_rows(template, plan, count):
            text += f"\nStock {name}: {sheets:,} sheets" + (" · " + request if request else "")
    barcodes = [element for element in template.all_elements() if element.type in {"qr", "code128", "i25"}]
    text += f"\nTemplate Barcode / QR objects: {len(barcodes)}"
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
        self.printing.setEnabled(False)
        layout.addWidget(self.printing)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        from ui.responsive import scroll_container
        layout.addWidget(scroll_container(self.summary), 1)
        self.settings_button = QPushButton("Return to Design settings…")
        self.return_to_design = False
        self.settings_button.clicked.connect(self.edit_settings)
        layout.addWidget(self.settings_button)
        self.footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.footer.button(QDialogButtonBox.StandardButton.Ok).setText("Generate production PDF")
        self.footer.accepted.connect(self.accept)
        self.footer.rejected.connect(self.reject)
        layout.addWidget(self.footer)
        self.printing.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def edit_settings(self):
        self.return_to_design = True
        self.reject()

    def refresh(self):
        value = self.template.to_dict()
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

    def build_design_settings(self, navigation):
        self.design_printing = printing_combo(self)
        self.design_printing.setItemText(0, "Simplex")
        self.design_printing.setItemText(1, "Duplex")
        self.design_printing.setToolTip("Template printing: Simplex = one page per sheet; Duplex = front / back with odd envelopes padded.")
        self.design_printing.setMaximumWidth(self.fontMetrics().horizontalAdvance("Duplex") + 50)
        self.design_printing.setMinimumWidth(0)
        self.design_printing.setStyleSheet("QComboBox { padding: 2px 4px; min-height: 0px; }")
        self.design_printing.currentIndexChanged.connect(self.change_design_printing)
        navigation.addWidget(self.design_printing)
        self.design_inserter_button = QToolButton()
        self.design_inserter_button.setText("Inserter…")
        self.design_inserter_button.setToolTip("Apply or update existing Inserter I25 control barcodes")
        self.design_inserter_button.setStyleSheet("QToolButton { padding: 2px 6px; min-height: 0px; }")
        menu = QMenu(self.design_inserter_button)
        self.design_place_barcode = QAction("Apply barcode to required fronts…", self)
        self.design_place_barcode.triggered.connect(self.place_inserter_fronts)
        menu.addAction(self.design_place_barcode)
        self.design_update_i25 = QAction("Update I25 sequences…", self)
        self.design_update_i25.triggered.connect(lambda: confirm_i25_update(self, self.template.to_dict()))
        menu.addAction(self.design_update_i25)
        self.design_inserter_button.setMenu(menu)
        self.design_inserter_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.design_inserter_button.hide()
        navigation.addWidget(self.design_inserter_button)

    def build_production_settings(self, layout):
        self.production_media_button = QPushButton("Edit template settings in Design…")
        self.production_media_button.clicked.connect(self.return_to_design_settings)
        layout.addWidget(self.production_media_button)
        self.production_plan = QLabel()
        self.production_plan.setWordWrap(True)
        self.production_plan.setTextFormat(Qt.TextFormat.PlainText)
        self.production_plan.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        from ui.responsive import scroll_container
        plan_scroll = scroll_container(self.production_plan)
        plan_scroll.setMinimumHeight(self.fontMetrics().lineSpacing()*10+12)
        plan_scroll.setMaximumHeight(self.fontMetrics().lineSpacing()*13+12)
        layout.addWidget(plan_scroll)

    def return_to_design_settings(self):
        self.tabs.setCurrentIndex(1)
        self.paper_tray_button.setFocus()

    def refresh_production_settings(self):
        if not hasattr(self, "design_printing"):
            return
        editable = self.production_settings_editable()
        self.design_printing.blockSignals(True)
        self.design_printing.setCurrentIndex(int(bool(self.template.media.get("duplex"))))
        self.design_printing.blockSignals(False)
        self.design_printing.setEnabled(editable and not self.template.media.get("enabled"))
        self.production_media_button.setEnabled(editable)
        inserter = has_inserter(self.template)
        self.design_place_barcode.setVisible(inserter)
        self.design_place_barcode.setEnabled(editable)
        self.design_inserter_button.setVisible(inserter and self.tabs.currentIndex() == 1)
        self.design_inserter_button.setEnabled(editable)
        self.design_update_i25.setVisible(any(needs_inserter_update(e.barcode_profile)
            for e in self.template.all_elements() if e.barcode_profile))
        self.design_update_i25.setEnabled(editable)
        try:
            plan = build_print_plan(self.template, max(1, self.record_count))
            text = plan_summary(self.template, self.record_count, plan=plan)
            if self.template.media.get("enabled"):
                text += "\nPrinting follows Print Media / Stocks."
            if self.design_update_i25.isVisible():
                text += "\nLegacy I25 requires an explicit sequence update before generation."
            self.production_plan.setText(text)
            self.production_console.display_plan(self.template, self.record_count, plan,
                stock_summary_rows(self.template, plan, self.record_count))
        except ValueError as exc:
            self.production_plan.setText(str(exc))
            self.production_console.unavailable_plan(exc)

    def change_design_printing(self):
        duplex = bool(self.design_printing.currentData())
        if self.template.media.get("enabled") or not self.production_settings_editable():
            self.refresh_production_settings()
            return
        if self.properties.apply() is False:
            self.refresh_production_settings()
            return
        before = self.template.to_dict()
        after = copy.deepcopy(before)
        after["media"]["duplex"] = duplex
        self._commit(before, after, "Change template printing")

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
                if dialog.return_to_design:
                    self.return_to_design_settings()
                return False
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
