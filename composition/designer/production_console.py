"""Compact Production view; all generation and approval remain with its owner."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from composition.production.output_naming import NamingSpec
from styles.tokens import S
from ui.responsive import reveal_widget
from ui.variable_name import VariableNameEdit

from .output_limits import OutputLimitsControl
from .production_activity import ProductionActivity


def label(text="", secondary=False):
    value = QLabel(text)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setWordWrap(True)
    value.setMinimumWidth(0)
    value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if secondary:
        value.setObjectName("secondary")
    return value


def disclosure(text, target):
    button = QToolButton()
    button.setText(text)
    button.setCheckable(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    target.hide()
    def toggle(checked):
        target.setVisible(checked)
        button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
    button.toggled.connect(toggle)
    return button


def panel(title):
    card = QFrame()
    card.setObjectName("productionPanel")
    card.setMinimumWidth(0)
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(S.MD, S.SM, S.MD, S.SM)
    layout.setSpacing(S.SM)
    heading = label(title)
    heading.setObjectName("reviewDashboardStatus")
    layout.addWidget(heading)
    return card, layout


class ProductionConsole(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.setObjectName("productionConsole")
        self.setMinimumSize(0, 0)
        self.owner = owner
        self._wide = None
        root = QVBoxLayout(self)
        root.setContentsMargins(S.SM, S.XS, S.SM, S.XS)
        root.setSpacing(S.SM)
        owner.production_heading = label("Production", secondary=True)
        root.addWidget(owner.production_heading)
        owner.production_activity = ProductionActivity(owner.cancel_job)
        root.addWidget(owner.production_activity)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumSize(0, 0)
        owner.production_page = QWidget()
        body = QVBoxLayout(owner.production_page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(S.SM)
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.columns.setSpacing(S.SM)
        self.summary_card, summary = panel("Production plan")
        self.settings_card, settings = panel("Output settings")
        self.columns.addWidget(self.summary_card, 1)
        self.columns.addWidget(self.settings_card, 1)
        body.addLayout(self.columns)
        body.addStretch(1)
        self.scroll.setWidget(owner.production_page)
        root.addWidget(self.scroll, 1)

        metrics = QHBoxLayout()
        metrics.setSpacing(S.SM)
        self.metrics = {}
        for key, title in (("records", "Mailpieces"), ("pages", "Output pages"), ("sheets", "Physical sheets")):
            card = QFrame()
            card.setObjectName("reviewMetricCard")
            card.setMinimumWidth(0)
            box = QVBoxLayout(card)
            box.setContentsMargins(S.SM, S.XS, S.SM, S.XS)
            box.setSpacing(S.XXS)
            box.addWidget(label(title, secondary=True))
            value = label("Not available")
            value.setObjectName("reviewMetricValue")
            value.setAccessibleName("Planned " + title.lower())
            box.addWidget(value)
            self.metrics[key] = value
            metrics.addWidget(card, 1)
        summary.addLayout(metrics)
        self.printing, self.profile, self.barcode = label(), label(secondary=True), label(secondary=True)
        for value in (self.printing, self.profile, self.barcode):
            summary.addWidget(value)
        self.plan_error = label()
        self.plan_error.setObjectName("validationError")
        self.plan_error.hide()
        summary.addWidget(self.plan_error)
        self.stocks = QTableWidget(0, 3)
        self.stocks.setHorizontalHeaderLabels(["Paper stock", "Sheets", "Selection"])
        self.stocks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stocks.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.stocks.setShowGrid(False)
        self.stocks.setWordWrap(False)
        self.stocks.setMinimumSize(0, 0)
        self.stocks.verticalHeader().hide()
        self.stocks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stocks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stocks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.stocks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stock_resize = QTimer(self)
        self.stock_resize.setSingleShot(True)
        self.stock_resize.timeout.connect(self._size_stock_rows)
        self.stocks.installEventFilter(self)
        summary.addWidget(self.stocks)
        self.plan_details = QWidget()
        details = QVBoxLayout(self.plan_details)
        details.setContentsMargins(0, 0, 0, 0)
        owner.build_production_settings(details)
        self.plan_toggle = disclosure("Full plan details", self.plan_details)
        summary.addWidget(self.plan_toggle)
        summary.addWidget(self.plan_details)

        settings.addWidget(label("Base PDF filename (Original naming preset)", secondary=True))
        owner.output_name_edit = VariableNameEdit(parent=self.settings_card)
        owner.output_name_edit.setMinimumWidth(0)
        owner.output_name_edit.edit.setMinimumWidth(0)
        owner.output_name_edit.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        settings.addWidget(owner.output_name_edit)
        owner.output_limits = OutputLimitsControl(owner, preferences=owner.preferences)
        owner.output_limits.setText("Limits and file naming…")
        settings.addWidget(owner.output_limits, 0, Qt.AlignmentFlag.AlignLeft)
        self.limits = label(secondary=True)
        settings.addWidget(self.limits)
        owner.output_limits.changed.connect(self.refresh_limits)
        self.refresh_limits()
        owner.auto_repair = QCheckBox("Substitute missing glyphs")
        owner.auto_repair.setChecked(owner.preferences.value("auto_glyph_repair", True, type=bool))
        owner.auto_repair.setToolTip("Keeps each object's primary font. Only missing characters use an available embeddable font. "
                                    "Preview uses the same policy. CSV lists record, output page, character and replacement font; "
                                    "substitutions may affect text width and wrapping. Uncheck for strict font validation.")
        owner.auto_repair.toggled.connect(owner._auto_repair_changed)
        settings.addWidget(owner.auto_repair)
        settings.addWidget(label("Substitutions are recorded for review; text width and wrapping may change.", secondary=True))
        details.removeWidget(owner.production_media_button)
        owner.production_media_button.setText("Return to Design settings…")
        settings.addWidget(owner.production_media_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.source_note = label(secondary=True)
        settings.addWidget(self.source_note)

        owner.production_summary = QPlainTextEdit()
        owner.production_summary.setReadOnly(True)
        owner.production_summary.setMinimumHeight(100)
        owner.production_summary.setMaximumHeight(190)
        owner.production_summary.setAccessibleName("Complete production job log and report")
        self.log_toggle = disclosure("Job log / detailed report", owner.production_summary)
        root.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(owner.production_summary)
        self.failure = label()
        self.failure.setObjectName("validationError")
        self.failure.setWordWrap(False)
        self.failure.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._error_text = ""
        self.failure.hide()
        root.addWidget(self.failure)
        owner.production_errors = QWidget()
        owner.production_errors.setLayout(QVBoxLayout())
        owner.production_errors.layout().setContentsMargins(0, 0, 0, 0)
        owner.production_errors.layout().setSpacing(S.XS)
        root.addWidget(owner.production_errors)

        self.footer = QWidget()
        self.footer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.footer)
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setSpacing(S.SM)
        result_actions = QWidget()
        owner.production_actions = QHBoxLayout(result_actions)
        owner.production_actions.setContentsMargins(0, 0, 0, 0)
        owner.production_actions.setSpacing(S.XS)
        owner.production_actions.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for name, text, description, callback in (
            ("open_output_button", "Open PDF", "Open production PDF", owner._open_output),
            ("open_font_report_button", "Font report", "Open font substitution report", owner._open_font_report),
        ):
            button = QPushButton(text)
            button.setAccessibleName(description)
            button.setToolTip(description)
            button.setEnabled(False)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(callback)
            owner.production_actions.addWidget(button)
            setattr(owner, name, button)
        self.footer_layout.addWidget(result_actions, 1)
        owner.review_production_button = QPushButton("Review Production…")
        owner.review_production_button.setProperty("primary", True)
        owner.review_production_button.clicked.connect(owner.generate_pdf)
        self.footer_layout.addWidget(owner.review_production_button, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.footer)
        owner.last_font_report = owner.last_output = ""
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._reveal_focus)
        QWidget.setTabOrder(owner.output_name_edit.edit, owner.output_limits)
        QWidget.setTabOrder(owner.output_limits, owner.auto_repair)
        QWidget.setTabOrder(owner.auto_repair, owner.production_media_button)
        QWidget.setTabOrder(owner.production_media_button, owner.review_production_button)

    def refresh_limits(self):
        value = self.owner.output_limits.policy()
        naming = NamingSpec.from_dict(value["naming"])
        name = {"summary": "Print summary (sheets, envelopes, D/S)",
                "original": "Original name + part number", "custom": "Custom structure"}[naming.mode]
        self.limits.setText(
            f"PDF limit: {value['pdf_bytes'] // 1_000_000:,} MB · PS limit: {value['ps_bytes'] // 1_000_000:,} MB\n"
            f"Envelopes per part: {value['envelopes'] or 'Automatic'} · Full envelopes stay together\n"
            f"Naming: {name}")
        self.limits.setToolTip(self.owner.output_limits.summary())

    def display_plan(self, template, count, plan, rows):
        self.plan_error.hide()
        for key, number in (("records", count), ("pages", plan.output_pages if count else 0),
                            ("sheets", plan.sheets if count else 0)):
            self.metrics[key].setText(f"{number:,}" if count else "Not available")
        media = template.media
        profile = media.get("printer_profile", {})
        backend = profile.get("backend", "pdf") if media.get("enabled") else "pdf"
        output = {"pdf": "PDF", "postscript": "PDF + PostScript", "canon_prismasync": "PDF + JDF"}.get(backend, backend)
        scope = "Planned totals" if count else "Awaiting records"
        self.printing.setText(f"{'Duplex' if plan.settings.duplex else 'Simplex'} · {output} · {scope}")
        blanks = f"{plan.inserted_blanks:,} inserted blank backs" if count else "Blank backs: Not checked"
        self.profile.setText(f"{len(template.pages)} template pages per record · {blanks}\n"
                             + ("Printer: " + (profile.get("profile_name") or "Unnamed profile")
                                if media.get("enabled") else "Paper / tray: no media assignment"))
        objects = sum(e.type in {"qr", "code128", "i25"} for e in template.all_elements())
        self.barcode.setText(f"{objects:,} template Barcode / QR objects · Details checked in Production Review")
        rows = rows if count else []
        self.stocks.setRowCount(len(rows))
        for index, (name, sheets, selection) in enumerate(rows):
            for column, value in enumerate((name, f"{sheets:,}", selection or "—")):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.stocks.setItem(index, column, item)
        self.stocks.setVisible(bool(rows))
        self._size_stock_rows()
        self.stock_resize.start(0)
        self.source_note.setText(
            (("Source: imported data snapshot." if template.record_mode == "imported" else "Source: generated records.")
             if count else "Import data or configure generated quantity to calculate planned totals.")
            + " Only validated output is published to a new job folder.")

    def unavailable_plan(self, error):
        for value in self.metrics.values():
            value.setText("Not available")
        if self.owner.record_count:
            self.metrics["records"].setText(f"{self.owner.record_count:,}")
        self.printing.setText("Print plan needs review")
        self.profile.clear()
        self.barcode.clear()
        self.stocks.setRowCount(0)
        self.stocks.hide()
        self.plan_error.setText(str(error))
        self.plan_error.show()

    def _show_failure(self, error):
        self._error_text = str(error)
        concise = " ".join(self._error_text.split())
        self.failure.setText(self.failure.fontMetrics().elidedText(
            concise, Qt.TextElideMode.ElideRight, max(100, self.width() - S.MD * 4)))
        self.failure.setToolTip(self._error_text)
        self.failure.show()

    def failed(self, error):
        self._show_failure(error)
        self.owner.production_summary.appendPlainText("Error: " + str(error))
        self.log_toggle.setText("Job log / detailed report — Failed")
        self.log_toggle.setChecked(True)

    def started(self):
        self._error_text = ""
        self.failure.clear()
        self.failure.hide()
        self.log_toggle.setText("Job log / detailed report — running")

    def completed(self, result):
        self.log_toggle.setText("Job log / detailed report — " + result["status"].title())
        if result.get("error"):
            self._show_failure(result["error"])
        if result["status"] != "completed":
            self.log_toggle.setChecked(True)

    def _reveal_focus(self, old, current):
        if current is not None and self.scroll.isAncestorOf(current):
            reveal_widget(current, whole_control=True)

    def _size_stock_rows(self):
        self.stocks.resizeRowsToContents()
        count = min(4, self.stocks.rowCount())
        height = self.stocks.horizontalHeader().height() + sum(self.stocks.rowHeight(i) for i in range(count)) + 4
        height = max(40, height)
        if self.stocks.height() != height:
            self.stocks.setFixedHeight(height)

    def eventFilter(self, watched, event):
        if watched is self.stocks and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange, QEvent.Type.Show):
            self.stock_resize.start(0)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.stock_resize.start(0)
        if self._error_text:
            self._show_failure(self._error_text)
        wide = self.width() >= max(880, self.fontMetrics().horizontalAdvance("M") * 70)
        if wide != self._wide:
            self._wide = wide
            self.columns.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
        direction = QBoxLayout.Direction.TopToBottom if self.width() < 540 else QBoxLayout.Direction.LeftToRight
        if self.footer_layout.direction() != direction:
            self.footer_layout.setDirection(direction)
