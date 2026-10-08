"""Dedicated existing-PDF envelope workspace with asynchronous headless workers."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from composition.media.planner import preview_plan
from composition.overlay.geometry import validate_changed_geometry
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.planner import SYSTEM_FIELDS, applies
from composition.template.model import MM_TO_PT, Template
from ui.combo_popup import WideComboBox
from ui.icons import icon
from ui.responsive import scroll_container

from .canvas import Canvas, FieldList
from .inspector import InspectorScrollArea
from .overlay_actions import OverlayActions
from .overlay_dialogs import SCOPE_LABELS
from .process import Worker
from .properties import Properties


class OverlayEdit(QUndoCommand):
    def __init__(self, window, before, after, label, selected):
        super().__init__(label)
        self.window, self.before, self.after, self.selected = window, before, after, selected

    def undo(self):
        self.window.apply_spec(self.before, self.selected)

    def redo(self):
        self.window.apply_spec(self.after, self.selected)


class OverlayWindow(OverlayActions, QMainWindow):
    activityChanged = pyqtSignal()
    projectClosed = pyqtSignal()

    def __init__(self, parent=None, project_path=None, *, embedded=False, project_host=None):
        super().__init__(parent, Qt.WindowType.Widget if embedded else Qt.WindowType.Window)
        self.embedded, self.project_host = embedded, project_host
        self._close_approved = False
        if embedded:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1280, 820)
        self.setMinimumSize(0 if embedded else 760, 0 if embedded else 540)
        self.spec = self.project_path = self.last_result = None
        self.temp = tempfile.TemporaryDirectory(prefix="document-designer-overlay-")
        self.directory = Path(self.temp.name)
        self.workers = []
        self.active_worker = self.preview_worker = None
        self.preview_generation = 0
        self.preview_pending = False
        self.close_pending = False
        self.font_token = None
        self.draft_error = ""
        self.clipboard = []
        self.auto_fit = True
        self.fitting = False
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self.title)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.render_preview)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.setInterval(60)
        self.layout_timer.timeout.connect(lambda: self.fit_canvas() if self.auto_fit else None)
        self.build_ui()
        self.canvas.previewScaleChanged.connect(self.schedule_preview)
        if embedded:
            self.menuBar().hide()
        from .layout_tools import install_layout_tools
        install_layout_tools(self, self.layout_menu)
        self.busy()
        self.title()
        QTimer.singleShot(0, self.load_fonts)
        if project_path:
            self.load_path(project_path)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            for action in getattr(self, "actions", {}).values():
                symbol = action.property("designer_icon")
                if symbol:
                    action.setIcon(icon(symbol))
            if hasattr(self, "layout_tools_button"):
                self.layout_tools_button.setIcon(icon("line-tool"))

    def build_ui(self):
        self.actions = {}
        menus = {name: self.menuBar().addMenu(name) for name in ("&File", "&Edit", "&Insert", "&View", "&Production")}
        self.layout_menu = menus["&View"]
        toolbar = QToolBar("PDF Overlay", self)
        toolbar.setObjectName("designerMainToolbar")
        self.layout_toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)
        def action(key, text, callback, menu, shortcut=None, symbol="file-text", bar=False):
            item = QAction(icon(symbol), text, self)
            item.setProperty("designer_icon", symbol)
            item.triggered.connect(callback)
            if shortcut:
                item.setShortcut(shortcut)
            menus[menu].addAction(item)
            if bar:
                toolbar.addAction(item)
            self.actions[key] = item
            return item
        action("source", "New PDF envelope overlay…", self.choose_source, "&File", "Ctrl+N", "folder-open", True)
        action("open", "Open overlay project…", self.open_project, "&File", "Ctrl+O", "folder-open", True)
        action("save", "Save", self.save_project, "&File", "Ctrl+S", "save", True)
        action("save_as", "Save as…", lambda: self.save_project(save_as=True), "&File", "Ctrl+Shift+S")
        action("grouping", "Grouping & running sequence…", self.edit_grouping, "&File", symbol="settings", bar=True)
        action("detect", "Mailpiece detection…", self.detect_mailpieces, "&File", symbol="scan", bar=True)
        self.actions["detect"].setText("Auto Detect Mailpieces…")
        self.actions["detect"].setIconText("Auto Detect")
        toolbar.widgetForAction(self.actions["detect"]).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        action("reinspect", "Reinspect / locate source PDF…", lambda: self.choose_source(replace=True), "&File")
        action("close", "Close overlay designer", self.close, "&File", "Ctrl+W", "x")
        for name in ("undo", "redo"):
            item = self.undo.createUndoAction(self, "Undo") if name == "undo" else self.undo.createRedoAction(self, "Redo")
            if name == "undo":
                item.setShortcut(QKeySequence.StandardKey.Undo)
            else:
                from ui.shortcut_bindings import redo_shortcuts
                item.setShortcuts(redo_shortcuts())
            item.setIcon(icon(name))
            item.setProperty("designer_icon", name)
            self.actions[name] = item
            menus["&Edit"].addAction(item)
            toolbar.addAction(item)
        for name, shortcut in [("copy", "Ctrl+C"), ("paste", "Ctrl+V"), ("duplicate", "Ctrl+D"), ("delete", "Delete"), ("select_all", "Ctrl+A")]:
            item = action(name, name.replace("_", " ").title(), lambda checked=False, command=name: self.object_command(command), "&Edit", shortcut)
            item.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for kind, text in [("text", "Sequence / text"), ("code128", "Code 128"), ("i25", "I25 (Interleaved 2 of 5)"), ("qr", "QR code")]:
            action("insert_"+kind, text, lambda checked=False, value=kind: self.add_object(value), "&Insert", symbol="scan" if kind != "text" else "file-text", bar=True)
        action("fit", "Fit page", self.fit_canvas, "&View", "Ctrl+0", "monitor", True)
        action("zoom_in", "Zoom in", lambda: self.canvas.zoom_by(1.2), "&View", "Ctrl++")
        action("zoom_out", "Zoom out", lambda: self.canvas.zoom_by(1/1.2), "&View", "Ctrl+-")
        for key, label, setter in (("grid", "Show 5 mm grid", lambda on: self.canvas.set_grid(on)),
                                   ("snap", "Snap to 5 mm grid", lambda on: self.canvas.set_snap(on))):
            item = action(key, label, setter, "&View", symbol="settings")
            item.setCheckable(True)
        action("generate", "Generate overlay PDF…", self.generate_pdf, "&Production", "Ctrl+Shift+G", "printer", True)
        action("media", "Print Media / Stocks…", self.edit_print_media, "&Production", symbol="printer")
        action("cancel", "Cancel current job", self.cancel_job, "&Production", symbol="x", bar=True)
        self.actions["generate"].setIconText("Generate PDF")
        toolbar.widgetForAction(self.actions["generate"]).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.widgetForAction(self.actions["generate"]).setProperty("primary", True)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        navigation = QHBoxLayout()
        self.envelope, self.print_page = QSpinBox(), QSpinBox()
        for control, prefix, width in [(self.envelope, "Envelope ", 170), (self.print_page, "Page ", 120)]:
            control.setPrefix(prefix)
            control.setRange(1, 1)
            control.setFixedWidth(width)
            control.setAccessibleName(prefix+"preview index")
            control.valueChanged.connect(self.refresh_canvas)
            navigation.addWidget(control)
        self.position = QLabel("Select an existing PDF to begin")
        self.position.setTextFormat(Qt.TextFormat.PlainText)
        self.position.setWordWrap(True)
        navigation.addWidget(self.position, 1)
        self.preview_only = QCheckBox("Preview")
        self.preview_only.toggled.connect(self.preview_mode_changed)
        navigation.addWidget(self.preview_only)
        layout.addLayout(navigation)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("designerPanelTabs")
        self.splitter = QSplitter()
        left = QWidget()
        left.setObjectName("designerSidePanel")
        panel = QVBoxLayout(left)
        panel.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.source_summary = QLabel("Fixed groups of existing PDF pages. Source stays unchanged.")
        self.source_summary.setWordWrap(True)
        self.source_summary.setTextFormat(Qt.TextFormat.PlainText)
        panel.addWidget(self.source_summary)
        select = QPushButton("Select PDF…")
        select.clicked.connect(self.choose_source)
        panel.addWidget(select)
        panel.addWidget(QLabel("SYSTEM FIELDS"))
        self.fields = FieldList()
        self.fields.addItems(sorted(SYSTEM_FIELDS))
        self.fields.setDragEnabled(True)
        self.fields.itemDoubleClicked.connect(lambda item: self.add_object("text", item.text()))
        self.source_panels = QTabWidget()
        self.source_panels.setObjectName("designerPanelTabs")
        self.source_panels.setMinimumHeight(165)
        field_page = QWidget()
        field_layout = QVBoxLayout(field_page)
        field_layout.setContentsMargins(0, 4, 0, 0)
        self.field_filter = QLineEdit()
        self.field_filter.setPlaceholderText("Find system field…")
        self.field_filter.setClearButtonEnabled(True)
        self.field_filter.textChanged.connect(self.filter_system_fields)
        field_layout.addWidget(self.field_filter)
        field_layout.addWidget(self.fields)
        self.source_panels.addTab(field_page, "Fields")
        object_page = QWidget()
        object_layout = QVBoxLayout(object_page)
        object_layout.setContentsMargins(0, 4, 0, 0)
        self.object_filter = QLineEdit()
        self.object_filter.setPlaceholderText("Find object or barcode…")
        self.object_filter.setClearButtonEnabled(True)
        self.object_filter.textChanged.connect(self.filter_layers)
        self.layers = QListWidget()
        self.layers.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layers.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.layers.setAccessibleName("Overlay objects on all pages")
        self.layers.itemSelectionChanged.connect(self.select_layer_objects)
        self.layers.itemDoubleClicked.connect(lambda *args: self.focus_overlay_properties())
        object_layout.addWidget(self.object_filter)
        object_layout.addWidget(self.layers)
        self.source_panels.addTab(object_page, "Objects")
        panel.addWidget(self.source_panels, 1)
        self.fields_help = QLabel("Drag fields onto the page.\nGeneric barcode profiles need actual inserter testing.")
        self.fields_help.setWordWrap(True)
        panel.addWidget(self.fields_help)
        self.source_scroll = scroll_container(left)
        self.source_scroll.setObjectName("designerDataPanel")
        self.source_scroll.setAccessibleName("System fields and source panel")
        self.source_scroll.setMinimumWidth(150)
        self.source_scroll.setMaximumWidth(260)
        self.canvas = Canvas()
        self.canvas.set_template(Template())
        self.canvas.editCommitted.connect(self.canvas_edit)
        self.canvas.selectionChanged.connect(self.selection_changed)
        self.canvas.fieldDropped.connect(lambda name, x, y: self.add_object("text", name, x, y))
        self.canvas.command.connect(self.object_command)
        self.canvas.zoomChanged.connect(self.zoom_changed)
        self.canvas.objectActivated.connect(self.focus_overlay_properties)
        for name in ("copy", "paste", "duplicate", "delete", "select_all"):
            self.canvas.addAction(self.actions[name])
        self.splitter.addWidget(self.source_scroll)
        self.splitter.addWidget(self.canvas)
        self.splitter.setSizes([200, 750])
        self.tabs.addTab(self.splitter, "Design & preview")
        production = QWidget()
        prod_layout = QVBoxLayout(production)
        review_button = QPushButton("Review Production…")
        review_button.clicked.connect(self.generate_pdf)
        prod_layout.addWidget(review_button)
        self.production_text = QPlainTextEdit()
        self.production_text.setReadOnly(True)
        prod_layout.addWidget(self.production_text)
        buttons = QHBoxLayout()
        self.pdf_button, self.report_button = QPushButton("Open output PDF"), QPushButton("Open reports")
        self.pdf_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.pdf_button.clicked.connect(lambda: self.open_result("output_pdf"))
        self.report_button.clicked.connect(lambda: self.open_result("report_dir"))
        buttons.addWidget(self.pdf_button)
        buttons.addWidget(self.report_button)
        prod_layout.addLayout(buttons)
        self.tabs.addTab(production, "Production results")
        layout.addWidget(self.tabs, 1)
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(18)
        layout.addWidget(self.progress)
        self.setCentralWidget(central)
        from .compact_chrome import DesignerStatusBar
        self.setStatusBar(DesignerStatusBar(self))
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setStyleSheet("QStatusBar { padding: 0px; min-height: 0px; } QStatusBar::item { border: none; }")
        self.statusBar().setObjectName("designerStatusBar")
        self.preview_status = QLabel("Preview: select a PDF")
        self.preview_status.setAccessibleName("Overlay preview status")
        self.preview_status.linkActivated.connect(self.review_preview_error)
        self.preview_error_object = None
        self.statusBar().addPermanentWidget(self.preview_status)
        self.inspector = QDockWidget("Object properties", self)
        self.inspector.setObjectName("designerDock")
        content = QWidget()
        content.setObjectName("designerProperties")
        inspector_layout = QVBoxLayout(content)
        scope_form = QFormLayout()
        scope_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.scope, self.required_scope = WideComboBox(), WideComboBox()
        for control, labels in ((self.scope, SCOPE_LABELS), (self.required_scope, SCOPE_LABELS[:-1])):
            for label, value in labels:
                control.addItem(label, value)
            control.setMinimumContentsLength(12)
            control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.scope.currentIndexChanged.connect(self.scope_edited)
        self.required_scope.currentIndexChanged.connect(self.required_scope_edited)
        self.letter_page = QSpinBox()
        self.letter_page.setRange(1, 100)
        self.letter_page.valueChanged.connect(self.scope_edited)
        self.control = QCheckBox("Machine control barcode")
        self.control.setToolTip("Enable required read-position checks for this barcode. Text-only overlays do not require a barcode.")
        self.control.toggled.connect(self.scope_edited)
        self.profile_button = QPushButton("Configure barcode…")
        self.profile_button.clicked.connect(self.edit_profile)
        scope_form.addRow("Apply to", self.scope)
        scope_form.addRow("Letter page", self.letter_page)
        scope_form.addRow(self.control)
        scope_form.addRow(self.profile_button)
        self.payload_summary = QLabel()
        self.payload_summary.setWordWrap(True)
        self.payload_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.payload_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.payload_summary.hide()
        scope_form.addRow(self.payload_summary)
        scope_form.addRow("Required read positions", self.required_scope)
        inspector_layout.addLayout(scope_form)
        self.properties = Properties()
        self.properties.barcodeProfileRequested.connect(self.edit_profile)
        self.properties.edited.connect(self.property_edit)
        self.properties.fontRequested.connect(self.request_font)
        self.properties.revertRequested.connect(self.revert_draft)
        self.properties.insertFieldRequested.connect(self.insert_field)
        inspector_layout.addWidget(self.properties)
        self.auto_repair = QCheckBox("Repair missing glyphs")
        self.auto_repair.setToolTip("Automatically repair missing glyphs and report substitutions; primary fonts are retained.")
        self.auto_repair.setChecked(True)
        self.auto_repair.toggled.connect(self.schedule_preview)
        inspector_layout.addWidget(self.auto_repair)
        scroll = InspectorScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.inspector_scroll = scroll
        scroll.setObjectName("designerInspector")
        self.inspector.setWidget(scroll)
        self.inspector.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector)
        properties_action = self.inspector.toggleViewAction()
        properties_action.setIconText("Properties")
        properties_action.setIcon(icon("panel-right"))
        properties_action.setProperty("designer_icon", "panel-right")
        properties_action.setToolTip("Show or hide object properties")
        self.actions["properties"] = properties_action
        menus["&View"].addAction(properties_action)
        toolbar.insertAction(self.actions["fit"], properties_action)
        QTimer.singleShot(0, lambda: self.fit_canvas() if self.auto_fit and not self.close_pending else None)

    def load_fonts(self):
        if not self.close_pending:
            self.worker({"task": "fonts"}, self.properties.set_catalogue,
                        lambda message: self.properties.font_status.setText(message))

    def worker(self, request, ready, failed=None, *, active=False):
        if self.close_pending:
            return None
        worker = Worker(self.directory, request, self)
        self.workers.append(worker)
        if active:
            self.active_worker = worker
            self.busy()
        worker.resultReady.connect(ready)
        worker.failed.connect(failed or self.error)
        worker.progress.connect(lambda done, total, message: self.show_progress(done, total, message) if worker is self.active_worker else None)
        worker.ended.connect(lambda: self.worker_ended(worker))
        return worker

    def worker_ended(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
        if worker is self.active_worker:
            self.active_worker = None
        if worker is self.preview_worker:
            self.preview_worker = None
            target = getattr(worker, "preview_target", None)
            if target:
                target.unlink(missing_ok=True)
                target.with_suffix(".png").unlink(missing_ok=True)
            if self.preview_pending and not self.close_pending:
                self.timer.start(0)
        self.busy()
        if self.close_pending and not self.workers:
            self.close()

    def show_progress(self, done, total, message):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.error(message)

    def busy(self):
        locked = bool(self.active_worker or self.font_token or getattr(self,"batch_pending",False) or getattr(self,"workflow_binding",False))
        valid = self.spec is not None and not self.draft_error
        for name in ("source", "open", "save", "save_as", "grouping", "detect", "reinspect", "insert_text", "insert_code128", "insert_i25", "insert_qr", "generate", "media"):
            self.actions[name].setEnabled(not locked and (valid or name in ("source", "open")))
        if self.spec and self.spec.needs_detection_review:
            self.actions["generate"].setEnabled(False)
        if self.spec and self.spec.needs_source_review:
            self.actions["generate"].setEnabled(False)
        if self.spec and self.spec.external_fields:
            self.actions["generate"].setEnabled(False)
            self.actions["generate"].setToolTip("Generate this overlay from Workflow using reviewed extraction data.")
        else:
            self.actions["generate"].setToolTip("Generate overlay PDF")
        if getattr(self,"media_error",""):
            self.actions["generate"].setEnabled(False)
            self.actions["generate"].setToolTip(self.media_error)
        self.actions["cancel"].setEnabled(bool(self.active_worker))
        self.actions["cancel"].setVisible(bool(self.active_worker))
        self.canvas.set_editable(valid and not locked)
        self.properties.setEnabled(not locked and not self.preview_only.isChecked())
        self.fields.setEnabled(valid and not locked)
        self.layers.setEnabled(valid and not locked)
        self.progress.setVisible(bool(self.active_worker))
        self.auto_repair.setEnabled(not locked)
        control_required = bool(self.spec and self.spec.requires_control_barcode)
        self.required_scope.setEnabled(valid and not locked and control_required)
        self.required_scope.setToolTip(
            "Each required position must contain exactly one visible machine control barcode."
            if control_required else "Not required: no object is marked as a machine control barcode.")
        self.envelope.setEnabled(not self.draft_error and not locked)
        self.print_page.setEnabled(not self.draft_error and not locked)
        if locked:
            for control in (self.scope, self.control, self.letter_page, self.profile_button):
                control.setEnabled(False)
        elif not self.draft_error:
            self.selection_changed()
        if self.embedded:
            self.actions["open"].setEnabled(not self.close_pending)
            if self.spec:
                self.actions["source"].setEnabled(not self.close_pending)
        for key in ("rotate_cw", "rotate_ccw", "rotate_reset"):
            if key in self.actions:
                self.actions[key].setEnabled(valid and not locked and not self.preview_only.isChecked()
                                             and bool(self.canvas.selected_ids()))
        if hasattr(self,"batch_editor"):
            self.batch_editor.update_actions()
        from .selection_tools import update_type_action
        update_type_action(self)
        self.activityChanged.emit()

    def title(self):
        self.setWindowTitle("Document Designer · PDF Envelope Overlay · " +
            (self.project_path.name if self.project_path else self.spec.name if self.spec and self.spec.source_link else "Untitled") + (" *" if not self.undo.isClean() else ""))

    def error(self, message):
        self.statusBar().showMessage(message)
        self.statusBar().setToolTip(message)

    def edit_print_media(self):
        if not self.spec or self.active_worker or self.draft_error:
            return
        if hasattr(self,"batch_editor") and not self.batch_editor.resolve():
            return
        from .media_dialog import MediaDialog
        dialog=MediaDialog(self.spec.media,{"kind":"overlay","project":self.spec.to_dict()},self)
        if dialog.exec():
            after=self.spec.to_dict()
            after["media"]=dialog.options
            if dialog.options["enabled"]:
                after["settings"]["duplex"]=dialog.options["duplex"]
            self.commit(after,"Change Print Media")

    def apply_spec(self, value, selected=None):
        try:
            candidate = EnvelopeSpec.from_dict(value)
            plan = preview_plan(candidate)
        except (ValueError, KeyError, TypeError) as exc:
            self.invalidate_preview(str(exc))
            return False
        self.spec = candidate
        self.fields.clear()
        self.fields.addItems(sorted(SYSTEM_FIELDS | set(self.spec.external_fields)))
        self.filter_system_fields(self.field_filter.text())
        self.draft_error = ""
        self.properties.revert_content.hide()
        self.media_error=getattr(plan,"media_error","")
        try:
            self.sync_preview_indices(plan)
        except (ValueError, KeyError, TypeError) as exc:
            self.invalidate_preview(str(exc))
            return False
        self.required_scope.blockSignals(True)
        self.required_scope.setCurrentIndex(self.required_scope.findData(self.spec.required_scope))
        self.required_scope.blockSignals(False)
        self.source_summary.setText(f"{Path(self.spec.source.path).name}\n{plan.source_pages:,} source pages\n"
            f"{plan.envelopes:,} envelopes\n{plan.output_pages:,} output pages\n{plan.sheets:,} sheets · {plan.inserted_blanks:,} blank backs")
        if self.spec.needs_detection_review:
            self.source_summary.setText(f"{Path(self.spec.source.path).name}\n{plan.source_pages:,} source pages\nDetection pending: scan and review boundaries before generation.")
        if self.media_error:
            self.source_summary.setText("Media needs repair: open Production → Print Media / Stocks.\n"+self.media_error)
        self.source_summary.setToolTip(self.spec.source.path)
        self.refresh_canvas(selected=selected)
        self.busy()
        self.title()
        return not self.draft_error

    def sync_preview_indices(self, plan):
        """Clamp the envelope before querying its possibly different page plan."""
        controls = (self.envelope, self.print_page)
        blocked = [control.blockSignals(True) for control in controls]
        try:
            self.envelope.setRange(1, plan.envelopes)
            self.envelope.setValue(max(1, min(self.envelope.value(), plan.envelopes)))
            maximum = plan.settings_for(self.envelope.value()).output_pages_per_envelope
            self.print_page.setRange(1, maximum)
            self.print_page.setValue(max(1, min(self.print_page.value(), maximum)))
        finally:
            for control, state in zip(controls, blocked, strict=True):
                control.blockSignals(state)

    def invalidate_preview(self, message):
        self.timer.stop()
        self.preview_generation += 1
        self.preview_pending = False
        if self.preview_worker:
            self.preview_worker.stop_preview()
        self.draft_error = message
        self.canvas.set_preview(None)
        self.preview_status.setText("Preview unavailable: " + message)
        self.preview_status.setToolTip(message)
        self.error(message)
        self.busy()

    def commit(self, after, label, selected=None):
        if self.active_worker or self.font_token:
            return False
        try:
            candidate = EnvelopeSpec.from_dict(after)
            preview_plan(candidate)
            if not candidate.needs_source_review:
                validate_changed_geometry(self.spec, candidate)
        except ValueError as exc:
            self.error(str(exc))
            return False
        before = self.spec.to_dict()
        if before != after:
            self.undo.push(OverlayEdit(self, before, after, label, selected or self.canvas.selected_ids()))
        return True

    def refresh_canvas(self, *args, selected=None):
        if not self.spec:
            return
        editor = getattr(self, "batch_editor", None)
        current_page = (self.envelope.value(), self.print_page.value())
        if editor and editor.last_page != current_page and not editor.committing:
            if not editor.resolve():
                if editor.last_page:
                    for control, value in zip((self.envelope, self.print_page), editor.last_page, strict=True):
                        control.blockSignals(True)
                        control.setValue(value)
                        control.blockSignals(False)
                return
        if editor:
            editor.last_page = current_page
        try:
            plan = preview_plan(self.spec)
            self.sync_preview_indices(plan)
            page = plan.page(self.envelope.value(), self.print_page.value())
            fields = page.fields("preview")
            geom = self.spec.source.page_geometry(page)
        except (ValueError, KeyError, TypeError) as exc:
            self.invalidate_preview(str(exc))
            return
        if editor:
            editor.last_page = (self.envelope.value(), self.print_page.value())
        chosen = self.canvas.selected_ids() if selected is None else selected
        elements = [copy.deepcopy(obj.element) for obj in self.spec.objects if applies(obj.scope, fields, obj.letter_page)]
        self.canvas.set_template(
            Template(width_mm=geom["width_pt"]/MM_TO_PT, height_mm=geom["height_pt"]/MM_TO_PT, elements=elements), chosen,
            context=(self.spec.source.path, self.spec.source.sha256,
                     page.source_page, page.output_page))
        self.position.setText(f"Seq {fields['EnvelopeSeq']} · Source {page.source_page or 'blank'} · Output {page.output_page} · Sheet {fields['SheetNo']} {fields['Side']}")
        self.selection_changed()
        self.schedule_preview()

    def schedule_preview(self, *args):
        self.preview_generation += 1
        self.preview_error_object = None
        self.preview_status.setText("Updating preview…" if self.spec else "Preview: select a PDF")
        self.preview_status.setToolTip("")
        self.timer.start()

    def render_preview(self):
        if not self.spec or self.close_pending or self.draft_error:
            return
        if self.spec.external_fields and not getattr(self,"workflow_database", ""):
            self.preview_status.setText("Open from Workflow to preview extracted values")
            return
        if self.preview_worker:
            self.preview_pending = True
            self.preview_worker.stop_preview()
            return
        self.preview_pending = False
        generation = self.preview_generation
        self.preview_worker = self.worker({"task": "overlay_preview", "project": self.spec.to_dict(),
            "envelope": self.envelope.value(), "print_page": self.print_page.value(),
            "external_database": getattr(self,"workflow_database", ""),
            "external_data":getattr(self,"workflow_data",""),
            "external_data_sha256":getattr(self,"workflow_data_sha256",""),
            "raster_scale": self.canvas.preview_scale(),
            "auto_repair": self.auto_repair.isChecked(), "target": str(self.directory/f"preview-{generation}.pdf")},
            lambda result: self.preview_ready(result, generation),
            lambda error: self.preview_failed(error, generation))
        if self.preview_worker is not None:
            self.preview_worker.preview_target = self.directory/f"preview-{generation}.pdf"

    def preview_ready(self, result, generation):
        if generation == self.preview_generation and not self.close_pending and not self.draft_error:
            self.canvas.set_preview(result["image"])
            self.preview_status.setText("Preview ready")
            self.preview_status.setToolTip("Current envelope and page; this does not generate the whole production job.")
        for key in ("pdf", "image"):
            Path(result[key]).unlink(missing_ok=True)

    def fit_canvas(self):
        if self.close_pending:
            return
        self.fitting = True
        try:
            self.canvas.fit_page()
        finally:
            self.fitting = False
        self.auto_fit = True

    def zoom_changed(self, value):
        if not self.fitting:
            self.auto_fit = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 1050
        if (hasattr(self, "inspector") and compact and not getattr(self, "compact_width", False)
                and not self.canvas.selected_ids() and not self.properties.has_batch_draft()):
            self.inspector.hide()
        self.compact_width = compact
        if hasattr(self, "layout_timer"):
            self.layout_timer.start()
