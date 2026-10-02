from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest
from PIL import Image
from pyzbar.pyzbar import ZBarSymbol, decode

from composition.engine.renderer import render_preview
from composition.overlay.generator import generate as generate_overlay
from composition.overlay.model import OverlayJob
from composition.template.model import (
    AlternativeContent,
    CompositionError,
    ConditionGroup,
    Element,
    ElementRules,
    RuleCondition,
    Template,
    required_fields,
)
from composition.template.serializer import load_project, save_project
from tests.composition.test_pdf_overlay_models import sample_spec
from tests.composition.test_production import job_for


def decoded_i25(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return [code.data.decode("ascii") for code in decode(image, symbols=[ZBarSymbol.I25])]


@pytest.mark.parametrize("payload,readable", [("000001", False), ("0000010103", True), ("00123456789012", False)])
def test_exact_payload_leading_zeros_and_vector_output(payload, readable):
    template = Template(elements=[Element(type="i25", value="{{Account}}", width_mm=100,
                                          height_mm=20, show_barcode_text=readable)])
    raw = render_preview(template, {"Account": payload})
    with fitz.open(stream=raw, filetype="pdf") as document:
        assert decoded_i25(document[0]) == [payload]
        assert not document[0].get_images()
        if readable:
            assert payload in document[0].get_text()


@pytest.mark.parametrize("payload,message", [
    ("12345", "even number"), ("AB1234", "digits 0-9"),
    ("\uff11\uff12\uff13\uff14\uff15\uff16", "digits 0-9"),
    ("12 3456", "digits 0-9"), ("", "empty"),
])
def test_invalid_payload_is_rejected_without_silent_padding(payload, message):
    template = Template(elements=[Element(type="i25", value="{{Account}}")])
    with pytest.raises(CompositionError, match=message):
        render_preview(template, {"Account": payload})


@pytest.mark.parametrize("width,height,readable,message", [
    (5, 20, False, "minimum module"), (100, 5, True, "too short"),
])
def test_minimum_module_and_readable_text_height(width, height, readable, message):
    template = Template(elements=[Element(type="i25", value="0000010103", width_mm=width,
                                          height_mm=height, show_barcode_text=readable)])
    with pytest.raises(CompositionError, match=message):
        render_preview(template, {})


def test_saved_template_keeps_variable_and_alternative_rule(tmp_path):
    element = Element(type="i25", value="{{Account}}", width_mm=100, height_mm=20)
    element.rules = ElementRules(alternative=AlternativeContent(
        when=ConditionGroup(conditions=[RuleCondition(field="Kind", value="alternate")]),
        value="{{AlternativeAccount}}"))
    template = Template(elements=[element])
    restored = load_project(save_project(template, tmp_path / "i25.pdcx"))
    assert required_fields(restored) == {"Account", "AlternativeAccount", "Kind"}
    raw = render_preview(restored, {"Account": "000001", "AlternativeAccount": "000002", "Kind": "alternate"})
    with fitz.open(stream=raw, filetype="pdf") as document:
        assert decoded_i25(document[0]) == ["000002"]


def test_data_production_keeps_font_preflight_and_counts(tmp_path):
    from composition.production.generator import generate
    job = job_for(tmp_path, values=["000001", "000002"], chunk=1)
    template = Template.from_dict(job.template)
    template.elements[0] = Element(type="i25", value="{{Name}}", width_mm=100,
                                   height_mm=20, show_barcode_text=True)
    job.template = template.to_dict()
    result = generate(job)
    assert result.status == "completed", result.error
    assert result.input_records == result.successful_records == result.generated_pages == 2
    with fitz.open(result.output_pdf) as document:
        assert [decoded_i25(page) for page in document] == [["000001"], ["000002"]]
        assert "000002" in document[1].get_text()


def test_overlay_reconciliation_and_exact_payload_report(tmp_path):
    spec = sample_spec(tmp_path)
    spec.objects[1].element.type = "i25"
    original = hashlib.sha256(Path(spec.source.path).read_bytes()).hexdigest()
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path / "output"), chunk_size=3))
    assert result.status == "completed", result.error
    assert result.generated_pages == result.copied_source_pages == 6
    assert result.successful_envelopes == 2
    assert result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == 6
    rows = [json.loads(line) for line in Path(result.report_dir, "barcodes.jsonl").read_text().splitlines()]
    assert [row["payload"] for row in rows] == [
        "0000010103", "0000010203", "0000010303", "0000020103", "0000020203", "0000020303"]
    assert all(row["symbology"] == "i25" for row in rows)
    assert hashlib.sha256(Path(spec.source.path).read_bytes()).hexdigest() == original


def test_designer_and_overlay_insert_actions(app, tmp_path, monkeypatch):
    from composition.designer.overlay_workspace import OverlayWindow
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_pdf_overlay_ui import finish
    from tests.composition.test_workspace import close_window

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    designer = CompositionWindow()
    try:
        designer.actions["insert_i25"].trigger()
        element = designer.template.elements[0]
        assert element.type == "i25" and len(element.value) % 2 == 0
        assert not designer.properties.barcode_group.isHidden()
        assert designer.properties.human.isEnabled()
        assert "even number" in designer.properties.barcode_hint.text()
    finally:
        close_window(designer)
    overlay = OverlayWindow()
    try:
        overlay.apply_spec(sample_spec(tmp_path).to_dict())
        overlay.actions["insert_i25"].trigger()
        obj = overlay.spec.objects[-1]
        assert obj.element.type == "i25" and obj.profile is not None
        assert obj.element.width_mm == 90 and obj.element.height_mm == 14
        assert overlay.properties.human.isEnabled()
    finally:
        finish(overlay)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
