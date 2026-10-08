"""Accepted device settings are retained and browsing does not unlock mutations."""
import fitz
import pytest
from PyQt6.QtCore import QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QDialog

import dialogs.batch_print_dialog as batch_module
from core.printing import PrintJob
from dialogs.batch_print_dialog import BatchPrintDialog
from dialogs.print_profile import printer_profile
from tests.test_printing import app, pdf, wait_for
from tests.test_search_page_actions import window_for


def device(tmp_path):
    app()
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "printed.pdf"))
    printer.setResolution(72)
    return printer


def test_preferences_accept_cancel_and_printer_change(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    dialog = BatchPrintDialog(window)
    dialog.printer.addItem("Test printer")
    dialog.printer.setCurrentText("Test printer")
    candidates = []

    def create(details):
        printer = device(tmp_path)
        candidates.append(printer)
        return printer

    monkeypatch.setattr(window.__class__, "_create_printer", staticmethod(create))

    class NativeDialog:
        accepted = True

        def __init__(self, printer, parent):
            self.printer = printer

        def setWindowTitle(self, title):
            pass

        def exec(self):
            self.printer.setCopyCount(5 if self.accepted else 99)
            self.printer.setResolution(150)
            self.printer.setColorMode(QPrinter.ColorMode.GrayScale)
            self.printer.setPageSize(QPageSize(QSizeF(160, 240), QPageSize.Unit.Millimeter, "Custom stock"))
            self.printer.setPageOrientation(QPageLayout.Orientation.Landscape)
            return QDialog.DialogCode.Accepted if self.accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(batch_module, "QPrintDialog", NativeDialog)
    monkeypatch.setattr(batch_module, "printer_profile",
                        lambda printer: {**printer_profile(printer), "printer": "Test printer"})
    try:
        dialog._printer_preferences()
        accepted = dialog.selected_printer
        assert accepted is candidates[0]
        assert dialog.copies.value() == 5
        assert dialog.colour.currentIndex() == 1
        assert dialog.orientation.currentIndex() == 2
        assert dialog.paper.currentText() == "Printer settings"
        NativeDialog.accepted = False
        dialog._printer_preferences()
        assert dialog.selected_printer is accepted and accepted.copyCount() == 5
        assert dialog.copies.value() == 5
        dialog.printer.addItem("Other printer")
        dialog.printer.setCurrentText("Other printer")
        assert dialog.selected_printer is None
        assert dialog.paper.currentText() == "PDF page size"
    finally:
        dialog.close()
        window.close()


def test_batch_retains_same_printer_custom_layout_and_manual_overrides(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    dialog = BatchPrintDialog(window)
    printer = device(tmp_path)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A5))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    dialog.selected_printer = printer
    dialog.selected_printer_profile = {"copies": 1, "dpi": 72}
    details = {
        "printer": "", "copies": 2, "collate": True, "colour": 1, "duplex": 1,
        "dpi": 72, "paper": "Printer settings", "orientation": 2,
        "scale_mode": 0, "scale": 100, "center": True, "offset_x": 0, "offset_y": 0,
    }
    seen = []
    original = window._print_render_settings

    def capture(current, choices):
        seen.append((current, current.pageLayout().pageSize().id(), current.copyCount()))
        return original(current, choices)

    monkeypatch.setattr(window, "_print_render_settings", capture)
    jobs = [PrintJob(str(pdf(tmp_path / f"input-{i}.pdf")), f"{i}.pdf", str(i)) for i in range(2)]
    try:
        window._start_print_jobs(jobs, details, dialog=dialog)
        wait_for(lambda: window._print_controller is None, timeout=15)
        assert len(seen) == 2
        assert all(value == (printer, QPageSize.PageSizeId.A5, 2) for value in seen)
        assert not window._printing and dialog.selected_printer is printer
    finally:
        dialog.close()
        window.close()


def test_print_browsing_switch_tabs_keeps_edit_actions_locked(tmp_path, monkeypatch):
    window = window_for(tmp_path, monkeypatch)
    first = window._open_in_new_tab_sync(str(pdf(tmp_path / "first.pdf")))
    second = window._open_in_new_tab_sync(str(pdf(tmp_path / "second.pdf")))
    original_tool = first.canvas.tool_mode
    try:
        with window._suspend_print_actions():
            assert window.workspace.isEnabled()
            assert not window.context_panel.isEnabled()
            assert not first.canvas.annotations_editable
            window.workspace.set_current_session(first)
            assert window.zoom_in_action.isEnabled()
            assert not window.save_action.isEnabled()
            assert not window.undo_action.isEnabled()
            window._run_shortcut_command("tool_image")
            assert first.canvas.tool_mode.value == "hand"
            window.close_document(first)
            assert first in window._sessions
            window.workspace.set_current_session(second)
            assert not window.undo_action.isEnabled()
        assert first.canvas.annotations_editable
        assert first.canvas.tool_mode == original_tool
    finally:
        window.close()


@pytest.mark.parametrize("orientation,width,height,expected", [
    (0, 200, 300, QPageLayout.Orientation.Portrait),
    (0, 300, 200, QPageLayout.Orientation.Landscape),
    (1, 300, 200, QPageLayout.Orientation.Portrait),
    (2, 200, 300, QPageLayout.Orientation.Landscape),
])
def test_custom_paper_preserved_with_orientation_overrides(tmp_path, orientation, width, height, expected):
    from core.viewer import PDFViewer

    printer = device(tmp_path)
    printer.setPageSize(QPageSize(QSizeF(160, 240), QPageSize.Unit.Millimeter, "Custom stock"))
    original = printer.pageLayout().pageSize()
    PDFViewer._configure_print_layout(printer, fitz.Rect(0, 0, width, height),
                                     {"paper": "Printer settings", "orientation": orientation})
    assert printer.pageLayout().pageSize() == original
    assert printer.pageLayout().orientation() == expected
