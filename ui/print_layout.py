"""GUI-thread paper negotiation shared by single and batch printing.

Capabilities describe a driver, never the stock physically loaded in a tray.
"""
import math
from dataclasses import dataclass

from PyQt6.QtCore import QSizeF
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo

from core.tasks import TaskCancelled


class PaperLayoutError(ValueError):
    pass


class PrintJobSkipped(Exception):
    pass


@dataclass(frozen=True)
class PaperCapabilities:
    sizes: tuple = ()
    custom: bool | None = None
    minimum: tuple | None = None
    maximum: tuple | None = None
    known: bool = False


@dataclass(frozen=True)
class PaperIssue:
    requested: QPageSize
    current: QPageSize
    reason: str


@dataclass(frozen=True)
class PaperDecision:
    action: str
    size: QPageSize | None = None
    remember: bool = False


def size_label(size):
    mm = size.size(QPageSize.Unit.Millimeter)
    return f"{size.name()} · {mm.width():.1f} × {mm.height():.1f} mm"


def paper_problem(size, capabilities):
    mm = size.size(QPageSize.Unit.Millimeter)
    if not size.isValid() or any(not math.isfinite(v) or v <= 0 for v in (mm.width(), mm.height())):
        return "The requested paper dimensions are invalid."
    if not capabilities.known:
        return "The driver paper capabilities are unavailable; confirm the output paper."
    if any(size.isEquivalentTo(other) for other in capabilities.sizes):
        return ""
    if capabilities.custom is not True:
        return "The driver does not report support for this paper size."
    if capabilities.minimum is None or capabilities.maximum is None:
        return "The custom paper limits are unavailable; confirm the output paper."
    w, h = sorted((mm.width(), mm.height()))
    low = sorted(capabilities.minimum)
    high = sorted(capabilities.maximum)
    if w < low[0] - .5 or h < low[1] - .5 or w > high[0] + .5 or h > high[1] + .5:
        return "The requested paper is outside the driver's custom paper limits."
    return ""


def read_capabilities(printer):
    if printer.outputFormat() == QPrinter.OutputFormat.PdfFormat:
        return PaperCapabilities(custom=True, minimum=(0, 0), maximum=(1e9, 1e9), known=True)
    info = QPrinterInfo.printerInfo(printer.printerName())
    if info.isNull():
        return PaperCapabilities()
    try:
        minimum = info.minimumPhysicalPageSize().size(QPageSize.Unit.Millimeter)
        maximum = info.maximumPhysicalPageSize().size(QPageSize.Unit.Millimeter)
        return PaperCapabilities(tuple(info.supportedPageSizes()), info.supportsCustomPageSizes(),
                                 (minimum.width(), minimum.height()), (maximum.width(), maximum.height()), True)
    except Exception:
        return PaperCapabilities()


def requested_size(printer, rect, details):
    paper = details["paper"]
    if paper == "Printer settings":
        return printer.pageLayout().pageSize()
    if paper == "PDF page size":
        width, height = sorted((rect.width, rect.height))
        return QPageSize(QSizeF(width, height), QPageSize.Unit.Point, "PDF page")
    standard = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3,
                "A5": QPageSize.PageSizeId.A5, "Letter": QPageSize.PageSizeId.Letter}
    if paper not in standard:
        raise PaperLayoutError("Choose a valid output paper size.")
    return QPageSize(standard[paper])


def apply_page_layout(printer, rect, details):
    requested = requested_size(printer, rect, details)
    if not requested.isValid():
        raise PaperLayoutError("The PDF paper dimensions are invalid.")
    if details["paper"] != "Printer settings":
        if printer.setPageSize(requested) is False or not printer.pageLayout().pageSize().isEquivalentTo(requested):
            raise PaperLayoutError("The printer did not accept the requested paper size.")
    orientation = int(details["orientation"])
    landscape = rect.width > rect.height if orientation == 0 else orientation == 2
    expected = QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    if printer.setPageOrientation(expected) is False or printer.pageLayout().orientation() != expected:
        raise PaperLayoutError("The printer did not accept the requested orientation.")


def geometry_problem(printer):
    layout = printer.pageRect(QPrinter.Unit.DevicePixel)
    actual = (printer.width(), printer.height())
    if any(v <= 0 for v in (*actual, layout.width(), layout.height())):
        return "The printer returned an invalid printable area."
    if abs(layout.width() - actual[0]) > 2 or abs(layout.height() - actual[1]) > 2:
        return "The driver layout and device printable area disagree; confirm the output paper."
    return ""


class PrintLayoutPolicy:
    def __init__(self, parent, *, batch=False, capabilities=None, choose=None, confirm_area=None):
        self.parent, self.batch = parent, batch
        self._provider = capabilities or read_capabilities
        self._choose = choose
        self._confirm_area = confirm_area
        self._caps, self._defaults, self._approved, self._areas = {}, {}, {}, set()
        self._log = None

    def invalidate(self, printer):
        self._caps.clear()
        self._approved.clear()
        self._areas.clear()
        self._defaults[id(printer)] = QPageLayout(printer.pageLayout())

    def configure(self, printer, rect, details, *, log=None):
        self._log = log
        default = self._defaults.setdefault(id(printer), QPageLayout(printer.pageLayout()))
        name = printer.printerName()
        if name not in self._caps:
            self._caps[name] = self._provider(printer)
        capabilities = self._caps[name]
        requested = requested_size(printer, rect, details)
        reason = paper_problem(requested, capabilities)
        if not reason:
            try:
                apply_page_layout(printer, rect, details)
                reason = geometry_problem(printer)
            except PaperLayoutError as exc:
                reason = str(exc)
        if reason:
            mm = requested.size(QPageSize.Unit.Millimeter)
            margins = default.margins(QPageLayout.Unit.Point)
            key = (name, round(mm.width(), 2), round(mm.height(), 2), int(details["orientation"]),
                   rect.width > rect.height, details.get("scale_mode"), details.get("dpi"),
                   default.pageSize().sizePoints().width(), default.pageSize().sizePoints().height(),
                   margins.left(), margins.top(), margins.right(), margins.bottom(), reason)
            decision = self._approved.get(key)
            choices = [default.pageSize()]
            for size in capabilities.sizes:
                if not any(size.isEquivalentTo(existing) for existing in choices):
                    choices.append(size)
            if decision is None:
                issue = PaperIssue(requested, default.pageSize(), reason)
                if self._choose is None:
                    from dialogs.print_paper_dialog import choose_paper
                    decision = choose_paper(self.parent, issue, choices, self.batch)
                else:
                    decision = self._choose(issue, choices, self.batch)
            if decision.action == "skip" and self.batch:
                raise PrintJobSkipped("Paper selection was skipped by the operator.")
            if decision.action != "use":
                raise TaskCancelled
            if decision.size is None or not any(decision.size.isEquivalentTo(s) for s in choices):
                raise PaperLayoutError("Choose one of the reported output paper sizes.")
            selected = QPageLayout(default)
            selected.setPageSize(decision.size)
            if printer.setPageLayout(selected) is False:
                raise PaperLayoutError("The printer did not accept the confirmed output paper.")
            apply_page_layout(printer, rect, {**details, "paper": "Printer settings"})
            remaining = geometry_problem(printer)
            if remaining:
                raise PaperLayoutError(remaining + " Reopen Printer Preferences before retrying.")
            if self.batch and decision.remember:
                self._approved[key] = decision
            if log:
                log(f"Paper confirmed: {size_label(requested)} → {size_label(decision.size)}. {reason}")
        elif log:
            log(f"Output paper: {size_label(printer.pageLayout().pageSize())}.")

    def confirm_effective(self, printer, before, after):
        old = (before.width, before.height, before.dpi, before.left, before.top)
        new = (after.width, after.height, after.dpi, after.left, after.top)
        if all(abs(a-b) <= 1 for a, b in zip(old, new, strict=True)):
            return
        key = (printer.printerName(), old, new, after.scale_mode, after.scale, after.center,
               after.offset_x, after.offset_y)
        if key in self._areas:
            return
        if self._confirm_area is None:
            from dialogs.print_paper_dialog import confirm_area
            decision = confirm_area(self.parent, before, after, self.batch)
        else:
            decision = self._confirm_area(before, after, self.batch)
        if decision.action == "skip" and self.batch:
            raise PrintJobSkipped("Changed printable area was skipped by the operator.")
        if decision.action != "use":
            raise TaskCancelled
        if self.batch and decision.remember:
            self._areas.add(key)
        if self._log:
            self._log(f"Driver printable area confirmed: {old[0]} × {old[1]} → {new[0]} × {new[1]} px; "
                      f"{after.dpi} dpi. Scaling uses the confirmed area.")
