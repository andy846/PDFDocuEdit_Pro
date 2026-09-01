"""Modern PyQt6 main window for PDFDocuEdit Pro."""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import fitz
from PyQt6.QtCore import QEvent, QPoint, QRectF, QSizeF, Qt, QThreadPool, QTimer
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPageLayout,
    QPageSize,
    QPainter,
    QPen,
    QShortcut,
    QTransform,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.analysis import (
    AnalysisRequest,
    Finding,
    FindingSource,
    InspectionReport,
    Severity,
    inspect_and_analyze,
)
from core.annotation_io import (
    export_annotation_summary,
    export_annotations_json,
    flatten_annotations,
    import_annotations_json,
)
from core.annotations import (
    AnnotationOp,
    AnnotationStyle,
    AnnotationValidationError,
    add_watermark_image,
    add_watermark_text,
    apply_annotation,
    apply_redaction_marks,
    list_document_annotations,
    remove_annotation,
    update_annotation,
    update_annotation_geometry,
    update_annotation_text,
    validate_annotation_op,
)
from core.capabilities import CapabilityId, detect_capabilities, refresh_capabilities
from core.commands import Command
from core.file_association import (
    is_default_app,
    is_installed,
    open_default_apps_settings,
    register_default_app,
)
from core.font_inspector import inspect_font_at
from core.ocr import OCRMode, OCRResult, run_ocr
from core.pdf_engine import (
    DOCUMENT_LOCK,
    PdfEngine,
    PdfInvalidPassword,
    PdfPasswordRequired,
    parse_page_range,
    search_pdf_file,
)
from core.platform_service import PlatformService
from core.resources import APP_VERSION, COPYRIGHT_NOTICE
from core.settings import SettingsManager
from core.tasks import FunctionTask
from core.tools import (
    compress_pdfs,
    convert_office_files,
    convert_pdf_to_word,
    convert_postscript,
    convert_postscript_files,
    create_page_count_report,
    decrypt_pdf_file,
    encrypt_pdf_file,
    extract_region_text,
    merge_pdfs,
    merge_spreadsheets,
    overlay_pdfs,
    scan_barcodes_batch,
    text_files_to_pdfs,
)
from core.undo import UndoStack
from core.verapdf import validate_with_verapdf
from dialogs.annotation_dialogs import WatermarkDialog
from dialogs.barcode_dialogs import BarcodeResultsDialog, BarcodeScanDialog
from dialogs.base import ask_password, remember_save_directory, start_in_save_directory
from dialogs.batch_print_dialog import BatchPrintDialog
from dialogs.batch_tools import CompressionDialog, MergePDFDialog, OverlayDialog
from dialogs.conversion_dialogs import (
    OfficeConversionDialog,
    PostScriptConversionDialog,
    TextConversionDialog,
)
from dialogs.data_dialogs import PageCountReportDialog, SpreadsheetMergeDialog
from dialogs.document_dialogs import PrintOptionsDialog, VisualOrganizerDialog
from dialogs.ocr_dialog import OCRDialog, OCRTextResultDialog
from dialogs.page_operations import InsertPagesDialog, PageSelectionDialog, SplitDialog
from dialogs.readme_dialog import ReadmeDialog
from dialogs.search_open_dialog import SearchOpenDialog
from dialogs.security_dialogs import DecryptDialog, EncryptDialog
from dialogs.shortcuts_dialog import ShortcutsDialog
from dialogs.text_extractor_dialog import TextExtractorDialog
from dialogs.undo_history_dialog import UndoHistoryDialog
from styles.components import global_style
from styles.theme import ThemeMode, apply_theme
from ui.bottom_bar import BottomBar
from ui.command_bar import CommandBar
from ui.command_palette import CommandPalette
from ui.context_panel import ContextPanel
from ui.deep_search_dialog import OPEN_CURRENT, OPEN_NEW_TAB, DeepSearchDialog
from ui.diagnostics_dialog import DiagnosticsDialog, PreferencesDialog
from ui.document_session import DocumentSession
from ui.icons import clear_icon_cache
from ui.infobar import InfoBar
from ui.side_panel import SHORTCUT_HINTS, SidePanel
from ui.task_bar import TaskBar
from ui.window_chrome import FramelessResizeHandles
from ui.workspace import DocumentWorkspace


def _prepare_pdf_engine(
    path: str,
    password: str | None = None,
) -> tuple[str, PdfEngine | str | None]:
    """Prepare an independent engine without blocking the GUI thread."""
    engine = PdfEngine()
    try:
        engine.open(path, password)
    except PdfPasswordRequired:
        engine.close()
        return ("password_required", None)
    except PdfInvalidPassword:
        engine.close()
        return ("invalid_password", None)
    except Exception as exc:
        engine.close()
        return ("error", str(exc) or exc.__class__.__name__)
    return ("ok", engine)


def _perform_document_analysis(
    source_path: str,
    document_id: str,
    revision: int,
    request: AnalysisRequest,
    *,
    progress=None,
    is_cancelled=None,
) -> InspectionReport:
    """Compose deterministic inspection with optional formal validation."""

    report = inspect_and_analyze(
        source_path,
        document_id,
        revision,
        request,
        progress=progress,
        is_cancelled=is_cancelled,
    )
    if request.standard_profile and not (is_cancelled and is_cancelled()):
        if progress:
            progress(0, 0, "Running veraPDF formal validation")
        validation = validate_with_verapdf(
            source_path,
            request.standard_profile,
            is_cancelled=is_cancelled,
        )
        report.standard_profile = request.standard_profile
        report.validation_summary = validation.summary
        report.standard_raw_xml = validation.raw_xml
        if validation.compliant is True:
            report.standard_status = "Passed"
        elif validation.compliant is False:
            unique_rules = (
                validation.summary.failed_rule_count
                if validation.summary
                else len(validation.findings)
            )
            report.standard_status = (
                f"Failed  -  {unique_rules} unique rule failure"
                f"{'s' if unique_rules != 1 else ''}"
            )
        else:
            report.standard_status = validation.message or "Unavailable"
        report.finding_set.findings.extend(validation.findings)
        report.finding_set.normalize()
        if validation.compliant is None and validation.message:
            report.finding_set.findings.append(
                Finding(
                    FindingSource.STANDARD,
                    "verapdf.unavailable",
                    Severity.WARNING,
                    None,
                    "Formal validation could not be completed",
                    validation.message,
                )
            )
    return report


class PDFViewer(QMainWindow):
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        self._integrated_chrome = os.name == "nt"
        if self._integrated_chrome:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.settings = SettingsManager()
        self._sessions: list[DocumentSession] = []
        self._session: DocumentSession | None = None
        self._idle_engine = PdfEngine()
        self._last_context_key: str | None = None
        self._tasks: set[FunctionTask] = set()
        self._search_tasks: dict[int, FunctionTask] = {}
        self._search_generations: dict[int, int] = {}
        self._child_windows: list[PDFViewer] = []
        self._task_had_error = False
        self._closing = False
        self._printing = False
        self._queued_open_paths: list[tuple[str, str | None]] = []
        self._open_queue_scheduled = False
        self._thread_pool = QThreadPool.globalInstance()
        self._init_ui()
        self._restore_window_state()
        self._apply_theme(self.settings.get_theme())
        if initial_path:
            self.queue_open_files([initial_path])

    # --- compatibility accessors (current session) ----------------------
    @property
    def engine(self) -> PdfEngine:
        """The current session's engine, or an idle engine when none is open."""
        return self._session.engine if self._session else self._idle_engine

    @property
    def _display_path(self) -> Path | None:
        return self._session.display_path if self._session else None

    @_display_path.setter
    def _display_path(self, value: Path | None) -> None:
        if self._session:
            self._session.display_path = value

    @property
    def _page(self) -> int:
        return self._session.page if self._session else 0

    @_page.setter
    def _page(self, value: int) -> None:
        if self._session:
            self._session.page = value

    @property
    def _undo_stack(self) -> UndoStack | None:
        return self._session.undo_stack if self._session else None

    # --- UI construction -------------------------------------------------
    def _init_ui(self) -> None:
        self.setWindowTitle("PDFDocuEdit Pro")
        app = QApplication.instance()
        if isinstance(app, QApplication) and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        self.setMinimumSize(960, 640)
        self.setAcceptDrops(True)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.command_bar = CommandBar(self.settings.get_theme())
        layout.addWidget(self.command_bar)
        self.task_bar = TaskBar()
        layout.addWidget(self.task_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.side_panel = SidePanel(
            bool(self.settings.get("left_panel_collapsed", False)),
            bool(self.settings.get("animations_enabled", True)),
        )
        self.workspace = DocumentWorkspace(
            self.settings.recent_files(),
            animations_enabled=bool(self.settings.get("animations_enabled", True)),
        )
        self.info_bar = InfoBar(root)
        self.info_bar.set_overlay_anchor(self.workspace)
        self.context_panel = ContextPanel()
        self.context_panel.hide()
        self.splitter.addWidget(self.side_panel)
        self.splitter.addWidget(self.workspace)
        self.splitter.addWidget(self.context_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setCollapsible(1, False)
        self.side_panel.set_collapsed(self.side_panel.is_collapsed(), animate=False)
        layout.addWidget(self.splitter, 1)

        self.bottom_bar = BottomBar()
        layout.addWidget(self.bottom_bar)
        self._registered_shortcut_actions: list[QAction] = []
        self._command_action_map: dict[str, QAction] = {}
        self._command_shortcuts: list[QShortcut] = []
        self._build_menu_bar()
        self.command_bar.set_application_menu(self.menuBar())
        self.command_bar.set_integrated_chrome(self._integrated_chrome)
        if self._integrated_chrome:
            self.menuBar().hide()
            self._main_menu_shortcut = QShortcut(QKeySequence("Alt+M"), self)
            self._main_menu_shortcut.activated.connect(
                self.command_bar.open_application_menu
            )
        self._connect_signals()
        self._load_custom_stamps()
        self._commands: list[Command] = []
        self._build_command_registry()
        self._install_shortcuts()
        self._set_motion_enabled(bool(self.settings.get("animations_enabled", True)))
        self._set_document_available(False)
        self._resize_handles = (
            FramelessResizeHandles(self) if self._integrated_chrome else None
        )

    def _build_menu_bar(self) -> None:
        menu = self.menuBar()
        menu.setNativeMenuBar(True)
        file_menu = menu.addMenu("&File")
        self.open_action = self._action(
            "Open…", QKeySequence.StandardKey.Open, self._open_dialog
        )
        self.search_open_action = self._action(
            "Search and Open PDF…", "Ctrl+Shift+O", self._search_and_open
        )
        self.save_action = self._action(
            "Save", QKeySequence.StandardKey.Save, self.save_file
        )
        self.save_as_action = self._action(
            "Save As…", QKeySequence.StandardKey.SaveAs, self.save_as_file
        )
        self.print_action = self._action(
            "Print…", QKeySequence.StandardKey.Print, self.print_pdf
        )
        self.close_action = self._action(
            "Close Document", "Ctrl+W", self.close_document
        )
        file_menu.addAction(self.open_action)
        self.open_postscript_action = self._action(
            "Open PostScript…", None, self._open_postscript
        )
        file_menu.addAction(self.open_postscript_action)
        file_menu.addAction(self.search_open_action)
        file_menu.addSeparator()
        self.save_all_action = self._action("Save All", None, self.save_all_files)
        for action in (self.save_action, self.save_as_action, self.save_all_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        self.encrypt_action = self._action("Encrypt PDF…", None, self._encrypt_pdf)
        self.decrypt_action = self._action("Decrypt PDF…", None, self._decrypt_pdf)
        file_menu.addAction(self.encrypt_action)
        file_menu.addAction(self.decrypt_action)
        file_menu.addSeparator()
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("Quit", "Ctrl+Q", self.close))

        edit_menu = menu.addMenu("&Edit")
        self.undo_action = self._action("Undo", "Ctrl+Z", self._undo)
        self.redo_action = self._action("Redo", "Ctrl+Y", self._redo)
        self.redo_action.setShortcuts(
            [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")]
        )
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        self.find_action = self._action(
            "Search…", QKeySequence.StandardKey.Find, self.search_document
        )
        edit_menu.addAction(self.find_action)
        edit_menu.addSeparator()
        self.rotate_action = self._action(
            "Rotate Pages…", "F6", lambda: self._show_context("rotate")
        )
        self.insert_action = self._action(
            "Insert Pages…", "F7", self._insert_pages_dialog
        )
        self.delete_action = self._action(
            "Delete Pages…", "F8", self._delete_pages_dialog
        )
        self.extract_action = self._action(
            "Extract Pages…", "F9", self._extract_pages_dialog
        )
        self.split_pages_action = self._action("Split PDF…", "F10", self._split_dialog)
        edit_menu.addAction(self.rotate_action)
        edit_menu.addAction(self.insert_action)
        edit_menu.addAction(self.delete_action)
        edit_menu.addAction(self.extract_action)
        edit_menu.addAction(self.split_pages_action)
        edit_menu.addSeparator()
        self.undo_history_action = self._action(
            "Undo History…", None, self._show_undo_history
        )
        edit_menu.addAction(self.undo_history_action)

        tools_menu = menu.addMenu("&Tools")
        for label, key in (
            ("Merge PDFs…", "merge"),
            ("Compress PDF…", "compress"),
            ("Deep Search…", "deep_search"),
            ("Page Count Report…", "page_report"),
            ("External Tools & Diagnostics…", "diagnostics"),
        ):
            tools_menu.addAction(
                self._action(
                    label,
                    None,
                    lambda _checked=False, value=key: self._tool_requested(value),
                )
            )

        view_menu = menu.addMenu("&View")
        view_menu.addAction(
            self._action("Toggle Tools Panel", "Ctrl+\\", self._toggle_side_panel)
        )
        view_menu.addAction(
            self._action("Toggle Context Panel", "Ctrl+.", self._toggle_context_panel)
        )
        view_menu.addAction(
            self._action("Toggle Page Thumbnails", "Ctrl+T", self._toggle_thumbnails)
        )
        view_menu.addSeparator()
        view_menu.addAction(
            self._action(
                "Show Outline Panel", None, lambda: self._show_nav_tab("outline")
            )
        )
        view_menu.addAction(
            self._action(
                "Show Bookmarks Panel", None, lambda: self._show_nav_tab("bookmarks")
            )
        )
        view_menu.addAction(
            self._action(
                "Show Search Panel", None, lambda: self._show_nav_tab("search")
            )
        )
        view_menu.addSeparator()

        layout_menu = view_menu.addMenu("Page Layout")
        self.layout_group = QActionGroup(self)
        self.layout_group.setExclusive(True)
        self._layout_actions: list[QAction] = []
        for label, shortcut, mode in (
            ("Single Page", "Ctrl+1", "single"),
            ("Continuous Pages", "Ctrl+2", "continuous"),
            ("Facing Pages", "Ctrl+3", "facing"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setShortcut(shortcut)
            action.setData(mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self._set_layout_mode(value)
            )
            self.layout_group.addAction(action)
            self._layout_actions.append(action)
            layout_menu.addAction(action)
        self._layout_actions[0].setChecked(True)

        self.fit_width_action = self._action(
            "Fit Page Width", "Ctrl+0", self._canvas_call("fit_width")
        )
        self.fit_page_action = self._action(
            "Fit Whole Page", "Ctrl+9", self._canvas_call("fit_page")
        )
        self.actual_size_action = self._action(
            "Actual Size", "Ctrl+8", self._canvas_call("actual_size")
        )
        view_menu.addAction(self.fit_width_action)
        view_menu.addAction(self.fit_page_action)
        view_menu.addAction(self.actual_size_action)
        view_menu.addSeparator()

        tool_menu = view_menu.addMenu("Canvas Tool")
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self._tool_actions: list[QAction] = []
        for label, mode in (
            ("Browse", "browse"),
            ("Hand (drag to pan)", "hand"),
            ("Select Text", "select"),
            ("Magnifier", "magnifier"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self._set_canvas_tool(value)
            )
            self.tool_group.addAction(action)
            self._tool_actions.append(action)
            tool_menu.addAction(action)
        self._tool_actions[0].setChecked(True)

        self.show_labels_action = QAction("Show Page Labels", self)
        self.show_labels_action.setCheckable(True)
        self.show_labels_action.setChecked(True)
        self.show_labels_action.triggered.connect(
            lambda checked: self._set_captions(checked)
        )
        view_menu.addAction(self.show_labels_action)

        self.split_action = QAction("Split View (two panes)", self)
        self.split_action.setCheckable(True)
        self.split_action.triggered.connect(self._toggle_split_view)
        view_menu.addAction(self.split_action)
        split_options = view_menu.addMenu("Split View Options")
        self.split_orientation_group = QActionGroup(self)
        self.split_orientation_group.setExclusive(True)
        self._split_orientation_actions: list[QAction] = []
        for label, value in (
            ("Side by side", "horizontal"),
            ("Stacked", "vertical"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(value)
            action.setChecked(
                value == str(self.settings.get("split_orientation", "horizontal"))
            )
            action.triggered.connect(
                lambda _checked=False, orientation=value: (
                    self._set_split_orientation(orientation)
                )
            )
            self.split_orientation_group.addAction(action)
            self._split_orientation_actions.append(action)
            split_options.addAction(action)
        self.split_sync_page_action = QAction("Synchronise page", self)
        self.split_sync_page_action.setCheckable(True)
        self.split_sync_page_action.setChecked(
            bool(self.settings.get("split_sync_page", False))
        )
        self.split_sync_page_action.triggered.connect(self._set_split_sync_page)
        split_options.addAction(self.split_sync_page_action)
        self.split_sync_zoom_action = QAction("Synchronise zoom", self)
        self.split_sync_zoom_action.setCheckable(True)
        self.split_sync_zoom_action.setChecked(
            bool(self.settings.get("split_sync_zoom", False))
        )
        self.split_sync_zoom_action.triggered.connect(self._set_split_sync_zoom)
        split_options.addAction(self.split_sync_zoom_action)
        split_options.addSeparator()
        self.split_reset_action = QAction("Reset panes to 50/50", self)
        self.split_reset_action.triggered.connect(self._reset_split_sizes)
        split_options.addAction(self.split_reset_action)
        self.split_open_document_action = QAction("Open comparison PDF…", self)
        self.split_open_document_action.triggered.connect(
            lambda: self._open_split_document(self._session)
            if self._session is not None
            else None
        )
        split_options.addAction(self.split_open_document_action)

        self.zoom_in_action = self._action(
            "Zoom In", "Ctrl+=", self._canvas_call("zoom_in")
        )
        self.zoom_out_action = self._action(
            "Zoom Out", "Ctrl+-", self._canvas_call("zoom_out")
        )
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addSeparator()
        view_menu.addAction(
            self._action("Toggle Full Screen", "F11", self._toggle_fullscreen)
        )

        navigate_menu = menu.addMenu("&Navigate")
        navigate_menu.addAction(
            self._action("Previous Page", "Ctrl+Left", self.previous_page)
        )
        navigate_menu.addAction(self._action("Next Page", "Ctrl+Right", self.next_page))
        navigate_menu.addAction(
            self._action("First Page", "Home", self._goto_first_page)
        )
        navigate_menu.addAction(self._action("Last Page", "End", self._goto_last_page))

        help_menu = menu.addMenu("&Help")
        help_menu.addAction(self._action("README", None, self._show_readme))
        help_menu.addAction(
            self._action("Command Palette…", "Ctrl+K", self._show_command_palette)
        )
        help_menu.addAction(
            self._action("Keyboard Shortcuts", "Ctrl+/", self._show_shortcuts)
        )
        help_menu.addSeparator()
        help_menu.addAction(
            self._action("Set as Default App…", None, self._set_default_app)
        )
        help_menu.addSeparator()
        help_menu.addAction(
            self._action("About PDFDocuEdit Pro", None, self.show_about)
        )

    def _action(self, label: str, shortcut, callback: Callable) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.setProperty("shortcutBaseLabel", label)
        action.setProperty(
            "shortcutDefault",
            action.shortcut().toString(QKeySequence.SequenceFormat.PortableText),
        )
        self._registered_shortcut_actions.append(action)
        action.triggered.connect(callback)
        return action

    def _connect_signals(self) -> None:
        command = self.command_bar
        command.panelToggled.connect(self._toggle_side_panel)
        command.openClicked.connect(self._open_dialog)
        command.saveClicked.connect(self.save_file)
        command.saveAsClicked.connect(self.save_as_file)
        command.searchClicked.connect(self.search_document)
        command.printClicked.connect(self.print_pdf)
        command.undoClicked.connect(self._undo)
        command.redoClicked.connect(self._redo)
        command.diagnosticsClicked.connect(lambda: self._tool_requested("diagnostics"))
        command.preferencesClicked.connect(self.show_preferences)
        command.aboutClicked.connect(self.show_about)
        command.themeChanged.connect(self._theme_changed)
        command.canvasToolChanged.connect(self._set_canvas_tool)
        command.commandRequested.connect(self._command_bar_requested)
        command.minimizeRequested.connect(self.showMinimized)
        command.maximizeRestoreRequested.connect(self._toggle_maximize_restore)
        command.closeRequested.connect(self.close)
        self.side_panel.toolRequested.connect(self._tool_requested)
        self.side_panel.collapsedChanged.connect(
            lambda value: self.settings.set("left_panel_collapsed", value)
        )
        self.workspace.openRequested.connect(self._open_dialog)
        self.workspace.fileDropped.connect(self._file_dropped)
        self.workspace.extraFilesDropped.connect(self._add_extra_dropped_files)
        self.workspace.tabCloseRequested.connect(self._on_tab_close_requested)
        self.workspace.tabCloseOthersRequested.connect(self._close_other_tabs)
        self.workspace.tabCloseAllRequested.connect(self._close_all_tabs)
        self.workspace.tabChanged.connect(self._on_tab_changed)
        self.bottom_bar.prevClicked.connect(self.previous_page)
        self.bottom_bar.nextClicked.connect(self.next_page)
        self.bottom_bar.gotoClicked.connect(self.goto_page)
        self.bottom_bar.zoomInClicked.connect(self._canvas_call("zoom_in"))
        self.bottom_bar.zoomOutClicked.connect(self._canvas_call("zoom_out"))
        self.bottom_bar.fitWidthClicked.connect(self._canvas_call("fit_width"))
        self.bottom_bar.fitPageClicked.connect(self._canvas_call("fit_page"))
        self.bottom_bar.actualSizeClicked.connect(self._canvas_call("actual_size"))
        self.bottom_bar.layoutChanged.connect(self._set_layout_mode)
        self.bottom_bar.rotateCurrentRequested.connect(self._rotate_current)
        self.bottom_bar.rotatePagesRequested.connect(
            lambda: self._show_context("rotate")
        )
        self.bottom_bar.rotateBoxRequested.connect(self._rotate_box_pages)
        self.bottom_bar.zoomSet.connect(self._canvas_zoom_set)
        self.bottom_bar.zoomSliderChanged.connect(self._zoom_slider_set)
        self.context_panel.annotationStyleChanged.connect(self._set_annot_style)
        self.context_panel.editAnnotationRequested.connect(self._edit_annotation)
        self.context_panel.annotationColorChanged.connect(self._set_annot_color)
        self.context_panel.annotationWidthChanged.connect(self._set_annot_width)
        self.context_panel.stampKindChanged.connect(self._set_stamp_kind)
        self.context_panel.stampImageChanged.connect(self._set_stamp_image)
        self.context_panel.customStampAddRequested.connect(self._add_custom_stamp)
        self.context_panel.customTextStampAddRequested.connect(
            self._add_custom_text_stamp
        )
        self.context_panel.customStampRemoveRequested.connect(
            self._remove_custom_stamp
        )
        self.context_panel.imagePathChanged.connect(self._set_annot_image)
        self.context_panel.removeAnnotationRequested.connect(
            self._handle_remove_annotation
        )
        self.context_panel.applyRedactionsRequested.connect(self._apply_redactions)
        self.context_panel.annotationSelected.connect(self._select_annotation)
        self.context_panel.exportAnnotationsRequested.connect(self._export_annotations)
        self.context_panel.importAnnotationsRequested.connect(self._import_annotations)
        self.context_panel.exportAnnotationSummaryRequested.connect(
            self._export_annotation_summary
        )
        self.context_panel.flattenAnnotationsRequested.connect(
            self._flatten_annotations
        )
        self.context_panel.fontStyleApplyRequested.connect(
            self._apply_inspected_font
        )
        self.context_panel.fontNameCopyRequested.connect(
            self._copy_inspected_font_name
        )
        self.context_panel.closed.connect(self._hide_context)
        self.context_panel.rotateRequested.connect(self._rotate_pages)
        self.context_panel.deleteRequested.connect(self._delete_pages)
        self.context_panel.extractRequested.connect(self._extract_pages)
        self.context_panel.splitRequested.connect(self._split_pdf)
        self.context_panel.insertRequested.connect(self._insert_pages)
        self.context_panel.orderRequested.connect(self._order_pages)
        self.task_bar.cancelRequested.connect(self._cancel_tasks)

    # --- Sessions and tabs ------------------------------------------------
    def _create_session(self) -> DocumentSession:
        session = DocumentSession(
            animations_enabled=bool(self.settings.get("animations_enabled", True)),
            parent=self,
        )
        session.set_split_orientation(
            str(self.settings.get("split_orientation", "horizontal"))
        )
        session.set_split_sync(
            page=bool(self.settings.get("split_sync_page", False)),
            zoom=bool(self.settings.get("split_sync_zoom", False)),
        )
        self._sessions.append(session)
        self.workspace.create_tab(session)
        self._wire_session(session)
        self._session = session
        return session

    def _wire_session(self, session: DocumentSession) -> None:
        self._wire_canvas(session, session.canvas)
        self._wire_navigation(session)
        session.splitSourceRequested.connect(
            lambda source, s=session: self._set_split_source(s, source)
        )
        session.splitOpenRequested.connect(
            lambda s=session: self._open_split_document(s)
        )
        session.splitCloseRequested.connect(
            lambda s=session: self._close_split_view(s)
        )

    def _wire_canvas(self, session: DocumentSession, canvas) -> None:
        canvas.pageChanged.connect(
            lambda page, s=session, c=canvas: self._canvas_page_changed(s, c, page)
        )
        canvas.zoomChanged.connect(
            lambda ratio, s=session, c=canvas: self._canvas_zoom_changed(s, c, ratio)
        )
        canvas.textCopied.connect(self._copy_text_to_clipboard)
        canvas.contextMenuRequested.connect(
            lambda pos, s=session, c=canvas: self._show_canvas_menu(pos, s, c)
        )
        canvas.annotationSelected.connect(
            lambda page, xref, s=session, c=canvas: self._canvas_annotation_selected_from(
                s, c, page, xref
            )
        )
        canvas.annotationContextRequested.connect(
            lambda page, xref, pos, s=session, c=canvas: self._show_annotation_menu_from(
                pos, s, c, page, xref
            )
        )
        canvas.annotationGeometryChanged.connect(
            lambda page, xref, payload, s=session, c=canvas: self._change_annotation_geometry_from(
                s, c, page, xref, payload
            )
        )
        canvas.annotationTextChanged.connect(
            lambda page, xref, text, s=session, c=canvas: self._inline_edit_annotation_from(
                s, c, page, xref, text
            )
        )
        canvas.annotationRequested.connect(
            lambda op, s=session, c=canvas: self._handle_annotation_from(s, c, op)
        )
        canvas.noteRequested.connect(
            lambda page, point, s=session, c=canvas: self._handle_note_from(
                s, c, page, point
            )
        )
        canvas.fontInspectionRequested.connect(
            lambda page, point, s=session, c=canvas: self._handle_font_inspection(
                s, c, page, point
            )
        )

    @staticmethod
    def _external_split_source(session: DocumentSession, canvas):
        if canvas is session.split_canvas:
            return session.split_source_session
        return None

    def _canvas_page_changed(
        self, session: DocumentSession, canvas, page: int
    ) -> None:
        if self._external_split_source(session, canvas) is None:
            self._session_page_changed(session, page)

    def _canvas_zoom_changed(
        self, session: DocumentSession, canvas, ratio: float
    ) -> None:
        if self._external_split_source(session, canvas) is None:
            self._session_zoom_changed(session, ratio)

    def _comparison_read_only(self) -> None:
        self.info_bar.show_message(
            "The comparison document is read-only here. Switch to its tab to edit it.",
            "info",
        )

    def _canvas_annotation_selected_from(
        self, session: DocumentSession, canvas, page: int, xref: int
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._comparison_read_only()
            return
        self._canvas_annotation_selected(session, page, xref)

    def _show_annotation_menu_from(
        self,
        global_pos,
        session: DocumentSession,
        canvas,
        page: int,
        xref: int,
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._show_canvas_menu(global_pos, session, canvas)
            return
        self._show_annotation_menu(global_pos, session, page, xref)

    def _change_annotation_geometry_from(
        self,
        session: DocumentSession,
        canvas,
        page: int,
        xref: int,
        payload: dict,
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._comparison_read_only()
            return
        self._change_annotation_geometry(session, page, xref, payload)

    def _inline_edit_annotation_from(
        self,
        session: DocumentSession,
        canvas,
        page: int,
        xref: int,
        text: str,
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._comparison_read_only()
            return
        self._inline_edit_annotation(session, page, xref, text)

    def _handle_annotation_from(
        self, session: DocumentSession, canvas, op: AnnotationOp
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._comparison_read_only()
            return
        self._handle_annotation(op, session)

    def _handle_note_from(
        self, session: DocumentSession, canvas, page: int, point
    ) -> None:
        if self._external_split_source(session, canvas) is not None:
            self._comparison_read_only()
            return
        self._handle_note_request(page, point, session)

    @staticmethod
    def _session_canvases(session: DocumentSession | None) -> tuple:
        if session is None:
            return ()
        if session.split_canvas is None or session.split_source_session is not None:
            return (session.canvas,)
        return (session.canvas, session.split_canvas)

    def _document_canvases(self, session: DocumentSession) -> tuple:
        canvases = list(self._session_canvases(session))
        for host in self._sessions:
            if (
                host is not session
                and host.split_canvas is not None
                and host.split_source_session is session
            ):
                canvases.append(host.split_canvas)
        return tuple(canvases)

    def _refresh_session_canvases(
        self, session: DocumentSession, pages: set[int] | None = None
    ) -> None:
        for canvas in self._document_canvases(session):
            if pages is None:
                canvas.refresh()
            else:
                canvas.invalidate_pages(pages)

    def _wire_navigation(self, session: DocumentSession) -> None:
        nav = session.nav_panel
        nav.thumbnails.pageSelected.connect(
            lambda page, s=session: self._session_goto(s, page)
        )
        nav.thumbnails.reorderRequested.connect(
            lambda order, s=session: self._handle_thumbnail_reorder(s, order)
        )
        nav.thumbnails.contextActionRequested.connect(
            lambda key, s=session: self._handle_thumbnail_action(s, key)
        )
        nav.closed.connect(lambda s=session: self._session_hide_nav(s))
        nav.tabChanged.connect(
            lambda key, s=session: self._session_nav_tab_changed(s, key)
        )
        nav.outline.jumpRequested.connect(
            lambda page, s=session: self._session_goto(s, page)
        )
        nav.bookmarks.jumpRequested.connect(
            lambda page, s=session: self._session_goto(s, page)
        )
        nav.bookmarks.addRequested.connect(lambda s=session: self._add_bookmark(s))
        nav.bookmarks.removeRequested.connect(
            lambda row, s=session: self._remove_bookmark(row, s)
        )
        nav.search.searchRequested.connect(
            lambda query, pages, s=session: self._run_search(query, s, pages)
        )
        nav.search.jumpRequested.connect(
            lambda page, rects, s=session: self._goto_search_hit(page, rects, s)
        )
        nav.search.closed.connect(lambda s=session: self._hide_search_panel(s))
        nav.search.ocrRequested.connect(lambda s=session: self._run_ocr_from_search(s))

        analysis = session.analysis_panel
        analysis.runRequested.connect(
            lambda request, s=session: self._run_analysis_request(s, request)
        )
        analysis.jumpRequested.connect(
            lambda page, s=session: self._session_goto(s, page)
        )
        analysis.organizeRequested.connect(
            lambda findings, s=session: self._organize_findings(s, findings)
        )
        analysis.extractRequested.connect(
            lambda pages, s=session: self._extract_analysis_pages(s, pages)
        )
        analysis.closed.connect(lambda s=session: s.analysis_panel.hide())

    def _canvas_call(self, method: str):
        def call() -> None:
            canvas = self.workspace.canvas
            if canvas is not None:
                getattr(canvas, method)()

        return call

    def _canvas_zoom_set(self, ratio: float) -> None:
        canvas = self.workspace.canvas
        if canvas is not None:
            canvas.set_zoom(ratio)

    def _zoom_slider_set(self, percent: int) -> None:
        self._canvas_zoom_set(percent / 100.0)

    def _session_page_changed(self, session: DocumentSession, page: int) -> None:
        if session is not self._session:
            return
        page_changed = session.page != page
        session.page = page
        if page_changed:
            # Selection handles are page-local editing affordances. Keeping
            # them across navigation makes an old annotation appear active
            # again when the user returns to its page.
            for canvas in self._session_canvases(session):
                canvas.clear_annotation_selection()
        self._update_page_state()
        session.nav_panel.thumbnails.set_current_page(page)
        session.nav_panel.bookmarks.set_current_page(page)
        self._refresh_annotate_list()

    def _session_nav_tab_changed(self, session: DocumentSession, key: str) -> None:
        if key != "thumbnails":
            return

        def synchronize() -> None:
            if session not in self._sessions or not session.engine.is_loaded():
                return
            if session.nav_panel.active_key() != "thumbnails":
                return
            page = min(
                max(0, session.canvas.current_page), session.engine.page_count - 1
            )
            session.page = page
            session.nav_panel.thumbnails.set_current_page(page)

        QTimer.singleShot(0, synchronize)

    def _session_zoom_changed(self, session: DocumentSession, ratio: float) -> None:
        if session is not self._session:
            return
        self.settings.set_zoom_ratio(ratio)
        self.bottom_bar.set_zoom_percent(round(ratio * 100))

    def _session_goto(self, session: DocumentSession, page: int) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        self.goto_page(page)

    def _session_hide_nav(self, session: DocumentSession) -> None:
        if session is self._session:
            self.workspace.show_thumbnails(False)

    def _handle_thumbnail_reorder(
        self, session: DocumentSession, order: list[int]
    ) -> None:
        self._session = session
        if not session.engine.is_loaded():
            return
        if order == list(range(session.engine.page_count)) or sorted(order) != list(
            range(session.engine.page_count)
        ):
            self._reload_thumbnails(session)
            return
        if not self._snapshot_before("Reorder Pages"):
            self._reload_thumbnails(session)
            return
        try:
            session.engine.reorder_pages(order)
        except Exception as exc:
            self.info_bar.show_message(f"Reorder failed: {exc}", "error", 0)
            self._reload_thumbnails(session)
            return
        self._refresh_session_canvases(session)
        self._reload_thumbnails(session)
        self._after_page_count_change()
        self.info_bar.show_message(
            "🔀 Pages reordered. Save the document to keep the change.", "success"
        )

    def _reload_thumbnails(self, session: DocumentSession) -> None:
        # The open-time temp copy never reflects in-memory edits, so snapshot
        # the live document into a fresh file the render tasks can read. The
        # previous snapshot is deleted after loading: stale render tasks then
        # fail silently and are dropped by the thumbnail panel's generation
        # guard.
        handle, temp_name = tempfile.mkstemp(prefix="thumbnails-", suffix=".pdf")
        os.close(handle)
        Path(temp_name).unlink(missing_ok=True)
        try:
            session.engine.snapshot(temp_name)
        except Exception:
            fallback = session.engine.temp_path
            if fallback:
                temp_name = str(fallback)
            else:
                return
        previous = getattr(session, "_thumbnail_snapshot", None)
        session.nav_panel.thumbnails.load_document(
            temp_name, session.engine.page_count, session.engine.password
        )
        session.nav_panel.thumbnails.set_current_page(session.page)
        session._thumbnail_snapshot = temp_name
        if previous and previous != temp_name:
            Path(previous).unlink(missing_ok=True)

    def _on_tab_changed(self, session: DocumentSession) -> None:
        self._session = session
        self._last_context_key = None
        self._set_canvas_tool(session.canvas.tool_mode.value)
        self.split_action.setChecked(session.has_split)
        self._sync_split_actions(session)
        for action in self._layout_actions:
            if action.data() == session.canvas.layout_mode.value:
                action.setChecked(True)
                break
        if not session.engine.is_loaded():
            return
        self._update_undo_actions()
        self._sync_modified_state()
        session_path = session.display_path or session.engine.original_path
        self.bottom_bar.set_document_info(
            session.document_name,
            session.engine.page_count,
            str(session_path) if session_path else "",
        )
        self.bottom_bar.set_current_page(session.page)
        self.bottom_bar.set_zoom_percent(round(session.canvas.zoom_ratio * 100))
        self.bottom_bar.set_layout_mode(str(session.canvas.layout_mode.value))
        self.context_panel.set_page_count(session.engine.page_count)
        session.nav_panel.search.set_page_count(session.engine.page_count)
        session.nav_panel.search.set_current_page(session.page)
        self._set_document_available(True)
        self._refresh_annotate_list()
        self._session_nav_tab_changed(session, session.nav_panel.active_key())
        self._refresh_all_split_source_choices()

    def _on_tab_close_requested(self, session: DocumentSession) -> None:
        self.close_document(session)

    def open_in_new_tab(self, path: str) -> DocumentSession | None:
        session = self._create_session()
        try:
            loaded = self._load_path(session, path)
        except Exception as exc:
            loaded = False
            self._error("Open failed", str(exc))
        if not loaded and not session.engine.is_loaded():
            # Remove the placeholder tab a failed open left behind.
            self.close_document(session)
            return None
        return session

    def open_files(self, paths: list[str]) -> None:
        """Open several documents at once, each in its own tab.

        The first document reuses the current tab when it is an untouched
        placeholder (a tab that exists but has nothing loaded); otherwise
        every document opens in a fresh tab, matching drag-and-drop
        behaviour.
        """
        paths = [path for path in paths if path]
        if not paths:
            return
        first, rest = paths[0], paths[1:]
        current = self._session
        if (
            current is not None
            and not current.engine.is_loaded()
            and not current.engine.is_modified
        ):
            self.load_file(first)
        else:
            self.open_in_new_tab(first)
        for path in rest:
            self.open_in_new_tab(path)

    def queue_open_files(self, paths: list[str]) -> None:
        """Open shell/file-association requests after the window can paint.

        Large PDFs are copied to an editable working file by PdfEngine.open.
        Running that work inside the constructor kept the splash on screen and
        made Windows report the app as loading. The zero-delay handoff lets
        the native main window and loading status become visible first.
        """
        self._queued_open_paths.extend((path, None) for path in paths if path)
        self._schedule_queued_open()

    def _schedule_queued_open(self) -> None:
        """Ensure queued shell/file-association paths have an active drain."""
        if not self._queued_open_paths or self._open_queue_scheduled:
            return
        self._open_queue_scheduled = True
        self.task_bar.start("Opening document", cancellable=False)
        self.command_bar.set_work_status("Opening document")
        self.bottom_bar.set_status("Opening document")
        QTimer.singleShot(0, self._drain_open_queue)

    def _drain_open_queue(self) -> None:
        if not self._queued_open_paths:
            self._open_queue_scheduled = False
            return
        if self._tasks:
            QTimer.singleShot(100, self._drain_open_queue)
            return
        path, password = self._queued_open_paths.pop(0)
        source = Path(path).expanduser().resolve()
        if source.suffix.casefold() != ".pdf":
            current = self._session
            if current is not None and not current.engine.is_loaded():
                self.load_file(str(source))
            else:
                self.open_in_new_tab(str(source))
            self._queued_open_finished()
            return
        current = self._session
        session = (
            current
            if current is not None
            and not current.engine.is_loaded()
            and not current.engine.is_modified
            else self._create_session()
        )
        self.workspace.set_current_session(session)
        self._session = session
        session.canvas.wait_for_renders()
        self._start_queued_pdf_open(session, str(source), password)

    def _start_queued_pdf_open(
        self,
        session: DocumentSession,
        path: str,
        password: str | None,
    ) -> None:
        display_path = Path(path)
        self._run_task(
            "Opening document",
            _prepare_pdf_engine,
            path,
            password,
            on_result=lambda result: self._queued_pdf_prepared(
                session,
                display_path,
                result,
            ),
            on_finished=self._queued_open_finished,
        )

    def _queued_pdf_prepared(
        self,
        session: DocumentSession,
        display_path: Path,
        result: tuple[str, PdfEngine | str | None],
    ) -> None:
        status, value = result
        if status in {"password_required", "invalid_password"}:
            if status == "invalid_password":
                self.info_bar.show_message("The password is not valid.", "error")
            password, accepted = ask_password(
                self,
                "Encrypted PDF",
                "Password (ASCII characters only)",
            )
            if accepted:
                self._queued_open_paths.insert(
                    0,
                    (str(display_path), password),
                )
                # QInputDialog.exec() runs a nested event loop. The worker's
                # finished signal may therefore have cleared the queue state
                # while the user was entering the password. Explicitly ensure
                # the authenticated retry has a live drain.
                self._schedule_queued_open()
            return
        if status == "error":
            self._error("Open failed", str(value))
            return
        opened = value
        if not isinstance(opened, PdfEngine):
            self._error("Open failed", "The PDF engine did not return a document.")
            return
        if self._closing or session not in self._sessions:
            opened.close()
            return
        self.workspace.set_current_session(session)
        self._session = session
        self._replace_session_engine(session, opened)
        self._complete_pdf_open(session, display_path)

    def _queued_open_finished(self) -> None:
        if self._closing:
            self._open_queue_scheduled = False
            return
        if self._queued_open_paths:
            QTimer.singleShot(0, self._drain_open_queue)
        else:
            self._open_queue_scheduled = False

    def _toggle_split_view(self) -> None:
        session = self._session
        if not session or not session.engine.is_loaded():
            self.info_bar.show_message(
                "Open a PDF before splitting the view.", "warning"
            )
            return
        session.set_split(not session.has_split)
        if session.split_canvas is not None:
            split = session.split_canvas
            split.set_tool_mode(session.canvas.tool_mode)
            split.set_annotation_options(**session.canvas.annotation_options())
            self._wire_canvas(session, split)
            self._refresh_split_source_choices(session)
        self.split_action.setChecked(session.has_split)
        self._sync_split_actions(session)
        if session.has_split:
            QTimer.singleShot(0, session.reset_split_sizes)
        self.info_bar.show_message(
            (
                "Split view enabled. Choose another open document or Open PDF "
                "in the comparison header."
                if session.has_split
                else "Split view closed."
            ),
            "success",
        )

    def _close_split_view(self, session: DocumentSession) -> None:
        if not session.has_split:
            return
        session.set_split(False)
        if session is self._session:
            self.split_action.setChecked(False)
            self._sync_split_actions(session)
        self.info_bar.show_message("Split view closed.", "success")

    def _set_split_source(
        self,
        host: DocumentSession,
        source: DocumentSession | None,
    ) -> None:
        if host not in self._sessions or not host.has_split:
            return
        if source is host or source not in self._sessions:
            source = None
        if not host.set_split_source(source):
            self.info_bar.show_message(
                "The selected comparison document is no longer available.",
                "warning",
            )
            source = None
            host.set_split_source(None)
        if host.split_canvas is not None:
            if source is None:
                host.split_canvas.set_tool_mode(host.canvas.tool_mode)
                host.split_canvas.set_annotation_options(
                    **host.canvas.annotation_options()
                )
            else:
                host.split_canvas.set_tool_mode("browse")
        self._refresh_split_source_choices(host)
        name = host.document_name if source is None else source.document_name
        mode = "same-document view" if source is None else "read-only comparison"
        self.info_bar.show_message(f"Split pane: {name} ({mode}).", "success")

    def _refresh_split_source_choices(self, host: DocumentSession) -> None:
        pane = host.split_pane
        if pane is None:
            return
        sources: list[tuple[str, object | None]] = [
            (f"Same document — {host.document_name}", None)
        ]
        sources.extend(
            (candidate.document_name, candidate)
            for candidate in self._sessions
            if candidate is not host and candidate.engine.is_loaded()
        )
        pane.set_sources(sources, host.split_source_session)

    def _refresh_all_split_source_choices(self) -> None:
        for session in self._sessions:
            self._refresh_split_source_choices(session)

    def _open_split_document(self, host: DocumentSession) -> None:
        if host not in self._sessions or not host.engine.is_loaded():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open comparison PDF",
            self.settings.get_last_directory(),
            "PDF (*.pdf)",
        )
        if not path:
            return
        source = self.open_in_new_tab(path)
        if source is None:
            return
        self.workspace.set_current_session(host)
        self._session = host
        if not host.has_split:
            host.set_split(True)
            if host.split_canvas is not None:
                self._wire_canvas(host, host.split_canvas)
        self._set_split_source(host, source)
        self.split_action.setChecked(True)
        self._sync_split_actions(host)

    def _set_split_orientation(self, orientation: str) -> None:
        value = "vertical" if orientation == "vertical" else "horizontal"
        self.settings.set("split_orientation", value)
        if self._session is not None:
            self._session.set_split_orientation(value)
            self._sync_split_actions(self._session)

    def _set_split_sync_page(self, checked: bool) -> None:
        self.settings.set("split_sync_page", bool(checked))
        if self._session is not None:
            self._session.set_split_sync(page=bool(checked))
            self._sync_split_actions(self._session)

    def _set_split_sync_zoom(self, checked: bool) -> None:
        self.settings.set("split_sync_zoom", bool(checked))
        if self._session is not None:
            self._session.set_split_sync(zoom=bool(checked))
            self._sync_split_actions(self._session)

    def _reset_split_sizes(self) -> None:
        if self._session is not None:
            self._session.reset_split_sizes()

    def _sync_split_actions(self, session: DocumentSession) -> None:
        for action in self._split_orientation_actions:
            action.setChecked(action.data() == session.split_orientation)
        self.split_sync_page_action.setChecked(session.split_sync_page)
        self.split_sync_zoom_action.setChecked(session.split_sync_zoom)
        self.split_reset_action.setEnabled(session.has_split)
        self.split_open_document_action.setEnabled(session.has_split)

    # --- Theme and window state -----------------------------------------
    def _apply_theme(self, value: str) -> None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        apply_theme(app, ThemeMode(value))
        app.setStyleSheet(global_style())
        clear_icon_cache()
        self.command_bar.refresh_icons()
        self.side_panel.refresh_icons()
        self.bottom_bar.refresh_icons()
        self.info_bar.refresh_icons()
        self.context_panel.refresh_icons()
        self.workspace.refresh_icons()
        self._update_title_bar()

    def _update_title_bar(self) -> None:
        """Match the Windows title bar (non-client frame) to the theme."""
        import sys as _sys

        if _sys.platform != "win32" or self._integrated_chrome:
            return
        try:
            import ctypes

            from styles.theme import get_colors

            hwnd = int(self.winId())
            if not hwnd:
                return
            base = get_colors().get("bg_base", "#1c1c1e")
            dark = QColor(base).lightness() < 128
            value = ctypes.c_int(1 if dark else 0)
            dwmapi = ctypes.windll.dwmapi
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (1903+), 19 (1809 fallback)
            for attribute in (20, 19):
                result = dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                if result == 0:
                    break

            def set_color(attribute: int, color: QColor) -> None:
                color_ref = (color.blue() << 16) | (color.green() << 8) | color.red()
                dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(ctypes.c_int(color_ref)), 4
                )

            background = QColor(base)
            if dark:
                # Windows 11 "show accent colour on title bars" overrides the
                # dark flag with the accent colour (blue), so pin the caption,
                # text and border colours explicitly to the app palette.
                # DWMWA_BORDER_COLOR = 34, CAPTION_COLOR = 35, TEXT_COLOR = 36.
                set_color(34, background)
                set_color(35, background)
                set_color(36, QColor(get_colors().get("text_primary", "#f2f2f4")))
            else:
                none = 0xFFFFFFFE  # DWMWA_COLOR_NONE
                for attribute in (34, 35, 36):
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(ctypes.c_int(none)), 4
                    )
        except Exception:
            pass

    def _theme_changed(self, value: str) -> None:
        self.settings.set_theme(value)
        self._apply_theme(value)

    def _set_motion_enabled(self, enabled: bool) -> None:
        self.command_bar.set_animations_enabled(enabled)
        self.side_panel.set_animations_enabled(enabled)
        self.bottom_bar.set_animations_enabled(enabled)
        self.context_panel.set_animations_enabled(enabled)
        self.info_bar.set_animations_enabled(enabled)
        self.workspace.set_animations_enabled(enabled)

    def _restore_window_state(self) -> None:
        width, height = self.settings.get_window_size()
        position = self.settings.get_window_position()
        screen = QGuiApplication.screenAt(QPoint(*position)) if position else None
        screen = screen or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(min(width, area.width()), min(height, area.height()))
            if position:
                x = max(area.left(), min(position[0], area.right() - self.width() + 1))
                y = max(area.top(), min(position[1], area.bottom() - self.height() + 1))
                self.move(x, y)
            else:
                self.move(area.center() - self.rect().center())
        else:
            self.resize(width, height)
        if self.settings.get("window_maximized", False):
            self.showMaximized()

    def _toggle_side_panel(self) -> None:
        self.side_panel.set_collapsed(not self.side_panel.is_collapsed())

    def _toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.command_bar.set_maximized(self.isMaximized())

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _close_other_tabs(self, session: DocumentSession) -> None:
        for candidate in list(self._sessions):
            if candidate is not session:
                self.close_document(candidate)

    def _close_all_tabs(self) -> None:
        for candidate in list(self._sessions):
            self.close_document(candidate)

    def _file_dropped(self, path: str) -> None:
        """A dropped file opens in a new tab when a document is already open.

        Replacing the current document on drop was legacy behaviour; with
        tabs available, drops must never destroy the open work.
        """
        if self._session is None or not self._session.engine.is_loaded():
            self.load_file(path)
        else:
            self.open_in_new_tab(path)

    def _add_extra_dropped_files(self, paths: list) -> None:
        for raw in paths:
            self.open_in_new_tab(raw)

    def _toggle_context_panel(self) -> None:
        if self.context_panel.isVisible():
            self._hide_context()
        elif self._last_context_key:
            self._show_context(self._last_context_key)

    def _toggle_thumbnails(self) -> None:
        session = self._session
        if session is None:
            return
        right_panel_visible = (
            session.search_panel.isVisible() or session.analysis_panel.isVisible()
        )
        if (
            session.nav_panel.isVisible()
            and session.nav_panel.active_key() == "thumbnails"
            and not right_panel_visible
        ):
            session.nav_panel.hide()
            sizes = session.tab_widget.sizes()
            total = max(sum(sizes), session.tab_widget.width(), 900)
            session.tab_widget.setSizes([0, total, 0, 0])
            return
        self._show_nav_tab("thumbnails")

    def _goto_first_page(self) -> None:
        self.goto_page(0)

    def _goto_last_page(self) -> None:
        engine = self.engine
        if engine is not None:
            self.goto_page(engine.page_count - 1)

    def _set_layout_mode(self, mode: str) -> None:
        canvas = self.workspace.canvas
        if canvas is not None:
            canvas.set_layout_mode(mode)
        self.bottom_bar.set_layout_mode(mode)

    def _set_canvas_tool(self, mode: str) -> None:
        session = self._session
        canvases = list(self._session_canvases(session))
        if (
            session is not None
            and session.split_canvas is not None
            and session.split_source_session is not None
        ):
            if mode == "font_inspect":
                canvases.append(session.split_canvas)
            else:
                session.split_canvas.set_tool_mode("browse")
        for canvas in canvases:
            canvas.set_tool_mode(mode)
        for action in self._tool_actions:
            action.setChecked(action.data() == mode)
        self.command_bar.set_canvas_tool(mode)
        self.bottom_bar.set_status(f"Tool: {mode.replace('_', ' ').title()}")

    def _escape_to_browse(self) -> None:
        canvas = self.workspace.canvas
        if canvas is None or str(canvas.tool_mode) == "browse":
            return
        self._set_canvas_tool("browse")
        self.side_panel.set_active_tool(None)

    def _command_bar_requested(self, key: str) -> None:
        if key == "toggle_thumbnails":
            self._toggle_thumbnails()
        elif key == "view_split":
            self._toggle_split_view()
        else:
            self._tool_requested(key)

    def _set_captions(self, checked: bool) -> None:
        session = self._session
        if session is None:
            return
        session.canvas.set_show_captions(bool(checked))
        if session.split_canvas is not None:
            session.split_canvas.set_show_captions(bool(checked))

    def _toggle_page_labels(self) -> None:
        session = self._session
        if session is None:
            return
        show = not session.canvas.show_captions
        self._set_captions(show)
        self.show_labels_action.setChecked(show)

    def _next_tab(self) -> None:
        self.workspace.activate_next()

    def _previous_tab(self) -> None:
        self.workspace.activate_previous()

    def _copy_text_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _show_canvas_menu(
        self, global_pos, session: DocumentSession, canvas=None
    ) -> None:
        """Right-click menu for the PDF canvas."""
        canvas = canvas or session.canvas
        source = self._external_split_source(session, canvas)
        if source is not None:
            self._show_comparison_canvas_menu(global_pos, session, source, canvas)
            return
        menu = QMenu(self)
        loaded = session.engine.is_loaded()

        def activate() -> None:
            self.workspace.set_current_session(session)
            self._session = session

        copy_action = menu.addAction("Copy Text", canvas.copy_selection)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.setEnabled(loaded and bool(canvas.selected_text()))
        menu.addSeparator()

        def activate_then(handler):
            def run() -> None:
                activate()
                handler()

            return run

        previous = menu.addAction(
            "Previous Page",
            activate_then(lambda: canvas.set_page(canvas.current_page - 1)),
        )
        previous.setShortcut("Ctrl+Left")
        previous.setEnabled(loaded)
        next_page = menu.addAction(
            "Next Page",
            activate_then(lambda: canvas.set_page(canvas.current_page + 1)),
        )
        next_page.setShortcut("Ctrl+Right")
        next_page.setEnabled(loaded)
        first = menu.addAction(
            "First Page", activate_then(lambda: canvas.set_page(0))
        )
        first.setShortcut("Home")
        first.setEnabled(loaded)
        last = menu.addAction(
            "Last Page",
            activate_then(lambda: canvas.set_page(session.engine.page_count - 1)),
        )
        last.setShortcut("End")
        last.setEnabled(loaded)
        menu.addSeparator()

        zoom_in = menu.addAction("Zoom In", activate_then(canvas.zoom_in))
        zoom_in.setShortcut("Ctrl+=")
        zoom_in.setEnabled(loaded)
        zoom_out = menu.addAction(
            "Zoom Out", activate_then(canvas.zoom_out)
        )
        zoom_out.setShortcut("Ctrl+-")
        zoom_out.setEnabled(loaded)
        fit_width = menu.addAction(
            "Fit Page Width", activate_then(canvas.fit_width)
        )
        fit_width.setShortcut("Ctrl+0")
        fit_width.setEnabled(loaded)
        fit_page = menu.addAction(
            "Fit Whole Page", activate_then(canvas.fit_page)
        )
        fit_page.setShortcut("Ctrl+9")
        fit_page.setEnabled(loaded)
        actual = menu.addAction(
            "Actual Size", activate_then(canvas.actual_size)
        )
        actual.setShortcut("Ctrl+8")
        actual.setEnabled(loaded)

        layout_menu = menu.addMenu("Page Layout")
        layout_menu.setEnabled(loaded)
        for label, mode in (
            ("Single Page", "single"),
            ("Continuous Pages", "continuous"),
            ("Facing Pages", "facing"),
        ):
            action = layout_menu.addAction(
                label, activate_then(lambda v=mode: canvas.set_layout_mode(v))
            )
            action.setCheckable(True)
            action.setChecked(canvas.layout_mode.value == mode)
        menu.addSeparator()

        rotate_left = menu.addAction(
            "Rotate Left", activate_then(lambda: self._rotate_current(-90))
        )
        rotate_left.setShortcut("Ctrl+L")
        rotate_left.setEnabled(loaded)
        rotate_right = menu.addAction(
            "Rotate Right", activate_then(lambda: self._rotate_current(90))
        )
        rotate_right.setShortcut("Ctrl+R")
        rotate_right.setEnabled(loaded)
        extract = menu.addAction(
            "Extract Current Page…",
            lambda: self._handle_thumbnail_action(session, "extract_current"),
        )
        extract.setEnabled(loaded)
        insert = menu.addAction(
            "Insert Pages…", activate_then(self._insert_pages_dialog)
        )
        insert.setShortcut("F7")
        insert.setEnabled(loaded)
        delete = menu.addAction(
            "Delete Pages…", activate_then(self._delete_pages_dialog)
        )
        delete.setShortcut("F8")
        delete.setEnabled(loaded)
        menu.addSeparator()

        bookmark = menu.addAction("Add Bookmark", lambda: self._add_bookmark(session))
        bookmark.setShortcut("Ctrl+D")
        bookmark.setEnabled(loaded)
        print_action = menu.addAction("Print…", activate_then(self.print_pdf))
        print_action.setShortcut("Ctrl+P")
        print_action.setEnabled(loaded)
        info = menu.addAction(
            "Document Info",
            self.show_document_info,
        )
        info.setEnabled(loaded)

        menu.exec(global_pos)

    def _show_comparison_canvas_menu(
        self,
        global_pos,
        host: DocumentSession,
        source: DocumentSession,
        canvas,
    ) -> None:
        """Safe navigation menu for an external, read-only comparison pane."""

        menu = QMenu(self)
        heading = menu.addAction(f"Comparing: {source.document_name}")
        heading.setEnabled(False)
        switch = menu.addAction("Switch to editable document tab")
        switch.triggered.connect(
            lambda: self.workspace.set_current_session(source)
        )
        menu.addSeparator()
        copy_action = menu.addAction("Copy Text", canvas.copy_selection)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.setEnabled(bool(canvas.selected_text()))
        previous = menu.addAction(
            "Previous Page", lambda: canvas.set_page(canvas.current_page - 1)
        )
        previous.setEnabled(canvas.current_page > 0)
        next_page = menu.addAction(
            "Next Page", lambda: canvas.set_page(canvas.current_page + 1)
        )
        next_page.setEnabled(canvas.current_page + 1 < source.engine.page_count)
        menu.addSeparator()
        menu.addAction("Zoom In", canvas.zoom_in)
        menu.addAction("Zoom Out", canvas.zoom_out)
        menu.addAction("Fit Page Width", canvas.fit_width)
        menu.addAction("Fit Whole Page", canvas.fit_page)
        layout_menu = menu.addMenu("Page Layout")
        for label, mode in (
            ("Single Page", "single"),
            ("Continuous Pages", "continuous"),
            ("Facing Pages", "facing"),
        ):
            action = layout_menu.addAction(
                label, lambda _checked=False, value=mode: canvas.set_layout_mode(value)
            )
            action.setCheckable(True)
            action.setChecked(canvas.layout_mode.value == mode)
        menu.addSeparator()
        menu.addAction(
            "Use same document in both panes",
            lambda: self._set_split_source(host, None),
        )
        menu.addAction("Close split view", lambda: self._close_split_view(host))
        menu.exec(global_pos)

    def _show_annotation_menu(
        self, global_pos, session: DocumentSession, page: int, xref: int
    ) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        session.canvas.select_annotation(page, xref)
        menu = QMenu(self)
        menu.addAction(
            "Edit Properties…",
            lambda: self._focus_annotation_properties(page, xref),
        )
        menu.addAction(
            "Delete Annotation",
            lambda: self._handle_remove_annotation(page, xref),
        )
        menu.exec(global_pos)

    def _focus_annotation_properties(self, page: int, xref: int) -> None:
        self._select_annotation(page, xref)
        self._show_context("annotate", "Annotation Options")

    def _canvas_annotation_selected(
        self, session: DocumentSession, page: int, xref: int
    ) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        for canvas in self._session_canvases(session):
            canvas.select_annotation(page, xref)
        if session.page != page:
            self.goto_page(page)
        self.context_panel.select_annotation(page, xref)

    def _change_annotation_geometry(
        self,
        session: DocumentSession,
        page: int,
        xref: int,
        payload: dict,
    ) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        if not self._snapshot_before("Move/Resize Annotation"):
            return
        try:
            new_xref = update_annotation_geometry(
                session.engine.document.load_page(page),
                xref,
                rect=payload.get("rect"),
                points=tuple(payload.get("points") or ()),
            )
            if new_xref is None:
                raise ValueError("This annotation cannot be moved or resized.")
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"Move/resize failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session, {page})
        for canvas in self._session_canvases(session):
            canvas.select_annotation(page, new_xref)
        self._sync_modified_state()
        self._refresh_annotate_list()

    def _inline_edit_annotation(
        self,
        session: DocumentSession,
        page: int,
        xref: int,
        text: str,
    ) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        if not self._snapshot_before("Edit Annotation Text"):
            return
        try:
            if not update_annotation_text(
                session.engine.document.load_page(page), xref, text
            ):
                raise ValueError("The annotation no longer exists or is not editable.")
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"Inline edit failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session, {page})
        self._sync_modified_state()
        self._refresh_annotate_list()

    # --- Document lifecycle ---------------------------------------------
    def _open_dialog(self) -> None:
        # Multi-select: every chosen file opens in its own tab.
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open documents",
            self.settings.get_last_directory(),
            "Supported documents (*.pdf *.ps *.eps);;PDF (*.pdf);;PostScript (*.ps *.eps)",
        )
        if paths:
            self.open_files(paths)

    def _open_postscript(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open PostScript",
            self.settings.get_last_directory(),
            "PostScript (*.ps *.eps)",
        )
        if path:
            self.load_file(path)

    def _search_and_open(self) -> None:
        dialog = SearchOpenDialog(self.settings.get_last_directory(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_path:
            return
        if dialog.open_in_new_tab:
            self.open_in_new_tab(dialog.selected_path)
        else:
            self.load_file(dialog.selected_path)

    def load_file(self, path: str) -> None:
        if self._session is not None and self._session.engine.is_loaded():
            if not self._confirm_discard_changes():
                return
        created = self._session is None
        session = self._session or self._create_session()
        try:
            loaded = self._load_path(session, path)
        except Exception as exc:
            # Never let an unexpected open failure escape the slot (qFatal).
            loaded = False
            self._error("Open failed", str(exc))
        if not loaded and created and not session.engine.is_loaded():
            # Remove the placeholder tab a failed open left behind so the
            # user is not stuck with an unclosable empty tab.
            self.close_document(session)

    def _load_path(self, session: DocumentSession, path: str) -> bool:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            self._error("Open failed", f"The file does not exist:\n{source}")
            return False
        if source.suffix.casefold() not in {".pdf", ".ps", ".eps"}:
            self._error("Open failed", "Choose a PDF, PostScript, or EPS file.")
            return False
        self.workspace.set_current_session(session)
        self._session = session
        if source.suffix.lower() in {".ps", ".eps"}:
            handle, temp_name = tempfile.mkstemp(suffix=".pdf")
            os.close(handle)
            try:
                convert_postscript(source, temp_name)
                return self._open_pdf(session, temp_name, display_path=source)
            except Exception as exc:
                self._error("PostScript conversion failed", str(exc))
                return False
            finally:
                Path(temp_name).unlink(missing_ok=True)
        return self._open_pdf(session, str(source), display_path=source)

    def _open_pdf(
        self,
        session: DocumentSession,
        path: str,
        display_path: Path,
        *,
        reset_history: bool = True,
        announce: bool = True,
        preserve_save_context: bool = False,
        restored_modified: bool = True,
    ) -> bool:
        # Background canvas renders hold the live document; wait for them
        # before replacing it.
        opened = PdfEngine()
        password: str | None = None
        while True:
            try:
                opened.open(path, password)
                break
            except PdfPasswordRequired:
                password, accepted = ask_password(
                    self,
                    "Encrypted PDF",
                    "Password (ASCII characters only)",
                )
                if not accepted:
                    opened.close()
                    return False
            except PdfInvalidPassword:
                self.info_bar.show_message("The password is not valid.", "error")
                password = None
            except Exception as exc:
                opened.close()
                self._error("Open failed", str(exc))
                return False
        if preserve_save_context:
            opened.inherit_save_context(
                session.engine, modified=restored_modified
            )
        self._replace_session_engine(session, opened)
        return self._complete_pdf_open(
            session,
            display_path,
            reset_history=reset_history,
            announce=announce,
        )

    def _replace_session_engine(
        self,
        session: DocumentSession,
        opened: PdfEngine,
    ) -> None:
        """Release all old-document readers before deleting its temp copy."""
        dependent_hosts = [
            host
            for host in self._sessions
            if host is not session and host.split_source_session is session
        ]
        for host in dependent_hosts:
            if host.split_canvas is not None:
                host.split_canvas.clear()
        session.canvas.clear()
        if (
            session.split_canvas is not None
            and session.split_source_session is None
        ):
            session.split_canvas.clear()
        session.nav_panel.thumbnails.quiesce_renders()
        previous = session.engine
        session.engine = opened
        previous.close()
        for host in dependent_hosts:
            host.set_split_source(session)

    def _complete_pdf_open(
        self,
        session: DocumentSession,
        display_path: Path,
        *,
        reset_history: bool = True,
        announce: bool = True,
    ) -> bool:
        self.workspace.set_current_session(session)
        self._session = session
        # Keep the user-facing source path when a PostScript temp PDF was used.
        if display_path.suffix.lower() == ".pdf":
            self.settings.add_recent_file(display_path)
        else:
            self.engine.detach_save_target()
        self._display_path = display_path
        self.settings.set_last_directory(display_path.parent)
        if reset_history:
            self._undo_stack.clear()
        self._update_undo_actions()
        self.workspace.set_recent_files(self.settings.recent_files())
        zoom = self.settings.get_zoom_ratio()
        session.canvas.load_doc(self.engine.document, zoom)
        if (
            session.split_canvas is not None
            and session.split_source_session is None
        ):
            session.split_canvas.load_doc(self.engine.document, zoom)
            session.split_canvas.set_page(0, emit=False)
        temp_path = self.engine.temp_path
        if temp_path:
            self.workspace.nav_panel.load_document(
                str(temp_path), self.engine.page_count, self.engine.password
            )
        self._load_navigation()
        self.workspace.show_document(True)
        self._page = 0
        self._set_document_available(True)
        self._sync_modified_state()
        self.bottom_bar.set_document_info(
            display_path.name, self.engine.page_count, str(display_path)
        )
        self.context_panel.set_page_count(self.engine.page_count)
        self._update_page_state()
        self._refresh_annotate_list()
        self._refresh_all_split_source_choices()
        if announce:
            self.info_bar.show_message(
                f"✅ Loaded: {display_path.name}", "success", 2500
            )
        return True

    def save_file(self) -> None:
        if not self.engine.is_loaded():
            return
        if not self.engine.original_path:
            self.save_as_file()
            return
        try:
            target = self.engine.save()
            self._display_path = target
            self._sync_modified_state()
            self.info_bar.show_message(f"💾 Saved: {target.name}", "success")
        except Exception as exc:
            self._error("Save failed", str(exc))

    def save_as_file(self) -> None:
        if not self.engine.is_loaded():
            return
        original = self.engine.original_path
        initial = start_in_save_directory(
            self,
            original.name if original else "document.pdf",
            original.parent if original else None,
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", initial, "PDF (*.pdf)"
        )
        if not path:
            return
        remember_save_directory(self, path)
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            target = self.engine.save_as(path)
            self.settings.add_recent_file(target)
            self.bottom_bar.set_document_info(
                target.name, self.engine.page_count, str(target)
            )
            self._display_path = target
            self._sync_modified_state()
            self.info_bar.show_message(f"💾 Saved as: {target.name}", "success")
        except Exception as exc:
            self._error("Save failed", str(exc))

    def close_document(self, session: DocumentSession | None = None) -> None:
        target = session or self._session
        if target is None:
            return
        previous = self._session
        self._session = target
        if not self._confirm_discard_changes():
            # A cancelled background-tab close must not leave the active
            # session pointing at a tab that is not the visible one.
            self._session = previous
            return
        for host in self._sessions:
            if host is not target and host.split_source_session is target:
                host.set_split_source(None)
        self._sessions = [item for item in self._sessions if item is not target]
        self.workspace.close_tab(target)
        thumbnail_snapshot = getattr(target, "_thumbnail_snapshot", None)
        if thumbnail_snapshot:
            Path(thumbnail_snapshot).unlink(missing_ok=True)
        target.close()
        self._refresh_all_split_source_choices()
        remaining = self.workspace.current_session()
        if remaining is not None:
            self._session = remaining
            self._on_tab_changed(remaining)
        else:
            self._session = None
            self._hide_context()
            self._set_document_available(False)
            self.bottom_bar.set_document_info("No document", 0)
            self.bottom_bar.set_page_size(0, 0)
            self._sync_modified_state()
        self._update_undo_actions()

    def _confirm_discard_changes(self) -> bool:
        if not self.engine.is_modified:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes before closing this document?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            self.save_file()
            return not self.engine.is_modified
        return answer == QMessageBox.StandardButton.Discard

    def _set_document_available(self, available: bool) -> None:
        self.command_bar.set_document_available(available)
        engine = self.engine
        encrypted = engine.is_encrypted() if available and engine else False
        self.side_panel.set_document_available(
            available,
            encrypted=encrypted,
        )
        nav = self.workspace.nav_panel
        if nav is not None:
            nav.set_document_available(available)
        for action in (
            self.save_action,
            self.save_as_action,
            self.save_all_action,
            self.print_action,
            self.close_action,
            self.encrypt_action,
            self.find_action,
            self.rotate_action,
            self.insert_action,
            self.delete_action,
            self.extract_action,
            self.split_pages_action,
            self.undo_history_action,
            self.show_labels_action,
            self.split_action,
            self.split_sync_page_action,
            self.split_sync_zoom_action,
            self.split_open_document_action,
            *self._split_orientation_actions,
            self.fit_width_action,
            self.fit_page_action,
            self.actual_size_action,
            self.zoom_in_action,
            self.zoom_out_action,
            *self._layout_actions,
            *self._tool_actions,
        ):
            action.setEnabled(available)
        self.decrypt_action.setEnabled(available and encrypted)
        self.split_reset_action.setEnabled(
            available and self._session is not None and self._session.has_split
        )
        self.split_open_document_action.setEnabled(
            available and self._session is not None and self._session.has_split
        )
        if not available:
            self.split_action.setChecked(False)

    def _sync_modified_state(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            self.setWindowModified(False)
            self.setWindowTitle("PDFDocuEdit Pro")
            self.command_bar.set_window_title("PDFDocuEdit Pro")
            return
        finding_set = session.analysis_panel.finding_set()
        if finding_set and finding_set.is_stale(
            session.engine.document_id, session.engine.revision
        ):
            session.analysis_panel.mark_stale()

        modified = session.engine.is_modified
        self.setWindowModified(modified)
        path = session.display_path or session.engine.original_path
        title = f"PDFDocuEdit Pro — {path.name}" if path else "PDFDocuEdit Pro"
        self.setWindowTitle(f"{title}[*]")
        self.command_bar.set_window_title(title, modified)
        self.workspace.update_tab_title(session)

    # --- Navigation and page operations ---------------------------------
    def previous_page(self) -> None:
        self.goto_page(self._page - 1)

    def next_page(self) -> None:
        self.goto_page(self._page + 1)

    def goto_page(self, page: int) -> None:
        engine = self.engine
        canvas = self.workspace.canvas
        if engine is not None and canvas is not None and 0 <= page < engine.page_count:
            canvas.set_page(page)

    def _update_page_state(self) -> None:
        engine = self.engine
        canvas = self.workspace.canvas
        if engine is None or not engine.is_loaded() or canvas is None:
            return
        self.bottom_bar.set_current_page(self._page)
        width, height = engine.get_page_size(self._page)
        self.bottom_bar.set_page_size(width, height)
        panel = self.workspace.nav_panel
        if panel is not None:
            panel.search.set_page_count(engine.page_count)
            panel.search.set_current_page(self._page)
        self.bottom_bar.set_zoom_percent(round(canvas.zoom_ratio * 100))

    def _show_context(self, key: str) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before using page tools.", "warning")
            return
        if self._session is not None:
            self._hide_search_panel(self._session)
        titles = {
            "rotate": "Rotate Pages",
            "insert": "Insert Pages",
            "delete": "Delete Pages",
            "extract": "Extract Pages",
            "sort": "Order Pages",
            "split": "Split PDF",
            "annotate": "Annotation Options",
            "font_inspect": "Font Inspector",
        }
        if self.context_panel.show_tool(key, titles.get(key, "Options")):
            self._last_context_key = key
            self.side_panel.set_active_tool(key)
            self.settings.set("right_panel_visible", True)
            if key == "annotate":
                self._refresh_annotate_list()

    def _hide_context(self) -> None:
        self.context_panel.close_animated()
        self.side_panel.set_active_tool(None)
        self.settings.set("right_panel_visible", False)

    def _pages_from_text(self, value: str) -> list[int]:
        normalized = value.strip().casefold()
        if normalized in {"", "current"}:
            return [self._page]
        if normalized == "all":
            return list(range(self.engine.page_count))
        return parse_page_range(value, self.engine.page_count)

    def _confirm_signature_invalidation(self) -> bool:
        if not self.engine.is_loaded() or not self.engine.has_digital_signatures():
            return True
        answer = QMessageBox.warning(
            self,
            "Signed PDF",
            "This PDF contains a digital signature. Editing or reorganizing pages "
            "will invalidate that signature. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _snapshot_before(self, description: str) -> bool:
        """Save a snapshot of the current *in-memory* document before a change.

        The engine's temp file only reflects the last saved state, so the live
        document must be serialized for undo to capture every pending edit.
        """
        if self.engine is None or not self.engine.is_loaded():
            return False
        if not self._confirm_signature_invalidation():
            return False
        stack = self._undo_stack
        if stack is None:
            return False
        handle, temp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".pdf")
        os.close(handle)
        try:
            self.engine.snapshot(temp_name)
            stack.push(
                temp_name,
                description,
                modified=self.engine.is_modified,
            )
        finally:
            Path(temp_name).unlink(missing_ok=True)
        self._update_undo_actions()
        return True

    def _update_undo_actions(self) -> None:
        stack = self._undo_stack
        if stack is None:
            self.undo_action.setEnabled(False)
            self.redo_action.setEnabled(False)
            self.undo_action.setText("Undo")
            self.redo_action.setText("Redo")
            self.command_bar.set_undo_redo_enabled(False, False)
            return
        can_undo = stack.can_undo
        can_redo = stack.can_redo
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)
        self.undo_action.setText(
            f"Undo {stack.undo_description}" if can_undo else "Undo"
        )
        self.redo_action.setText(
            f"Redo {stack.redo_description}" if can_redo else "Redo"
        )
        self.command_bar.set_undo_redo_enabled(can_undo, can_redo)

    def _undo(self) -> None:
        stack = self._undo_stack
        if stack is None or self.engine is None:
            return
        temp = self.engine.temp_path
        if not temp or not temp.is_file():
            return
        snapshot_path = self._pop_undo()
        if snapshot_path:
            self._reopen_from_snapshot(
                snapshot_path, modified=stack.restored_modified
            )

    def _redo(self) -> None:
        stack = self._undo_stack
        if stack is None or self.engine is None:
            return
        temp = self.engine.temp_path
        if not temp or not temp.is_file():
            return
        snapshot_path = self._pop_redo()
        if snapshot_path:
            self._reopen_from_snapshot(
                snapshot_path, modified=stack.restored_modified
            )

    def _pop_undo(self) -> Path | None:
        stack = self._undo_stack
        if stack is None or self.engine is None:
            return None
        self._push_current_history_snapshot(
            stack.push_redo, stack.undo_description
        )
        path = stack.pop_undo()
        if path:
            self._update_undo_actions()
        return path

    def _pop_redo(self) -> Path | None:
        stack = self._undo_stack
        if stack is None or self.engine is None:
            return None
        self._push_current_history_snapshot(
            stack.push_undo, stack.redo_description
        )
        path = stack.pop_redo()
        if path:
            self._update_undo_actions()
        return path

    def _push_current_history_snapshot(self, push, description: str) -> None:
        """Serialize the live document before moving through undo history."""
        handle, temp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".pdf")
        os.close(handle)
        try:
            self.engine.snapshot(temp_name)
            push(
                temp_name,
                description,
                modified=self.engine.is_modified,
            )
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _reopen_from_snapshot(
        self, snapshot_path: Path, *, modified: bool
    ) -> None:
        """Re-open the document from a snapshot file."""
        session = self._session
        if session is None:
            return
        view_state = self._capture_session_view_state(session)
        try:
            session.canvas.wait_for_renders()
            restored = self._open_pdf(
                session,
                str(snapshot_path),
                display_path=session.display_path or snapshot_path,
                reset_history=False,
                announce=False,
                preserve_save_context=True,
                restored_modified=modified,
            )
            if not restored:
                return
            self._restore_session_view_state(session, view_state)
            self.info_bar.show_message("Undo applied.", "success")
        except Exception as exc:
            self._error("Undo failed", str(exc))
        finally:
            snapshot_path.unlink(missing_ok=True)

    @staticmethod
    def _capture_canvas_view_state(canvas) -> dict[str, object]:
        return {
            "page": canvas.current_page,
            "zoom": canvas.zoom_ratio,
            "layout": canvas.layout_mode.value,
            "horizontal_scroll": canvas.horizontalScrollBar().value(),
            "vertical_scroll": canvas.verticalScrollBar().value(),
        }

    def _capture_session_view_state(
        self, session: DocumentSession
    ) -> dict[str, object]:
        return {
            "page": session.page,
            "primary": self._capture_canvas_view_state(session.canvas),
            "secondary": (
                self._capture_canvas_view_state(session.split_canvas)
                if session.split_canvas is not None
                else None
            ),
        }

    @staticmethod
    def _restore_canvas_view_state(canvas, state: dict[str, object]) -> None:
        canvas.set_layout_mode(str(state["layout"]), emit=False)
        canvas.set_zoom(float(state["zoom"]), emit=False)
        canvas.set_page(int(state["page"]), emit=False)
        canvas.horizontalScrollBar().setValue(int(state["horizontal_scroll"]))
        canvas.verticalScrollBar().setValue(int(state["vertical_scroll"]))

    def _restore_session_view_state(
        self, session: DocumentSession, state: dict[str, object]
    ) -> None:
        primary = state.get("primary")
        if isinstance(primary, dict):
            self._restore_canvas_view_state(session.canvas, primary)
        secondary = state.get("secondary")
        if session.split_canvas is not None and isinstance(secondary, dict):
            self._restore_canvas_view_state(session.split_canvas, secondary)
        session.page = max(
            0, min(int(state.get("page", 0)), session.engine.page_count - 1)
        )
        session.nav_panel.thumbnails.set_current_page(session.page)
        session.nav_panel.bookmarks.set_current_page(session.page)
        self._update_page_state()
        self._refresh_annotate_list()

    def _rotate_pages(self, pages: str, angle: int) -> None:
        try:
            selected = self._pages_from_text(pages)
            if not self._snapshot_before("Rotate Pages"):
                return
            self.engine.rotate_pages(selected, angle)
            self.workspace.canvas.refresh()
            self._sync_modified_state()
            self.info_bar.show_message(
                f"🔄 Rotated {len(selected)} page(s). Save the document to keep the change.",
                "success",
            )
            self._hide_context()
        except Exception as exc:
            self._error("Rotate failed", str(exc))

    def _delete_pages(self, value: str) -> None:
        try:
            pages = self._pages_from_text(value)
            if not pages:
                raise ValueError("Enter at least one valid page.")
            answer = QMessageBox.question(
                self,
                "Delete pages",
                f"Delete {len(pages)} selected page(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if not self._snapshot_before("Delete Pages"):
                return
            self.engine.delete_pages(pages)
            self._after_page_count_change()
            self.info_bar.show_message(
                f"🗑 Deleted {len(pages)} page(s). Save the document to keep the change.",
                "success",
            )
            self._hide_context()
        except Exception as exc:
            self._error("Delete failed", str(exc))

    def _extract_pages(self, value: str) -> None:
        try:
            pages = self._pages_from_text(value)
            if not pages:
                raise ValueError("Enter at least one valid page.")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Extract Pages",
                start_in_save_directory(
                    self,
                    "extracted-pages.pdf",
                    (
                        self.engine.original_path.parent
                        if self.engine.original_path
                        else None
                    ),
                ),
                "PDF (*.pdf)",
            )
            if path:
                remember_save_directory(self, path)
                if not path.casefold().endswith(".pdf"):
                    path += ".pdf"
                if (
                    self.engine.original_path
                    and Path(path).resolve() == self.engine.original_path
                ):
                    raise ValueError(
                        "Choose a new output file instead of the open PDF."
                    )
                target = self.engine.extract_pages(pages, path)
                self.info_bar.show_message(f"📄 Created {target.name}", "success")
                self._hide_context()
        except Exception as exc:
            self._error("Extract failed", str(exc))

    def _split_pdf(self, every: int) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Split PDF output folder",
            self.settings.get_last_save_directory(self.settings.get_last_directory()),
        )
        if not folder:
            return
        ranges = [
            (start, min(start + every - 1, self.engine.page_count - 1))
            for start in range(0, self.engine.page_count, every)
        ]
        try:
            outputs = self.engine.split_pdf(ranges, folder)
            self.settings.set_last_save_directory(folder)
            self.info_bar.show_message(f"Created {len(outputs)} PDF files.", "success")
            self._hide_context()
        except Exception as exc:
            self._error("Split failed", str(exc))

    def _insert_pages(self, mode: str, source: str, position: int) -> None:
        if mode == "browse":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Insert pages from PDF",
                self.settings.get_last_directory(),
                "PDF (*.pdf)",
            )
            if path:
                self.context_panel.set_insert_source(path)
            return
        if not source:
            self.info_bar.show_message("Choose a source PDF first.", "warning")
            return
        try:
            with fitz.open(source) as document:
                pages = list(range(document.page_count))
            if not self._snapshot_before("Insert Pages"):
                return
            self.engine.insert_pages(source, pages, position - 1)
            self._after_page_count_change()
            self.info_bar.show_message(
                "Pages inserted. Save the document to keep the change.", "success"
            )
            self._hide_context()
        except Exception as exc:
            self._error("Insert failed", str(exc))

    def _order_pages(self, value: str) -> None:
        try:
            if value == "reverse":
                order = list(reversed(range(self.engine.page_count)))
            else:
                order = [
                    int(part.strip()) - 1 for part in value.split(",") if part.strip()
                ]
            if not self._snapshot_before("Reorder Pages"):
                return
            self.engine.reorder_pages(order)
            self.workspace.canvas.set_page(0)
            self._reload_thumbnails(self._session)
            self._sync_modified_state()
            self.info_bar.show_message(
                "🔀 Page order changed. Save the document to keep the change.",
                "success",
            )
            self._hide_context()
        except Exception as exc:
            self._error("Reorder failed", str(exc))

    def _after_page_count_change(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        session.page = min(session.page, session.engine.page_count - 1)
        canvas = session.canvas
        # The cached page renders are keyed by page index, which is now
        # stale, so the canvas must re-render before scrolling.
        canvas.refresh()
        canvas.set_page(max(0, session.page))
        name = session.document_name
        path = session.display_path or session.engine.original_path
        self.bottom_bar.set_document_info(
            name, session.engine.page_count, str(path) if path else ""
        )
        self.context_panel.set_page_count(session.engine.page_count)
        session.nav_panel.search.set_page_count(session.engine.page_count)
        self._reload_thumbnails(session)
        # set_page() does not emit when the page index stays unchanged (the
        # common case when deleting from an Outlook attachment on page 1), so
        # explicitly refresh every page-dependent status control.
        self._update_page_state()
        self._sync_modified_state()

    # --- Search, information and printing -------------------------------
    def search_document(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before searching.", "warning")
            return
        self._show_nav_tab("search")
        self.workspace.nav_panel.search.focus_query()

    def show_document_info(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        self._hide_search_panel(session)
        session.analysis_panel.show()
        sizes = session.tab_widget.sizes()
        total = max(sum(sizes), session.tab_widget.width(), 900)
        nav_width = sizes[0] if sizes and session.nav_panel.isVisible() else 0
        session.tab_widget.setSizes(
            [nav_width, max(360, total - nav_width - 430), 0, 430]
        )
        self._run_analysis_request(session, AnalysisRequest())

    def show_smart_detection(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            self.info_bar.show_message(
                "Open a PDF before running detection.", "warning"
            )
            return
        self._hide_search_panel(session)
        session.analysis_panel.show()
        session.analysis_panel.tabs.setCurrentIndex(2)
        sizes = session.tab_widget.sizes()
        total = max(sum(sizes), session.tab_widget.width(), 900)
        nav_width = sizes[0] if sizes and session.nav_panel.isVisible() else 0
        session.tab_widget.setSizes(
            [nav_width, max(360, total - nav_width - 430), 0, 430]
        )

    def _run_analysis_request(
        self, session: DocumentSession, request: AnalysisRequest
    ) -> None:
        if session not in self._sessions or not session.engine.is_loaded():
            return
        source = session.engine.original_path
        snapshot: tempfile.TemporaryDirectory[str] | None = None
        if source is None or session.engine.is_modified or session.engine.password:
            try:
                fallback = source or Path("document.pdf")
                directory = tempfile.TemporaryDirectory(prefix="pdfdocuedit-analysis-")
                analysis_path = Path(directory.name) / fallback.name
                session.engine.snapshot(analysis_path)
                snapshot = directory
                source = analysis_path
            except Exception as exc:
                if snapshot:
                    snapshot.cleanup()
                self._error("Analysis failed", str(exc))
                return
        document_id = session.engine.document_id
        revision = session.engine.revision
        request = replace(request, original_encrypted=bool(session.engine.password))
        session.analysis_panel.set_running(True)

        def received(report: InspectionReport) -> None:
            if session not in self._sessions:
                return
            session.analysis_panel.set_report(report)
            if report.finding_set.is_stale(
                session.engine.document_id, session.engine.revision
            ):
                session.analysis_panel.mark_stale()

        task = self._run_task(
            "Analyzing PDF",
            _perform_document_analysis,
            str(source),
            document_id,
            revision,
            request,
            on_result=received,
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )
        if task is None:
            session.analysis_panel.status.setText(
                "Another background operation is active. Try again when it finishes."
            )

    def _extract_analysis_pages(
        self, session: DocumentSession, pages: tuple[int, ...]
    ) -> None:
        if session not in self._sessions or not pages:
            return
        self.workspace.set_current_session(session)
        self._session = session
        value = ",".join(str(page + 1) for page in pages)
        self._extract_pages(value)

    def _organize_findings(self, session: DocumentSession, finding_set) -> None:
        if session not in self._sessions:
            return
        if finding_set.is_stale(session.engine.document_id, session.engine.revision):
            session.analysis_panel.mark_stale()
            self.info_bar.show_message(
                "Analysis results are stale. Run the scan again before organizing pages.",
                "warning",
            )
            return
        self.workspace.set_current_session(session)
        self._session = session
        self._organize_pages(preselected_pages=finding_set.pages())

    def print_pdf(self) -> None:
        doc = self.engine.document
        if not doc:
            return
        options = PrintOptionsDialog(doc.page_count, self._page, self)
        if options.exec() != QDialog.DialogCode.Accepted or not options.details:
            return
        details = options.details
        self.settings.set_print_profile(details)
        printer = self._create_printer(details)
        # Name the print job after the document (visible in the print queue),
        # matching the legacy version.
        printer.setDocName(Path(doc.name).name)
        first_page = doc.load_page(list(details["pages"])[0])
        self._configure_print_layout(printer, first_page, details)
        if details.get("confirm_system_dialog"):
            native_dialog = QPrintDialog(printer, self)
            native_dialog.setWindowTitle("System Print")
            if native_dialog.exec() != QDialog.DialogCode.Accepted:
                return
        if self._printing:
            self.info_bar.show_message("A print job is already in progress.", "warning")
            return
        self._printing = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:

            def progress(_document_index, page, total):
                self.bottom_bar.set_status(f"Printing page {page + 1} of {total}…")
                QApplication.processEvents()

            self._paint_documents(
                printer,
                [(doc, list(details["pages"]), Path(doc.name).name)],
                details,
                progress=progress,
            )
            self.info_bar.show_message(
                "The document was sent to the printer.", "success"
            )
        except Exception as exc:
            self._error("Print failed", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self.bottom_bar.set_status("Ready")
            self._printing = False

    @staticmethod
    def _create_printer(details: dict[str, object]) -> QPrinter:
        name = str(details.get("printer", ""))
        info = QPrinterInfo.printerInfo(name) if name else QPrinterInfo()
        printer = (
            QPrinter(info, QPrinter.PrinterMode.HighResolution)
            if not info.isNull()
            else QPrinter(QPrinter.PrinterMode.HighResolution)
        )
        # QPrinter's HighResolution mode follows the driver default, which is
        # not necessarily the quality selected in our dialog. Set the desired
        # raster/output resolution before the painter or page layout starts.
        printer.setResolution(min(600, max(72, int(details.get("dpi", 300)))))
        printer.setCopyCount(int(details["copies"]))
        printer.setCollateCopies(bool(details["collate"]))
        printer.setColorMode(
            QPrinter.ColorMode.Color
            if int(details["colour"]) == 0
            else QPrinter.ColorMode.GrayScale
        )
        duplex_modes = {
            1: QPrinter.DuplexMode.DuplexNone,
            2: QPrinter.DuplexMode.DuplexLongSide,
            3: QPrinter.DuplexMode.DuplexShortSide,
        }
        if int(details["duplex"]) in duplex_modes:
            printer.setDuplex(duplex_modes[int(details["duplex"])])
        return printer

    def _paint_documents(
        self,
        printer: QPrinter,
        documents: list[tuple[fitz.Document, list[int], str]],
        details: dict[str, object],
        log=None,
        progress=None,
        should_cancel=None,
    ) -> None:
        """Paint each page of each document onto the printer.

        ``log`` receives progress lines. ``progress`` receives
        ``(document_index, page_number, page_count)`` before each page is
        drawn. ``should_cancel`` is polled between pages; returning True
        stops the job after the current page.
        """
        painter = QPainter(printer)
        if not painter.isActive():
            raise RuntimeError("The selected printer could not start a print job.")
        try:
            output_index = 0
            for document_index, (document, pages, name) in enumerate(documents):
                if log:
                    log(f"Printing {name} ({len(pages)} page(s))…")
                for page_number in pages:
                    page = document.load_page(page_number)
                    if progress:
                        progress(document_index, page_number, len(pages))
                    # Qt applies one page layout per print job; the caller
                    # configures it before the first page, so mid-job changes
                    # would be ignored anyway.
                    if output_index and not printer.newPage():
                        raise RuntimeError(
                            "The printer could not create the next page."
                        )
                    self._draw_print_page(painter, printer, page, details)
                    output_index += 1
                    if should_cancel is not None and should_cancel():
                        return
        finally:
            painter.end()

    @staticmethod
    def _draw_print_page(
        painter: QPainter,
        printer: QPrinter,
        page: fitz.Page,
        details: dict[str, object],
    ) -> None:
        rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        # Respect the effective QPrinter resolution. The dialog constrains
        # custom values to 72–600 DPI so high quality remains practical for
        # large pages while Draft mode materially reduces time and memory.
        render_dpi = min(600, max(72, printer.resolution()))
        pix = page.get_pixmap(dpi=render_dpi, alpha=False)
        image = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        mode = int(details["scale_mode"])
        if mode == 0:
            # Qt applies one page layout per print job, so pages whose
            # orientation differs from the job's are rotated: their content
            # still fills the paper upright instead of being squashed.
            # (An A4 page rotated 90 degrees is physically an A4 page, so
            # mixed landscape/portrait documents print correctly.)
            job_landscape = rect.width() > rect.height()
            page_landscape = page.rect.width > page.rect.height
            if page_landscape != job_landscape:
                image = image.transformed(
                    QTransform().rotate(90),
                    Qt.TransformationMode.SmoothTransformation,
                )
            scaled = image.scaled(
                rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            factor = 1.0 if mode == 1 else float(details["scale"]) / 100.0
            target_width = max(
                1, int(page.rect.width / 72 * printer.resolution() * factor)
            )
            target_height = max(
                1, int(page.rect.height / 72 * printer.resolution() * factor)
            )
            scaled = image.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        if bool(details["center"]):
            x = rect.x() + (rect.width() - scaled.width()) / 2
            y = rect.y() + (rect.height() - scaled.height()) / 2
        else:
            x, y = rect.x(), rect.y()
        x += float(details["offset_x"]) / 25.4 * printer.resolution()
        y += float(details["offset_y"]) / 25.4 * printer.resolution()
        painter.drawImage(int(x), int(y), scaled)

    @staticmethod
    def _configure_print_layout(
        printer: QPrinter, page: fitz.Page, details: dict[str, object]
    ) -> None:
        paper = str(details["paper"])
        sizes = {
            "A4": QPageSize.PageSizeId.A4,
            "A3": QPageSize.PageSizeId.A3,
            "A5": QPageSize.PageSizeId.A5,
            "Letter": QPageSize.PageSizeId.Letter,
        }
        if paper == "PDF page size":
            # QPageSize stores sizes in portrait convention, so the shorter
            # side must be the width; the orientation below then produces
            # the correct full-page rectangle for landscape pages.
            width, height = page.rect.width, page.rect.height
            if width > height:
                width, height = height, width
            printer.setPageSize(
                QPageSize(
                    QSizeF(width, height),
                    QPageSize.Unit.Point,
                    "PDF page",
                )
            )
        else:
            printer.setPageSize(QPageSize(sizes[paper]))
        orientation = int(details["orientation"])
        if orientation == 0:
            landscape = page.rect.width > page.rect.height
        else:
            landscape = orientation == 2
        printer.setPageOrientation(
            QPageLayout.Orientation.Landscape
            if landscape
            else QPageLayout.Orientation.Portrait
        )

    # --- Tools -----------------------------------------------------------
    ANNOTATION_TOOL_KEYS = {
        "highlight",
        "underline",
        "strikeout",
        "squiggly",
        "note",
        "ink",
        "rect",
        "line",
        "arrow",
        "ellipse",
        "polygon",
        "freetext_typewriter",
        "freetext_box",
        "freetext_callout",
        "redact",
        "stamp",
        "signature",
        "image",
        "watermark",
    }

    def _tool_requested(self, key: str) -> None:
        if key in self.ANNOTATION_TOOL_KEYS:
            self._activate_annotation_tool(key)
            return
        handlers = {
            "search": self.search_document,
            "font_inspect": self._activate_font_inspector,
            "rotate": lambda: self._show_context("rotate"),
            "insert": self._insert_pages_dialog,
            "delete": self._delete_pages_dialog,
            "extract": self._extract_pages_dialog,
            "order": lambda: self._show_context("sort"),
            "sort": self._organize_pages,
            "split": self._split_dialog,
            "info": self.show_document_info,
            "smart_detection": self.show_smart_detection,
            "pdf_to_word": self._pdf_to_word,
            "office_to_pdf": self._office_to_pdf,
            "txt_to_pdf": self._txt_to_pdf,
            "postscript": self._postscript_to_pdf,
            "page_report": self._page_report,
            "extract_text": self._extract_text,
            "merge": self._merge_pdfs,
            "overlay": self._overlay_pdf,
            "compress": self._compress_pdf,
            "deep_search": self._deep_search,
            "ocr": self._ocr,
            "merge_sheet": self._merge_sheets,
            "barcode": self._scan_barcodes,
            "barcode_batch": self._scan_barcodes_batch,
            "encrypt": self._encrypt_pdf,
            "decrypt": self._decrypt_pdf,
            "diagnostics": lambda: DiagnosticsDialog(self).exec(),
            "find_file": self._search_and_open,
            "batch_print": self._batch_print,
        }
        handler = handlers.get(key)
        if handler:
            try:
                handler()
            finally:
                if key not in {"rotate", "font_inspect"}:
                    self.side_panel.set_active_tool(None)

    # --- P3: annotations and content editing -----------------------------
    def _activate_font_inspector(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message(
                "Open a PDF before inspecting text fonts.", "warning"
            )
            return
        self._set_canvas_tool("font_inspect")
        self.context_panel.set_font_inspection(None)
        self._show_context("font_inspect")
        self.side_panel.set_active_tool("font_inspect")
        self.bottom_bar.set_status(
            "Font Inspector: click text to identify its PDF font, size and color."
        )

    def _handle_font_inspection(
        self,
        host: DocumentSession,
        canvas,
        page_number: int,
        point: fitz.Point,
    ) -> None:
        source = self._external_split_source(host, canvas) or host
        if not source.engine.is_loaded() or not (
            0 <= int(page_number) < source.engine.page_count
        ):
            return
        with DOCUMENT_LOCK:
            page = source.engine.document.load_page(int(page_number))
            inspection = inspect_font_at(page, fitz.Point(point))
        for candidate in (host.canvas, host.split_canvas):
            if candidate is not None and candidate is not canvas:
                candidate.clear_font_inspection()
        if inspection is None:
            canvas.clear_font_inspection()
            self.context_panel.set_font_inspection(None, no_hit=True)
            self.bottom_bar.set_status(
                "Font Inspector: no selectable PDF text at that position."
            )
            return
        canvas.show_font_inspection(
            int(page_number), fitz.Rect(inspection["bbox"])
        )
        self.context_panel.set_font_inspection(inspection)
        self._show_context("font_inspect")
        self.side_panel.set_active_tool("font_inspect")
        self.bottom_bar.set_status(
            "Font Inspector: "
            f"{inspection['display_font']} · {float(inspection['size']):.2f} pt"
        )

    def _apply_inspected_font(
        self, tool: str, inspection: dict[str, object]
    ) -> None:
        if tool not in {"freetext_typewriter", "freetext_box"}:
            return
        if not inspection.get("usable_for_annotations"):
            self.info_bar.show_message(
                "That PDF font is not installed and cannot be reused for a new annotation.",
                "warning",
            )
            return
        defaults = self.settings.get("annotation_defaults", {}) or {}
        defaults = dict(defaults) if isinstance(defaults, dict) else {}
        current = defaults.get(tool, {})
        values = dict(current) if isinstance(current, dict) else {}
        values.update(
            {
                "font": str(inspection.get("suggested_font") or "Helv"),
                "font_size": max(1.0, float(inspection.get("size") or 11.0)),
                "stroke": str(inspection.get("color") or "#202124"),
            }
        )
        defaults[tool] = values
        self.settings.set("annotation_defaults", defaults)
        self._activate_annotation_tool(tool)
        self.info_bar.show_message(
            f"Using {values['font']} at {values['font_size']:.2f} pt for new text annotations.",
            "success",
        )

    def _copy_inspected_font_name(self, name: str) -> None:
        QApplication.clipboard().setText(name)
        self.info_bar.show_message(f"Copied font name: {name}", "success")

    def _activate_annotation_tool(self, key: str) -> None:
        if key == "watermark":
            self.side_panel.set_active_tool(None)
            self._show_watermark_dialog()
            return
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before annotating.", "warning")
            return
        defaults = self.settings.get("annotation_defaults", {}) or {}
        saved_values = defaults.get(key, {}) if isinstance(defaults, dict) else {}
        values = dict(saved_values) if isinstance(saved_values, dict) else {}
        text_defaults = key.startswith("freetext_") and not values
        values = {
            "stroke": values.get("stroke", "#202124" if text_defaults else "yellow"),
            "fill": values.get(
                "fill",
                "#fff4b8"
                if text_defaults and key != "freetext_typewriter"
                else "",
            ),
            "opacity": values.get("opacity", 1.0),
            "width": values.get("width", 1.5),
            "font": values.get("font", "Helv"),
            "font_size": values.get("font_size", 14.0 if text_defaults else 11.0),
            "alignment": values.get("alignment", 0),
        }
        self._set_canvas_tool(key)
        self.context_panel.set_annotation_tool(key)
        self.context_panel.set_annotation_defaults(values)
        canvas_values = dict(values)
        canvas_values["color"] = canvas_values.pop("stroke")
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(**canvas_values)
        if key == "stamp":
            stamp_kind, stamp_image = self.context_panel.current_stamp()
            for canvas in self._session_canvases(self._session):
                canvas.set_annotation_options(
                    stamp_kind=stamp_kind,
                    stamp_image_path=stamp_image,
                )
        self._show_context("annotate")
        self.side_panel.set_active_tool(key)
        if key == "polygon":
            self.bottom_bar.set_status(
                "Polygon: click each vertex; double-click or right-click to finish."
            )
        elif key == "freetext_callout":
            self.bottom_bar.set_status(
                "Callout: drag the text box; an arrow leader is added automatically."
            )

    def _set_annot_color(self, value: str) -> None:
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(color=value)

    def _set_annot_width(self, value: float) -> None:
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(width=float(value))

    def _set_annot_style(self, values: dict[str, object]) -> None:
        session = self._session
        if session is None:
            return
        options = dict(values)
        options["color"] = options.pop("stroke", "yellow")
        for canvas in self._session_canvases(session):
            canvas.set_annotation_options(**options)
        tool = str(session.canvas.tool_mode)
        if tool not in self.ANNOTATION_TOOL_KEYS:
            return
        defaults = self.settings.get("annotation_defaults", {}) or {}
        defaults = dict(defaults) if isinstance(defaults, dict) else {}
        defaults[tool] = dict(values)
        self.settings.set("annotation_defaults", defaults)

    def _set_stamp_kind(self, value: str) -> None:
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(stamp_kind=value)

    def _set_stamp_image(self, value: str) -> None:
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(stamp_image_path=value)

    def _load_custom_stamps(self, selected: str = "") -> None:
        self.context_panel.set_custom_stamps(
            self.settings.get_custom_stamps(), selected=selected
        )

    def _add_custom_stamp(self) -> None:
        source_value, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Custom Stamp Image",
            self.settings.get_last_directory(),
            "Images (*.png *.jpg *.jpeg)",
        )
        if not source_value:
            return
        source = Path(source_value).expanduser().resolve()
        image = QImage(str(source))
        if not source.is_file() or image.isNull():
            self._error("Custom stamp", "Choose a valid PNG or JPG image.")
            return
        name, accepted = QInputDialog.getText(
            self,
            "Custom Stamp Name",
            "Name",
            text=source.stem,
        )
        name = " ".join(name.split())[:60]
        if not accepted or not name:
            return
        stamps = self.settings.get_custom_stamps()
        if any(existing.casefold() == name.casefold() for existing in stamps):
            self._error("Custom stamp", f'A custom stamp named "{name}" already exists.')
            return
        stamp_dir = self.settings.path.parent / "stamps"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        target = stamp_dir / f"{uuid.uuid4().hex}{source.suffix.casefold()}"
        try:
            shutil.copy2(source, target)
            stamps[name] = str(target.resolve())
            self.settings.set_custom_stamps(stamps)
        except OSError as exc:
            target.unlink(missing_ok=True)
            self._error("Custom stamp", f"Could not import the stamp image:\n{exc}")
            return
        self._load_custom_stamps(selected=name)
        kind, image_path = self.context_panel.current_stamp()
        self._set_stamp_kind(kind)
        self._set_stamp_image(image_path)
        self.info_bar.show_message(f"Custom stamp added: {name}", "success")

    def _add_custom_text_stamp(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Custom Text Stamp",
            "Stamp text (up to 3 lines)",
        )
        text = "\n".join(line.strip() for line in text.strip().splitlines())
        if not accepted or not text:
            return
        wrapped: list[str] = []
        for line in text.splitlines():
            wrapped.extend(textwrap.wrap(line, width=24) or [""])
        display_lines = wrapped[:3]
        if len(wrapped) > 3:
            display_lines[-1] = display_lines[-1].rstrip("…") + "…"
        stamp_text = "\n".join(display_lines)
        default_name = " ".join(text.split())[:40]
        name, named = QInputDialog.getText(
            self,
            "Custom Stamp Name",
            "Name",
            text=default_name,
        )
        name = " ".join(name.split())[:60]
        if not named or not name:
            return
        stamps = self.settings.get_custom_stamps()
        if any(existing.casefold() == name.casefold() for existing in stamps):
            self._error("Custom stamp", f'A custom stamp named "{name}" already exists.')
            return
        stamp_dir = self.settings.path.parent / "stamps"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        target = stamp_dir / f"{uuid.uuid4().hex}.png"
        try:
            self._render_text_stamp(stamp_text, target)
            stamps[name] = str(target.resolve())
            self.settings.set_custom_stamps(stamps)
        except OSError as exc:
            target.unlink(missing_ok=True)
            self._error("Custom stamp", f"Could not create the text stamp:\n{exc}")
            return
        self._load_custom_stamps(selected=name)
        kind, image_path = self.context_panel.current_stamp()
        self._set_stamp_kind(kind)
        self._set_stamp_image(image_path)
        self.info_bar.show_message(f"Custom text stamp added: {name}", "success")

    @staticmethod
    def _render_text_stamp(text: str, target: Path) -> None:
        """Render reusable stamp text to a transparent, high-resolution PNG."""
        font = QFont("Arial", 42, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        lines = text.splitlines() or [text]
        padding_x = 34
        padding_y = 24
        width = max(260, max(metrics.horizontalAdvance(line) for line in lines) + 68)
        height = max(110, metrics.height() * len(lines) + 48)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            color = QColor("#c62828")
            painter.setPen(QPen(color, 5))
            painter.drawRoundedRect(QRectF(3, 3, width - 6, height - 6), 16, 16)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(
                QRectF(
                    padding_x,
                    padding_y,
                    width - padding_x * 2,
                    height - padding_y * 2,
                ),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
        finally:
            painter.end()
        if not image.save(str(target), "PNG"):
            raise OSError("The generated PNG could not be saved.")

    def _remove_custom_stamp(self, name: str) -> None:
        stamps = self.settings.get_custom_stamps()
        path_value = stamps.get(name)
        if not path_value:
            self._load_custom_stamps()
            return
        answer = QMessageBox.question(
            self,
            "Remove custom stamp",
            f'Remove the custom stamp "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        stamps.pop(name, None)
        self.settings.set_custom_stamps(stamps)
        target = Path(path_value).resolve()
        managed_dir = (self.settings.path.parent / "stamps").resolve()
        if target.parent == managed_dir:
            target.unlink(missing_ok=True)
        self._load_custom_stamps()
        self._set_stamp_kind("Draft")
        self._set_stamp_image("")
        self.info_bar.show_message(f"Custom stamp removed: {name}", "success")

    def _set_annot_image(self, value: str) -> None:
        for canvas in self._session_canvases(self._session):
            canvas.set_annotation_options(image_path=value)

    def _handle_annotation(
        self, op: AnnotationOp, session: DocumentSession | None = None
    ) -> None:
        target = session or self._session
        if target is None:
            return
        session = target
        self._session = target
        if not session.engine.is_loaded():
            return
        if op.kind in {"signature", "signature_image", "image"} and not Path(
            op.image_path
        ).is_file():
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose image", "", "Images (*.png *.jpg *.jpeg)"
            )
            if not path:
                return
            self._set_annot_image(path)
            self.context_panel.set_annotate_image(path)
            op = replace(op, image_path=path)
        if op.kind.startswith("freetext_") and not op.text.strip():
            text, accepted = QInputDialog.getMultiLineText(
                self,
                op.description(),
                "Text",
                op.text,
            )
            if not accepted or not text.strip():
                return
            op = replace(op, text=text)

        document = session.engine.document
        if document is None:
            return
        try:
            op = validate_annotation_op(document, op)
        except AnnotationValidationError as exc:
            self.info_bar.show_message(str(exc), "warning")
            return
        if not self._snapshot_before(op.description()):
            return
        try:
            apply_annotation(session.engine.document, op)
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"{op.description()} failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session, {op.page})
        self._sync_modified_state()
        self._refresh_annotate_list()
        message = (
            "Redaction mark added for review. Content has not been removed."
            if op.kind == "redact"
            else f"{op.description()} added. Save the document to keep the change."
        )
        self.info_bar.show_message(message, "success")

    def _handle_note_request(
        self, page: int, point, session: DocumentSession | None = None
    ) -> None:
        target = session or self._session
        if target is None:
            return
        session = target
        self._session = target
        if not session.engine.is_loaded():
            return
        text, accepted = QInputDialog.getText(self, "Sticky Note", "Note text:")
        if not accepted:
            return
        op = AnnotationOp(
            kind="note",
            page=page,
            points=((point.x, point.y),),
            text=text.strip() or "Note",
        )
        self._handle_annotation(op, session)

    def _handle_remove_annotation(self, page_or_xref: int, xref: int | None = None) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        page = session.page if xref is None else int(page_or_xref)
        target_xref = int(page_or_xref) if xref is None else int(xref)
        if not self._snapshot_before("Remove Annotation"):
            return
        try:
            changed = remove_annotation(
                session.engine.document.load_page(page), target_xref
            )
            if not changed:
                raise ValueError("The annotation no longer exists.")
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"Remove annotation failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session, {page})
        self._sync_modified_state()
        self._refresh_annotate_list()

    def _apply_redactions(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        with DOCUMENT_LOCK:
            mark_count = sum(
                1
                for entry in list_document_annotations(session.engine.document)
                if str(entry.get("kind")) == "Redact"
            )
        if mark_count == 0:
            self.info_bar.show_message("No redaction marks were found.", "warning")
            return
        answer = QMessageBox.question(
            self,
            "Apply redaction marks",
            "Permanently remove content covered by every redaction mark?\n\n"
            "This step cannot be reversed after saving. A document snapshot "
            "will be kept for Undo during this session.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._snapshot_before("Apply Redactions"):
            return
        try:
            count = apply_redaction_marks(session.engine.document)
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"Apply redactions failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session)
        self._sync_modified_state()
        self._refresh_annotate_list()
        self.info_bar.show_message(
            f"Applied {count} redaction mark{'s' if count != 1 else ''}. "
            "Save to make the removal permanent.",
            "success",
        )

    def _edit_annotation(
        self, page: int, xref: int, values: dict[str, object]
    ) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        style = AnnotationStyle(
            stroke=str(values.get("stroke") or "yellow"),
            fill=str(values.get("fill") or ""),
            opacity=float(values.get("opacity", 1.0)),
            width=float(values.get("width", 1.5)),
            font=str(values.get("font") or "Helv"),
            font_size=float(values.get("font_size", 11.0)),
            alignment=int(values.get("alignment", 0)),
        )
        if not self._snapshot_before("Edit Annotation Properties"):
            return
        try:
            changed = update_annotation(
                session.engine.document.load_page(page),
                xref,
                style,
                text=str(values.get("text", "")),
            )
            if not changed:
                raise ValueError("The annotation no longer exists.")
            session.engine.mark_modified()
        except Exception as exc:
            self.info_bar.show_message(f"Edit annotation failed: {exc}", "error", 0)
            return
        self._refresh_session_canvases(session, {page})
        self._sync_modified_state()
        self._refresh_annotate_list()
        self.info_bar.show_message(
            "Annotation properties updated. Save to keep the changes.", "success"
        )

    def _refresh_annotate_list(self) -> None:
        session = self._session
        with DOCUMENT_LOCK:
            entries = (
                list_document_annotations(session.engine.document)
                if session is not None and session.engine.is_loaded()
                else []
            )
            self.context_panel.refresh_annotation_list(entries)

    def _select_annotation(self, page: int, xref: int) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        if session.page != page:
            self.goto_page(page)
        for canvas in self._session_canvases(session):
            canvas.select_annotation(page, xref)

    def _export_annotations(self) -> None:
        if not self.engine.is_loaded():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export annotations", "annotations.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            target = export_annotations_json(self.engine.document, path)
            self.info_bar.show_message(f"Annotations exported: {target.name}", "success")
        except Exception as exc:
            self.info_bar.show_message(f"Export annotations failed: {exc}", "error", 0)

    def _import_annotations(self) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import annotations", "", "JSON (*.json)"
        )
        if not path or not self._snapshot_before("Import Annotations"):
            return
        try:
            result = import_annotations_json(session.engine.document, path)
            imported = int(result["imported"])
            skipped = list(result["skipped"])
            if imported:
                session.engine.mark_modified()
                self._refresh_session_canvases(session)
                self._sync_modified_state()
                self._refresh_annotate_list()
            self.info_bar.show_message(
                f"Imported {imported} annotation(s); skipped {len(skipped)}.",
                "success" if imported else "warning",
                0 if skipped else 3000,
            )
        except Exception as exc:
            self.info_bar.show_message(f"Import annotations failed: {exc}", "error", 0)

    def _export_annotation_summary(self) -> None:
        if not self.engine.is_loaded():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export annotation summary", "annotation-summary.md", "Markdown (*.md)"
        )
        if not path:
            return
        try:
            target = export_annotation_summary(self.engine.document, path)
            self.info_bar.show_message(f"Summary exported: {target.name}", "success")
        except Exception as exc:
            self.info_bar.show_message(f"Summary export failed: {exc}", "error", 0)

    def _flatten_annotations(self) -> None:
        if not self.engine.is_loaded():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save flattened copy", "flattened.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            target = flatten_annotations(self.engine.document, path)
            self.info_bar.show_message(
                f"Flattened copy created: {target.name}", "success", 5000
            )
        except Exception as exc:
            self.info_bar.show_message(f"Flatten failed: {exc}", "error", 0)

    def _show_watermark_dialog(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message(
                "Open a PDF before adding a watermark.", "warning"
            )
            return
        dialog = WatermarkDialog(self.engine.page_count, self._page, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        pages = self._pages_from_text(str(details["pages"]))
        if not pages:
            self.info_bar.show_message("Choose a valid page range.", "warning")
            return
        if not self._snapshot_before("Watermark"):
            return
        try:
            if details["mode"] == "text":
                add_watermark_text(
                    self.engine.document,
                    pages,
                    str(details["text"]),
                    fontsize=int(details["fontsize"]),
                    opacity=float(details["opacity"]),
                    rotation=float(details["rotation"]),
                )
            else:
                add_watermark_image(
                    self.engine.document,
                    pages,
                    str(details["image"]),
                    opacity=float(details["opacity"]),
                )
            self.engine.mark_modified()
        except Exception as exc:
            self._error("Watermark failed", str(exc))
            return
        self.workspace.canvas.refresh()
        self._sync_modified_state()
        self.info_bar.show_message(
            "Watermark applied. Save to keep the change.", "success"
        )

    # --- P1: navigation panels, bookmarks and search --------------------
    def _show_nav_tab(self, key: str) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF first.", "warning")
            return
        if key == "search":
            self._show_search_panel()
            return
        session = self._session
        if session is None:
            return
        self._hide_search_panel(session)
        session.analysis_panel.hide()
        self.workspace.show_nav_tab(key)
        sizes = session.tab_widget.sizes()
        total = max(sum(sizes), session.tab_widget.width(), 900)
        nav_width = max(1, session.nav_panel.width())
        session.tab_widget.setSizes([nav_width, max(360, total - nav_width), 0, 0])

    def _show_search_panel(self, session: DocumentSession | None = None) -> None:
        session = session or self._session
        if session is None:
            return
        self._hide_context()
        session.analysis_panel.hide()
        session.search_panel.show()
        sizes = session.tab_widget.sizes()
        total = max(sum(sizes), session.tab_widget.width(), 900)
        nav_width = sizes[0] if sizes and session.nav_panel.isVisible() else 0
        search_width = 340
        session.tab_widget.setSizes(
            [nav_width, max(360, total - nav_width - search_width), search_width, 0]
        )
        session.search_panel.raise_()
        session.search_panel.focus_query()

    def _hide_search_panel(self, session: DocumentSession | None = None) -> None:
        session = session or self._session
        if session is None:
            return
        session.search_panel.hide()
        sizes = session.tab_widget.sizes()
        total = max(sum(sizes), session.tab_widget.width(), 900)
        nav_width = sizes[0] if sizes and session.nav_panel.isVisible() else 0
        analysis_width = (
            sizes[3] if len(sizes) > 3 and session.analysis_panel.isVisible() else 0
        )
        session.tab_widget.setSizes(
            [nav_width, max(360, total - nav_width - analysis_width), 0, analysis_width]
        )

    def _load_navigation(self) -> None:
        session = self._session
        if session is None:
            return
        nav = session.nav_panel
        nav.outline.load_toc(session.engine.get_toc())
        key = self._bookmark_key(session)
        nav.bookmarks.load_bookmarks(self.settings.get_bookmarks(key) if key else [])
        nav.bookmarks.set_current_page(session.page)
        nav.search.reset_query()

    def _clear_navigation(self) -> None:
        self.workspace.nav_panel.clear_document()

    def _bookmark_key(self, session: DocumentSession) -> str | None:
        path = session.engine.original_path or session.display_path
        return str(path) if path else None

    def _add_bookmark(self, session: DocumentSession | None = None) -> None:
        session = session or self._session
        if session is None:
            return
        if not session.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before adding bookmarks.", "warning")
            return
        key = self._bookmark_key(session)
        if not key:
            self.info_bar.show_message(
                "Save the PDF before adding bookmarks.", "warning"
            )
            return
        default = f"Page {session.page + 1}"
        title, accepted = QInputDialog.getText(
            self, "Add Bookmark", "Bookmark title:", text=default
        )
        if not accepted:
            return
        items = self.settings.get_bookmarks(key)
        items.append({"page": session.page, "title": title.strip() or default})
        self.settings.set_bookmarks(key, items)
        session.nav_panel.bookmarks.load_bookmarks(items)
        self.info_bar.show_message("Bookmark added.", "success")

    def _remove_bookmark(
        self, row: int, session: DocumentSession | None = None
    ) -> None:
        session = session or self._session
        if session is None:
            return
        key = self._bookmark_key(session)
        if not key:
            return
        items = self.settings.get_bookmarks(key)
        if 0 <= row < len(items):
            del items[row]
            self.settings.set_bookmarks(key, items)
            session.nav_panel.bookmarks.load_bookmarks(items)
            self.info_bar.show_message("Bookmark removed.", "info")

    def _run_search(
        self,
        query: str,
        session: DocumentSession | None = None,
        pages: list[int] | None = None,
    ) -> None:
        target = session or self._session
        if target is None:
            return
        session = target
        panel = session.search_panel
        if not session.engine.is_loaded():
            return
        temp = session.engine.temp_path
        if not temp or not temp.is_file():
            return
        key = id(session)
        generation = self._search_generations.get(key, 0) + 1
        self._search_generations[key] = generation
        previous = self._search_tasks.pop(key, None)
        if previous is not None:
            previous.cancel()
            self._tasks.discard(previous)
        panel.show_searching()
        case_sensitive = panel.case_sensitive()
        whole_word = panel.whole_word()

        if session.engine.page_count <= 50:
            try:
                hits = session.engine.search_text_detailed(
                    query,
                    case_sensitive=case_sensitive,
                    whole_word=whole_word,
                    pages=pages,
                )
                self._finish_search(hits, session, query, generation)
            except Exception as exc:
                panel.show_error(str(exc))
            return
        if self._tasks:
            panel.show_error("Wait for the current background operation to finish.")
            return
        task = self._run_task(
            "Searching document",
            search_pdf_file,
            str(temp),
            query,
            case_sensitive=case_sensitive,
            whole_word=whole_word,
            password=session.engine.password,
            pages=pages,
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda hits: self._finish_search(
                hits, session, query, generation
            ),
            on_finished=lambda: self._finish_search_task(key, generation),
        )
        if task is not None:
            self._search_tasks[key] = task

            task.signals.progress.connect(panel.show_progress)

    def _finish_search_task(self, key: int, generation: int) -> None:
        if self._search_generations.get(key) == generation:
            self._search_tasks.pop(key, None)

    def _finish_search(
        self,
        hits,
        session: DocumentSession | None = None,
        query: str | None = None,
        generation: int | None = None,
    ) -> None:
        if session is None:
            return
        key = id(session)
        if generation is not None and self._search_generations.get(key) != generation:
            return
        if (
            query is not None
            and session.search_panel.query_text()
            and session.search_panel.query_text() != query.strip()
        ):
            return
        results = list(hits or [])
        total = sum(len(hit.rects) for hit in results)
        session.search_panel.set_results(results, total)

    def _goto_search_hit(
        self, page: int, rects, session: DocumentSession | None = None
    ) -> None:
        session = session or self._session
        if session is None:
            return
        self.workspace.set_current_session(session)
        self._session = session
        self.goto_page(page)
        session.canvas.show_search_hits(page, list(rects or []))

    # --- P1: command registry, palette, shortcuts and undo history -------
    def _tool_available(self, key: str) -> bool:
        loaded = self._session is not None and self._session.engine.is_loaded()
        if key in SidePanel.DOCUMENT_TOOLS and not loaded:
            return False
        if key == "decrypt" and not (loaded and self._session.engine.is_encrypted()):
            return False
        capabilities = detect_capabilities()
        for _section_key, _title, items in SidePanel.SECTIONS:
            for item in items:
                if item.key == key and item.capability is not None:
                    return capabilities[item.capability].available
        return True

    def _build_command_registry(self) -> None:
        commands: list[Command] = []
        overrides = self.settings.get_shortcut_overrides()

        def document() -> bool:
            return self._session is not None and self._session.engine.is_loaded()

        def make(
            key: str,
            label: str,
            shortcut: str,
            section: str,
            handler,
            enabled=None,
        ) -> None:
            default = QKeySequence(shortcut).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            current = (
                QKeySequence(overrides[key]).toString(
                    QKeySequence.SequenceFormat.PortableText
                )
                if key in overrides
                else default
            )
            commands.append(
                Command(
                    key,
                    label,
                    current,
                    section,
                    handler,
                    enabled,
                    default_shortcut=default,
                )
            )

        make("open", "Open…", "Ctrl+O", "File", self._open_dialog)
        make(
            "search_open",
            "Search and Open PDF…",
            "Ctrl+Shift+O",
            "File",
            self._search_and_open,
        )
        make("save", "Save", "Ctrl+S", "File", self.save_file, document)
        make("save_as", "Save As…", "Ctrl+Shift+S", "File", self.save_as_file, document)
        make("print", "Print…", "Ctrl+P", "File", self.print_pdf, document)
        make("close", "Close Document", "Ctrl+W", "File", self.close_document, document)
        make("open_postscript", "Open PostScript…", "", "File", self._open_postscript)

        make(
            "undo",
            "Undo",
            "Ctrl+Z",
            "Edit",
            self._undo,
            lambda: self._session is not None and self._session.undo_stack.can_undo,
        )
        make(
            "redo",
            "Redo",
            "Ctrl+Y",
            "Edit",
            self._redo,
            lambda: self._session is not None and self._session.undo_stack.can_redo,
        )
        make(
            "undo_history",
            "Undo History…",
            "",
            "Edit",
            self._show_undo_history,
            lambda: self._session is not None
            and (
                self._session.undo_stack.can_undo or self._session.undo_stack.can_redo
            ),
        )

        tool_shortcuts = {"search": "Ctrl+F", **SHORTCUT_HINTS}
        for section_key, _title, items in SidePanel.SECTIONS:
            for item in items:
                make(
                    item.key,
                    item.label,
                    tool_shortcuts.get(item.key, ""),
                    "Annotate" if section_key == "annotate" else "Tools",
                    lambda key=item.key: self._tool_requested(key),
                    lambda key=item.key: self._tool_available(key),
                )
        make(
            "diagnostics",
            "External Tools & Diagnostics…",
            "",
            "Tools",
            lambda: self._tool_requested("diagnostics"),
        )
        make(
            "toggle_tools",
            "Toggle Tools Panel",
            "Ctrl+\\",
            "View",
            self._toggle_side_panel,
        )
        make(
            "toggle_context",
            "Toggle Context Panel",
            "Ctrl+.",
            "View",
            self._toggle_context_panel,
            document,
        )
        make(
            "toggle_thumbnails",
            "Toggle Page Thumbnails",
            "Ctrl+T",
            "View",
            self._toggle_thumbnails,
            document,
        )
        make(
            "nav_outline",
            "Show Outline Panel",
            "",
            "View",
            lambda: self._show_nav_tab("outline"),
            document,
        )
        make(
            "nav_bookmarks",
            "Show Bookmarks Panel",
            "",
            "View",
            lambda: self._show_nav_tab("bookmarks"),
            document,
        )
        make(
            "nav_search",
            "Show Search Panel",
            "",
            "View",
            lambda: self._show_nav_tab("search"),
            document,
        )
        make(
            "add_bookmark",
            "Add Bookmark",
            "Ctrl+D",
            "View",
            self._add_bookmark,
            document,
        )
        make(
            "view_single",
            "Single Page Layout",
            "Ctrl+1",
            "View",
            lambda: self._set_layout_mode("single"),
            document,
        )
        make(
            "view_continuous",
            "Continuous Page Layout",
            "Ctrl+2",
            "View",
            lambda: self._set_layout_mode("continuous"),
            document,
        )
        make(
            "view_facing",
            "Facing Page Layout",
            "Ctrl+3",
            "View",
            lambda: self._set_layout_mode("facing"),
            document,
        )
        make(
            "fit_width",
            "Fit Page Width",
            "Ctrl+0",
            "View",
            self._canvas_call("fit_width"),
            document,
        )
        make(
            "fit_page",
            "Fit Whole Page",
            "Ctrl+9",
            "View",
            self._canvas_call("fit_page"),
            document,
        )
        make(
            "actual_size",
            "Actual Size",
            "Ctrl+8",
            "View",
            self._canvas_call("actual_size"),
            document,
        )
        make(
            "tool_browse",
            "Browse Tool",
            "",
            "View",
            lambda: self._set_canvas_tool("browse"),
            document,
        )
        make(
            "tool_hand",
            "Hand Tool (pan)",
            "",
            "View",
            lambda: self._set_canvas_tool("hand"),
            document,
        )
        make(
            "tool_select",
            "Select Text Tool",
            "",
            "View",
            lambda: self._set_canvas_tool("select"),
            document,
        )
        make(
            "tool_magnifier",
            "Magnifier Tool",
            "",
            "View",
            lambda: self._set_canvas_tool("magnifier"),
            document,
        )
        make(
            "toggle_page_labels",
            "Show Page Labels",
            "",
            "View",
            self._toggle_page_labels,
            document,
        )
        make(
            "zoom_in",
            "Zoom In",
            "Ctrl+=",
            "View",
            self._canvas_call("zoom_in"),
            document,
        )
        make(
            "zoom_out",
            "Zoom Out",
            "Ctrl+-",
            "View",
            self._canvas_call("zoom_out"),
            document,
        )

        make("tab_next", "Next Tab", "Ctrl+Tab", "View", self._next_tab)
        make("tab_prev", "Previous Tab", "Ctrl+Shift+Tab", "View", self._previous_tab)
        make(
            "view_split",
            "Toggle Split View",
            "",
            "View",
            self._toggle_split_view,
            document,
        )
        make(
            "prev_page",
            "Previous Page",
            "Ctrl+Left",
            "Navigate",
            self.previous_page,
            document,
        )
        make(
            "next_page", "Next Page", "Ctrl+Right", "Navigate", self.next_page, document
        )
        make(
            "first_page",
            "First Page",
            "Home",
            "Navigate",
            self._goto_first_page,
            document,
        )
        make(
            "last_page", "Last Page", "End", "Navigate", self._goto_last_page, document
        )

        make(
            "rotate_left",
            "Rotate Current Page Left",
            "Ctrl+L",
            "Page",
            lambda: self._rotate_current(-90),
            document,
        )
        make(
            "rotate_right",
            "Rotate Current Page Right",
            "Ctrl+R",
            "Page",
            lambda: self._rotate_current(90),
            document,
        )
        make(
            "quick_extract",
            "Extract Pages",
            "Ctrl+E",
            "Page",
            self._extract_pages_dialog,
            document,
        )
        make(
            "quick_delete",
            "Delete Selected Pages",
            "Delete",
            "Page",
            self._delete_pages_shortcut,
            document,
        )
        make(
            "escape_browse",
            "Return to Browse Tool",
            "Escape",
            "View",
            self._escape_to_browse,
            document,
        )
        make("readme", "README", "", "Help", self._show_readme)
        make("preferences", "Preferences…", "", "Help", self.show_preferences)
        make("save_all", "Save All", "", "File", self.save_all_files, document)
        make("about", "About PDFDocuEdit Pro", "", "Help", self.show_about)
        make(
            "command_palette",
            "Command Palette…",
            "Ctrl+K",
            "Help",
            self._show_command_palette,
        )
        make("shortcuts", "Keyboard Shortcuts", "Ctrl+/", "Help", self._show_shortcuts)

        override_shortcuts = {
            QKeySequence(value).toString(QKeySequence.SequenceFormat.PortableText)
            for value in overrides.values()
            if value
        }
        used_shortcuts: set[str] = set()
        resolved_commands: list[Command] = []
        for command in commands:
            sequence = command.shortcut
            is_override = command.id in overrides
            if sequence and not is_override and sequence in override_shortcuts:
                sequence = ""
            elif sequence and sequence in used_shortcuts:
                fallback = command.default_shortcut
                sequence = (
                    fallback
                    if fallback
                    and fallback not in used_shortcuts
                    and fallback not in override_shortcuts
                    else ""
                )
            if sequence:
                used_shortcuts.add(sequence)
            resolved_commands.append(replace(command, shortcut=sequence))
        self._commands = resolved_commands

    @staticmethod
    def _shortcut_label_key(value: str) -> str:
        return (
            value.replace("&", "")
            .replace("…", "")
            .replace("...", "")
            .strip()
            .casefold()
        )

    def _command_action(
        self, command: Command, claimed: set[QAction]
    ) -> QAction | None:
        if command.id in {
            "rotate_left",
            "rotate_right",
            "quick_extract",
            "quick_delete",
            "escape_browse",
        }:
            return None
        label_key = self._shortcut_label_key(command.label)
        label_matches = [
            action
            for action in self._registered_shortcut_actions
            if action not in claimed
            and self._shortcut_label_key(
                str(action.property("shortcutBaseLabel") or action.text())
            )
            == label_key
        ]
        if len(label_matches) == 1:
            return label_matches[0]
        if command.default_shortcut:
            shortcut_matches = [
                action
                for action in self._registered_shortcut_actions
                if action not in claimed
                and str(action.property("shortcutDefault") or "")
                == command.default_shortcut
            ]
            if len(shortcut_matches) == 1:
                return shortcut_matches[0]
        return None

    def _run_shortcut_command(self, command_id: str) -> None:
        command = next((item for item in self._commands if item.id == command_id), None)
        if command is None or not command.is_enabled():
            return
        if command_id != "escape_browse" and self._editing_focused():
            return
        command.handler()

    def _apply_command_shortcuts(self) -> None:
        for action in self._registered_shortcut_actions:
            action.setShortcut(
                QKeySequence(str(action.property("shortcutDefault") or ""))
            )
        for shortcut in self._command_shortcuts:
            shortcut.setEnabled(False)
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._command_shortcuts.clear()
        self._command_action_map.clear()

        for name in (
            "_shortcut_bookmark",
            "_shortcut_next_tab",
            "_shortcut_prev_tab",
            "_shortcut_browse",
            "_shortcut_rotate_left",
            "_shortcut_rotate_right",
            "_shortcut_extract",
            "_shortcut_delete",
        ):
            setattr(self, name, None)

        claimed: set[QAction] = set()
        named_shortcuts = {
            "add_bookmark": "_shortcut_bookmark",
            "tab_next": "_shortcut_next_tab",
            "tab_prev": "_shortcut_prev_tab",
            "escape_browse": "_shortcut_browse",
            "rotate_left": "_shortcut_rotate_left",
            "rotate_right": "_shortcut_rotate_right",
            "quick_extract": "_shortcut_extract",
            "quick_delete": "_shortcut_delete",
        }
        for command in self._commands:
            sequence = QKeySequence(command.shortcut)
            action = self._command_action(command, claimed)
            if action is not None:
                action.setShortcut(sequence)
                claimed.add(action)
                self._command_action_map[command.id] = action
                continue
            if sequence.isEmpty():
                continue
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda command_id=command.id: self._run_shortcut_command(command_id)
            )
            self._command_shortcuts.append(shortcut)
            attribute = named_shortcuts.get(command.id)
            if attribute:
                setattr(self, attribute, shortcut)

        self.side_panel.set_shortcut_hints(
            {
                command.id: command.shortcut
                for command in self._commands
                if command.shortcut
            }
        )

    def _install_shortcuts(self) -> None:
        self._apply_command_shortcuts()

    def _editing_focused(self) -> bool:
        widget = QApplication.focusWidget()
        return isinstance(widget, (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit))

    def _delete_pages_shortcut(self) -> None:
        """Delete a selected annotation first, otherwise open page deletion."""
        if self._editing_focused():
            return
        session = self._session
        if session is not None:
            for canvas in self._session_canvases(session):
                selected = canvas.selected_annotation()
                if selected is not None:
                    self._handle_remove_annotation(*selected)
                    for target in self._session_canvases(session):
                        target.clear_annotation_selection()
                    return
        self._delete_pages_dialog()

    def _show_command_palette(self) -> None:
        existing = getattr(self, "_command_palette", None)
        if existing is not None:
            existing.refresh()
            existing.move(
                self.mapToGlobal(self.rect().center() - existing.rect().center())
            )
            existing.show()
            existing.raise_()
            existing.activateWindow()
            existing.focus_input()
            return
        palette = CommandPalette(self._commands, self)
        palette.commandTriggered.connect(self._run_command)
        offset = self.rect().center() - palette.rect().center()
        palette.move(self.mapToGlobal(offset))
        self._command_palette = palette
        palette.destroyed.connect(lambda: setattr(self, "_command_palette", None))
        palette.show()
        palette.raise_()
        palette.activateWindow()
        palette.focus_input()

    def _run_command(self, command_id: str) -> None:
        for command in self._commands:
            if command.id == command_id:
                command.handler()
                return

    def _show_shortcuts(self) -> None:
        ShortcutsDialog(self._commands, self).exec()

    def _show_undo_history(self) -> None:
        stack = self._undo_stack
        if stack is None:
            return
        dialog = UndoHistoryDialog(
            stack.undo_descriptions(),
            stack.redo_descriptions(),
            self,
        )
        dialog.undoToRequested.connect(self._undo_to)
        dialog.redoToRequested.connect(self._redo_to)
        dialog.exec()

    def _undo_to(self, steps: int) -> None:
        stack = self._undo_stack
        for _ in range(steps):
            if stack is None or not stack.can_undo:
                break
            self._undo()

    def _redo_to(self, steps: int) -> None:
        stack = self._undo_stack
        for _ in range(steps):
            if stack is None or not stack.can_redo:
                break
            self._redo()

    def _batch_print(self) -> None:
        existing = getattr(self, "_batch_print_dialog", None)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = BatchPrintDialog(self)
        dialog.printRequested.connect(
            lambda details: self._run_batch_print(dialog, details)
        )
        dialog.destroyed.connect(lambda: setattr(self, "_batch_print_dialog", None))
        self._batch_print_dialog = dialog
        dialog.show()

    def _run_batch_print(
        self, dialog: BatchPrintDialog, details: dict[str, object]
    ) -> None:
        dialog.set_printing(True)
        self.settings.set_print_profile(details)
        try:
            printer = self._create_printer(details)
            paths: list[str] = list(details["paths"])
            with ExitStack() as stack:
                # Open each file individually so one unreadable PDF skips
                # instead of aborting the whole batch (legacy behaviour).
                documents: list[fitz.Document] = []
                printed_paths: list[str] = []
                for path in paths:
                    try:
                        documents.append(stack.enter_context(fitz.open(path)))
                        printed_paths.append(path)
                    except Exception as exc:
                        dialog.mark_file_error(str(path))
                        dialog.log_message(
                            f"Skipped {Path(path).name}: could not open it ({exc})."
                        )
                if not documents:
                    dialog.log_message("No documents to print.")
                    return
                first_page = documents[0].load_page(0)
                self._configure_print_layout(printer, first_page, details)
                if details.get("confirm_system_dialog"):
                    native_dialog = QPrintDialog(printer, self)
                    native_dialog.setWindowTitle("Confirm Batch Print")
                    if native_dialog.exec() != QDialog.DialogCode.Accepted:
                        dialog.log_message("Print job cancelled.")
                        return
                # One print job per file (legacy behaviour): each job gets
                # its own paper size and orientation from that file's first
                # page and is named after the file in the print queue.
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    sent = 0
                    skipped = len(paths) - len(documents)
                    failed = 0
                    cancelled = False
                    for path, document in zip(printed_paths, documents, strict=True):
                        if dialog.cancel_requested():
                            cancelled = True
                            break
                        try:
                            job = self._create_printer(details)
                            job.setDocName(Path(path).name)
                            self._configure_print_layout(
                                job, document.load_page(0), details
                            )
                            self._paint_documents(
                                job,
                                [
                                    (
                                        document,
                                        list(range(document.page_count)),
                                        Path(path).name,
                                    )
                                ],
                                details,
                                log=dialog.log_message,
                                progress=lambda i, page, total, p=path: (
                                    dialog.set_file_status(
                                        p, f"Printing page {page + 1} of {total}"
                                    ),
                                    self.bottom_bar.set_status(
                                        f"Printing {Path(p).name}: page {page + 1} of {total}…"
                                    ),
                                    QApplication.processEvents(),
                                ),
                                should_cancel=dialog.cancel_requested,
                            )
                        except Exception as exc:
                            failed += 1
                            dialog.mark_file_error(str(path))
                            dialog.log_message(f"Failed {Path(path).name}: {exc}")
                            continue
                        if dialog.cancel_requested():
                            cancelled = True
                            dialog.set_file_status(str(path), "Cancelled")
                            dialog.log_message("Batch print cancelled.")
                            break
                        dialog.mark_file_printed(str(path))
                        sent += 1

                    summary = (
                        f"Sent {sent} PDF file(s); {failed} failed; {skipped} skipped"
                    )
                    if cancelled:
                        summary += ", cancelled before completion"
                    dialog.log_message(summary + ".")
                    self.info_bar.show_message(
                        summary + ".", "warning" if failed or cancelled else "success"
                    )
                finally:
                    QApplication.restoreOverrideCursor()
                    self.bottom_bar.set_status("Ready")
        except Exception as exc:
            dialog.log_message(f"Batch print failed: {exc}")
            dialog.mark_printing_as_error()
            self._error("Batch print failed", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self.bottom_bar.set_status("Ready")
            dialog.set_printing(False)

    def _extract_pages_dialog(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before extracting pages.", "warning")
            return
        dialog = PageSelectionDialog("Extract", self.engine.page_count, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        source = self.engine.original_path
        suggested = f"{source.stem}_extracted.pdf" if source else "extracted-pages.pdf"
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Save Extracted Pages",
            start_in_save_directory(self, suggested, source.parent if source else None),
            "PDF (*.pdf)",
        )
        if output:
            remember_save_directory(self, output)
            if not output.casefold().endswith(".pdf"):
                output += ".pdf"
            try:
                if (
                    self.engine.original_path
                    and Path(output).resolve() == self.engine.original_path
                ):
                    raise ValueError(
                        "Choose a new output file instead of the open PDF."
                    )
                target = self.engine.extract_pages(dialog.selected_pages, output)
                self.info_bar.show_message(
                    f"📄 Created {target.name} with {len(dialog.selected_pages)} selected page(s).",
                    "success",
                )
            except Exception as exc:
                self._error("Extract failed", str(exc))

    def _delete_pages_dialog(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before deleting pages.", "warning")
            return
        dialog = PageSelectionDialog("Delete", self.engine.page_count, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pages = dialog.selected_pages
        answer = QMessageBox.question(
            self,
            "Delete pages",
            f"Delete {len(pages)} selected page(s)? This change is applied when you save the PDF.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self._snapshot_before("Delete Pages"):
                return
            self.engine.delete_pages(pages)
            self._after_page_count_change()
            self.info_bar.show_message(
                f"🗑 Deleted {len(pages)} page(s). Save the document to keep the change.",
                "success",
            )
        except Exception as exc:
            self._error("Delete failed", str(exc))

    def _insert_pages_dialog(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before inserting pages.", "warning")
            return
        dialog = InsertPagesDialog(self.engine.page_count, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        try:
            if not self._snapshot_before("Insert Pages"):
                return
            if details["mode"] == "single":
                self.engine.insert_pages(
                    str(details["source"]),
                    list(details["pages"]),
                    int(details["position"]),
                )
            elif details["mode"] == "repeat":
                self.engine.repeat_insert_pages(
                    str(details["source"]),
                    list(details["pages"]),
                    int(details["interval"]),
                )
            else:
                sizes = {
                    "A4": (595.0, 842.0),
                    "A3": (842.0, 1191.0),
                    "Letter": (612.0, 792.0),
                }
                if details["size"] == "Same as current page":
                    width, height = self.engine.get_page_size(self._page)
                else:
                    width, height = sizes[str(details["size"])]
                if details["orientation"] == "Landscape" and width < height:
                    width, height = height, width
                elif details["orientation"] == "Portrait" and width > height:
                    width, height = height, width
                self.engine.insert_blank_pages(
                    int(details["count"]),
                    int(details["position"]),
                    width,
                    height,
                )
            self._after_page_count_change()
            self.info_bar.show_message(
                "Pages inserted. Save to keep the change.", "success"
            )
        except Exception as exc:
            self._error("Insert failed", str(exc))

    def _split_dialog(self) -> None:
        if not self.engine.is_loaded():
            self.info_bar.show_message("Open a PDF before splitting it.", "warning")
            return
        source = self.engine.original_path
        dialog = SplitDialog(
            self.engine.page_count, source.stem if source else "document", self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        try:
            outputs = self.engine.split_pdf(
                list(details["ranges"]),
                str(details["folder"]),
                str(details["prefix"]),
                bool(details["overwrite"]),
            )
            self.info_bar.show_message(
                f"Created {len(outputs)} PDF file(s).", "success"
            )
        except Exception as exc:
            self._error("Split failed", str(exc))

    def _organize_pages(self, preselected_pages: tuple[int, ...] = ()) -> None:
        document = self.engine.document
        if not document:
            self.info_bar.show_message("Open a PDF before organizing pages.", "warning")
            return
        if preselected_pages:
            dialog = VisualOrganizerDialog(
                document, self, preselected_pages=preselected_pages
            )
        else:
            dialog = VisualOrganizerDialog(document, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if not self._snapshot_before("Organize Pages"):
                return
            plan = getattr(dialog, "page_plan", None)
            if plan:
                self.engine.apply_page_plan(plan)
            else:
                self.engine.organize_pages(dialog.order, dialog.rotations)
            self._after_page_count_change()
            self.info_bar.show_message(
                "The page plan was applied as one undoable transaction. "
                "Save to keep the changes.",
                "success",
            )
        except Exception as exc:
            self._error("Organize pages failed", str(exc))

    def _require_source(self) -> Path | None:
        if not self.engine.is_loaded() or not self.engine.original_path:
            self.info_bar.show_message("Open a PDF before using this tool.", "warning")
            return None
        return self.engine.original_path

    @staticmethod
    def _safe_cleanup(
        directory: tempfile.TemporaryDirectory[str],
    ) -> Callable[[], None]:
        """Wrap TemporaryDirectory.cleanup so a failed cleanup never escapes
        into the Qt slot that calls it."""

        def cleanup() -> None:
            try:
                directory.cleanup()
            except Exception:
                pass

        return cleanup

    def _working_snapshot(
        self, source: Path
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory(prefix="pdfdocuedit-working-")
        path = Path(directory.name) / source.name
        try:
            self.engine.snapshot(path)
        except Exception:
            directory.cleanup()
            raise
        return directory, path

    def _reload_session_if_replaced(
        self, session: DocumentSession, values: list[Path]
    ) -> None:
        """Reload the session that started the task if its file was rewritten.

        The task may finish after the user switched tabs; the completion must
        target the originating session, not whichever one is now active.
        """
        if session is None or session not in self._sessions:
            return
        current = session.engine.original_path
        if current and any(Path(value).resolve() == current for value in values):
            self.workspace.set_current_session(session)
            self._session = session
            self.load_file(str(current))

    def _batch_completed(
        self, session: DocumentSession, values: list[Path], message: str
    ) -> None:
        self._reload_session_if_replaced(session, values)
        self.info_bar.show_message(message.format(count=len(values)), "success")

    def _run_ocr_from_search(self, session: DocumentSession) -> None:
        if session not in self._sessions:
            return
        self.workspace.set_current_session(session)
        self._session = session
        self._ocr()

    def _ocr(self) -> None:
        source = self._require_source()
        if source is None:
            return
        capability = detect_capabilities().get(CapabilityId.OCR)
        if capability is None or not capability.available:
            reason = (
                capability.reason if capability else "OCR capability is unavailable."
            )
            self.info_bar.show_message(f"OCR unavailable: {reason}", "warning", 0)
            return
        session = self._session
        if session is None:
            return
        dialog = OCRDialog(
            source,
            session.engine.page_count,
            session.page,
            session.engine.password,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.request is None:
            return
        request = dialog.request
        snapshot = None
        if session.engine.is_modified:
            try:
                snapshot, working = self._working_snapshot(source)
                request = replace(request, source_path=str(working))
            except Exception as exc:
                self._error("OCR failed", str(exc))
                return
        self._run_task(
            "Running OCR",
            run_ocr,
            request,
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=self._ocr_finished,
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _ocr_finished(self, result: OCRResult) -> None:
        if result.mode == OCRMode.EXTRACT_TEXT:
            OCRTextResultDialog(result, self).exec()
            if result.output_path:
                self.info_bar.show_message(
                    f"OCR text saved: {Path(result.output_path).name}", "success"
                )
            return
        if not result.output_path:
            return
        target = Path(result.output_path)
        message = QMessageBox(self)
        message.setWindowTitle("OCR complete")
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(f"Created searchable PDF: {target.name}")
        open_button = message.addButton(
            "Open in new tab", QMessageBox.ButtonRole.ActionRole
        )
        folder_button = message.addButton(
            "Show in folder", QMessageBox.ButtonRole.ActionRole
        )
        message.addButton(QMessageBox.StandardButton.Close)
        message.exec()
        clicked = message.clickedButton()
        if clicked is open_button:
            self.open_in_new_tab(str(target))
        elif clicked is folder_button:
            PlatformService.reveal_file(target)
        self.info_bar.show_message(f"Created searchable PDF: {target.name}", "success")

    def _pdf_to_word(self) -> None:
        source = self._require_source()
        if not source:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Convert PDF to Word",
            start_in_save_directory(self, f"{source.stem}.docx", source.parent),
            "Word (*.docx)",
        )
        if path:
            remember_save_directory(self, path)
            if not path.casefold().endswith(".docx"):
                path += ".docx"
            snapshot = None
            input_source = source
            if self.engine.is_modified:
                try:
                    snapshot, input_source = self._working_snapshot(source)
                except Exception as exc:
                    self._error("PDF to Word failed", str(exc))
                    return
            self._run_task(
                "Converting to Word",
                convert_pdf_to_word,
                input_source,
                path,
                on_finished=self._safe_cleanup(snapshot) if snapshot else None,
            )

    def _office_to_pdf(self) -> None:
        dialog = OfficeConversionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        self._run_task(
            "Converting Office documents",
            convert_office_files,
            details["paths"],
            details["output_folder"],
            details["overwrite"],
            details["source_folder"],
            details["keep_structure"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda values: self.info_bar.show_message(
                f"Created {len(values)} PDF file(s).", "success"
            ),
        )

    def _txt_to_pdf(self) -> None:
        dialog = TextConversionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        self._run_task(
            "Creating PDF from text",
            text_files_to_pdfs,
            details["paths"],
            details["output_folder"],
            details["filename"],
            details["single"],
            details["encoding"],
            details["overwrite"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda values: self.info_bar.show_message(
                f"Created {len(values)} PDF file(s).", "success"
            ),
        )

    def _postscript_to_pdf(self) -> None:
        dialog = PostScriptConversionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        self._run_task(
            "Converting PostScript",
            convert_postscript_files,
            details["paths"],
            details["output_folder"],
            details["prefix"],
            details["overwrite"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda values: self.info_bar.show_message(
                f"Created {len(values)} PDF file(s).", "success"
            ),
        )

    def _page_report(self) -> None:
        dialog = PageCountReportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        self._run_task(
            "Creating page report",
            create_page_count_report,
            details["folder"],
            details["output"],
            details["recursive"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
        )

    def _extract_text(self) -> None:
        source = self._require_source()
        document = self.engine.document
        if not source or not document:
            return
        dialog = TextExtractorDialog(
            document,
            self._page,
            str(source.with_name(f"{source.stem}_extracted.xlsx")),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        snapshot_directory = tempfile.TemporaryDirectory(prefix="pdfdocuedit-extract-")
        extraction_source = Path(snapshot_directory.name) / "working-copy.pdf"
        try:
            self.engine.snapshot(extraction_source)
        except Exception as exc:
            snapshot_directory.cleanup()
            self._error("Text extraction failed", str(exc))
            return
        self._run_task(
            "Extracting selected text region",
            extract_region_text,
            extraction_source,
            details["pages"],
            details["rect"],
            details["output"],
            details["excel"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_finished=self._safe_cleanup(snapshot_directory),
        )

    def _merge_pdfs(self) -> None:
        dialog = MergePDFDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.output_path:
            current = self.engine.original_path
            if current and Path(dialog.output_path).resolve() == current:
                self.info_bar.show_message(
                    "Choose an output other than the PDF currently open in this window.",
                    "error",
                    0,
                )
                return
            self._run_task(
                "Merging PDFs",
                merge_pdfs,
                dialog.file_paths,
                dialog.output_path,
                progress_argument="progress",
                cancel_argument="is_cancelled",
                on_result=lambda value: self.info_bar.show_message(
                    f"🔗 Merged PDF saved: {Path(value).name}", "success"
                ),
            )

    def _overlay_pdf(self) -> None:
        dialog = OverlayDialog(self.engine.original_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        session = self._session
        targets = [Path(value).resolve() for value in details["targets"]]
        current = self.engine.original_path
        snapshot = None
        if current and self.engine.is_modified and current in targets:
            if not details["suffix"] and details["overwrite"]:
                self.info_bar.show_message(
                    "Save the current PDF before applying an in-place overlay.",
                    "warning",
                    0,
                )
                return
            try:
                snapshot, working = self._working_snapshot(current)
            except Exception as exc:
                self._error("PDF overlay failed", str(exc))
                return
            targets = [working if value == current else value for value in targets]
        self._run_task(
            "Applying PDF overlay",
            overlay_pdfs,
            details["template"],
            targets,
            details["output_folder"],
            details["suffix"],
            details["overwrite"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda values: self._batch_completed(
                session, values, "Overlay completed for {count} PDF file(s)."
            ),
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _compress_pdf(self) -> None:
        dialog = CompressionDialog(self.engine.original_path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        paths = [Path(value).resolve() for value in details["paths"]]
        output_folder = details["output_folder"]
        current = self.engine.original_path
        session = self._session
        snapshot = None
        if current and self.engine.is_modified and current in paths:
            if not details["suffix"] and details["overwrite"]:
                self.info_bar.show_message(
                    "Save the current PDF before compressing it in place.",
                    "warning",
                    0,
                )
                return
            try:
                snapshot, working = self._working_snapshot(current)
            except Exception as exc:
                self._error("Compression failed", str(exc))
                return
            paths = [working if value == current else value for value in paths]
            # Only the single-current-file case needs the fallback folder
            # (the working snapshot lives in a temp dir); folder batches
            # must keep "use each source folder" semantics.
            if output_folder is None and len(paths) == 1:
                output_folder = str(current.parent)
        self._run_task(
            "Compressing PDF files",
            compress_pdfs,
            paths,
            output_folder,
            details["suffix"],
            details["overwrite"],
            details["garbage"],
            details["clean"],
            details["deflate"],
            details["deflate_images"],
            details["deflate_fonts"],
            details["linear"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_result=lambda values: self._batch_completed(
                session, values, "Compressed {count} PDF file(s)."
            ),
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _deep_search(self) -> None:
        existing = getattr(self, "_deep_search_dialog", None)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = DeepSearchDialog(self.settings.get_last_directory(), self)
        dialog.openRequested.connect(self._open_deep_search_result)
        dialog.destroyed.connect(lambda: setattr(self, "_deep_search_dialog", None))
        self._deep_search_dialog = dialog
        dialog.show()

    def _open_deep_search_result(self, path: str, method: str) -> None:
        if method == OPEN_NEW_TAB:
            self.open_in_new_tab(path)
        elif method == OPEN_CURRENT:
            self.load_file(path)
        else:
            from core.platform_service import PlatformService

            PlatformService.open_path(path)

    def _merge_sheets(self) -> None:
        dialog = SpreadsheetMergeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        self._run_task(
            "Merging spreadsheets",
            merge_spreadsheets,
            details["paths"],
            details["output"],
            details["skip_rows"],
            details["exclude_keywords"],
            details["first_cell_only"],
            details["encoding"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
        )

    def _scan_barcodes(self, *, preload_current: bool = True) -> None:
        dialog = BarcodeScanDialog(
            self.engine.original_path if preload_current else None, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        paths = [Path(value).resolve() for value in details["paths"]]
        current = self.engine.original_path
        snapshot = None
        remap: dict[Path, Path] = {}
        if current and self.engine.is_modified and current in paths:
            try:
                snapshot, working = self._working_snapshot(current)
            except Exception as exc:
                self._error("Barcode scan failed", str(exc))
                return
            paths = [working if value == current else value for value in paths]
            remap[working] = current
        self._run_task(
            "Scanning barcodes",
            scan_barcodes_batch,
            paths,
            details["page_range"],
            details["dpi"],
            on_result=lambda results: self._show_barcode_results(results, remap),
            barcode_types=details["barcode_types"],
            progress_argument="progress",
            cancel_argument="is_cancelled",
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _show_barcode_results(
        self,
        results: list[dict[str, object]],
        remap: dict[Path, Path] | None = None,
    ) -> None:
        for result in results:
            value = Path(str(result.get("path", ""))).resolve()
            if remap and value in remap:
                result["path"] = str(remap[value])
        BarcodeResultsDialog(results, self).exec()

    def _encrypt_pdf(self) -> None:
        source = self._require_source()
        if not source:
            return
        dialog = EncryptDialog(source, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.details:
            return
        details = dialog.details
        if Path(str(details["output"])).resolve() == source:
            self.info_bar.show_message(
                "Choose a new output file instead of the open PDF.", "error", 0
            )
            return
        input_source = source
        snapshot = None
        if self.engine.is_modified:
            try:
                snapshot, input_source = self._working_snapshot(source)
            except Exception as exc:
                self._error("Encryption failed", str(exc))
                return
        self._run_task(
            "Encrypting PDF",
            encrypt_pdf_file,
            input_source,
            str(details["output"]),
            user_password=str(details["user_password"]),
            owner_password=str(details["owner_password"]),
            encryption=int(details["algorithm"]),
            permissions=int(details["permissions"]),
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _decrypt_pdf(self) -> None:
        source = self._require_source()
        if not source:
            return
        dialog = DecryptDialog(source, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.output_path:
            return
        if Path(dialog.output_path).resolve() == source:
            self.info_bar.show_message(
                "Choose a new output file instead of the open PDF.", "error", 0
            )
            return
        input_source = source
        snapshot = None
        if self.engine.is_modified:
            try:
                snapshot, input_source = self._working_snapshot(source)
            except Exception as exc:
                self._error("Decryption failed", str(exc))
                return
        self._run_task(
            "Decrypting PDF",
            decrypt_pdf_file,
            input_source,
            dialog.output_path,
            password=self.engine.password,
            on_finished=self._safe_cleanup(snapshot) if snapshot else None,
        )

    def _run_task(
        self,
        label: str,
        function: Callable,
        *args,
        on_result: Callable | None = None,
        progress_argument: str | None = None,
        cancel_argument: str | None = None,
        on_finished: Callable[[], None] | None = None,
        **kwargs,
    ) -> FunctionTask | None:
        if self._tasks:
            self.info_bar.show_message(
                "Wait for the current background operation to finish or cancel it first.",
                "warning",
            )
            if on_finished:
                try:
                    on_finished()
                except OSError:
                    pass
            return None
        self._task_had_error = False
        task = FunctionTask(
            function,
            *args,
            progress_argument=progress_argument,
            cancel_argument=cancel_argument,
            **kwargs,
        )
        self._tasks.add(task)
        self.task_bar.start(label, cancellable=bool(cancel_argument))
        self.command_bar.set_work_status(label)
        self.bottom_bar.set_status(label)

        def progress(current: int, total: int, message: str) -> None:
            if self._closing:
                return
            self.task_bar.update_progress(current, total, message)
            self.command_bar.set_work_status(message)
            self.bottom_bar.set_status(message)

        def result(value) -> None:
            if self._closing:
                return
            if on_result:
                on_result(value)
            else:
                name = (
                    Path(value).name
                    if isinstance(value, (str, os.PathLike, Path))
                    else "Operation complete"
                )
                self.info_bar.show_message(f"Completed: {name}", "success")

        def finished() -> None:
            self._tasks.discard(task)
            if on_finished:
                try:
                    on_finished()
                except OSError:
                    pass
            if self._closing:
                return  # the window is gone: never touch its widgets again
            if not self._tasks:
                self.task_bar.clear()
                self.command_bar.set_work_status("Ready")
                if not self._task_had_error:
                    self.bottom_bar.set_status("Ready")

        task.signals.progress.connect(progress)
        task.signals.result.connect(result)
        task.signals.cancelled.connect(
            lambda: (
                None
                if self._closing
                else self.info_bar.show_message(f"Cancelled: {label}", "info")
            )
        )
        task.signals.error.connect(
            lambda message: None if self._closing else self._task_failed(label, message)
        )
        task.signals.finished.connect(finished)
        self._thread_pool.start(task)
        return task

    def _cancel_tasks(self) -> None:
        if not self._tasks:
            return
        for task in list(self._tasks):
            task.cancel()
        self.task_bar.set_cancelling()
        self.command_bar.set_work_status("Cancelling…")
        self.bottom_bar.set_status("Cancelling…")

    def _task_failed(self, label: str, message: str) -> None:
        self._task_had_error = True
        self.info_bar.show_message(f"{label} failed: {message}", "error", 0)
        self.command_bar.set_work_status("Ready")
        self.bottom_bar.set_status("Error")

    # --- Preferences/help/errors ----------------------------------------
    def show_preferences(self) -> None:
        dialog = PreferencesDialog(self.settings, self, self._commands)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            refresh_capabilities()
            self.side_panel.refresh_capabilities()
            self._set_motion_enabled(
                bool(self.settings.get("animations_enabled", True))
            )
            self._apply_theme(self.settings.get_theme())
            self._build_command_registry()
            self._apply_command_shortcuts()
            palette = getattr(self, "_command_palette", None)
            if palette is not None:
                palette.close()

    def _show_readme(self) -> None:
        ReadmeDialog(self).exec()

    def save_all_files(self) -> None:
        sessions = [
            session
            for session in self._sessions
            if session.engine.is_loaded() and session.engine.is_modified
        ]
        if not sessions:
            self.info_bar.show_message("No files need to be saved.", "info")
            return
        saved = 0
        skipped = 0
        for session in sessions:
            if session.engine.original_path is None:
                # Never-saved documents need a file name: prompt Save As
                # instead of silently dropping their changes.
                initial = start_in_save_directory(
                    self,
                    (
                        f"{session.document_name}.pdf"
                        if not session.document_name.casefold().endswith(".pdf")
                        else session.document_name
                    ),
                )
                path, _ = QFileDialog.getSaveFileName(
                    self, f"Save {session.document_name} As", initial, "PDF (*.pdf)"
                )
                if not path:
                    skipped += 1
                    continue
                if not path.casefold().endswith(".pdf"):
                    path += ".pdf"
                try:
                    target = session.engine.save_as(path)
                except Exception as exc:
                    self._error("Save failed", f"{session.document_name}: {exc}")
                    continue
                remember_save_directory(self, target)
                session.display_path = target
                self.workspace.update_tab_title(session)
                saved += 1
                continue
            try:
                target = session.engine.save()
                session.display_path = target
                self.workspace.update_tab_title(session)
                saved += 1
            except Exception as exc:
                self._error("Save failed", f"{session.document_name}: {exc}")
        if saved:
            self.info_bar.show_message(f"💾 Saved {saved} file(s).", "success")
        if skipped:
            self.info_bar.show_message(
                f"⚠ {skipped} file(s) were not saved because no file name was chosen.",
                "warning",
                0,
            )
        self._sync_modified_state()

    def _rotate_current(self, angle: int) -> None:
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        if not self._snapshot_before("Rotate Page"):
            return
        try:
            session.engine.rotate_pages([session.page], angle)
        except Exception as exc:
            self.info_bar.show_message(f"Rotate failed: {exc}", "error", 0)
            return
        session.canvas.refresh()
        self._sync_modified_state()
        self.info_bar.show_message(
            "🔄 Page rotated. Save the document to keep the change.", "success"
        )

    def _rotate_box_pages(self, angle: int) -> None:
        """Rotate the pages entered in the bottom page box (legacy ROTATE row)."""
        session = self._session
        if session is None or not session.engine.is_loaded():
            return
        raw = self.bottom_bar.page_box_text()
        try:
            pages = parse_page_range(raw, session.engine.page_count)
        except ValueError as exc:
            self.info_bar.show_message(f"Rotate failed: {exc}", "error", 0)
            return
        if not pages:
            self.info_bar.show_message(
                "Enter a page number (or a range like 1-3,5) in the page box first.",
                "warning",
                0,
            )
            return
        if not self._snapshot_before("Rotate Pages"):
            return
        try:
            session.engine.rotate_pages(pages, angle)
        except Exception as exc:
            self.info_bar.show_message(f"Rotate failed: {exc}", "error", 0)
            return
        session.canvas.refresh()
        self._sync_modified_state()
        self.info_bar.show_message(
            f"🔄 Rotated {len(pages)} page(s). Save the document to keep the change.",
            "success",
        )

    def _handle_thumbnail_action(self, session: DocumentSession, key: str) -> None:
        self.workspace.set_current_session(session)
        self._session = session
        if not session.engine.is_loaded():
            return
        if key == "insert":
            self._insert_pages_dialog()
        elif key == "delete_current":
            answer = QMessageBox.question(
                self,
                "Delete page",
                f"Delete page {session.page + 1}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            if not self._snapshot_before("Delete Page"):
                return
            page_number = session.page + 1
            try:
                session.engine.delete_page(session.page)
            except Exception as exc:
                self.info_bar.show_message(f"Delete failed: {exc}", "error", 0)
                return
            self._after_page_count_change()
            self._reload_thumbnails(session)
            self.info_bar.show_message(
                f"🗑 Deleted page {page_number}. Save the document to keep the change.",
                "success",
            )
        elif key == "extract_current":
            suggested = (
                f"{session.engine.original_path.stem}_page_{session.page + 1}.pdf"
                if session.engine.original_path
                else f"page_{session.page + 1}.pdf"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Extract Current Page",
                start_in_save_directory(
                    self,
                    suggested,
                    (
                        session.engine.original_path.parent
                        if session.engine.original_path
                        else None
                    ),
                ),
                "PDF (*.pdf)",
            )
            if path:
                remember_save_directory(self, path)
                if not path.casefold().endswith(".pdf"):
                    path += ".pdf"
                if (
                    session.engine.original_path
                    and Path(path).resolve() == session.engine.original_path
                ):
                    self.info_bar.show_message(
                        "Choose a new output file instead of the open PDF.", "error", 0
                    )
                    return
                try:
                    target = session.engine.extract_pages([session.page], path)
                    self.info_bar.show_message(f"📄 Created {target.name}", "success")
                except Exception as exc:
                    self.info_bar.show_message(f"Extract failed: {exc}", "error", 0)
        elif key == "rotate":
            self._show_context("rotate")
        elif key == "search":
            self._show_nav_tab("search")
            session.nav_panel.search.focus_query()
        elif key == "info":
            self.show_document_info()

    def _scan_barcodes_batch(self) -> None:
        self._scan_barcodes(preload_current=False)

    def _set_default_app(self) -> None:
        """Register the app as the default handler for PDF/PS/EPS files."""
        if not is_installed():
            self.info_bar.show_message(
                "Default-app registration is available in the installed version.",
                "info",
            )
            return
        if register_default_app():
            self.info_bar.show_message(
                "PDFDocuEdit Pro is now the default app for PDF, PS and EPS files.",
                "success",
            )
        else:
            self.info_bar.show_message(
                "Windows keeps its own file association. Choose PDFDocuEdit Pro "
                "in the Settings window that just opened.",
                "warning",
                0,
            )
            open_default_apps_settings()

    def offer_default_app(self) -> None:
        """One-time prompt when the installed app is not the default handler."""
        if not is_installed():
            return
        if self.settings.get("default_app_prompt_shown", False):
            return
        self.settings.set("default_app_prompt_shown", True)
        if is_default_app():
            return
        answer = QMessageBox.question(
            self,
            "Set as default app",
            "PDFDocuEdit Pro is not the default app for PDF/PS files.\n"
            "Set it as the default now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._set_default_app()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PDFDocuEdit Pro",
            f"<h3>PDFDocuEdit Pro V{APP_VERSION}</h3>"
            "<p>A cross-platform PDF workspace built with Python, PyQt6 and PyMuPDF.</p>"
            "<p><b>Developer:</b> Andy Leung</p>"
            f"<p>{COPYRIGHT_NOTICE}</p>"
            "<p>Interface icons are provided by Lucide under the ISC License.</p>",
        )

    def _error(self, title: str, message: str) -> None:
        """Non-blocking error report: persistent info bar + status text.

        Operation failures must never freeze the UI behind a modal dialog
        (a failed background job would otherwise interrupt unrelated work).
        """
        self.command_bar.set_work_status("Ready")
        self.bottom_bar.set_status("Error")
        self.info_bar.show_message(message, "error", 0)

    # --- Qt events -------------------------------------------------------
    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self.command_bar.set_maximized(self.isMaximized())
            resize_handles = getattr(self, "_resize_handles", None)
            if resize_handles is not None:
                resize_handles.update()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        resize_handles = getattr(self, "_resize_handles", None)
        if resize_handles is not None:
            resize_handles.update()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(
            url.toLocalFile().lower().endswith((".pdf", ".ps", ".eps"))
            for url in event.mimeData().urls()
        ):
            if not self.engine.is_loaded():
                self.workspace.set_drag_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.workspace.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.workspace.set_drag_active(False)
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith((".pdf", ".ps", ".eps"))
        ]
        if not paths:
            return
        self.load_file(paths[0])
        for extra in paths[1:]:
            self.open_in_new_tab(extra)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        for session in list(self._sessions):
            self._session = session
            if not self._confirm_discard_changes():
                event.ignore()
                self._closing = False
                self._session = self.workspace.current_session()
                return
        self.settings.update(
            {
                "window_size": [self.width(), self.height()],
                "window_position": [self.x(), self.y()],
                "window_maximized": self.isMaximized(),
                "left_panel_collapsed": self.side_panel.is_collapsed(),
            }
        )
        for task in list(self._tasks):
            task.cancel()
        for session in list(self._sessions):
            thumbnail_snapshot = getattr(session, "_thumbnail_snapshot", None)
            if thumbnail_snapshot:
                Path(thumbnail_snapshot).unlink(missing_ok=True)
            session.close()
        event.accept()
