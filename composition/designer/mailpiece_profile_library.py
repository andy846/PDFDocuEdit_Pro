"""Small source-free profile library; all disk operations use the existing worker."""

from __future__ import annotations

import copy
from collections import Counter

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

from composition.pdf_source.profile_library import (
    is_single_profile,
    new_profile,
    new_rule,
    new_single_profile,
    validate_library_profile,
)
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
        self.refresh_pending = False
        self.setWindowTitle("Mailpiece Detection Profile Library")
        self.resize(840, 620)
        outer = QVBoxLayout(self)
        help_text = QLabel(
            "Profiles are created, saved or imported by you; scanning does not create profiles automatically. Save profile adds your current rules here. Every new PDF still needs a scan and explicit boundary review."
        )
        help_text.setWordWrap(True)
        outer.addWidget(help_text)
        self.location = QLabel("Library location: " + self.root)
        self.location.setWordWrap(True)
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.location)
        splitter = QSplitter()
        self.entries = QListWidget()
        self.entries.currentRowChanged.connect(self.open_selected)
        splitter.addWidget(self.entries)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        self.form = form
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
        self.rule_actions = []
        for title, callback in (
            ("Create profile", self.create_profile),
            ("Save revision / rename", self.save_revision),
            ("Duplicate profile…", self.duplicate_profile),
            ("Import .pdmp / .pdmpx…", self.import_profile),
            ("Export profile…", self.export_profile),
            ("Add taught rule", self.add_taught_rule),
            ("Replace selected with taught rule", self.replace_taught_rule),
            ("Remove selected rule", self.remove_rule),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            form.addRow(button)
            self.actions.append(button)
            if callback in (self.add_taught_rule, self.replace_taught_rule, self.remove_rule):
                self.rule_actions.append(button)
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
            if self.status.text() == "Working…":
                self.status.setText("Profile loaded. Choose Use saved profile to scan the current PDF." if self.saved else "Ready.")
            if self.refresh_pending:
                self.refresh_pending = False
                QTimer.singleShot(0, self.refresh)

        if self.pending_worker:
            self.pending_worker.ended.connect(ended)
        else:
            ended()

    def refresh(self):
        def ready(result):
            from composition.pdf_source.profile_library import profile_name_key

            self.records = result["entries"]
            counts = Counter(profile_name_key(entry["name"]) for entry in self.records)
            seen = Counter()
            self.entries.blockSignals(True)
            self.entries.clear()
            for entry in self.records:
                category = "Single rule" if entry.get("kind") == "single_mailpiece_detection" else "Multiple templates"
                key = profile_name_key(entry["name"])
                seen[key] += 1
                duplicate = f" · Duplicate {seen[key]}" if counts[key] > 1 else ""
                self.entries.addItem(f"{entry['name']}{duplicate} · r{entry['revision']} · {category}")
            self.entries.blockSignals(False)
            duplicate_hint = " Some profiles share a name; select one and rename it." if any(n > 1 for n in counts.values()) else ""
            self.status.setText(
                ("; ".join(result["errors"]) if result["errors"] else f"{len(self.records)} saved profiles") + duplicate_hint
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
        self.revision.setText(str(value["revision"]) if is_single_profile(value) else f"{value['revision']} · {value['profile_id']}")
        self.populate_rules()
        self.description.setEnabled(not is_single_profile(value))
        self.update_use()

    def create_profile(self):
        if not self.busy:
            if self.taught_config and self.taught_config.get("version", 1) == 1:
                self.display(new_single_profile(self.taught_config, name="New profile"), saved=False)
            else:
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
                validate_library_profile(self.value, for_scan=True)
                valid = True
            except CompositionError:
                pass
        self.use_button.setEnabled(valid and not self.busy)
        single = is_single_profile(self.value)
        self.description.setEnabled(not single)
        for button in self.rule_actions:
            button.setEnabled(not single)
        self.primary.setEnabled(not single)
        self.combination.setEnabled(not single)
        for control in (self.description, self.rules, self.primary, self.combination):
            self.form.setRowVisible(control, not single)
        self.rule_detail.setMaximumHeight(180 if single else 120)

    def populate_rules(self):
        self.rules.blockSignals(True)
        single = is_single_profile(self.value)
        rows = ([{"name": "Single detection rule", "template_id": "Not applicable", "primary":
                  " + ".join(rule["kind"] for rule in self.value["config"]["rules"])}]
                if single else self.value["rule_sets"])
        self.rules.setRowCount(len(rows))
        for row, rule in enumerate(rows):
            for column, key in enumerate(("name", "template_id", "primary")):
                item = QTableWidgetItem(rule[key])
                if column == 2 or single:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rules.setItem(row, column, item)
        self.rules.blockSignals(False)
        if single:
            self.rules.selectRow(0)
        self.show_rule()

    def rules_changed(self, item):
        if self.value and not is_single_profile(self.value) and item.column() < 2:
            self.value["rule_sets"][item.row()][("name", "template_id")[item.column()]] = item.text()
            self.update_use()

    def signal_settings_changed(self, *_):
        row = self.rules.currentRow()
        if self.value and not is_single_profile(self.value) and 0 <= row < len(self.value["rule_sets"]):
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
        if is_single_profile(self.value):
            config = self.value["config"]
            region = config.get("region_mm")
            lines = ["Single detection rule · edit settings in the detection preview.",
                     "Whole page" if region is None else "X / Y / W / H: " + " / ".join(f"{v:g}" for v in region) + " mm",
                     "Combination: " + config["combine"]]
            for signal in config["rules"]:
                lines.append({"region_present": "Text present in selected region", "first_text": "First-page text",
                              "page_number": "Printed page restart", "document_id": "Identity change",
                              "separator": "Separator"}.get(signal["kind"], signal["kind"]))
                if signal.get("pattern"):
                    lines.append("  " + signal["pattern"])
                if signal.get("terms"):
                    lines.append("  " + " + ".join(signal["terms"]))
                if signal.get("region_mm"):
                    lines.append("  X / Y / W / H: " + " / ".join(f"{v:g}" for v in signal["region_mm"]) + " mm")
                for field in signal.get("fields", []):
                    lines.append("  Identity label: " + field["label"])
            self.rule_detail.setPlainText("\n".join(lines))
        elif self.value and 0 <= row < len(self.value["rule_sets"]):
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
        if is_single_profile(self.value):
            return
        if not self.value or not self.taught_config or self.taught_config.get("version", 1) != 2 or len(self.value["rule_sets"]) >= 16:
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
        if self.value and not is_single_profile(self.value) and self.taught_config and self.taught_config.get("version", 1) == 2 and 0 <= row < len(self.value["rule_sets"]):
            rule = self.value["rule_sets"][row]
            replacement = new_rule(rule["name"], self.taught_config, template_id=rule["template_id"])
            replacement["rule_id"] = rule["rule_id"]
            self.value["rule_sets"][row] = replacement
            self.populate_rules()
            self.update_use()

    def remove_rule(self):
        row = self.rules.currentRow()
        if self.value and not is_single_profile(self.value) and 0 <= row < len(self.value["rule_sets"]):
            self.value["rule_sets"].pop(row)
            self.populate_rules()
            self.update_use()

    def saved_result(self, result):
        self.display(result["profile"])
        self.status.setText("Revision saved. Use this profile to scan and review the current PDF.")
        # Refresh only after ended releases the busy/owner locks.
        self.refresh_pending = True

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
        pattern = "Single detection profile (*.pdmp)" if is_single_profile(self.saved) else "Detection collection (*.pdmpx)"
        path, _ = QFileDialog.getSaveFileName(self, "Export detection profile", "", pattern)
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
