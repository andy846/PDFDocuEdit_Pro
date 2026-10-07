"""Edited, multi-page PDF templates reused for each customer record."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import fitz
import pytest

from composition.data.source import import_records
from composition.engine.renderer import render_preview
from composition.handoff import capture_template_pdf, detach_template_page
from composition.overlay.qc import check_mark
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, SequenceSpec, Template
from composition.template.serializer import load_project, save_project
from core.pdf_engine import PdfEngine


@pytest.fixture
def engine(tmp_path):
    path = tmp_path / "word-template.pdf"
    with fitz.open() as doc:
        for ordinal, size in enumerate(((595, 842), (420, 595), (612, 792)), 1):
            page = doc.new_page(width=size[0], height=size[1])
            page.insert_text((35, 45), f"Template background {ordinal}")
        doc.save(path)
    engine = PdfEngine()
    engine.open(path)
    yield engine
    engine.close()


def capture(engine, target, **kwargs):
    return capture_template_pdf(engine, target, (engine.document_id, engine.revision), **kwargs)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_capture_unsaved_crop_rotation_forms_and_vector_backgrounds(engine, tmp_path, rotation):
    original = Path(engine.original_path).read_bytes()
    engine.document[1].set_cropbox(fitz.Rect(10, 10, 400, 550))
    engine.rotate_pages([1], rotation)
    page = engine.document[0]
    annotation = page.add_freetext_annot(fitz.Rect(35, 65, 180, 95), "Edited note", fontsize=11)
    annotation.update()
    widget = fitz.Widget()
    widget.field_name = "Reference"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "Saved form appearance"
    widget.rect = fitz.Rect(35, 100, 220, 125)
    page.add_widget(widget)
    engine.mark_modified()
    captured = capture(engine, tmp_path / "handoff")
    model = Template(pages=captured.pages, source_link=captured.link)
    assert model.record_mode == "imported"
    assert len(captured.pages) == 3 and captured.link["page_map"] == [0, 1, 2]
    width, height = (540, 390) if rotation % 180 else (390, 540)
    assert captured.pages[1].width_mm == pytest.approx(width * 25.4/72)
    assert captured.pages[1].height_mm == pytest.approx(height * 25.4/72)
    for ordinal, spec in enumerate(captured.pages):
        with fitz.open(spec.background) as background:
            assert background.page_count == 1
            assert f"Template background {ordinal+1}" in background[0].get_text()
            assert not list(background[0].annots() or [])
            assert not list(background[0].widgets() or [])
            if ordinal == 0:
                assert "Edited note" in background[0].get_text()
                assert "Saved form appearance" in background[0].get_text()
            with fitz.open(stream=render_preview(model, {}, page_index=ordinal), filetype="pdf") as preview:
                assert preview[0].rect.width == pytest.approx(background[0].rect.width, abs=.01)
                assert preview[0].rect.height == pytest.approx(background[0].rect.height, abs=.01)
                # Background placement must keep rotated/cropped geometry, not merely text.
                assert preview[0].get_pixmap().samples == background[0].get_pixmap().samples
    assert Path(engine.original_path).read_bytes() == original
    assert engine.is_modified


def test_three_pages_two_customers_seq_reference_and_all_barcode_types(engine, tmp_path):
    captured = capture(engine, tmp_path / "handoff")
    data = tmp_path / "customers.csv"
    data.write_text("Name,Reference\nAlice,REF-001\nBob,REF-002\n", encoding="utf-8")
    model = Template(pages=captured.pages, source_link=captured.link, data=DataConfig(path=str(data)),
                     sequences=[SequenceSpec("Seq", padding=6), SequenceSpec("PageSeq", scope="page", padding=3)])
    for index, page in enumerate(model.pages):
        page.elements = [
            Element(value="{{Name}} / {{Reference}} / {{Seq}} / {{PageSeq}}", y_mm=55,
                    width_mm=110, font=FontSpec(family="Noto Sans")),
            Element(type=("code128", "i25", "qr")[index], value="{{Seq}}", x_mm=25, y_mm=85,
                    width_mm=80 if index < 2 else 35, height_mm=22 if index < 2 else 35),
        ]
    store = import_records(model.data, tmp_path / "records.db")
    result = generate(ProductionJob(model.to_dict(), str(store.path), str(tmp_path / "output")))
    assert result.status == "completed", result.error
    assert result.input_records == result.successful_records == 2
    assert result.generated_pages == result.expected_pages == 6 and result.pages_per_record == 3
    with fitz.open(result.output_pdf) as pdf:
        for output_index, output in enumerate(pdf):
            record, template_page = divmod(output_index, 3)
            name = ("Alice", "Bob")[record]
            assert f"Template background {template_page+1}" in output.get_text()
            assert f"{name} / REF-00{record+1} / {record+1:06} / {output_index+1:03}" in output.get_text()
            barcode = model.pages[template_page].elements[1]
            scale = 72/25.4
            rect = (barcode.x_mm*scale, barcode.y_mm*scale,
                    (barcode.x_mm+barcode.width_mm)*scale, (barcode.y_mm+barcode.height_mm)*scale)
            assert check_mark(output, {"rect": rect, "symbology": barcode.type,
                                       "payload": f"{record+1:06}", "object": barcode.id})
    log = json.loads((Path(result.report_dir) / "job.json").read_text(encoding="utf-8"))
    assert log["pdf_source_link"]["template_page_map"] == captured.link["template_page_map"]
    assert log["page_mapping"]["pages_per_record"] == 3


def test_selected_pages_roundtrip_asset_move_and_page_id_mapping(engine, tmp_path):
    captured = capture(engine, tmp_path / "handoff", pages=[2, 0, 2])
    model = Template(pages=list(reversed(captured.pages)), source_link=captured.link)
    assert captured.link["page_map"] == [0, 2]
    saved = save_project(model, tmp_path / "project" / "customer.pdcx")
    shutil.rmtree(tmp_path / "handoff")
    engine.close()
    Path(tmp_path / "word-template.pdf").unlink()
    shutil.move(str(saved.parent), str(tmp_path / "relocated"))
    reopened = load_project(tmp_path / "relocated" / "customer.pdcx")
    assert reopened.template_version == 12
    first = reopened.pages[0]
    assert reopened.source_link["template_page_map"][first.id] == 2
    with fitz.open(stream=render_preview(reopened, {}), filetype="pdf") as pdf:
        assert "Template background 3" in pdf[0].get_text()
        assert "Template background 1" in pdf[1].get_text()


@pytest.mark.parametrize("mutation", ["missing_page", "empty_background", "duplicate_source", "unknown_source", "old_version"])
def test_invalid_mapping_and_v8_migration(engine, tmp_path, mutation):
    captured = capture(engine, tmp_path / "handoff")
    raw = Template(pages=captured.pages, source_link=captured.link).to_dict()
    mapping = raw["source_link"]["template_page_map"]
    if mutation == "missing_page":
        raw["pages"].pop()
    elif mutation == "empty_background":
        raw["pages"][0]["background"] = ""
    elif mutation == "duplicate_source":
        mapping[raw["pages"][1]["id"]] = 0
    elif mutation == "unknown_source":
        mapping[raw["pages"][0]["id"]] = 99
    else:
        raw["template_version"] = 8
    with pytest.raises(CompositionError):
        Template.from_dict(raw)
    old = Template().to_dict()
    old["template_version"] = 8
    assert Template.from_dict(old).template_version == 12


def test_detaching_one_background_preserves_other_page_mappings(engine, tmp_path):
    captured = capture(engine, tmp_path / "handoff")
    raw = Template(pages=captured.pages, source_link=captured.link).to_dict()
    removed = raw["pages"].pop(0)
    detach_template_page(raw, removed["id"])
    assert len(Template.from_dict(raw).source_link["template_page_map"]) == 2
    for page in raw["pages"]:
        detach_template_page(raw, page["id"])
    assert raw["source_link"] == {}


def test_cancel_stale_invalid_and_large_templates_leave_no_backgrounds(engine, tmp_path):
    folder = tmp_path / "cancel"
    cancelled = False
    def progress(done, total, message):
        nonlocal cancelled
        cancelled = done >= 1
    with pytest.raises(Exception, match="cancel|Cancel"):
        capture(engine, folder, progress=progress, is_cancelled=lambda: cancelled)
    assert not list(folder.glob("*.pdf"))
    identity = (engine.document_id, engine.revision)
    engine.rotate_pages([0], 90)
    with pytest.raises(CompositionError, match="changed before"):
        capture_template_pdf(engine, tmp_path / "stale", identity)
    for pages in ([], [1000]):
        with pytest.raises(CompositionError, match="no longer available"):
            capture(engine, tmp_path / "bad", pages=pages)
    for _ in range(98):
        engine.document.new_page()
    engine.mark_modified()
    with pytest.raises(CompositionError, match="at most 100"):
        capture(engine, tmp_path / "too-large")
    assert not list((tmp_path / "too-large").glob("*.pdf"))
