"""Effective printable geometry, late driver changes, and margin origins."""

import fitz
import pytest
from PyQt6.QtCore import QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize
from PyQt6.QtPrintSupport import QPrinter

import ui.print_controller as module
from core.printing import PrintJob, PrintRenderSettings, place_print_image
from core.tasks import TaskCancelled
from core.viewer import PDFViewer
from tests.test_printing import app, wait_for
from ui.print_controller import PrintController


def choices():
    return {"paper": "PDF page size", "orientation": 0, "scale_mode": 0,
            "scale": 100, "center": True, "offset_x": 0, "offset_y": 0}


def printer(path):
    result = QPrinter(QPrinter.PrinterMode.HighResolution)
    result.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    result.setOutputFileName(str(path))
    result.setResolution(72)
    result.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    result.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    return result


def test_printable_origin_is_not_added_twice(tmp_path):
    app()
    device = printer(tmp_path / "margin.pdf")
    device.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter)
    settings = PDFViewer._print_render_settings(device, choices())
    assert not device.fullPage()
    assert settings.left == 0 and settings.top == 0


def test_fit_rejects_empty_target_area():
    from PyQt6.QtGui import QImage
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    with pytest.raises(ValueError, match="printable"):
        place_print_image(image, 100, 100, PrintRenderSettings(72, 0, 200, 0, 0, 0, 100, True, 0, 0))


@pytest.mark.parametrize("cancel", [False, True])
def test_controller_rechecks_area_after_begin_without_rerasterising(tmp_path, monkeypatch, cancel):
    app()
    source = tmp_path / "large.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=450 / 25.4 * 72, height=500 / 25.4 * 72)
        page.draw_rect(page.rect + (6, 6, -6, -6), color=(0, 0, 0), width=3)
        pdf.save(source)
    output = tmp_path / "printed.pdf"
    devices, observed, renders, finished = [], [], [], []
    def create(job, prepared):
        device = printer(output)
        PDFViewer._configure_print_layout(device, fitz.Rect(0, 0, *prepared.first_size), choices())
        devices.append(device)
        return device
    original_painter = module.QPainter
    def begin(device):
        device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        return original_painter(device)
    monkeypatch.setattr(module, "QPainter", begin)
    original_render = module.render_print_page
    def count(*args, **kwargs):
        renders.append(1)
        return original_render(*args, **kwargs)
    monkeypatch.setattr(module, "render_print_page", count)
    def confirm(device, before, after):
        observed.append((before.width, after.width))
        if cancel:
            raise TaskCancelled
    controller = PrintController([PrintJob(str(source), "test", "test")], create,
                                 lambda p: PDFViewer._print_render_settings(p, choices()),
                                 confirm_layout=confirm)
    controller.finished.connect(lambda *args: finished.append(args))
    controller.start()
    wait_for(lambda: bool(finished), timeout=15)
    assert observed == [(1276, 595)]
    assert len(renders) == 1
    assert finished == ([(0, 0, 0, True)] if cancel else [(1, 0, 0, False)])
    if output.exists():
        with fitz.open(output) as pdf:
            images = pdf[0].get_image_info()
            if cancel:
                assert not images
            else:
                assert len(images) == 1
                assert pdf[0].rect.contains(fitz.Rect(images[0]["bbox"]))
                assert pdf[0].rect.width == pytest.approx(595, abs=1)
    controller.deleteLater()


@pytest.mark.parametrize("mode,scale,expected_width", [(1, 100, 1275), (2, 40, 510)])
def test_actual_and_custom_scale_are_not_silently_changed_to_fit(mode, scale, expected_width):
    from PyQt6.QtGui import QImage
    image = QImage(900, 1000, QImage.Format.Format_RGB32)
    config = PrintRenderSettings(72, 595, 842, 0, 0, mode, scale, True, 0, 0)
    output, _, _ = place_print_image(image, 450 / 25.4 * 72, 500 / 25.4 * 72, config)
    assert output.width() == pytest.approx(expected_width, abs=1)


def test_pdf_output_margin_geometry_keeps_image_inside_printable_area(tmp_path):
    from PyQt6.QtGui import QPainter
    app()
    output = tmp_path / "margins.pdf"
    device = printer(output)
    device.setPageMargins(QMarginsF(10, 12, 15, 20), QPageLayout.Unit.Millimeter)
    with fitz.open() as pdf:
        page = pdf.new_page(width=450 / 25.4 * 72, height=500 / 25.4 * 72)
        painter = QPainter(device)
        PDFViewer._draw_print_page(painter, device, page, choices())
        painter.end()
    with fitz.open(output) as pdf:
        bounds = fitz.Rect(pdf[0].get_image_info()[0]["bbox"])
        assert bounds.x0 == pytest.approx(28, abs=1)
        assert bounds.x1 <= 595 - 42 + 1


def test_late_consent_is_scoped_and_actual_size_warning_remains(qt_application, tmp_path):
    from dataclasses import replace

    from ui.print_layout import PaperDecision, PrintLayoutPolicy
    calls = []
    def confirm(before, after, batch):
        calls.append((before, after, batch))
        return PaperDecision("use", remember=True)
    policy = PrintLayoutPolicy(None, batch=True, confirm_area=confirm)
    device = printer(tmp_path / "none.pdf")
    old = PrintRenderSettings(72, 1276, 1417, 0, 0, 1, 100, True, 0, 0)
    new = replace(old, width=595, height=842)
    policy.confirm_effective(device, old, new)
    policy.confirm_effective(device, old, new)
    assert len(calls) == 1 and new.scale_mode == 1
    policy.invalidate(device)
    policy.confirm_effective(device, old, new)
    assert len(calls) == 2
