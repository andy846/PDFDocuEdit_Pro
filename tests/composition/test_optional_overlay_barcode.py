from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QApplication

from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.generator import generate, reconcile
from composition.overlay.model import BarcodeProfile, EnvelopeSpec, OverlayJob, OverlayObject
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.template.model import Element
from tests.composition.test_pdf_overlay_models import make_source, sample_spec
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import wait_until


@pytest.mark.parametrize("kind", ["copy", "sequence", "non_control_barcode"])
def test_optional_barcode_production_16_pages_8_envelopes(tmp_path, monkeypatch, kind):
    source = make_source(tmp_path / "source.pdf", 16)
    settings = EnvelopeSettings(pages_per_envelope=2)
    objects = []
    if kind == "sequence":
        objects = [OverlayObject(Element(value="Envelope {{EnvelopeSeq}}", x_mm=20, y_mm=20))]
    elif kind == "non_control_barcode":
        objects = [OverlayObject(Element(type="code128", x_mm=20, y_mm=20, width_mm=90, height_mm=14),
                                 profile=BarcodeProfile(), control=False)]
    else:
        monkeypatch.setattr("composition.overlay.generator.check_mark",
                            lambda *a, **k: pytest.fail("No barcode must not invoke the decoder"))
    spec = EnvelopeSpec(inspect_source(source, settings), settings, objects)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert not spec.requires_control_barcode
    result = generate(OverlayJob(spec.to_dict(), str(tmp_path / "output"), chunk_size=4))
    assert result.status == "completed", result.error
    assert result.input_envelopes == result.successful_envelopes == 8
    assert result.generated_pages == result.copied_source_pages == 16
    assert result.failed_envelopes == result.unverified_envelopes == 0
    expected = 16 if kind == "non_control_barcode" else 0
    assert result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == expected
    reconcile(result)
    with fitz.open(result.output_pdf) as output:
        assert output.page_count == 16
        assert "Original Source Page 16" in output[15].get_text()
        if kind == "sequence":
            assert "Envelope 000008" in output[15].get_text()
    log = json.loads(Path(result.report_dir, "job.json").read_text(encoding="utf8"))
    assert log["control_barcode_required"] is False
    assert log["required_barcode_scope"] is None
    with Path(result.report_dir, "control.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.DictReader(stream))["control_barcode_required"] == "False"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_duplicate_control_barcodes_still_fail(tmp_path):
    spec = sample_spec(tmp_path)
    spec.objects.append(OverlayObject(Element(type="code128", x_mm=115, y_mm=35, width_mm=70, height_mm=14),
                                      control=True, profile=BarcodeProfile()))
    assert spec.requires_control_barcode
    result = generate(OverlayJob(spec.to_dict(), str(tmp_path / "output")))
    assert result.status == "failed"
    assert "found 2" in result.error
    assert not result.output_pdf and result.generated_files == 0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(app, monkeypatch):
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    window = OverlayWindow()
    yield window
    finish(window)


def test_new_source_starts_with_sequence_without_implicit_barcode(overlay, tmp_path):
    source = make_source(tmp_path / "input.pdf", 4)
    overlay.inspect_source(source, EnvelopeSettings(pages_per_envelope=2))
    wait_until(lambda: overlay.spec is not None and overlay.active_worker is None)
    assert len(overlay.spec.objects) == 1
    assert overlay.spec.objects[0].element.type == "text"
    assert not overlay.spec.requires_control_barcode
    assert not overlay.required_scope.isEnabled()
    assert not overlay.control.isEnabled()
    assert "Not required" in overlay.required_scope.toolTip()


def test_control_requirement_tracks_checkbox_delete_and_undo(overlay, tmp_path):
    overlay.apply_spec(sample_spec(tmp_path).to_dict())
    barcode = overlay.spec.objects[1].element.id
    overlay.canvas.select_ids([barcode])
    assert overlay.control.isEnabled() and overlay.required_scope.isEnabled()
    overlay.control.setChecked(False)
    assert not overlay.spec.requires_control_barcode
    assert not overlay.required_scope.isEnabled()
    overlay.undo.undo()
    assert overlay.spec.requires_control_barcode and overlay.required_scope.isEnabled()
    raw = overlay.spec.to_dict()
    raw["objects"] = raw["objects"][:1]
    assert overlay.commit(raw, "Delete control barcode")
    assert not overlay.spec.requires_control_barcode and not overlay.required_scope.isEnabled()
    overlay.undo.undo()
    assert overlay.spec.requires_control_barcode and overlay.required_scope.isEnabled()
