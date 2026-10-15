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
