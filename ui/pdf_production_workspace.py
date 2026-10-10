"""Persistent PDF Workspace tab for font, flatten and repair operations."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QKeySequence, QUndoStack
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.io_atomic import atomic_output
from dialogs.font_preflight import FontPreflightPanel
from dialogs.pdf_operations import PdfOperationPanel
from ui.combo_popup import WideComboBox
from ui.responsive import scroll_container

from .pdf_production_controller import PdfProductionController


class PdfProductionWorkspace(QWidget):
    outputReady = pyqtSignal(str)
    pageRequested = pyqtSignal(int)
    activityChanged = pyqtSignal(bool)
    closed = pyqtSignal()
    SECTIONS = ("Overview", "Fonts", "Flatten", "Repair / Normalise", "Results")
    KEYS = ("overview", "fonts", "flatten", "repair", "results")

    def __init__(self, window=None):
        super().__init__(window)
        self.window = window
        self.stopped = self.pending_close = self.saving = False
        self.exit_approved = False
        self.undo = QUndoStack(self)
        self.actions, self.shortcut_defaults = {}, {}
        self.menu = QMenu("&PDF Production Tools", self)
        self.panels = {
            "fonts": FontPreflightPanel("document.pdf", parent=self),
            "flatten": PdfOperationPanel("document.pdf", "flatten", parent=self),
            "repair": PdfOperationPanel("document.pdf", "repair", parent=self),
        }
        self.controller = PdfProductionController(self.panels, self)
        self._build()
        for key, panel in self.panels.items():
            panel.outputReady.connect(self.outputReady)
            panel.taskStarted.connect(lambda _request, p=panel: p.footer.hide())
            panel.taskEnded.connect(lambda p=panel: p.footer.hide())
            panel.controlsChanged.connect(lambda key=key: self.controller.settings_changed(key))
            panel.controlsChanged.connect(self.sync_controls)
        self.panels["fonts"].pageRequested.connect(self.pageRequested)
        self.panels["fonts"].monitor.stop()  # One shared source monitor owns invalidation.
        self.controller.changed.connect(self.sync_controls)
        self.controller.progress.connect(self.show_progress)
        self.controller.resultAdded.connect(self.add_result)
        self.controller.idle.connect(self.finished_task)
        self.controller.changed.connect(self.render_overview)
        self.controller.changed.connect(self.refresh_history)
        self._action("open", "Choose PDFs…", "Ctrl+O", self.choose_sources)
        self._action("close", "Close tool tab", "Ctrl+W", self.request_close)
        self._action("analyze", "Analyze current section", "", self.analyze)
        self._action("generate", "Generate new copy", "", self.generate)
        self._action("refresh", "Refresh source", "", self.refresh_source)
        self.sync_controls()
        self.render_overview()

    @property
    def workers(self):
        return self.controller.workers

    @property
    def busy_state(self):
        return self.controller.busy

    def _action(self, key, text, shortcut, callback):
        action = QAction(text, self)
        action.triggered.connect(callback)
        action.setShortcut(QKeySequence(shortcut))
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.shortcut_defaults[key] = list(action.shortcuts())
        self.actions[key] = action
        self.addAction(action)
        self.menu.addAction(action)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        title = QLabel("PDF Production Tools")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.source_label = QLabel("Choose a PDF to begin. Analysis does not modify the source.")
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)
        row = QHBoxLayout()
        self.choose_button = QPushButton("Choose PDFs…")
        self.refresh_button = QPushButton("Refresh source")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Source password, if required")
        self.password.textChanged.connect(self.controller.set_password)
        self.choose_button.clicked.connect(self.choose_sources)
        self.refresh_button.clicked.connect(self.refresh_source)
        row.addWidget(self.choose_button)
        row.addWidget(self.refresh_button)
        row.addStretch()
        row.addWidget(self.password, 1)
        root.addLayout(row)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.navigation = WideComboBox()
        for section in self.SECTIONS:
            self.tabs.addTab(section)
            self.navigation.addItem(section)
        root.addWidget(self.tabs)
        root.addWidget(self.navigation)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        overview = QWidget()
        layout = QVBoxLayout(overview)
        self.overview_hint = QLabel("Not checked. Select Analyze to inspect structure, appearances and fonts in the background.")
        self.overview_hint.setWordWrap(True)
        layout.addWidget(self.overview_hint)
        shortcuts = QHBoxLayout()
        for section, label in (("fonts", "Review Fonts"), ("flatten", "Review Annotations / Forms"), ("repair", "Review Structure")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, key=section: self.select_section(key))
            shortcuts.addWidget(button)
        shortcuts_container = QWidget()
        shortcuts_container.setLayout(shortcuts)
        shortcuts_scroll = scroll_container(shortcuts_container)
        shortcuts_scroll.setFixedHeight(shortcuts_container.sizeHint().height() + 18)
        layout.addWidget(shortcuts_scroll)
        self.overview_table = QTableWidget(0, 7)
        self.overview_table.setHorizontalHeaderLabels(["PDF", "Status", "Pages", "Fonts", "Annotations", "Forms", "Structure"])
        self.overview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.overview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.overview_table.cellClicked.connect(self.overview_clicked)
        layout.addWidget(self.overview_table, 1)
        self.overview_details = QPlainTextEdit()
        self.overview_details.setReadOnly(True)
        self.overview_details.setMinimumHeight(90)
        layout.addWidget(self.overview_details)
        self.stack.addWidget(scroll_container(overview))
        for section in ("fonts", "flatten", "repair"):
            panel = self.panels[section]
            self.prepare_panel(section, panel)
            self.stack.addWidget(scroll_container(panel))
        results = QWidget()
        layout = QVBoxLayout(results)
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["Source", "Section", "Type", "Status"])
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.result_table.itemSelectionChanged.connect(self.show_result)
        layout.addWidget(self.result_table, 1)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        layout.addWidget(self.result_details)
        self.output_table = QTableWidget(0, 3)
        self.output_table.setHorizontalHeaderLabels(["PDF", "Status", "Output / error"])
        self.output_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.output_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.output_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.output_table.itemSelectionChanged.connect(self.result_buttons)
        layout.addWidget(self.output_table)
        row = QHBoxLayout()
        self.open_output = QPushButton("Open output PDF")
        self.open_reports = QPushButton("Open reports")
        self.export = QPushButton("Export report…")
        self.open_output.clicked.connect(self.open_selected_output)
        self.open_reports.clicked.connect(self.open_selected_reports)
        self.export.clicked.connect(self.export_result)
        for button in (self.open_output, self.open_reports, self.export):
            row.addWidget(button)
        result_actions = QWidget()
        result_actions.setLayout(row)
        actions_scroll = scroll_container(result_actions)
        actions_scroll.setFixedHeight(result_actions.sizeHint().height() + 18)
        layout.addWidget(actions_scroll)
        self.stack.addWidget(scroll_container(results))
        self.tabs.currentChanged.connect(self.change_section)
        self.navigation.currentIndexChanged.connect(self.change_section)
        self.output_folder = QLineEdit()
        self.output_folder.setPlaceholderText("Output root — each run creates a new PDF + report job folder")
        self.output_folder.textChanged.connect(self.sync_output_folder)
        self.output_browse = QPushButton("Browse…")
        self.output_browse.clicked.connect(self.browse_output)
        row = QHBoxLayout()
        row.addWidget(self.output_folder, 1)
        row.addWidget(self.output_browse)
        root.addLayout(row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        root.addWidget(self.progress)
        row = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze")
        self.generate_button = QPushButton("Generate new copy")
        self.cancel_button = QPushButton("Cancel task")
        self.analyze_button.clicked.connect(self.analyze)
        self.generate_button.clicked.connect(self.generate)
        self.cancel_button.clicked.connect(self.controller.cancel)
        row.addWidget(self.analyze_button)
        row.addStretch()
        row.addWidget(self.generate_button)
        row.addWidget(self.cancel_button)
        self.footer = QWidget()
        self.footer.setLayout(row)
        root.addWidget(self.footer)

    def prepare_panel(self, section, panel):
        # Transfer the action row into a hidden QWidget; workers still update
        # their original controls, and the common footer mirrors validity.
        item = panel._root.takeAt(panel._root.count() - 1)
        panel.footer = QWidget(panel)
        panel.footer.setLayout(item.layout())
        panel.footer.hide()
        for widget in (panel.source_label, panel.password_edit,
                       getattr(panel, "batch_button", None), getattr(panel, "batch", None),
                       getattr(panel, "open_button", None), getattr(panel, "export_button", None),
                       getattr(panel, "reports_button", None), panel.progress):
            if widget is not None:
                widget.hide()
        if section == "fonts":
            safe = QGroupBox("Safe Embed — original fonts and evidence")
            safe.setCheckable(True)
            safe.setChecked(False)
            content = QWidget()
            layout = QVBoxLayout(content)
            # These rows are consecutive in the shared Font panel.
            first = panel._root.indexOf(panel.authorized) - 1
            for _ in range(4):
                item = panel._root.takeAt(first)
                if item.widget():
                    layout.addWidget(item.widget())
                elif item.layout():
                    layout.addLayout(item.layout())
            safe_layout = QVBoxLayout(safe)
            safe_layout.addWidget(content)
            content.hide()
            safe.toggled.connect(content.setVisible)
            panel._root.insertWidget(first, safe)
            panel.safe_embed = safe
            self.compact_disclosure(safe, content)
            panel.table.setMaximumHeight(220)
            panel.details.setMinimumHeight(65)
            panel.details.setMaximumHeight(100)
            panel._root.removeWidget(panel.details)
            panel._root.insertWidget(first, panel.details)
            # Check sources is a font-only preparation action, not production.
            panel.check_button.setParent(panel)
            panel._root.insertWidget(first + 1, panel.check_button)
            panel.check_button.show()
        else:
            form = next(panel._root.itemAt(i).layout() for i in range(panel._root.count())
                        if isinstance(panel._root.itemAt(i).layout(), QFormLayout))
            panel.form = form
            for control in (panel.password_edit, panel.output_folder, panel.output_browse):
                control.hide()
                label = form.labelForField(control)
                if label:
                    label.hide()
            advanced = QGroupBox("Advanced — rasterisation")
            advanced.setCheckable(True)
            advanced.setChecked(False)
            content = QWidget()
            advanced_form = QFormLayout(content)
            for control in (panel.raster, panel.dpi):
                row = form.takeRow(control)
                if row.labelItem:
                    advanced_form.addRow(row.labelItem.widget(), row.fieldItem.widget())
                else:
                    advanced_form.addRow(row.fieldItem.widget())
            advanced_layout = QVBoxLayout(advanced)
            advanced_layout.addWidget(content)
            content.hide()
            advanced.toggled.connect(content.setVisible)
            form.insertRow(4, advanced)
            self.compact_disclosure(advanced, content)
            panel.advanced = advanced
            panel.pages.currentIndexChanged.connect(lambda _index, p=panel: self.adjust_repair(p))
            panel.mode.currentIndexChanged.connect(lambda _index: self.adjust_repair(panel))
            self.adjust_repair(panel)

    @staticmethod
    def compact_disclosure(group, content):
        def update(expanded):
            content.setVisible(expanded)
            group.setMinimumHeight(0)
            group.setMaximumHeight(16777215 if expanded else group.fontMetrics().height() + 24)
        group.toggled.connect(update)
        update(group.isChecked())

    def adjust_repair(self, panel):
        if panel.operation != "repair":
            panel.form.setRowVisible(panel.range, panel.pages.currentIndex() == 2)
            return
        normalise = panel.mode.currentData() == "normalise"
        maximum = panel.mode.currentData() == "maximum"
        for control in (panel.annotations, panel.forms, panel.javascript, panel.attachments, panel.metadata, panel.boxes):
            panel.form.setRowVisible(control, normalise)
        panel.advanced.setVisible(normalise or maximum)
        if maximum:
            panel.advanced.setChecked(True)
        panel.raster.setVisible(normalise)
        panel.form.setRowVisible(panel.pages, not maximum)
        panel.form.setRowVisible(panel.range, not maximum and panel.pages.currentIndex() == 2)

    def select_section(self, key):
        self.change_section(self.KEYS.index(key))

    def change_section(self, index):
        if not 0 <= index < len(self.KEYS):
            return
        for control in (self.tabs, self.navigation):
            control.blockSignals(True)
            control.setCurrentIndex(index)
            control.blockSignals(False)
        self.stack.setCurrentIndex(index)
        self.sync_controls()

    def set_sources(self, **kwargs):
        changed = self.controller.set_sources(**kwargs)
        if changed:
            self.password.blockSignals(True)
            self.password.setText(self.controller.secrets.get("password", ""))
            self.password.blockSignals(False)
        return changed

    def choose_sources(self):
        if self.busy_state:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF production sources", "", "PDF (*.pdf)")
        if paths:
            self.set_sources(paths=paths)

    def refresh_source(self):
        try:
            self.controller.refresh()
            self.password.blockSignals(True)
            self.password.setText(self.controller.secrets.get("password", ""))
            self.password.blockSignals(False)
        except Exception as exc:
            self.status.setText(str(exc))

    def sync_output_folder(self, value):
        for section in ("flatten", "repair"):
            self.panels[section].output_folder.setText(value)

    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Output root folder", self.output_folder.text())
        if directory:
            self.output_folder.setText(directory)

    def analyze(self):
        if self.busy_state or not self.controller.is_current():
            return
        key = self.KEYS[self.stack.currentIndex()]
        if key == "overview":
            self.controller.analyze_overview()
        elif key in self.panels:
            self.panels[key].analyze()
        self.sync_controls()

    def generate(self):
        if not self.generate_button.isEnabled():
            return
        section = self.KEYS[self.stack.currentIndex()]
        panel = self.panels[section]
        if not self.output_folder.text().strip():
            self.status.setText("Choose an output root folder before generation.")
            self.output_folder.setFocus()
            return
        if section == "fonts":
            panel.start({"task": "font_repair", "output_dir": self.output_folder.text().strip(),
                         "selections": panel.approved_selections(), "reference": panel.reference.text(),
                         "authorized_reference": panel.trusted.isChecked()}, panel.repaired)
        else:
            panel.generate()
        self.sync_controls()

    def sync_controls(self):
        if self.stopped:
            return
        controller = self.controller
        busy = controller.busy
        section = self.KEYS[self.stack.currentIndex()]
        current = controller.is_current() and bool(controller.sources)
        self.source_label.setText(
            ("Source: " + controller.label +
             (f" · {controller.source_metadata['page_count']} pages" if controller.source_metadata.get("page_count") else "") +
             (" · Editor working copy (includes unsaved changes)" if controller.editor_source else " · External PDF source"))
            if controller.sources else "Choose a PDF to begin."
        )
        self.choose_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy and bool(controller.refresh_factory))
        self.password.setEnabled(not busy)
        self.password.setVisible(not controller.editor_source)
        self.output_folder.setEnabled(not busy)
        self.output_browse.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.analyze_button.setEnabled(current and not busy and section != "results")
        ready = False
        for key, panel in self.panels.items():
            panel.setEnabled(not busy or controller.active == key)
            if not busy:
                if key == "fonts":
                    ready = panel.repair_button.isEnabled() if section == key else ready
                else:
                    ready = panel.generate_button.isEnabled() if section == key else ready
                self.adjust_repair(panel) if key != "fonts" else None
            if key != "fonts":
                panel.open_button.hide()
                panel.reports_button.hide()
            panel.footer.hide()
        self.generate_button.setVisible(section in self.panels)
        self.generate_button.setEnabled(current and not busy and ready and section in self.panels)
        self.status.setText(
            "Source changed or closed. Results are out of date; refresh from the Editor or choose PDFs."
            if controller.stale else
            f"{self.progress.format().replace(' %p%', '')} · {controller.active}. You can switch sections or return to the PDF."
            if busy else
            "Select a processing section; analyze and review its settings before generating a copy."
            if section in {"overview", "results"} else
            "Ready to generate a new copy. Original preserved."
            if ready else
            "Analysis / settings check required. Review the section details for blocking reasons."
        )
        if not busy and not controller.stale and section == "fonts":
            self.status.setText(self.font_blocker())
        self.progress.setVisible(busy)
        for key in ("open", "refresh", "analyze", "generate"):
            if key in self.actions:
                self.actions[key].setEnabled({"open": not busy, "refresh": self.refresh_button.isEnabled(),
                                              "analyze": self.analyze_button.isEnabled(), "generate": self.generate_button.isEnabled()}[key])
        self.activityChanged.emit(busy)
        self.result_buttons()

    def font_blocker(self):
        panel = self.panels["fonts"]
        if not panel.inventory:
            return "Analyze fonts first. For a batch, inspect one PDF to configure safe embedding."
        inventory = panel.inventory
        if panel.scan_only or inventory.get("protected"):
            return "This source is scan-only (signed, encrypted or restricted). Export the report to review its fonts."
        if not inventory.get("complete"):
            return "Font analysis is incomplete; safe embedding is blocked. Review the reported issues."
        if all(r["status"] in {"EMBEDDED", "BASE14_POLICY_EXEMPT"} for r in inventory["resources"]):
            return "No embedding required under the selected policy. The font report can be exported in Results."
        if not panel.selections:
            return "Open Safe Embed and select the affected font's authorized original file."
        if not panel.authorized.isChecked():
            return "Confirm authorization to embed the selected original fonts."
        if not panel.report.get("matches") or any(m["status"] != "CANDIDATE_FOUND" for m in panel.report["matches"]):
            return "Check sources to validate the selected fonts. Unsupported or mismatched fonts remain blocked."
        if not panel.reference.text() or not panel.trusted.isChecked():
            return "Select and confirm a trusted original-font reference PDF in Safe Embed."
        return "Ready to generate a verified new copy. Original preserved."

    def show_progress(self, done, total, message):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(message + " %p%" if total else message)
        self.status.setText(message)

    def render_overview(self):
        rows = self.controller.overview.get("files", [])
        self.overview_hint.setText("Analysis complete. Review each category; this analysis does not approve processing."
                                   if rows else "Not checked / out of date. Analyze to inspect the current source.")
        self.overview_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            pdf, fonts = row.get("pdf", {}), row.get("fonts", {})
            resources = fonts.get("resources", [])
            font_status = "Unable to check" if not fonts else "Needs review" if not fonts.get("complete") or any(
                f["status"] not in {"EMBEDDED", "BASE14_POLICY_EXEMPT"} for f in resources) else "OK"
            structural = pdf.get("diagnostics", {}).get("qpdf", pdf.get("diagnostics", {}).get("structure", {}))
            values = [Path(row["source"]).name, row["status"], str(pdf.get("page_count", fonts.get("page_count", "—"))),
                      font_status, str(pdf.get("annotations", "—")), str(pdf.get("forms", "—")), structural.get("status", "Unable to check")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.overview_table.setItem(index, column, item)
        if rows and self.overview_table.currentRow() < 0:
            self.overview_table.selectRow(0)
            self.overview_clicked(0, 0)

    def overview_clicked(self, row, column):
        rows = self.controller.overview.get("files", [])
        if not 0 <= row < len(rows):
            return
        entry = rows[row]
        pdf, fonts = entry.get("pdf", {}), entry.get("fonts", {})
        lines = ["Each category is counted independently; no combined error total.",
                 f"Digital signature detected: {pdf.get('signed', 'Not checked')}",
                 f"Encrypted source: {pdf.get('encrypted', 'Not checked')}",
                 f"Original encrypted / restricted (Editor): {self.controller.source_metadata.get('scan_only', False)}",
                 *pdf.get("issues", []), *fonts.get("issues", [])]
        for key, value in pdf.get("diagnostics", {}).items():
            lines.append(f"{key}: {value.get('status', 'Not checked')} · {value.get('message', value.get('coverage', ''))}")
        lines.extend(f"{key}: {value}" for key, value in entry.get("errors", {}).items())
        self.overview_details.setPlainText("\n".join(lines))
        if column == 3:
            self.select_section("fonts")
        elif column in (4, 5):
            self.select_section("flatten")
        elif column == 6:
            self.select_section("repair")

    def add_result(self, entry):
        self.refresh_history()
        self.result_table.selectRow(len(self.controller.history) - 1)
        self.show_result()

    def refresh_history(self):
        self.result_table.setRowCount(len(self.controller.history))
        for index, item in enumerate(self.controller.history):
            status = item["result"].get("status", "Analysis available")
            if item["outdated"]:
                status = "Out of date · " + status
            for column, value in enumerate((item["source"], item["section"], item["kind"], status)):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.result_table.setItem(index, column, cell)
        self.show_result()

    def selected_result(self):
        row = self.result_table.currentRow()
        return self.controller.history[row] if 0 <= row < len(self.controller.history) else None

    def show_result(self):
        entry = self.selected_result()
        self.output_table.setRowCount(0)
        if not entry:
            return
        result = entry["result"]
        lines = [f"Source: {entry['source']}", f"Section: {entry['section']}", f"Type: {entry['kind']}"]
        if entry["outdated"]:
            lines.append("OUT OF DATE — source or settings changed. Historical evidence only.")
        lines.extend(["Status: " + result.get("status", "Analysis available"),
                      "PDF: " + result.get("output_pdf", ""),
                      "Reports: " + result.get("report_dir", "")])
        if entry.get("input_files"):
            lines.append("Inputs: " + ", ".join(entry["input_files"][:20]))
        options = entry["settings"].get("options", entry["settings"].get("plan", {}).get("options", {}))
        if options:
            lines.append("Mode: " + options.get("mode", ""))
            lines.append("Selected changes: " + ", ".join(key.replace("_", " ") for key in
                         ("annotations", "forms", "rasterise", "remove_javascript", "remove_attachments", "remove_metadata", "normalise_boxes") if options.get(key)))
        if result.get("inventory"):
            inventory = result["inventory"]
            lines.extend([f"Pages: {inventory['page_count']}", f"Font resources: {len(inventory['resources'])}",
                          "Font check: " + ("Complete" if inventory["complete"] else "Incomplete"),
                          *inventory.get("issues", [])])
        if result.get("plan"):
            plan = result["plan"]
            lines.extend([f"Pages: {plan['page_count']}", f"Annotations: {plan['annotations']}", f"Form widgets: {plan['forms']}", *plan.get("issues", [])])
        lines.extend(str(item) for item in result.get("warnings", []))
        if result.get("error"):
            lines.append("Error: " + result["error"])
        if result.get("files"):
            files = result["files"]
            lines.append(f"Files: {len(files)}")
            counts = {}
            for item in files:
                status = item.get("status", "Unknown")
                counts[status] = counts.get(status, 0) + 1
            lines.append(" · ".join(f"{status}: {count}" for status, count in counts.items()))
        self.result_details.setPlainText("\n".join(lines))
        files = result.get("files", []) if entry["kind"] == "production" else []
        self.output_rows = files or ([result] if result.get("output_pdf") else [])
        self.output_table.setRowCount(len(self.output_rows))
        for index, item in enumerate(self.output_rows):
            for column, value in enumerate((Path(item.get("source", item.get("output_pdf", ""))).name,
                                           item.get("status", ""), item.get("output_pdf", item.get("error", "")))):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.output_table.setItem(index, column, cell)
        self.output_table.setVisible(bool(self.output_rows))
        if self.output_rows:
            self.output_table.selectRow(0)
        self.result_buttons()

    def selected_output(self):
        row = self.output_table.currentRow()
        rows = getattr(self, "output_rows", [])
        return rows[row] if 0 <= row < len(rows) else {}

    def result_buttons(self):
        if not hasattr(self, "open_output"):
            return
        entry = self.selected_result()
        output = self.selected_output()
        self.open_output.setEnabled(bool(output.get("output_pdf")))
        self.open_reports.setEnabled(bool(entry and (entry["result"].get("report_dir") or output.get("report_dir"))))
        self.export.setEnabled(bool(entry))

    def open_selected_output(self):
        path = self.selected_output().get("output_pdf")
        if path:
            self.outputReady.emit(path)

    def open_selected_reports(self):
        entry = self.selected_result()
        path = self.selected_output().get("report_dir") or (entry["result"].get("report_dir") if entry else "")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def export_result(self):
        entry = self.selected_result()
        if not entry:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export production evidence", "production-report.json", "JSON (*.json);;CSV (*.csv)")
        if path:
            try:
                self.export_evidence(entry, path)
            except Exception as exc:
                self.status.setText(str(exc))

    @staticmethod
    def export_evidence(entry, path):
        if str(path).lower().endswith(".csv") and entry["section"] == "fonts":
            from core.font_preflight.service import export_report
            result = entry["result"]
            export_report(result.get("inventory", result), path)
            return
        with atomic_output(path) as staged:
            if not str(path).lower().endswith(".csv"):
                staged.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
                return
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(["Source", "Section", "Type", "Out of date", "Status", "Output PDF", "Report directory", "Error"])
            result = entry["result"]
            files = result.get("files", result.get("analyses", [])) or [result]
            for row in files:
                values = [row.get("source", entry["source"]), entry["section"], entry["kind"], entry["outdated"],
                          row.get("status", "Analysis available"), row.get("output_pdf", ""), row.get("report_dir", result.get("report_dir", "")),
                          row.get("error", "; ".join(row.get("errors", {}).values()))]
                writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
            with staged.open("w", encoding="utf-8-sig", newline="") as stream:
                stream.write(buffer.getvalue())

    def finished_task(self):
        if self.pending_close or self.stopped:
            self.finish_close()
        elif self.controller.current_entry and self.controller.current_entry["kind"] in {"production", "failure"}:
            self.select_section("results")

    def confirm_discard(self, after_save=None):
        if self.stopped or not self.busy_state:
            return True
        accepted = QMessageBox.question(self, "PDF production running", "Cancel this task and close? Completed outputs are retained.",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        self.exit_approved = accepted
        return accepted

    def request_close(self):
        if not self.confirm_discard():
            return
        self.pending_close = True
        self.stop()
        if not self.workers:
            self.finish_close()

    def stop(self):
        self.stopped = True
        self.controller.stop()

    def finish_close(self):
        if self.workers or getattr(self, "_closed", False):
            return
        self._closed = True
        self.controller.cleanup()
        if self.window is not None:
            self.window.workspace.remove_tool_tab(self)
        self.closed.emit()
        self.deleteLater()

    def refresh_theme(self):
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < max(800, sum(self.fontMetrics().horizontalAdvance(s) + 36 for s in self.SECTIONS))
        self.tabs.setVisible(not narrow)
        self.navigation.setVisible(narrow)
