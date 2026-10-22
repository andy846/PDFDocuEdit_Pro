"""Native/frozen GUI acceptance for existing PDF envelope overlays."""
from __future__ import annotations

import json
import time

import fitz
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.serializer import load_project
from composition.pdf_source.model import EnvelopeSettings


def wait(predicate, timeout=60):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    if not predicate():
        raise RuntimeError("PDF overlay smoke test timed out")


def run_overlay(output):
    output.mkdir(parents=True, exist_ok=True)
    source = output/"source.pdf"
    with fitz.open() as document:
        for index in range(60):
            page = document.new_page(width=595, height=842)
            page.insert_text((100, 230), f"Original source page {index+1}")
        document.save(source)
    window = OverlayWindow()
    window.show()
    window.inspect_source(source)
    wait(lambda: window.spec is not None and not window.active_worker)
    if len(window.spec.objects) != 1 or window.spec.requires_control_barcode:
        raise RuntimeError("New source must start with a sequence and no implicit control barcode")
    window.add_object("code128", x=20, y=35)
    window.control.setChecked(True)
    if not window.spec.requires_control_barcode:
        raise RuntimeError("Explicit control barcode was not enabled")
    window.add_object("qr", "EnvelopeSeq", x=120, y=65)
    window.envelope.setValue(20)
    window.print_page.setValue(3)
    wait(lambda: window.canvas.preview_item is not None)
    window.resize(1280, 820)
    QTest.qWait(100)
    window.grab().save(str(output/"overlay-design.png"))
    for width in (960, 760):
        window.resize(width, 640)
        QTest.qWait(100)
        for spin in (window.envelope, window.print_page):
            edit = spin.lineEdit()
            margins = edit.textMargins()
            available = edit.contentsRect().width()-margins.left()-margins.right()
            if edit.fontMetrics().horizontalAdvance(spin.text()) > available:
                raise RuntimeError("Envelope/page navigation text was clipped")
        window.grab().save(str(output/f"overlay-narrow-{width}.png"))
    target = output/"envelopes.pdcx"
    window.save_project(path=target)
    wait(lambda: not window.active_worker)
    if load_project(target).source.pages != 60:
        raise RuntimeError("Project source did not round-trip")
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    window.generate_pdf(output_dir=output/"simplex")
    wait(lambda: window.last_result is not None and not window.active_worker)
    simplex = window.last_result
    if simplex["status"] != "completed" or simplex["decoded_barcodes"] != 120:
        raise RuntimeError(str(simplex))
    window.inspect_source(source, EnvelopeSettings(duplex=True), preserve=True)
    wait(lambda: not window.active_worker)
    window.generate_pdf(output_dir=output/"duplex")
    wait(lambda: window.last_result is not None and not window.active_worker)
    duplex = window.last_result
    timer.stop()
    if duplex["status"] != "completed" or duplex["generated_pages"] != 80 or duplex["sheets"] != 40 or duplex["decoded_barcodes"] != 120:
        raise RuntimeError(str(duplex))
    if not ticks:
        raise RuntimeError("GUI did not process events during production")
    with fitz.open(duplex["output_pdf"]) as document:
        if "Original source page 60" not in document[78].get_text() or document[79].get_text():
            raise RuntimeError("Source ordering or blank back content changed")
    window.grab().save(str(output/"overlay-production.png"))
    window.undo.setClean()
    window.close()
    wait(lambda: not window.workers)
    summary = {"passed": True, "event_loop_ticks": len(ticks), "simplex": simplex, "duplex": duplex}
    (output/"result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
