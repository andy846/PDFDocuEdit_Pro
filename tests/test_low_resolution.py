"""Exercise every custom dialog family at small logical screen sizes."""

import fitz
import pytest
from PyQt6.QtCore import QPoint, QRect, QSettings
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from core.commands import Command
from core.ocr import OCRMode, OCRResult
from core.page_plan import PagePlanEntry, PlanReader
from core.settings import SettingsManager
from dialogs.annotation_dialogs import WatermarkDialog
from dialogs.barcode_dialogs import BarcodeResultsDialog, BarcodeScanDialog
from dialogs.batch_print_dialog import BatchPrintDialog
from dialogs.batch_tools import CompressionDialog, MergePDFDialog, OverlayDialog
from dialogs.comparison_dialog import ComparisonDialog
from dialogs.conversion_dialogs import (
    OfficeConversionDialog,
    PostScriptConversionDialog,
    TextConversionDialog,
)
from dialogs.data_dialogs import PageCountReportDialog, SpreadsheetMergeDialog
from dialogs.document_dialogs import DocumentInfoDialog, PrintOptionsDialog, VisualOrganizerDialog
from dialogs.form_dialog import FormDialog
from dialogs.ocr_dialog import OCRDialog, OCRTextResultDialog
from dialogs.organizer_tools import BlankPagesDialog, CropDialog, InterleaveDialog, JobDialog, SplitPlanDialog
from dialogs.page_operations import InsertPagesDialog, PageSelectionDialog, SplitDialog
from dialogs.readme_dialog import ReadmeDialog
from dialogs.search_open_dialog import SearchOpenDialog
from dialogs.security_dialogs import DecryptDialog, EncryptDialog
from dialogs.shortcuts_dialog import ShortcutsDialog
from dialogs.signature_appearance import SignatureAppearanceDialog
from dialogs.text_extractor_dialog import TextExtractorDialog
from dialogs.undo_history_dialog import UndoHistoryDialog
from ui.command_palette import CommandPalette
from ui.deep_search_dialog import DeepSearchDialog
from ui.diagnostics_dialog import DiagnosticsDialog, PreferencesDialog
from ui.update_dialog import UpdateDialog


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    app = QApplication.instance() or QApplication([])
    from styles.theme import apply_theme
    apply_theme(app, "light")
    location = tmp_path_factory.mktemp("low-resolution-settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(location))
    return app


NAMES = ["watermark", "barcode_scan", "barcode_results", "batch_print", "compression", "merge", "overlay",
         "compare", "office", "postscript", "text_conversion", "page_report", "spreadsheet", "organizer",
         "document_info", "print", "form", "ocr", "ocr_text", "blank", "crop", "interleave", "job", "split_plan",
         "page_selection", "insert", "split", "readme", "search_open", "encrypt", "decrypt", "shortcuts",
         "signature", "text_extractor", "undo", "palette", "deep_search", "diagnostics", "preferences", "update"]


def factories(doc, path, reader, settings, parent):
    commands = [Command("open", "Open PDF", "Ctrl+O", "File", lambda: None)]
    entries = [PagePlanEntry(f"current-{i}", "current", i) for i in range(3)]
    return dict(zip(NAMES, [
        lambda: WatermarkDialog(3, 0), lambda: BarcodeScanDialog(path), lambda: BarcodeResultsDialog([]),
        BatchPrintDialog, lambda: CompressionDialog(path), MergePDFDialog, lambda: OverlayDialog(path),
        lambda: ComparisonDialog(("Sample", lambda: doc.tobytes(), lambda: 0), []),
        OfficeConversionDialog, PostScriptConversionDialog, TextConversionDialog, PageCountReportDialog,
        SpreadsheetMergeDialog, lambda: VisualOrganizerDialog(doc), lambda: DocumentInfoDialog(doc, path),
        lambda: PrintOptionsDialog(3, 0), lambda: FormDialog(doc.tobytes()), lambda: OCRDialog(path, 3, 0),
        lambda: OCRTextResultDialog(OCRResult(OCRMode.EXTRACT_TEXT, (0,), "Sample text")),
        lambda: BlankPagesDialog((595, 842)), lambda: CropDialog(entries, [0], reader),
        lambda: InterleaveDialog(entries[:1], entries[1:], reader), lambda: JobDialog("Preparing", lambda: None, None),
        lambda: SplitPlanDialog(entries), lambda: PageSelectionDialog("Delete", 3), lambda: InsertPagesDialog(3),
        lambda: SplitDialog(3, "sample"), ReadmeDialog, lambda: SearchOpenDialog(str(path.parent)),
        lambda: EncryptDialog(path), lambda: DecryptDialog(path), lambda: ShortcutsDialog(commands),
        SignatureAppearanceDialog, lambda: TextExtractorDialog(doc, 0, "sample.xlsx"),
        lambda: UndoHistoryDialog(["Rotate page"], []), lambda: CommandPalette(commands),
        lambda: DeepSearchDialog(str(path.parent)), DiagnosticsDialog,
        lambda: PreferencesDialog(settings, commands=commands), lambda: UpdateDialog(parent),
    ], strict=True))


@pytest.mark.parametrize("size", [(1280, 680), (1024, 700), (800, 560), (853, 440), (640, 440)])
@pytest.mark.parametrize("name", NAMES)
def test_dialog_screen_bounds_and_action_access(app, tmp_path, monkeypatch, size, name):
    import ui.responsive as responsive
    monkeypatch.setattr(responsive, "available_area", lambda widget: QRect(0, 0, *size))
    monkeypatch.delenv("PDFDOCUEDIT_UPDATE_ROOT", raising=False)
    settings = SettingsManager(tmp_path / "settings.json")
    settings.set("animations_enabled", False)
    parent = QWidget()
    parent.settings = settings
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page()
        path = tmp_path / "sample.pdf"
        doc.save(path)
        reader = PlanReader(doc)
        dialog = factories(doc, path, reader, settings, parent)[name]()
        try:
            dialog._animations_enabled = False
            dialog.show()
            app.processEvents()
            assert dialog.width() <= size[0] - 12, (name, dialog.size())
            assert dialog.height() <= size[1] - 40, (name, dialog.size())
            scroll = dialog._responsive_scroll
            assert scroll.viewport().height() > 40
            footer = dialog._responsive_footer
            if footer is not None:
                pos = footer.mapTo(dialog, QPoint(0, 0))
                assert pos.y() >= 0 and pos.y() + footer.height() <= dialog.height()
            # Every visible body action can be reached through scrollbars.
            for button in scroll.widget().findChildren(QPushButton):
                if button.isVisible() and button.width() <= scroll.viewport().width():
                    responsive.reveal_widget(button)
                    app.processEvents()
                    center = button.mapTo(scroll.viewport(), button.rect().center())
                    assert scroll.viewport().rect().contains(center), (name, button.text(), center)
        finally:
            dialog.close()
            if hasattr(dialog, "release_sources"):
                dialog.release_sources()
            if name == "form":
                dialog.release()
            dialog.deleteLater()
            app.processEvents()
            reader.close()
            parent.deleteLater()


@pytest.mark.parametrize("size", [(1024, 700), (800, 560), (853, 440), (640, 440)])
def test_main_window_controls_fit_small_screen(app, tmp_path, monkeypatch, size):
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLineEdit

    import core.viewer as viewer_module
    import ui.responsive as responsive
    settings = SettingsManager(tmp_path / "main-settings.json")
    settings.set("animations_enabled", False)
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    monkeypatch.setattr(responsive, "available_area", lambda widget: QRect(0, 0, *size))
    window = viewer_module.PDFViewer()
    try:
        window.show()
        app.processEvents()
        assert window.width() <= size[0] - 12, window.size()
        assert window.height() <= size[1] - 40, window.size()
        for bar in (window.command_bar, window.bottom_bar):
            for widget in bar.findChildren(QWidget):
                if isinstance(widget, (QAbstractButton, QComboBox, QLineEdit)) and widget.isVisible():
                    rect = QRect(widget.mapTo(bar, QPoint(0, 0)), widget.size())
                    assert bar.rect().contains(rect), (type(widget).__name__, widget.objectName(), rect, bar.size())
        assert window.workspace.width() >= 150
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_analysis_tabs_and_context_options_remain_scrollable(app):
    from PyQt6.QtWidgets import QAbstractButton, QScrollArea

    from ui.analysis_panel import AnalysisPanel
    from ui.context_panel import ContextPanel
    from ui.responsive import reveal_widget
    analysis = AnalysisPanel()
    analysis.resize(400, 280)
    analysis.show()
    context = ContextPanel()
    context.set_animations_enabled(False)
    context.resize(360, 280)
    try:
        for index in range(analysis.tabs.count()):
            analysis.tabs.setCurrentIndex(index)
            app.processEvents()
            scroll = analysis.tabs.widget(index)
            assert isinstance(scroll, QScrollArea)
            for button in scroll.widget().findChildren(QAbstractButton):
                if button.isVisible():
                    reveal_widget(button)
                    app.processEvents()
                    assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), button.rect().center()))
        for key in ("rotate", "delete", "extract", "split", "insert", "sort"):
            context.show_tool(key, key.title())
            context.show()
            app.processEvents()
            assert any(scroll.widget() is context._stack for scroll in context.findChildren(QScrollArea))
    finally:
        analysis.close()
        context.close()
        analysis.deleteLater()
        context.deleteLater()
        app.processEvents()


def test_dialog_reopen_and_changed_screen_preserve_single_scroll_shell(app, monkeypatch):
    import ui.responsive as responsive
    area = QRect(1000, 100, 800, 560)
    monkeypatch.setattr(responsive, "available_area", lambda widget: area)
    dialog = CompressionDialog(None)
    dialog.move(-5000, -5000)
    dialog.show()
    app.processEvents()
    assert area.contains(dialog.frameGeometry())
    original_scroll = dialog._responsive_scroll
    dialog.hide()
    area.setSize(QRect(0, 0, 640, 440).size())
    dialog.show()
    app.processEvents()
    assert dialog._responsive_scroll is original_scroll
    assert area.contains(dialog.frameGeometry())
    dialog.close()
    dialog.deleteLater()


def test_inline_validation_is_revealed_below_long_form(app, monkeypatch):
    import ui.responsive as responsive
    monkeypatch.setattr(responsive, "available_area", lambda widget: QRect(0, 0, 640, 440))
    dialog = CompressionDialog(None)
    dialog._animations_enabled = False
    dialog.show()
    app.processEvents()
    dialog.show_error("Choose a valid input PDF before continuing.")
    app.processEvents()
    app.processEvents()
    scroll = dialog._responsive_scroll
    assert scroll.viewport().rect().contains(dialog._validation.mapTo(scroll.viewport(), dialog._validation.rect().center()))
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("size", [(800, 560), (640, 440)])
def test_loaded_document_panels_use_real_width_and_preserve_toolbox_preference(app, tmp_path, monkeypatch, size):
    import core.viewer as viewer_module
    import ui.responsive as responsive
    settings = SettingsManager(tmp_path / "panels-settings.json")
    settings.set("animations_enabled", False)
    settings.set("left_panel_collapsed", False)
    monkeypatch.setattr(viewer_module, "SettingsManager", lambda: settings)
    monkeypatch.setattr(responsive, "available_area", lambda widget: QRect(0, 0, *size))
    source = tmp_path / "panel.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    window = viewer_module.PDFViewer()
    monkeypatch.setattr(window, "_run_analysis_request", lambda *args: None)
    try:
        window._load_file_sync(str(source))
        window.show()
        app.processEvents()
        window.show_document_info()
        app.processEvents()
        assert window.side_panel.is_collapsed()
        assert not settings.get("left_panel_collapsed")
        assert window._session.tab_widget.sizes()[3] >= 300
        window._show_nav_tab("search")
        app.processEvents()
        assert window._session.tab_widget.sizes()[2] >= 300
        window._toggle_thumbnails()
        app.processEvents()
        assert window._session.tab_widget.sizes()[0] >= 200
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
    assert not settings.get("left_panel_collapsed")
