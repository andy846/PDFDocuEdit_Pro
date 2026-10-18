"""One runtime-only output policy editor shared by Designer and Workflow."""

import json

from PyQt6.QtCore import QSettings, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from composition.production.output_naming import SUMMARY_PATTERN, NamingSpec, part_filename
from composition.production.output_policy import SYSTEM_MAX_BYTES, OutputPolicy
from core.variables import VariableContext
from ui.combo_popup import WideComboBox


class WrapLabel(QLabel):
    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())


class StackedForm(QVBoxLayout):
    def addRow(self, *items):
        for item in items:
            self.addWidget(QLabel(item) if isinstance(item, str) else item)


class OutputLimitsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        form = StackedForm(body)
        self.pdf, self.ps, self.count = QSpinBox(), QSpinBox(), QSpinBox()
        for spin in (self.pdf, self.ps):
            spin.setRange(1, SYSTEM_MAX_BYTES // 1_000_000)
            spin.setSuffix(" MB")
        self.count.setRange(0, 1_000_000)
        self.count.setSpecialValueText("Automatic")
        form.addRow("Maximum PDF size per part", self.pdf)
        form.addRow("Maximum PostScript size per part", self.ps)
        form.addRow("Maximum envelopes per part", self.count)
        note = QLabel(
            "MB = 1,000,000 bytes. System limit: 2,000 MB per PDF / PS, 20,000 pages per part, 10,000 parts. Complete envelopes stay together; a single envelope exceeding a limit stops production. Resolution and quality are unchanged."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.mode = WideComboBox()
        for label, value in (
            ("Print summary (sheets, envelopes, D/S)", "summary"),
            ("Original name + part number", "original"),
            ("Custom structure", "custom"),
        ):
            self.mode.addItem(label, value)
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(18)
        form.addRow("File naming", self.mode)
        self.pattern = QLineEdit(SUMMARY_PATTERN)
        self.pattern.setMinimumWidth(0)
        self.pattern.setToolTip(
            "Job-level variables plus {{part.number}}, {{part.total_number}}, {{part.sheet_count}}, {{part.envelope_count}}, {{part.page_count}}, {{part.print_mode_code}}. Part number is always six digits. Do not add .pdf or .ps."
        )
        self.pattern_label = QLabel("Custom structure (without extension)")
        form.addRow(self.pattern_label, self.pattern)
        self.single = QCheckBox("Name single part")
        self.single.setToolTip("Use the selected naming structure even when only one part is produced.")
        form.addRow(self.single)
        self.preview = WrapLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow("Illustrative filename (counts are examples)", self.preview)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self.error)
        for label in body.findChildren(QLabel):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll)
        for widget in (self.pdf, self.ps, self.count):
            widget.valueChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)
        self.pattern.textChanged.connect(self.refresh)
        self.single.toggled.connect(self.refresh)
        self.context = VariableContext.for_job(
            job_name="Statement",
            job_id="preview",
            input_path="Example.pdf",
            sequence=1,
            batch_id="example-batch",
        )
        self.set_policy(OutputPolicy.recommended().to_dict())

    def policy(self):
        return OutputPolicy.from_dict(
            dict(
                pdf_bytes=self.pdf.value() * 1_000_000,
                ps_bytes=self.ps.value() * 1_000_000,
                envelopes=self.count.value(),
                naming=dict(
                    mode=self.mode.currentData(),
                    pattern=self.pattern.text() if self.mode.currentData() == "custom" else "",
                    single=self.single.isChecked(),
                ),
            )
        ).to_dict()

    def set_policy(self, value):
        policy = OutputPolicy.from_dict(value)
        naming = NamingSpec.from_dict(policy.naming)
        self.pdf.setValue(policy.pdf_bytes // 1_000_000)
        self.ps.setValue(policy.ps_bytes // 1_000_000)
        self.count.setValue(policy.envelopes)
        self.single.setChecked(naming.single)
        self.pattern.setText(naming.pattern or SUMMARY_PATTERN)
        self.pattern.setCursorPosition(0)
        self.mode.setCurrentIndex(self.mode.findData(naming.mode))
        self.refresh()

    def resolved_preview(self):
        value = self.policy()
        return part_filename(
            NamingSpec.from_dict(value["naming"]),
            self.context,
            "production.pdf",
            index=1,
            total=2,
            sheets=1000,
            envelopes=1000,
            pages=1000,
            duplex=False,
            first=1,
            last=1000,
            group="ExampleGroup",
        )

    def refresh(self, *_):
        custom = self.mode.currentData() == "custom"
        self.pattern.setVisible(custom)
        self.pattern_label.setVisible(custom)
        self.single.setEnabled(self.mode.currentData() != "original")
        try:
            example = self.resolved_preview()
            self.preview.setText(example + " / " + example.removesuffix(".pdf") + ".ps")
            self.error.clear()
        except ValueError as exc:
            self.error.setText(str(exc))
            self.preview.setText("Invalid naming structure")
        self.changed.emit()


class OutputLimitsControl(QPushButton):
    changed = pyqtSignal()

    def __init__(self, parent=None, preferences=None):
        super().__init__("Output limits & file naming…", parent)
        self.preferences = preferences if preferences is not None else QSettings()
        preferences = self.preferences
        self._value = OutputPolicy.recommended().to_dict()
        if preferences is not None:
            try:
                raw = preferences.value("production_output_policy", "")
                if raw:
                    self._value = OutputPolicy.from_dict(json.loads(raw)).to_dict()
            except (ValueError, TypeError):
                pass  # Invalid local preference returns to documented safe defaults.
        self.clicked.connect(self.configure)
        self.setToolTip(self.summary())

    def policy(self):
        return OutputPolicy.from_dict(self._value).to_dict()

    def summary(self):
        value = self.policy()
        return f"PDF ≤ {value['pdf_bytes'] // 1_000_000} MB; PS ≤ {value['ps_bytes'] // 1_000_000} MB; envelopes per part: {value['envelopes'] or 'automatic'}; naming: {NamingSpec.from_dict(value['naming']).mode}. Limits are checked on actual output."

    def configure(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Output limits & file naming")
        available = self.screen().availableGeometry()
        dialog.resize(max(280, min(620, available.width() - 32)), max(180, min(540, available.height() - 64)))
        layout = QVBoxLayout(dialog)
        panel = OutputLimitsPanel(dialog)
        owner = self.parentWidget()
        subject = getattr(owner, "template", None) or getattr(owner, "spec", None)
        if subject is not None:
            panel.context = VariableContext.for_job(
                job_name=getattr(subject, "name", "Statement"),
                job_id="preview",
                input_path="Example.pdf",
                sequence=1,
                batch_id="example-batch",
            )
        panel.set_policy(self.policy())
        layout.addWidget(panel, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)

        def valid():
            try:
                panel.resolved_preview()
                buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
            except ValueError:
                buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        panel.changed.connect(valid)
        valid()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._value = panel.policy()
            if self.preferences is not None:
                self.preferences.setValue("production_output_policy", json.dumps(self._value))
            self.setToolTip(self.summary())
            self.changed.emit()
        dialog.deleteLater()
