"""Preserve source content when rotating; compare PDF resources and rendered pixels."""
from dataclasses import replace

import cv2
import fitz
import pytest
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QGroupBox
from pyzbar.pyzbar import decode

from core.page_plan import PagePlanEntry, PlanReader, export_plan
from core.pdf_engine import PdfEngine
from dialogs.document_dialogs import VisualOrganizerDialog


def fixture_pdf(path, offset=False):
    with fitz.open() as doc:
        page = doc.new_page(width=595.2756, height=841.8898)
        if offset:
            page.set_cropbox(fitz.Rect(10, 15, 585, 820))
        qr = cv2.QRCodeEncoder_create().encode("Organizer rotation: original QR preserved")
        png = cv2.imencode(".png", qr)[1].tobytes()
        page.insert_image(fitz.Rect(60, 60, 200, 200), stream=png)
        # EAN-13 5901234123457, drawn as fine vector bars (not an image).
        left = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
        parity = "LGGLLG"  # first digit 5
        bits = "101"
        for digit, kind in zip("901234", parity, strict=True):
            pattern = left[int(digit)]
            bits += pattern if kind == "L" else "".join("1" if c == "0" else "0" for c in reversed(pattern))
        bits += "01010"
        for digit in "123457":
            bits += "".join("1" if c == "0" else "0" for c in left[int(digit)])
        bits += "101"
        shape = page.new_shape()
        for i, bit in enumerate(bits):
            if bit == "1":
                shape.draw_rect(fitz.Rect(65 + i * 2, 250, 67 + i * 2, 305))
        shape.finish(color=None, fill=(0, 0, 0))
        shape.commit()
        page.insert_text((60, 340), "Original 4pt text: ABCxyz 0123456789", fontsize=4)
        page.draw_line((60, 360), (320, 361), width=.1)
        page.draw_circle((310, 80), 6, width=.2)
        on = doc.add_ocg("Original visible marks", on=True)
        off = doc.add_ocg("Hidden marks", on=False)
        page.insert_text((60, 400), "VISIBLE MARK", oc=on)
        page.insert_text((60, 440), "HIDDEN MARK", oc=off)
        note = page.add_freetext_annot(fitz.Rect(60, 470, 230, 500), "Original annotation", fontsize=8)
        note.update()
        field = fitz.Widget()
        field.field_name = "original-form"
        field.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        field.field_value = "Form appearance"
        field.rect = fitz.Rect(60, 530, 240, 555)
        page.add_widget(field)
        doc.save(path)


def decoded(page):
    pix = page.get_pixmap(dpi=180)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return {item.data for item in decode(image)}


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("offset", [False, True])
def test_rotation_keeps_streams_codes_small_text_and_appearances(tmp_path, rotation, offset, monkeypatch):
    path = tmp_path / "original.pdf"
    fixture_pdf(path, offset)
    engine = PdfEngine()
    engine.open(path)
    try:
        doc = engine.document
        before_streams = {i: doc.xref_stream_raw(i) for i in range(1, doc.xref_length()) if doc.xref_is_stream(i)}
        codes = decoded(doc[0])
        assert b"5901234123457" in codes
        assert b"Organizer rotation: original QR preserved" in codes
        with fitz.open(path) as reference:
            reference[0].set_rotation(rotation)
            expected = reference[0].get_pixmap(dpi=144)
            entry = PagePlanEntry("current-page", "current", 0, final_rotation=rotation)
            with PlanReader(doc) as reader:
                preview = reader.render(entry, max(expected.width, expected.height))
            preview_scale = max(expected.width, expected.height) / max(reference[0].rect.width, reference[0].rect.height)
            preview_expected = reference[0].get_pixmap(matrix=fitz.Matrix(preview_scale, preview_scale))
            assert preview.samples == preview_expected.samples

            def forbidden(*args, **kwargs):
                raise AssertionError("Rotation-only plans must not rebuild or copy pages")

            monkeypatch.setattr(fitz.Document, "select", forbidden)
            monkeypatch.setattr(fitz.Document, "insert_pdf", forbidden)
            with engine.mutation_transaction("Rotate original content"):
                engine.apply_page_plan([entry])
            assert before_streams == {i: doc.xref_stream_raw(i) for i in before_streams}
            assert doc[0].get_pixmap(dpi=144).samples == expected.samples
            assert decoded(doc[0]) == codes
            assert "Original 4pt text" in doc[0].get_text()
            assert len(list(doc[0].widgets())) == 1
            saved = engine.save(tmp_path / "saved.pdf")
            with fitz.open(saved) as opened:
                assert opened[0].get_pixmap(dpi=144).samples == expected.samples
                assert decoded(opened[0]) == codes
                assert before_streams == {i: opened.xref_stream_raw(i) for i in before_streams}
            result = export_plan(doc.tobytes(), [(tmp_path / "export.pdf", [entry])])
            assert not result.error
            with fitz.open(tmp_path / "export.pdf") as exported:
                assert exported[0].get_pixmap(dpi=144).samples == expected.samples
    finally:
        engine.close()


def test_preview_retains_optional_content_configuration(tmp_path):
    path = tmp_path / "layers.pdf"
    fixture_pdf(path)
    with fitz.open(path) as doc, PlanReader(doc) as reader:
        entry = PagePlanEntry("page", "current", 0)
        for rotation in (90, 0, 270, 180, 0):
            candidate = replace(entry, final_rotation=rotation)
            with fitz.open(path) as reference:
                reference[0].set_rotation(rotation)
                scale = 600 / max(reference[0].rect.width, reference[0].rect.height)
                expected = reference[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
                assert reader.render(candidate, 600).samples == expected.samples
        assert doc[0].rotation == 0


def test_landscape_paper_frame_dimensions_and_grouped_controls(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "a4.pdf"
    fixture_pdf(path)
    with fitz.open(path) as doc:
        dialog = VisualOrganizerDialog(doc)
        dialog.show()
        app.processEvents()
        assert dialog.windowTitle() == "Advanced Page Organizer"
        assert {g.title() for g in dialog.findChildren(QGroupBox)} >= {
            "Select pages", "Arrange pages", "Rotate / crop", "Add / replace", "Export copies"}
        dialog._select_expression("1")
        dialog._rotate_selected(90)
        widget = dialog.pages.selected_widgets()[0]
        assert widget._thumb.width() > widget._thumb.height()
        assert "297 × 210 mm" in widget._dimensions.text()
        dialog.pages._render_thumbnail(widget)
        assert widget._thumb.pixmap().width() > widget._thumb.pixmap().height()
        dialog._undo()
        assert widget._thumb.width() < widget._thumb.height()
        assert "210 × 297 mm" in widget._dimensions.text()
        # Narrow desktop layout must retain the footer and usable page area.
        dialog.resize(800, 720)
        app.processEvents()
        assert dialog.rect().contains(dialog.apply_button.mapTo(dialog, dialog.apply_button.rect().bottomRight()))
        assert dialog.height() <= 720
        assert dialog.pages.viewport().width() >= 300
        assert widget._thumb.alignment() == Qt.AlignmentFlag.AlignCenter
        dialog.reject()
