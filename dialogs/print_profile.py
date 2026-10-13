"""Shared print-profile binding for single and batch print dialogs."""

from __future__ import annotations


def quality_changed(owner) -> None:
    dpi = owner.quality.currentData()
    custom = dpi is None
    owner.quality_dpi.setEnabled(custom)
    if not custom:
        owner.quality_dpi.setValue(int(dpi))


def selected_quality_dpi(owner) -> int:
    dpi = owner.quality.currentData()
    return owner.quality_dpi.value() if dpi is None else int(dpi)


def _offset(owner, key: str):
    control = getattr(owner, f"offset_{key}", None)
    return control if control is not None else getattr(owner, key)


def restore_print_profile(owner, profile: dict[str, object]) -> None:
    if not profile:
        return
    printer_index = owner.printer.findText(str(profile.get("printer", "")))
    if printer_index >= 0:
        owner.printer.setCurrentIndex(printer_index)
    owner.copies.setValue(int(profile.get("copies", 1)))
    owner.collate.setChecked(bool(profile.get("collate", True)))
    owner.colour.setCurrentIndex(int(profile.get("colour", 0)))
    owner.duplex.setCurrentIndex(int(profile.get("duplex", 0)))
    dpi = int(profile.get("dpi", 300))
    quality_index = owner.quality.findData(dpi)
    if quality_index >= 0:
        owner.quality.setCurrentIndex(quality_index)
    else:
        owner.quality.setCurrentIndex(owner.quality.count() - 1)
        owner.quality_dpi.setValue(dpi)
    owner.confirm_system.setChecked(bool(profile.get("confirm_system_dialog", False)))
    paper_index = owner.paper.findText(str(profile.get("paper", "PDF page size")))
    if paper_index >= 0:
        owner.paper.setCurrentIndex(paper_index)
    owner.orientation.setCurrentIndex(int(profile.get("orientation", 0)))
    owner.scale_mode.setCurrentIndex(int(profile.get("scale_mode", 0)))
    owner.scale.setValue(int(profile.get("scale", 100)))
    owner.center.setChecked(bool(profile.get("center", True)))


def collect_print_profile(owner) -> dict[str, object]:
    left = _offset(owner, "left").value()
    right = _offset(owner, "right").value()
    top = _offset(owner, "top").value()
    bottom = _offset(owner, "bottom").value()
    return {
        "printer": owner.printer.currentText(),
        "copies": owner.copies.value(),
        "collate": owner.collate.isChecked(),
        "colour": owner.colour.currentIndex(),
        "duplex": owner.duplex.currentIndex(),
        "dpi": selected_quality_dpi(owner),
        "paper": owner.paper.currentText(),
        "orientation": owner.orientation.currentIndex(),
        "scale_mode": owner.scale_mode.currentIndex(),
        "scale": owner.scale.value(),
        "center": owner.center.isChecked(),
        "offset_left": left,
        "offset_right": right,
        "offset_top": top,
        "offset_bottom": bottom,
        "offset_x": left - right,
        "offset_y": top - bottom,
        "confirm_system_dialog": owner.confirm_system.isChecked(),
    }


def printer_profile(printer):
    """Qt-exposed device choices; vendor settings stay in the QPrinter itself."""
    from PyQt6.QtGui import QPageLayout
    from PyQt6.QtPrintSupport import QPrinter
    return {
        "printer": printer.printerName(), "copies": printer.copyCount(),
        "collate": printer.collateCopies(), "dpi": printer.resolution(),
        "colour": 0 if printer.colorMode() == QPrinter.ColorMode.Color else 1,
        "duplex": {QPrinter.DuplexMode.DuplexNone: 1,
                   QPrinter.DuplexMode.DuplexLongSide: 2,
                   QPrinter.DuplexMode.DuplexShortSide: 3}.get(printer.duplex(), 0),
        "paper": "Printer settings",
        "orientation": 2 if printer.pageLayout().orientation() == QPageLayout.Orientation.Landscape else 1,
    }


def apply_printer_settings(printer, details, previous=None):
    from PyQt6.QtPrintSupport import QPrinter
    previous = previous or {}
    setters = {
        "dpi": lambda v: printer.setResolution(min(600, max(72, int(v)))),
        "copies": lambda v: printer.setCopyCount(int(v)),
        "collate": lambda v: printer.setCollateCopies(bool(v)),
        "colour": lambda v: printer.setColorMode(QPrinter.ColorMode.Color if int(v) == 0 else QPrinter.ColorMode.GrayScale),
        "duplex": lambda v: printer.setDuplex({1: QPrinter.DuplexMode.DuplexNone,
                                               2: QPrinter.DuplexMode.DuplexLongSide,
                                               3: QPrinter.DuplexMode.DuplexShortSide}[int(v)]) if int(v) else None,
    }
    for key, setter in setters.items():
        if key in details and details[key] != previous.get(key):
            setter(details[key])
