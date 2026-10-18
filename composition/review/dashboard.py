"""Compact widgets for an already-computed, read-only production summary."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from styles.tokens import S

from .presentation import ReviewDashboardModel


def label(text="", *, secondary=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setMinimumWidth(0)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if secondary:
        widget.setObjectName("secondary")
    return widget


class ReviewDashboard(QWidget):
    issuesRequested = pyqtSignal(str)
    barcodeRequested = pyqtSignal()
    fontRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewDashboard")
        self.setMinimumSize(0, 0)
        self.model = None
        self.values = {}
        self.cards = []
        self._columns = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(S.SM)
        self.state = label()
        self.state.setObjectName("reviewDashboardStatus")
        root.addWidget(self.state)
        self.identity = label(secondary=True)
        root.addWidget(self.identity)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(S.SM)
        root.addLayout(self.grid)
        empty = ReviewDashboardModel.from_review(None)
        for metric in empty.metrics[:6]:
            card = QFrame()
            card.setObjectName("reviewMetricCard")
            card.setMinimumSize(0, 0)
            box = QVBoxLayout(card)
            box.setContentsMargins(S.SM, S.XS, S.SM, S.XS)
            box.setSpacing(S.XXS)
            box.addWidget(label(metric.label, secondary=True))
            value = label()
            value.setObjectName("reviewMetricValue")
            self.values[metric.key] = value
            box.addWidget(value)
            self.cards.append(card)
        self.issue_row = QWidget()
        row = QHBoxLayout(self.issue_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.error_button = QPushButton("Errors: Not Checked")
        self.warning_button = QPushButton("Warnings: Not Checked")
        self.error_button.clicked.connect(lambda: self.issuesRequested.emit("error"))
        self.warning_button.clicked.connect(lambda: self.issuesRequested.emit("warning"))
        row.addWidget(self.error_button)
        row.addWidget(self.warning_button)
        root.addWidget(self.issue_row)
        self.planned_barcode = label()
        self.final_barcode = label()
        self.font_status = label()
        for value in (self.planned_barcode, self.final_barcode, self.font_status):
            root.addWidget(value)
        actions = QHBoxLayout()
        self.barcode_button = QPushButton("Barcode details")
        self.barcode_button.clicked.connect(self.barcodeRequested.emit)
        self.font_button = QPushButton("Open font substitution report")
        self.font_button.clicked.connect(self.fontRequested.emit)
        actions.addWidget(self.barcode_button)
        actions.addWidget(self.font_button)
        self.action_row = QWidget()
        self.action_row.setLayout(actions)
        root.addWidget(self.action_row)
        self.detail_values = {}
        for metric in empty.metrics[6:]:
            value = label()
            self.values[metric.key] = value
            self.detail_values[metric.key] = metric.label
            root.addWidget(value)
        self.scope = label(
            "Checked plan, authorization and output publication are separate. No dashboard action grants production approval.",
            secondary=True,
        )
        root.addWidget(self.scope)
        self._layout_cards()
        self.display(empty)

    def _layout_cards(self):
        columns = 3 if self.width() >= 720 else 2 if self.width() >= 400 else 1
        if columns == self._columns:
            return
        for index in range(max(columns, self._columns)):
            self.grid.setColumnStretch(index, 1 if index < columns else 0)
        self._columns = columns
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        vertical = self.width() < 400
        self.issue_row.layout().setDirection(
            QHBoxLayout.Direction.TopToBottom if vertical else QHBoxLayout.Direction.LeftToRight
        )
        if hasattr(self, "action_row"):
            self.action_row.layout().setDirection(
                QHBoxLayout.Direction.TopToBottom if vertical else QHBoxLayout.Direction.LeftToRight
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_cards()

    def display(self, model):
        if model == self.model:
            return
        self.model = model
        self.state.setText(model.status_label)
        self.state.setAccessibleName(model.status_label)
        self.identity.setText("Job: " + (model.job_id or "Not assigned"))
        self.identity.setToolTip("Checked snapshot: " + (model.snapshot_id or "Not Checked"))
        for metric in model.metrics:
            value = self.values[metric.key]
            value.setText((metric.label + ": " if metric.key in self.detail_values else "") + metric.value)
            value.setToolTip(metric.label + ": " + metric.value)
            value.setAccessibleName(metric.label + ": " + metric.value)
        self.error_button.setText(
            "Errors: " + (str(model.errors) if model.errors is not None else "Not Checked")
        )
        self.warning_button.setText(
            "Warnings: " + (str(model.warnings) if model.warnings is not None else "Not Checked")
        )
        self.error_button.setEnabled(bool(model.errors))
        self.warning_button.setEnabled(bool(model.warnings))
        planned = model.planned_barcode
        count = f" - {planned.expected:,} planned" if planned.expected is not None else ""
        self.planned_barcode.setText("Planned barcode validation: " + planned.state + count)
        self.planned_barcode.setToolTip(planned.detail)
        final = model.final_barcode
        coverage = (
            f" - {final.verified:,} / {final.expected:,} audit targets verified"
            if final.verified is not None and final.expected is not None
            else ""
        )
        remaining = f"; {final.unverified:,} unverified audit targets" if final.unverified is not None else ""
        self.final_barcode.setText(
            "Final output decode: " + final.state + coverage + remaining + "\n" + final.detail
        )
        font = model.fonts
        count = f" - {font.count:,} character occurrence(s)" if font.count is not None else ""
        records = (
            f", {font.records:,} {font.reference_label}"
            if font.records is not None
            else f"; affected {font.reference_label}: Not Available"
        )
        self.font_status.setText("Font substitutions: " + font.state + count + records + "\n" + font.detail)
        self.font_button.setEnabled(bool(font.report))
        self.barcode_button.setEnabled(bool(model.snapshot_id))
