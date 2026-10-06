import csv
from pathlib import Path

import fitz
import pytest

from composition.engine.barcode_profiles import BarcodeProfile
from composition.overlay.generator import generate as generate_overlay
from composition.overlay.model import EnvelopeSpec, OverlayJob, OverlayObject
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import Element, PageSpec, Template
from tests.composition.test_pdf_overlay_models import make_source


def template_for(pages=4, count=2, duplex=True):
    profile = BarcodeProfile.inserter().to_dict()
    return Template(pages=[PageSpec(id=f"page_{i}", elements=[Element(type="i25", width_mm=100, height_mm=14,
        barcode_profile=profile)]) for i in range(pages)], record_mode="generated", generated_count=count,
        media={"duplex": duplex})


@pytest.mark.parametrize("pages,total,marks", [(4, 8, 4), (3, 8, 4), (1, 4, 2)])
def test_template_duplex_decode_reconcile_and_audit(tmp_path, pages, total, marks):
    template = template_for(pages)
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), chunk_size=3))
    assert result.status == "completed", result.error
    assert result.generated_pages == total
    assert result.expected_barcodes == result.rendered_barcodes == result.decoded_barcodes == marks
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == marks and all(len(row["Payload"]) == 18 for row in rows)
    assert rows[0]["Output page"] == "1"
    assert rows[0]["EOG"] == ("1" if pages == 1 else "0")
    with fitz.open(result.output_pdf) as document:
        assert not document[1].get_drawings()


def test_template_preflight_missing_duplicate_size_and_data(tmp_path):
    for case in ("missing", "duplicate", "width", "data"):
        template = template_for()
        if case == "missing":
            template.pages[2].elements.clear()
        elif case == "duplicate":
            template.pages[0].elements.append(Element(type="i25", y_mm=50, width_mm=100,
                barcode_profile=BarcodeProfile.inserter().to_dict()))
        elif case == "width":
            template.pages[0].elements[0].width_mm = 20
        else:
            for element in template.all_elements():
                element.barcode_profile["customer_field"] = "MissingCustomer"
        result = generate(ProductionJob(template.to_dict(), "", str(tmp_path/case)))
        assert result.status == "failed" and not result.output_pdf
        assert result.generated_pages == 0 and result.error_record == 1
        assert "Barcode preflight" in result.error


def test_overlay_preset_uses_exact_physical_sheet_codes(tmp_path):
    path = make_source(tmp_path/"source.pdf", 8)
    settings = EnvelopeSettings(pages_per_envelope=4, duplex=True)
    barcode = OverlayObject(Element(type="i25", width_mm=100, height_mm=14), scope="front", control=True,
                            profile=BarcodeProfile.inserter())
    spec = EnvelopeSpec(inspect_source(path, settings), settings, [barcode], required_scope="front")
    result = generate_overlay(OverlayJob(spec.to_dict(), str(tmp_path/"output")))
    assert result.status == "completed", result.error
    assert result.expected_barcodes == result.decoded_barcodes == 4
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["Payload"] == "010100000000000008"
    assert rows[1]["Payload"] == "010200100000000004"
    assert [row["Sheet"] for row in rows] == ["1", "2", "1", "2"]


def test_1000_envelopes_real_decode_and_rollover(tmp_path):
    template = template_for(pages=1, count=1000, duplex=False)
    result = generate(ProductionJob(template.to_dict(), "", str(tmp_path), chunk_size=73))
    assert result.status == "completed", result.error
    assert result.generated_pages == result.decoded_barcodes == result.expected_barcodes == 1000
    with Path(result.report_dir, "barcodes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["Group sequence"] for row in rows[97:101]] == ["98", "99", "00", "01"]
    assert rows[-1]["Envelope"] == "1000" and rows[-1]["Group sequence"] == "00"
