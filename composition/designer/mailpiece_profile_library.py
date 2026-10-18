"""Small source-free profile library; all disk operations use the existing worker."""

from __future__ import annotations

import copy

from PyQt6 import sip
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from composition.pdf_source.profile_library import new_profile, new_rule, validate_profile
from composition.template.model import CompositionError


class ProfileLibraryDialog(QDialog):
    def __init__(self, window, taught_config=None, *, root=None, parent=None):
        super().__init__(parent or window)
        from core.resources import data_dir

        self.window = window
        self.root = str(root or data_dir() / "composition" / "mailpiece-profiles")
        self.taught_config = copy.deepcopy(taught_config)
        self.value = None
        self.selected_profile = None
        self.saved = None
        self.busy = False
        self.closed = False
        self.setWindowTitle("Mailpiece Detection Profile Library")
        self.resize(840, 620)
        outer = QVBoxLayout(self)
        help_text = QLabel(
            "Profiles contain recognition rules only. Teach regions in the detection preview, then add or replace a rule here. Every new PDF still needs a scan and explicit boundary review."
        )
        help_text.setWordWrap(True)
        outer.addWidget(help_text)
        splitter = QSplitter()
        self.entries = QListWidget()
        self.entries.currentRowChanged.connect(self.open_selected)
        splitter.addWidget(self.entries)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name = QLineEdit()
        self.name.setMaxLength(120)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(64)
        self.revision = QLabel()
        self.rules = QTableWidget(0, 3)
        self.rules.setHorizontalHeaderLabels(["Document type / rule", "TemplateID", "Primary signal"])
        self.rules.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rules.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rules.horizontalHeader().setStretchLastSection(True)
        self.rules.setMinimumWidth(0)
        self.primary = QComboBox()
        self.combination = QComboBox()
        self.combination.addItem("Primary + optional corroborating signals", "any")
        self.combination.addItem("Require all configured signals at a start", "all")
        for control in (self.primary, self.combination):
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.primary.currentIndexChanged.connect(self.signal_settings_changed)
        self.combination.currentIndexChanged.connect(self.signal_settings_changed)
        self.rule_detail = QPlainTextEdit()
        self.rule_detail.setReadOnly(True)
        self.rule_detail.setMaximumHeight(120)
        self.rules.currentCellChanged.connect(self.show_rule)
        self.rules.itemChanged.connect(self.rules_changed)
        self.name.textChanged.connect(self.changed)
        self.description.textChanged.connect(self.changed)
        for label, widget in (
            ("Profile name", self.name),
            ("Description", self.description),
            ("Revision", self.revision),
            ("Detection rules (maximum 16)", self.rules),
            ("Primary signal", self.primary),
            ("Verification", self.combination),
            ("Recognition details", self.rule_detail),
        ):
            form.addRow(label, widget)
        self.actions = []
        for title, callback in (
            ("Create profile", self.create_profile),
            ("Save revision / rename", self.save_revision),
            ("Duplicate profile…", self.duplicate_profile),
            ("Import .pdmp / .pdmpx…", self.import_profile),
            ("Export .pdmpx…", self.export_profile),
            ("Add taught rule", self.add_taught_rule),
            ("Replace selected with taught rule", self.replace_taught_rule),
            ("Remove selected rule", self.remove_rule),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            form.addRow(button)
            self.actions.append(button)
        scroll.setWidget(self.editor)
        splitter.addWidget(scroll)
        splitter.setSizes([220, 580])
        outer.addWidget(splitter, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        bottom = QHBoxLayout()
        self.use_button = QPushButton("Use saved profile")
        self.use_button.clicked.connect(self.use_profile)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        bottom.addStretch()
        bottom.addWidget(self.use_button)
        bottom.addWidget(close)
        outer.addLayout(bottom)
        self.use_button.setEnabled(False)
        self.records = []
        QTimer.singleShot(0, self.refresh)

    def task(self, operation, ready, **arguments):
        if self.busy or self.closed or self.window.active_worker:
            return
        self.busy = True
        self.editor.setEnabled(False)
        self.entries.setEnabled(False)
        self.use_button.setEnabled(False)
        self.status.setText("Working…")

        def delivered(value):
            if self.closed or sip.isdeleted(self):
                return
            ready(value)

        def failed(message):
            if not self.closed and not sip.isdeleted(self):
                self.status.setText(message)

        self.pending_worker = self.window.worker(
            {"task": "mailpiece_library", "operation": operation, "root": self.root, **arguments},
            delivered,
            failed,
            active=True,
        )

        def ended():
            if self.closed or sip.isdeleted(self):
                return
            self.busy = False
            self.editor.setEnabled(True)
            self.entries.setEnabled(True)
            self.update_use()

        if self.pending_worker:
            self.pending_worker.ended.connect(ended)
        else:
            ended()

    def refresh(self):
        def ready(result):
            self.records = result["entries"]
            self.entries.blockSignals(True)
            self.entries.clear()
            for entry in self.records:
                self.entries.addItem(f"{entry['name']} · r{entry['revision']}")
            self.entries.blockSignals(False)
            self.status.setText(
                "; ".join(result["errors"]) if result["errors"] else f"{len(self.records)} saved profiles"
            )

        self.task("list", ready)

    def open_selected(self, index):
        if 0 <= index < len(self.records) and not self.busy:
            self.task(
                "read",
                lambda result: self.display(result["profile"]),
                profile_id=self.records[index]["profile_id"],
            )

    def display(self, value, *, saved=True):
        self.value = copy.deepcopy(value)
        self.saved = copy.deepcopy(value) if saved else None
        self.name.blockSignals(True)
        self.description.blockSignals(True)
        self.name.setText(value["name"])
        self.description.setPlainText(value["description"])
        self.name.blockSignals(False)
        self.description.blockSignals(False)
        self.revision.setText(f"{value['revision']} · {value['profile_id']}")
        self.populate_rules()
        self.update_use()

    def create_profile(self):
        if not self.busy:
            self.display(new_profile("New profile"), saved=False)
            self.name.setFocus()
            self.name.selectAll()

    def changed(self, *_):
        if self.value is not None:
            self.value["name"] = self.name.text()
            self.value["description"] = self.description.toPlainText()
        self.update_use()

    def update_use(self):
        valid = False
        if self.value and self.value == self.saved:
            try:
                validate_profile(self.value, for_scan=True)
                valid = True
            except CompositionError:
                pass
        self.use_button.setEnabled(valid and not self.busy)

    def populate_rules(self):
        self.rules.blockSignals(True)
        self.rules.setRowCount(len(self.value["rule_sets"]))
        for row, rule in enumerate(self.value["rule_sets"]):
            for column, key in enumerate(("name", "template_id", "primary")):
                item = QTableWidgetItem(rule[key])
                if column == 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rules.setItem(row, column, item)
        self.rules.blockSignals(False)
        self.show_rule()

    def rules_changed(self, item):
        if self.value and item.column() < 2:
            self.value["rule_sets"][item.row()][("name", "template_id")[item.column()]] = item.text()
            self.update_use()

    def signal_settings_changed(self, *_):
        row = self.rules.currentRow()
        if self.value and 0 <= row < len(self.value["rule_sets"]):
            rule = self.value["rule_sets"][row]
            if self.primary.currentData():
                rule["primary"] = self.primary.currentData()
                self.rules.item(row, 2).setText(rule["primary"])
            rule["config"]["combine"] = self.combination.currentData()
            self.update_use()

    def show_rule(self, *_):
        row = self.rules.currentRow()
        self.primary.blockSignals(True)
        self.combination.blockSignals(True)
        self.primary.clear()
        if self.value and 0 <= row < len(self.value["rule_sets"]):
            rule = self.value["rule_sets"][row]
            kinds = {signal["kind"] for signal in rule["config"]["rules"]}
            for name in ("first_text", "page_number"):
                if name in kinds:
                    self.primary.addItem({"first_text": "Required first-page marker", "page_number": "Printed page restart"}[name], name)
            self.primary.setCurrentIndex(self.primary.findData(rule["primary"]))
            self.combination.setCurrentIndex(self.combination.findData(rule["config"]["combine"]))
            def region_text(region):
                return "Whole page" if region is None else "X / Y / W / H: " + " / ".join(f"{v:g}" for v in region) + " mm"
            lines = [f"Rule: {rule['name']} · {rule['template_id']}", "Primary: " + self.primary.currentText(),
                     "Verification: " + self.combination.currentText()]
            for signal in rule["config"]["rules"]:
                kind = signal["kind"]
                if kind == "first_text":
                    lines.append("First-page text (all markers): " + " + ".join(signal["terms"]))
                elif kind == "page_number":
                    lines.append("Printed counter: " + ("Automatic recognition" if signal.get("auto") else signal["pattern"]))
                else:
                    lines.append("Identity labels (values are never saved):")
                    for field in signal["fields"]:
                        lines.append("  " + field["label"] + " · " + region_text(field.get("region_mm")))
                lines.append("  " + region_text(signal.get("region_mm")))
            self.rule_detail.setPlainText("\n".join(lines))
        else:
            self.rule_detail.clear()
        self.primary.blockSignals(False)
        self.combination.blockSignals(False)

    def add_taught_rule(self):
        if not self.value or not self.taught_config or len(self.value["rule_sets"]) >= 16:
            self.status.setText(
                "Teach a static first-page feature in the detection preview first (maximum 16 rule sets)."
            )
            return
        used = {rule["template_id"] for rule in self.value["rule_sets"]}
        template_id = next(f"TYPE_{index:02}" for index in range(1, 18) if f"TYPE_{index:02}" not in used)
        self.value["rule_sets"].append(
            new_rule(f"Document type {len(self.value['rule_sets']) + 1}", self.taught_config, template_id=template_id)
        )
        self.populate_rules()
        self.rules.selectRow(len(self.value["rule_sets"]) - 1)
        self.update_use()

    def replace_taught_rule(self):
        row = self.rules.currentRow()
        if self.value and self.taught_config and 0 <= row < len(self.value["rule_sets"]):
            rule = self.value["rule_sets"][row]
            replacement = new_rule(rule["name"], self.taught_config, template_id=rule["template_id"])
            replacement["rule_id"] = rule["rule_id"]
            self.value["rule_sets"][row] = replacement
            self.populate_rules()
            self.update_use()

    def remove_rule(self):
        row = self.rules.currentRow()
        if self.value and 0 <= row < len(self.value["rule_sets"]):
            self.value["rule_sets"].pop(row)
            self.populate_rules()
            self.update_use()

    def saved_result(self, result):
        self.display(result["profile"])
        self.status.setText("Revision saved. Use this profile to scan and review the current PDF.")
        # A subsequent refresh is scheduled after the worker releases the owner lock.
        QTimer.singleShot(0, self.refresh)

    def save_revision(self):
        if self.value:
            self.task("save", self.saved_result, profile=copy.deepcopy(self.value))

    def duplicate_profile(self):
        if not self.saved:
            return
        name, ok = QInputDialog.getText(
            self, "Duplicate detection profile", "New profile name", text=self.name.text() + " copy"
        )
        if ok:
            self.task("duplicate", self.saved_result, profile_id=self.saved["profile_id"], name=name)

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import detection profile", "", "Detection profiles (*.pdmp *.pdmpx)"
        )
        if path:
            self.task("import", self.saved_result, path=path)

    def export_profile(self):
        if not self.saved or self.value != self.saved:
            self.status.setText("Save the current revision before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export detection profile", "", "Detection collection (*.pdmpx)"
        )
        if path:
            self.task(
                "export",
                lambda result: self.status.setText("Exported: " + result["path"]),
                path=path,
                profile=self.saved,
            )

    def use_profile(self):
        if self.use_button.isEnabled():
            self.selected_profile = copy.deepcopy(self.saved)
            self.accept()

    def done(self, result):
        self.closed = True
        super().done(result)
