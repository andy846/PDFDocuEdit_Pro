"""Structured object rules; no script editor or GUI-dependent evaluation."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from composition.engine.rules import (
    EMPTY_OPERATORS,
    NUMBER_OPERATORS,
    TEXT_OPERATORS,
    ElementPlan,
    validate_rules,
)
from composition.template.model import (
    AlternativeContent,
    CompositionError,
    ConditionGroup,
    ElementRules,
    RuleCondition,
)
from ui.combo_popup import WideComboBox as QComboBox

LABELS = {
    "eq": "Equals",
    "ne": "Does not equal",
    "gt": "Greater than",
    "ge": "At least",
    "lt": "Less than",
    "le": "At most",
    "contains": "Contains",
    "starts_with": "Starts with",
    "ends_with": "Ends with",
    "is_empty": "Is empty",
    "not_empty": "Is not empty",
}


class ConditionEditor(QGroupBox):
    def __init__(self, title, fields, group=None, parent=None):
        super().__init__(title, parent)
        self.fields = fields
        self.setCheckable(True)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Match"))
        self.mode = QComboBox()
        self.mode.addItem("All conditions", "all")
        self.mode.addItem("Any condition", "any")
        self.mode.setCurrentIndex(1 if group and group.mode == "any" else 0)
        row.addWidget(self.mode, 1)
        self.add_button = QPushButton("+ Condition")
        self.add_button.clicked.connect(lambda: self.add_condition())
        self.remove_button = QPushButton("Remove row")
        self.remove_button.clicked.connect(self.remove_condition)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Field", "Comparison", "Type", "Value"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName(title + " conditions")
        layout.addWidget(self.table)
        for condition in group.conditions if group else [RuleCondition(field=fields[0] if fields else "")]:
            self.add_condition(condition)
        self.setChecked(group is not None)

    def add_condition(self, condition=None):
        if self.table.rowCount() >= 20:
            return
        condition = condition or RuleCondition(field=self.fields[0] if self.fields else "")
        row = self.table.rowCount()
        self.table.insertRow(row)
        field = QComboBox()
        field.setEditable(True)
        field.addItems(self.fields)
        field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        field.setMinimumContentsLength(3)
        field.setCurrentText(condition.field)
        operator = QComboBox()
        kind = QComboBox()
        kind.addItem("Text", "text")
        kind.addItem("Number", "number")
        kind.setCurrentIndex(1 if condition.data_type == "number" else 0)
        value = QLineEdit(condition.value)
        value.setMaxLength(10000)
        for index, (widget, name) in enumerate(
            zip((field, operator, kind, value), ("Field", "Comparison", "Type", "Value"), strict=True)
        ):
            widget.setAccessibleName(name + f" row {row + 1}")
            self.table.setCellWidget(row, index, widget)

        def update_operators():
            previous = operator.currentData()
            operator.blockSignals(True)
            operator.clear()
            for key in NUMBER_OPERATORS if kind.currentData() == "number" else TEXT_OPERATORS:
                operator.addItem(LABELS[key], key)
            index = operator.findData(previous)
            operator.setCurrentIndex(max(0, index))
            operator.blockSignals(False)
            value.setEnabled(operator.currentData() not in EMPTY_OPERATORS)

        update_operators()
        operator.setCurrentIndex(max(0, operator.findData(condition.operator)))
        value.setEnabled(condition.operator not in EMPTY_OPERATORS)
        kind.currentIndexChanged.connect(update_operators)
        operator.currentIndexChanged.connect(
            lambda: value.setEnabled(operator.currentData() not in EMPTY_OPERATORS)
        )
        self.table.setRowHeight(row, 34)
        self.add_button.setEnabled(self.table.rowCount() < 20)
        self.table.setCurrentCell(row, 0)
        self._fit_table()

    def remove_condition(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        if row >= 0:
            self.table.removeRow(row)
            self.add_button.setEnabled(True)
            self._fit_table()

    def _fit_table(self):
        height = self.table.horizontalHeader().sizeHint().height() + self.table.rowCount() * 34 + 6
        self.table.setFixedHeight(min(220, max(80, height)))

    def read_group(self):
        if not self.isChecked():
            return None
        conditions = []
        for row in range(self.table.rowCount()):
            field, operator, kind, value = (self.table.cellWidget(row, column) for column in range(4))
            key = operator.currentData()
            conditions.append(
                RuleCondition(
                    field.currentText().strip(),
                    key,
                    kind.currentData(),
                    "" if key in EMPTY_OPERATORS else value.text(),
                )
            )
        return ConditionGroup(self.mode.currentData(), conditions)


class RulesDialog(QDialog):
    def __init__(self, element, fields=(), sample=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Object rules")
        self.setMinimumSize(520, 400)
        self.resize(
            min(700, max(520, parent.width() - 60)) if parent else 700,
            min(620, max(400, parent.height() - 70)) if parent else 620,
        )
        self.element, self.fields, self.sample = element, list(fields), list(sample)
        self.choice = None
        layout = QVBoxLayout(self)
        description = QLabel(
            "Text comparisons are exact and case-sensitive. Numbers use a dot decimal separator.\n"
            "All template pages remain; rules control objects within each page."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        content = QVBoxLayout(body)
        self.visibility = ConditionEditor(
            "Visible when (unchecked: always visible)", self.fields, element.rules.visible_when
        )
        content.addWidget(self.visibility)
        alternative = element.rules.alternative
        self.variant = ConditionEditor(
            "Use alternative content when", self.fields, alternative.when if alternative else None
        )
        supported = element.type in {"text", "image", "qr", "code128", "i25"}
        self.variant.setVisible(supported)
        content.addWidget(self.variant)
        self.alt_text = QPlainTextEdit(alternative.value if alternative else "")
        self.alt_text.setPlaceholderText("Alternative text, including {{Field_Name}}")
        self.alt_text.setMaximumHeight(90)
        self.alt_text.setAccessibleName("Alternative content")
        self.alt_text.setVisible(element.type in {"text", "qr", "code128", "i25"})
        self.alt_text.setEnabled(bool(alternative))
        content.addWidget(self.alt_text)
        image_row = self.image_row = QWidget()
        row = QHBoxLayout(image_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.alt_image = QLineEdit(alternative.image if alternative else "")
        self.alt_image.setReadOnly(True)
        self.alt_image.setAccessibleName("Alternative image")
        row.addWidget(self.alt_image, 1)
        choose = QPushButton("Choose alternative image…")
        choose.clicked.connect(self.choose_image)
        row.addWidget(choose)
        image_row.setVisible(element.type == "image")
        image_row.setEnabled(bool(alternative))
        content.addWidget(image_row)
        self.variant.toggled.connect(self.alt_text.setEnabled)
        self.variant.toggled.connect(image_row.setEnabled)
        sample_button = self.sample_button = QPushButton(f"Check imported sample ({len(self.sample)} rows)")
        sample_button.setEnabled(bool(self.sample))
        sample_button.clicked.connect(self.check_sample)
        content.addWidget(sample_button)
        sample_note = QLabel(
            "Sample values may be truncated to 500 characters. Use record Preview for full data."
        )
        sample_note.setWordWrap(True)
        content.addWidget(sample_note)
        self.sample_status = QPlainTextEdit()
        self.sample_status.setReadOnly(True)
        self.sample_status.setMaximumHeight(90)
        self.sample_status.hide()
        content.addWidget(self.sample_status)
        content.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.apply_rules)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Alternative image", "", "Images (*.png *.jpg *.jpeg *.tif *.tiff)"
        )
        if path:
            self.alt_image.setText(path)

    def build_rules(self):
        alternative = None
        when = self.variant.read_group() if self.element.type in {"text", "image", "qr", "code128", "i25"} else None
        if when:
            alternative = AlternativeContent(
                when,
                "" if self.element.type == "image" else self.alt_text.toPlainText(),
                self.alt_image.text() if self.element.type == "image" else "",
            )
        rules = ElementRules(self.visibility.read_group(), alternative)
        candidate = replace(self.element, rules=rules)
        validate_rules(candidate)
        if self.fields:
            missing = ElementPlan(candidate).fields - set(self.fields)
            if missing:
                raise CompositionError("Missing mapped fields: " + ", ".join(sorted(missing)))
        return rules

    def apply_rules(self):
        try:
            self.choice = self.build_rules()
        except CompositionError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def check_sample(self):
        try:
            plan = ElementPlan(replace(self.element, rules=self.build_rules()))
        except CompositionError as exc:
            self.error.setText(str(exc))
            return
        rows = []
        for ordinal, record in enumerate(self.sample, 1):
            try:
                selected = plan.resolve(record)
                state = "hidden" if not selected.visible else "visible"
                state += " / alternative content" if selected.alternative else " / normal content"
                rows.append(f"Sample {ordinal}: {state}")
            except CompositionError as exc:
                rows.append(f"Sample {ordinal}: ERROR - {exc}")
        self.sample_status.setPlainText("\n".join(rows))
        self.sample_status.show()
        self.error.clear()
