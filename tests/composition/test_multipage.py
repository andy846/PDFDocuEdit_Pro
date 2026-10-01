from __future__ import annotations

import copy
import csv
import json

import fitz
import pytest

from composition.data.source import import_records
from composition.engine.renderer import Renderer, render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, PageSpec, Template
from composition.template.serializer import load_project, save_project
from composition.worker import dispatch


def template():
    return Template(pages=[
        PageSpec(id="front", name="Statement", elements=[Element(value="Front {{Name}}", height_mm=20)]),
        PageSpec(id="back", name="Terms", width_mm=148, height_mm=210,
                 elements=[Element(value="Back {{Name}}", height_mm=20)]),
    ])


def job_for(tmp_path, model=None, count=4, chunk=3):
    source = tmp_path / "data.csv"
    source.write_text("Name\n"+"".join(f"Customer {i}\n" for i in range(count)), encoding="utf-8")
    store = import_records(DataConfig(path=str(source)), tmp_path / "records.db")
    return ProductionJob((model or template()).to_dict(), str(store.path), str(tmp_path / "output"),
                         chunk_size=chunk)


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_migration_preserves_layout_and_exact_fonts(version):
    old = {"template_version": version, "name": "Client",
           "width_mm": 215.9, "height_mm": 279.4, "background": "",
           "elements": [{"id": "client", "value": "{{Name}}",
                         "font": {"family": "Arial", "file": "exact.ttf", "size_pt": 12},
                         "glyph_repairs": {"U+E473": {"family": "Ming", "file": "repair.ttf"}}}]}
    before = copy.deepcopy(old)
    model = Template.from_dict(old)
    assert old == before
    assert len(model.pages) == 1 and model.pages[0].id == "page_1"
    assert model.width_mm == 215.9 and model.elements[0].font.file == "exact.ttf"
    assert model.elements[0].glyph_repairs["U+E473"].file == "repair.ttf"
    canonical = model.to_dict()
    assert canonical["template_version"] == 3
    assert "elements" not in canonical and "width_mm" not in canonical
    assert Template.from_dict(canonical).to_dict() == canonical


@pytest.mark.parametrize("change", ["empty", "too_many", "duplicate_page", "duplicate_object", "bounds", "ambiguous"])
def test_invalid_pages_rejected(change):
    raw = template().to_dict()
    if change == "empty":
        raw["pages"] = []
    elif change == "too_many":
        raw["pages"] = raw["pages"] * 51
    elif change == "duplicate_page":
        raw["pages"][1]["id"] = raw["pages"][0]["id"]
    elif change == "duplicate_object":
        raw["pages"][1]["elements"][0]["id"] = raw["pages"][0]["elements"][0]["id"]
    elif change == "bounds":
        raw["pages"][1]["elements"][0]["x_mm"] = 140
    elif change == "ambiguous":
        raw["elements"] = []
    with pytest.raises(CompositionError):
        Template.from_dict(raw)


def test_all_page_assets_roundtrip_and_backgrounds_remain_unchanged(tmp_path):
    model = template()
    originals = []
    for i, page in enumerate(model.pages):
        source = tmp_path / f"background-{i}.pdf"
        with fitz.open() as doc:
            background = doc.new_page(width=page.width_mm * 72/25.4, height=page.height_mm * 72/25.4)
            background.insert_text((20, 20), f"Background {i+1}")
            doc.save(source)
        originals.append((source, source.read_bytes()))
        page.background = str(source)
    project = save_project(model, tmp_path / "client.pdcx")
    for source, content in originals:
        assert source.read_bytes() == content
        source.unlink()
    loaded = load_project(project)
    assert loaded.to_dict()["pages"][1]["name"] == "Terms"
    with fitz.open(stream=render_preview(loaded, {"Name": "Alice"}), filetype="pdf") as doc:
        assert doc.page_count == 2
        for index, page in enumerate(doc):
            assert f"Background {index+1}" in page.get_text()
            assert "Alice" in page.get_text()


def test_preview_selected_page_uses_one_page_and_reports_original_index(tmp_path):
    model = template()
    result = dispatch({"task": "preview", "template": model.to_dict(), "page": 1,
                       "target": str(tmp_path/"preview.pdf")})
    assert result["page"] == 1
    with fitz.open(result["pdf"]) as doc:
        assert doc.page_count == 1
        assert "Back" in doc[0].get_text() and "Front" not in doc[0].get_text()
        assert doc[0].rect.width == pytest.approx(148*72/25.4, abs=.01)
    with pytest.raises(CompositionError, match="page number"):
        render_preview(model, {"Name": "Alice"}, page_index=2)


def test_production_order_counts_sizes_reports_and_chunk_bound(tmp_path, monkeypatch):
    model = template()
    model.pages.append(PageSpec(id="insert", name="Insert",
                                elements=[Element(value="Insert {{Name}}", height_mm=20)]))
    sizes = []
    original = Renderer.finalize
    def measured(self, document):
        sizes.append(document.page_count)
        original(self, document)
    monkeypatch.setattr(Renderer, "finalize", measured)
    result = generate(job_for(tmp_path, model, count=5, chunk=4))
    assert result.status == "completed", result.error
    assert result.successful_records == result.input_records == 5
    assert result.pages_per_record == 3 and result.expected_pages == result.generated_pages == 15
    assert max(sizes) <= 4+3-1
    with fitz.open(result.output_pdf) as doc:
        for record in range(5):
            for offset, label in enumerate(("Front", "Back", "Insert")):
                assert f"{label} Customer {record}" in doc[record*3+offset].get_text()
    report = json.loads((__import__("pathlib").Path(result.report_dir)/"job.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in report["page_mapping"]["template_pages"]] == ["front", "back", "insert"]
    with (__import__("pathlib").Path(result.report_dir)/"control.csv").open(encoding="utf-8-sig") as stream:
        control = next(csv.DictReader(stream))
    assert control["Expected Pages"] == "15" and control["Pages Per Record"] == "3"


def test_later_page_font_validation_and_explicit_repairs(tmp_path):
    model = template()
    model.pages[1].elements[0].value = "Repair \u7530"
    job = job_for(tmp_path, model)
    failure = generate(job)
    assert failure.status == "failed" and "Template page 2" in failure.error
    assert failure.successful_records == failure.generated_files == 0
    model.pages[1].elements[0].vertical_align = "center"
    primary = copy.deepcopy(model.pages[1].elements[0].font)
    model.pages[1].elements[0].glyph_repairs["U+7530"] = FontSpec(family="Noto Sans CJK HK")
    repaired = generate(ProductionJob(model.to_dict(), job.record_store, job.output_dir))
    assert repaired.status == "completed", repaired.error
    assert repaired.repaired_glyphs == repaired.repaired_records == 4
    assert model.pages[1].elements[0].font == primary
    with open(repaired.glyph_repair_report, encoding="utf-8-sig") as stream:
        assert {row["Template page"] for row in csv.DictReader(stream)} == {"2"}


def test_partial_record_failure_publishes_no_pdf(tmp_path):
    model = template()
    model.pages[1].elements[0].value = "This box is too short"
    model.pages[1].elements[0].height_mm = .1
    result = generate(job_for(tmp_path, model))
    assert result.status == "failed" and "template page 2" in result.error
    assert result.processed_records == result.failed_records == 1
    assert result.successful_records == result.generated_files == 0
    assert not list((tmp_path/"output").rglob("*.pdf"))


def test_cancel_after_completed_records_keeps_only_diagnostics(tmp_path):
    job = job_for(tmp_path, count=40)
    cancelled = False
    def progress(done, total, message):
        nonlocal cancelled
        if done == 25:
            cancelled = True
    result = generate(job, progress=progress, is_cancelled=lambda: cancelled)
    assert result.status == "cancelled" and result.successful_records == 25
    assert result.pages_per_record == 2 and result.expected_pages == 80
    assert result.generated_files == 0 and not list((tmp_path/"output").rglob("*.pdf"))

def test_cancel_between_pages_does_not_count_partial_record(tmp_path, monkeypatch):
    cancelled = False
    original = Renderer._render_element
    def stop_after_first_page(self, page, element, record):
        nonlocal cancelled
        original(self, page, element, record)
        cancelled = True
    monkeypatch.setattr(Renderer, "_render_element", stop_after_first_page)
    result = generate(job_for(tmp_path), is_cancelled=lambda: cancelled)
    assert result.status == "cancelled"
    assert result.processed_records == result.successful_records == result.failed_records == 0
    assert result.generated_files == 0 and not list((tmp_path/"output").rglob("*.pdf"))
