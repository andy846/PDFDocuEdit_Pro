from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication, QDialog

from dialogs.barcode_dialogs import BarcodeResultsDialog, BarcodeScanDialog
from dialogs.batch_print_dialog import BatchPrintDialog
from dialogs.batch_tools import CompressionDialog, MergePDFDialog, OverlayDialog
from dialogs.conversion_dialogs import (
    OfficeConversionDialog,
    PostScriptConversionDialog,
    TextConversionDialog,
)
from dialogs.data_dialogs import PageCountReportDialog, SpreadsheetMergeDialog
from dialogs.document_dialogs import (
    DocumentInfoDialog,
    PrintOptionsDialog,
    VisualOrganizerDialog,
)
from dialogs.page_operations import InsertPagesDialog, PageSelectionDialog, SplitDialog
from dialogs.search_open_dialog import SearchOpenDialog
from dialogs.security_dialogs import DecryptDialog, EncryptDialog
from dialogs.text_extractor_dialog import TextExtractorDialog


def make_pdf(path: Path, pages: int = 2) -> Path:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 96), f"Detailed dialog page {index + 1}")
        document.save(path)
    return path


def test_detailed_tool_dialogs_construct(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-dialog-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    source = make_pdf(tmp_path / "sample.pdf")

    with fitz.open(source) as document:
        dialogs = [
            CompressionDialog(source),
            MergePDFDialog(),
            OverlayDialog(source),
            OfficeConversionDialog(),
            TextConversionDialog(),
            PostScriptConversionDialog(),
            PageCountReportDialog(),
            SpreadsheetMergeDialog(),
            DocumentInfoDialog(document, source),
            PrintOptionsDialog(document.page_count, 0),
            VisualOrganizerDialog(document),
            PageSelectionDialog("Extract", document.page_count),
            InsertPagesDialog(document.page_count),
            SplitDialog(document.page_count, source.stem),
            EncryptDialog(source),
            DecryptDialog(source),
            BarcodeScanDialog(source),
            BarcodeResultsDialog([]),
            TextExtractorDialog(document, 0, str(tmp_path / "text.xlsx")),
            SearchOpenDialog(str(tmp_path)),
            BatchPrintDialog(),
        ]
        for dialog in dialogs:
            assert dialog.windowTitle()
            assert dialog.minimumWidth() <= 960
            assert dialog.minimumHeight() <= 720
            dialog.close()
    app.processEvents()


def test_security_dialogs_normalize_extensions_and_block_open_source(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication(["pdfdocuedit-security-test"])
    source = make_pdf(tmp_path / "source.pdf")

    encrypt = EncryptDialog(source)
    encrypt.user_password.setText("secret")
    encrypt.confirm_password.setText("secret")
    encrypt.output.setText(str(tmp_path / "encrypted-copy"))
    encrypt._validate()
    assert encrypt.result() == QDialog.DialogCode.Accepted
    assert encrypt.details is not None
    assert str(encrypt.details["output"]).endswith("encrypted-copy.pdf")

    decrypt = DecryptDialog(source)
    decrypt.output.setText(str(tmp_path / "decrypted-copy"))
    decrypt._validate()
    assert decrypt.result() == QDialog.DialogCode.Accepted
    assert decrypt.output_path.endswith("decrypted-copy.pdf")

    blocked = EncryptDialog(source)
    blocked.user_password.setText("secret")
    blocked.confirm_password.setText("secret")
    blocked.output.setText(str(source))
    messages: list[str] = []
    blocked.show_error = messages.append  # type: ignore[method-assign]
    blocked._validate()
    assert messages and "new output file" in messages[0]
    assert blocked.details is None
    app.processEvents()


def test_visual_organizer_drag_reorders_pages(tmp_path: Path) -> None:
    """The Organize Pages tool must support animated thumbnail drag reorder."""
    from PyQt6.QtTest import QTest

    app = QApplication.instance() or QApplication(["pdfdocuedit-organizer-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    source = make_pdf(tmp_path / "organize.pdf", pages=4)

    with fitz.open(source) as document:
        dialog = VisualOrganizerDialog(document)
        dialog.show()
        app.processEvents()
        pages = dialog.pages

        def settle() -> None:
            """Finish pending animations deterministically (offscreen timers
            are not guaranteed to fire during QTest waits)."""
            for animation in list(pages._animations.values()):
                animation.stop()
            pages._animations.clear()
            pages._relayout()
            app.processEvents()

        emitted: list[bool] = []
        pages.orderChanged.connect(lambda: emitted.append(True))

        def widget_by_original(original: int):
            return next(w for w in pages._widgets if w.original_index == original)

        def target_in(widget, container_point):
            return widget.mapFrom(pages._container, container_point)

        try:
            # Press page 1 and drag it onto the lower half of page 4.
            first = widget_by_original(0)
            QTest.mousePress(first, Qt.MouseButton.LeftButton, pos=first.rect().center())
            target = widget_by_original(3).geometry().center()
            QTest.mouseMove(first, pos=target_in(first, target), delay=30)
            QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=target_in(first, target))
            settle()

            assert pages.order() == [1, 2, 3, 0]
            assert emitted == [True]

            # Drag page 4 (originally 3) before page 2 (originally 1).
            fourth = widget_by_original(3)
            QTest.mousePress(fourth, Qt.MouseButton.LeftButton, pos=fourth.rect().center())
            target = widget_by_original(1).geometry().topLeft()
            QTest.mouseMove(fourth, pos=target_in(fourth, target), delay=30)
            QTest.mouseRelease(fourth, Qt.MouseButton.LeftButton, pos=target_in(fourth, target))
            settle()

            assert pages.order() == [3, 1, 2, 0]

            # Rotating and removing selected pages keeps working on the grid.
            pages._set_selection([widget_by_original(1), widget_by_original(2)])
            pages.rotate_selected(90)
            assert pages.rotations() == {1: 90, 2: 90}
            pages._set_selection([widget_by_original(3)])
            assert pages.remove_selected() is True
            assert pages.order() == [1, 2, 0]

            # Pressing the real Apply button accepts the dialog with the new order.
            QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
            assert dialog.result() == QDialog.DialogCode.Accepted
            assert dialog.order == [1, 2, 0]
            assert dialog.rotations == {1: 90, 2: 90}
        finally:
            dialog.close()
    app.processEvents()


def test_text_conversion_dialog_output_folder_uses_path(tmp_path: Path) -> None:
    from dialogs.conversion_dialogs import TextConversionDialog

    app = QApplication.instance() or QApplication(["pdfdocuedit-textconv-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    dialog = TextConversionDialog()
    # The output folder must support .path() (browse and validation).
    assert dialog.output_folder.path() == ""
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello", encoding="utf-8")
    dialog.add_paths([str(text_file)])
    errors: list[str] = []
    dialog.show_error = errors.append  # type: ignore[method-assign]
    dialog._validate()
    assert errors and "output folder" in errors[0]
    dialog.close()
    app.processEvents()


def test_print_options_requires_a_printer(tmp_path: Path) -> None:
    from dialogs.document_dialogs import PrintOptionsDialog

    app = QApplication.instance() or QApplication(["pdfdocuedit-printoptions-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    dialog = PrintOptionsDialog(page_count=5, current_page=0)
    dialog.printer.clear()
    errors: list[str] = []
    dialog.show_error = errors.append  # type: ignore[method-assign]
    dialog._validate()
    assert errors and "No printer" in errors[0]
    assert dialog.details is None
    dialog.close()
    app.processEvents()


def test_print_dialogs_prefill_offsets_from_preferences(tmp_path: Path) -> None:
    from PyQt6.QtWidgets import QWidget

    from core.settings import SettingsManager
    from dialogs.batch_print_dialog import BatchPrintDialog
    from dialogs.document_dialogs import PrintOptionsDialog

    app = QApplication.instance() or QApplication(["pdfdocuedit-offset-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = SettingsManager(tmp_path / "settings.json")
    settings.set_print_offsets(1.0, 5.0, 2.0, 6.0)
    parent = QWidget()
    parent.settings = settings  # type: ignore[attr-defined]

    single = PrintOptionsDialog(page_count=3, current_page=0, parent=parent)
    assert single.offset_left.value() == 1.0
    assert single.offset_right.value() == 5.0
    assert single.offset_top.value() == 2.0
    assert single.offset_bottom.value() == 6.0
    single.printer.addItem("Fake Printer")
    single.printer.setCurrentText("Fake Printer")
    single._validate()
    assert single.details is not None
    assert single.details["offset_x"] == 1.0 - 5.0
    assert single.details["offset_y"] == 2.0 - 6.0
    single.close()

    batch = BatchPrintDialog(parent)
    assert batch.left.value() == 1.0
    assert batch.right.value() == 5.0
    assert batch.top.value() == 2.0
    assert batch.bottom.value() == 6.0
    batch.close()
    parent.deleteLater()
    app.processEvents()


def test_preferences_save_print_offsets(tmp_path: Path) -> None:
    from core.settings import SettingsManager
    from ui.diagnostics_dialog import PreferencesDialog

    app = QApplication.instance() or QApplication(["pdfdocuedit-prefs-offset-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = SettingsManager(tmp_path / "settings.json")
    dialog = PreferencesDialog(settings)
    dialog.offset_left.setValue(0.0)
    dialog.offset_right.setValue(5.0)
    dialog.offset_top.setValue(0.5)
    dialog.offset_bottom.setValue(4.5)
    dialog.accept()
    assert settings.get_print_offsets() == (0.0, 5.0, 0.5, 4.5)

    # A fresh dialog starts from the saved values.
    dialog2 = PreferencesDialog(settings)
    assert dialog2.offset_right.value() == 5.0
    assert dialog2.offset_bottom.value() == 4.5
    dialog2.close()
    app.processEvents()


def test_batch_print_dialog_layout_and_log(tmp_path: Path) -> None:
    from PyQt6.QtTest import QTest

    from dialogs.batch_print_dialog import BatchPrintDialog

    app = QApplication.instance() or QApplication(["pdfdocuedit-batchprint-test"])
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    source = make_pdf(tmp_path / "batch.pdf", pages=3)

    dialog = BatchPrintDialog()
    assert dialog.isModal() is False
    assert dialog.log.isReadOnly() is True
    assert dialog.start_button.text() == "Start Batch Print"

    dialog.add_paths([str(source)])
    assert dialog.total.text() == "1 PDFs · 3 pages"
    assert dialog.table.columnCount() == 8
    assert dialog.table.horizontalHeaderItem(5).text() == "Status"
    assert dialog.table.horizontalHeaderItem(6).text() == "Print date"
    assert dialog.table.horizontalHeaderItem(7).text() == "Print time"
    assert dialog.table.item(0, 1).text() == "batch.pdf"
    assert dialog.table.item(0, 2).text() == "3"
    assert dialog.table.item(0, 5).text() == "Pending"
    assert dialog.table.item(0, 6).text() == "—"
    assert dialog.table.item(0, 7).text() == "—"
    # Cached page counts: refreshing again must not re-open the PDF.
    opens = []
    import fitz as _fitz
    original_open = _fitz.open

    def counting_open(*args, **kwargs):
        opens.append(args[0] if args else None)
        return original_open(*args, **kwargs)

    import dialogs.batch_print_dialog as module
    module.fitz.open = counting_open
    dialog._refresh()
    module.fitz.open = original_open
    assert opens == []  # served from cache

    dialog.log_message("Hello print")
    assert "Hello print" in dialog.log.toPlainText()

    # Per-file status updates (legacy parity).
    dialog.set_file_status(str(source), "Printing page 1 of 3")
    assert dialog.table.item(0, 5).text() == "Printing page 1 of 3"
    dialog.mark_file_printed(str(source))
    assert dialog.table.item(0, 5).text() == "Done"
    assert dialog.table.item(0, 6).text() == datetime.now().strftime("%Y-%m-%d")
    assert dialog.table.item(0, 7).text()
    dialog.mark_file_error(str(source))
    assert dialog.table.item(0, 5).text() == "Error"
    dialog.set_file_status(str(source), "Printing page 1 of 3")
    dialog.mark_printing_as_error()
    assert dialog.table.item(0, 5).text() == "Error"

    # Header-click sorting reorders the file list (legacy parity).
    second = make_pdf(tmp_path / "alpha.pdf", pages=1)
    dialog.add_paths([str(second)])
    assert [Path(p).name for p in dialog.file_paths] == ["batch.pdf", "alpha.pdf"]
    dialog._sort_column(1)
    assert [Path(p).name for p in dialog.file_paths] == ["alpha.pdf", "batch.pdf"]
    dialog._sort_column(1)
    assert [Path(p).name for p in dialog.file_paths] == ["batch.pdf", "alpha.pdf"]

    # Cancel is disabled while idle, enabled and reset while printing.
    assert not dialog.cancel_button.isEnabled()
    dialog.set_printing(True)
    assert not dialog.start_button.isEnabled()
    assert dialog.cancel_button.isEnabled()
    assert dialog.cancel_requested() is False
    dialog._cancel_request()
    assert dialog.cancel_requested() is True
    assert not dialog.cancel_button.isEnabled()
    dialog.set_printing(False)
    assert dialog.start_button.isEnabled()
    assert not dialog.cancel_button.isEnabled()
    assert dialog.cancel_requested() is False

    # Validation without a printer shows an error instead of emitting.
    # Windows always registers virtual printers, so only assert the
    # missing-printer path on systems that genuinely have none.
    from PyQt6.QtPrintSupport import QPrinterInfo

    errors: list[str] = []
    dialog.show_error = errors.append  # type: ignore[method-assign]
    if QPrinterInfo.availablePrinters():
        dialog._validate()
        assert errors == []
        assert dialog.details is not None
    else:
        dialog._validate()
        assert errors and "No printer" in errors[0]

    # With a (fake) printer, Start emits the details and keeps the dialog open.
    dialog.printer.addItem("Fake Printer")
    dialog.printer.setCurrentText("Fake Printer")
    emitted: list[bool] = []
    dialog.printRequested.connect(lambda details: emitted.append(True))
    QTest.mouseClick(dialog.start_button, Qt.MouseButton.LeftButton)
    assert emitted == [True]
    assert dialog.details is not None
    assert dialog.details["paths"] == [str(source), str(second)]
    assert dialog.details["printer"] == "Fake Printer"
    dialog.close()
    app.processEvents()
