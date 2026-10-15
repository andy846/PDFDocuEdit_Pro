"""Paper negotiation must require an explicit decision, never silent A4."""
import fitz
import pytest
from PyQt6.QtCore import QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtPrintSupport import QPrinter

from ui.print_layout import (
    PaperCapabilities,
    PaperDecision,
    PaperLayoutError,
    PrintLayoutPolicy,
    apply_page_layout,
    paper_problem,
)


def size(w, h):
    return QPageSize(QSizeF(w, h), QPageSize.Unit.Millimeter)


@pytest.fixture
def device(qt_application):
    printer = QPrinter()
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setResolution(72)
    return printer


def details(paper="PDF page size", orientation=0):
    return {"paper": paper, "orientation": orientation, "scale_mode": 0, "dpi": 72}


def caps():
    return PaperCapabilities(sizes=(size(210, 297),), custom=False, known=True)


def test_supported_standard_and_custom_bounds():
    assert not paper_problem(size(210, 297), caps())
    assert paper_problem(size(450, 500), caps())
    custom = PaperCapabilities(custom=True, minimum=(100, 150), maximum=(500, 600), known=True)
    assert not paper_problem(size(450, 500), custom)
    assert paper_problem(size(600, 700), custom)
    assert paper_problem(size(50, 100), custom)
    assert paper_problem(size(450, 500), PaperCapabilities())


def test_unsupported_paper_requires_confirmation_and_preserves_default(device):
    calls = []
    def choose(issue, choices, batch):
        calls.append((issue, choices, batch, device.pageLayout().pageSize()))
        return PaperDecision("use", choices[0], True)
    policy = PrintLayoutPolicy(None, batch=True, capabilities=lambda _: caps(), choose=choose)
    large = fitz.Rect(0, 0, 450 / 25.4 * 72, 500 / 25.4 * 72)
    policy.configure(device, large, details())
    policy.configure(device, large, details())
    assert len(calls) == 1
    assert calls[0][2] is True
    assert calls[0][3].id() == QPageSize.PageSizeId.A4
    assert device.pageLayout().pageSize().id() == QPageSize.PageSizeId.A4
    policy.invalidate(device)
    policy.configure(device, large, details())
    assert len(calls) == 2


def test_supported_large_size_is_not_silently_changed_to_a4(device):
    policy = PrintLayoutPolicy(None, capabilities=lambda _: PaperCapabilities(
        custom=True, minimum=(10, 10), maximum=(1000, 1000), known=True),
        choose=lambda *_: pytest.fail("Valid custom paper must not prompt"))
    policy.configure(device, fitz.Rect(0, 0, 450 / 25.4 * 72, 500 / 25.4 * 72), details())
    assert device.pageLayout().pageSize().size(QPageSize.Unit.Millimeter).width() == pytest.approx(450, abs=.5)


def test_setter_rejection_is_not_ignored(device, monkeypatch):
    monkeypatch.setattr(device, "setPageSize", lambda _: False)
    with pytest.raises(PaperLayoutError, match="accept"):
        apply_page_layout(device, fitz.Rect(0, 0, 300, 400), details())


def test_unknown_capability_requires_confirmation(device):
    calls = []
    def choose(issue, choices, batch):
        calls.append(issue.reason)
        return PaperDecision("use", choices[0])
    policy = PrintLayoutPolicy(None, capabilities=lambda _: PaperCapabilities(), choose=choose)
    policy.configure(device, fitz.Rect(0, 0, 300, 400), details())
    assert calls and "confirm" in calls[0].lower()


def test_single_printer_settings_choice_retains_custom_stock(device):
    device.setPageSize(size(160, 240))
    policy = PrintLayoutPolicy(None)
    policy.configure(device, fitz.Rect(0, 0, 900, 600), details("Printer settings", 2))
    assert device.pageLayout().pageSize().size(QPageSize.Unit.Millimeter).width() == pytest.approx(160, abs=.5)
    assert device.pageLayout().orientation() == QPageLayout.Orientation.Landscape


@pytest.mark.parametrize("action", ["cancel", "skip"])
def test_paper_decision_can_cancel_or_skip_without_changing_device(device, action):
    from core.tasks import TaskCancelled
    from ui.print_layout import PrintJobSkipped
    policy = PrintLayoutPolicy(None, batch=True, capabilities=lambda _: caps(),
                               choose=lambda *_: PaperDecision(action))
    with pytest.raises(TaskCancelled if action == "cancel" else PrintJobSkipped):
        policy.configure(device, fitz.Rect(0, 0, 1300, 1500), details())
    assert device.pageLayout().pageSize().id() == QPageSize.PageSizeId.A4


def test_batch_skip_preserves_next_file_and_does_not_start_skipped_output(tmp_path):
    from core.printing import PrintJob
    from core.viewer import PDFViewer
    from tests.test_printing import app, wait_for
    from ui.print_controller import PrintController
    app()
    paths = []
    for name, width, height in [("large", 1300, 1500), ("a4", 595, 842)]:
        path = tmp_path / (name + ".pdf")
        with fitz.open() as pdf:
            pdf.new_page(width=width, height=height)
            pdf.save(path)
        paths.append(path)
    policy = PrintLayoutPolicy(None, batch=True, capabilities=lambda _: caps(),
                               choose=lambda *_: PaperDecision("skip"))
    def create(job, prepared):
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(tmp_path / (job.name + "-printed.pdf")))
        printer.setResolution(72)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        policy.configure(printer, fitz.Rect(0, 0, *prepared.first_size), details())
        return printer
    result = []
    controller = PrintController([PrintJob(str(p), p.stem, p.stem) for p in paths], create,
                                 lambda p: PDFViewer._print_render_settings(p, {
                                     **details(), "scale":100, "center":True, "offset_x":0, "offset_y":0}))
    controller.finished.connect(lambda *v: result.append(v))
    controller.start()
    wait_for(lambda: bool(result), timeout=15)
    assert result == [(1, 0, 1, False)]
    assert not (tmp_path / "large-printed.pdf").exists()
    assert (tmp_path / "a4-printed.pdf").exists()
    controller.deleteLater()


def test_confirmation_dialog_explains_source_and_output_and_safe_cancel(qt_application):
    from PyQt6.QtWidgets import QLabel, QPushButton

    from dialogs.print_paper_dialog import PrintPaperDialog
    from ui.print_layout import PaperIssue
    issue = PaperIssue(size(450, 500), size(210, 297), "Driver limit", (450, 500), "Fit to printable area")
    dialog = PrintPaperDialog(issue, [size(210, 297)], True)
    try:
        text = " ".join(w.text() for w in dialog.findChildren(QLabel))
        assert "PDF page: 450.0" in text and "Scaling: Fit" in text
        assert "Requested paper:" in text and "previous setting:" in text
        assert any(b.isDefault() and b.text() == "Cancel batch" for b in dialog.findChildren(QPushButton))
        assert dialog.decision.action == "cancel"
    finally:
        dialog.close()
