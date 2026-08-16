"""Offscreen audit for text overflow across dialogs and panels.

Instantiates every dialog with a sample document and reports widgets whose
text does not fit their rendered width. Run with:

    .venv-pyqt6/bin/python scripts/audit_overflow.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableView,
    QToolButton,
    QWidget,
)

# Sandbox-safe settings locations.
settings_dir = tempfile.mkdtemp(prefix="pdfdocuedit-audit-")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir)

import core.settings as settings_module  # noqa: E402
import core.viewer as viewer_module  # noqa: E402

_original_settings_manager = settings_module.SettingsManager


def _make_settings(*args, **kwargs):
    if not args and not kwargs:
        return _original_settings_manager(Path(settings_dir) / "app-settings.json")
    return _original_settings_manager(*args, **kwargs)


settings_module.SettingsManager = _make_settings
viewer_module.SettingsManager = _make_settings

import ui.diagnostics_dialog as diagnostics_module  # noqa: E402

diagnostics_module.config_dir = lambda: Path(settings_dir) / "config"
diagnostics_module.log_dir = lambda: Path(settings_dir) / "logs"

from dialogs.barcode_dialogs import BarcodeResultsDialog, BarcodeScanDialog  # noqa: E402
from dialogs.batch_print_dialog import BatchPrintDialog  # noqa: E402
from dialogs.batch_tools import CompressionDialog, MergePDFDialog, OverlayDialog  # noqa: E402
from dialogs.conversion_dialogs import (  # noqa: E402
    OfficeConversionDialog,
    PostScriptConversionDialog,
    TextConversionDialog,
)
from dialogs.data_dialogs import PageCountReportDialog, SpreadsheetMergeDialog  # noqa: E402
from dialogs.document_dialogs import (  # noqa: E402
    DocumentInfoDialog,
    PrintOptionsDialog,
    VisualOrganizerDialog,
)
from dialogs.page_operations import InsertPagesDialog, PageSelectionDialog, SplitDialog  # noqa: E402
from dialogs.search_open_dialog import SearchOpenDialog  # noqa: E402
from dialogs.security_dialogs import DecryptDialog, EncryptDialog  # noqa: E402
from dialogs.text_extractor_dialog import TextExtractorDialog  # noqa: E402
from ui.deep_search_dialog import DeepSearchDialog  # noqa: E402
from ui.diagnostics_dialog import DiagnosticsDialog  # noqa: E402

PADDING = {
    QLabel: 0,
    QPushButton: 24,
    QToolButton: 20,
    QRadioButton: 30,
    QCheckBox: 28,
    QComboBox: 36,
    QLineEdit: 12,
    QSpinBox: 30,
    QDoubleSpinBox: 30,
}

ISSUES: list[str] = []


def check_widget(widget: QWidget, path: str) -> None:
    if not widget.isVisible() or widget.width() <= 0:
        return
    width = widget.width()
    fm = widget.fontMetrics()

    if isinstance(widget, QLabel):
        text = widget.text()
        if text and not widget.wordWrap():
            needed = fm.horizontalAdvance(text) + PADDING[QLabel]
            if needed > width:
                ISSUES.append(f"[QLabel] {path} text={text[:40]!r} width={width} needed={needed}")
        return

    if isinstance(widget, (QPushButton, QToolButton)):
        text = widget.text()
        if text:
            needed = fm.horizontalAdvance(text) + PADDING[type(widget)]
            if needed > width:
                ISSUES.append(f"[Button] {path} text={text[:40]!r} width={width} needed={needed}")
        return

    if isinstance(widget, (QRadioButton, QCheckBox)):
        text = widget.text()
        if text:
            needed = fm.horizontalAdvance(text) + PADDING[type(widget)]
            if needed > width:
                ISSUES.append(f"[Check] {path} text={text[:40]!r} width={width} needed={needed}")
        return

    if isinstance(widget, QComboBox):
        text = widget.currentText()
        if text:
            needed = fm.horizontalAdvance(text) + PADDING[QComboBox]
            if needed > width:
                ISSUES.append(f"[Combo] {path} text={text[:40]!r} width={width} needed={needed}")
        return

    if isinstance(widget, QLineEdit):
        # Editable fields scroll horizontally by design; only read-only
        # displays must fit their full text.
        if widget.isReadOnly():
            text = widget.displayText()
            if text:
                needed = fm.horizontalAdvance(text) + PADDING[QLineEdit]
                if needed > width:
                    ISSUES.append(f"[LineEdit] {path} text={text[:40]!r} width={width} needed={needed}")
        return

    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        needed = fm.horizontalAdvance(widget.text()) + PADDING[type(widget)]
        if needed > width:
            ISSUES.append(f"[Spin] {path} text={widget.text()!r} width={width} needed={needed}")
        return

    if isinstance(widget, QGroupBox):
        needed = fm.horizontalAdvance(widget.title()) + 12
        if needed > width:
            ISSUES.append(f"[GroupBox] {path} title={widget.title()!r} width={width} needed={needed}")
        return


def walk(widget: QWidget, prefix: str = "") -> None:
    for child in widget.findChildren(QWidget):
        if child.parentWidget() is not widget:
            continue
        path = f"{prefix}/{child.__class__.__name__}"
        if child.objectName():
            path += f"#{child.objectName()}"
        check_widget(child, path)
        walk(child, path)


def check_table(widget: QWidget, prefix: str) -> None:
    for table in widget.findChildren(QTableView):
        header = table.horizontalHeader()
        fm = table.fontMetrics()
        for column in range(table.model().columnCount()):
            header_text = table.model().headerData(column, Qt.Orientation.Horizontal)
            if not header_text:
                continue
            size = header.sectionSize(column)
            needed = fm.horizontalAdvance(str(header_text)) + 20
            if needed > size + 2:
                ISSUES.append(
                    f"[TableHeader] {prefix}/{table.__class__.__name__} col={column} "
                    f"header={header_text!r} size={size} needed={needed}"
                )


def main() -> int:
    app = QApplication.instance() or QApplication(["pdfdocuedit-audit"])
    # Match the real macOS UI font so measurements reflect on-screen widths.
    apple_font = QFont(".AppleSystemUIFont", 13)
    if QFontDatabase.families() and apple_font.family():
        app.setFont(apple_font)
    tmp = Path(tempfile.mkdtemp(prefix="pdfdocuedit-sample-"))

    sample = tmp / "sample.pdf"
    with fitz.open() as document:
        for index in range(3):
            page = document.new_page()
            page.insert_text((72, 96), f"Sample page {index + 1}")
        document.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 2]])
        document.save(sample)

    window = viewer_module.PDFViewer()
    window.resize(1200, 800)
    window.load_file(str(sample))
    app.processEvents()

    dialogs = [
        ("PageSelectionDialog", PageSelectionDialog("Delete", 3, window)),
        ("InsertPagesDialog", InsertPagesDialog(3, window)),
        ("SplitDialog", SplitDialog(3, "sample", window)),
        ("VisualOrganizerDialog", VisualOrganizerDialog(window.engine.document, window)),
        ("DocumentInfoDialog", DocumentInfoDialog(window.engine.document, sample, window)),
        ("PrintOptionsDialog", PrintOptionsDialog(3, 0, window)),
        ("BarcodeScanDialog", BarcodeScanDialog(sample, window)),
        ("BarcodeResultsDialog", BarcodeResultsDialog([{"file": "a.pdf", "page": 1, "value": "x"}], window)),
        ("BatchPrintDialog", BatchPrintDialog(window)),
        ("CompressionDialog", CompressionDialog(sample, window)),
        ("MergePDFDialog", MergePDFDialog(window)),
        ("OverlayDialog", OverlayDialog(sample, window)),
        ("OfficeConversionDialog", OfficeConversionDialog(window)),
        ("PostScriptConversionDialog", PostScriptConversionDialog(window)),
        ("TextConversionDialog", TextConversionDialog(window)),
        ("PageCountReportDialog", PageCountReportDialog(window)),
        ("SpreadsheetMergeDialog", SpreadsheetMergeDialog(window)),
        ("TextExtractorDialog", TextExtractorDialog(window.engine.document, 0, "out.xlsx", window)),
        ("SearchOpenDialog", SearchOpenDialog(str(tmp), window)),
        ("EncryptDialog", EncryptDialog(sample, window)),
        ("DecryptDialog", DecryptDialog(sample, window)),
        ("DeepSearchDialog", DeepSearchDialog(str(tmp), window)),
        ("DiagnosticsDialog", DiagnosticsDialog(window)),
    ]

    for name, dialog in dialogs:
        dialog.show()
        app.processEvents()
        check_table(dialog, name)
        walk(dialog, name)
        dialog.close()
        app.processEvents()

    # Main window chrome.
    walk(window, "MainWindow")
    check_table(window, "MainWindow")

    # Context panel pages (each option page).
    for key in ("rotate", "delete", "extract", "split", "insert", "sort"):
        window.context_panel.show_tool(key, key.title())
        app.processEvents()
        walk(window.context_panel, f"ContextPanel/{key}")
    window._hide_context()

    if ISSUES:
        print(f"{len(ISSUES)} potential overflow(s):")
        for issue in sorted(set(ISSUES)):
            print("  ", issue)
        return 1
    print("No text overflow detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
