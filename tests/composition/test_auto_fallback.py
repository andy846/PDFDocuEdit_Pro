from __future__ import annotations

import csv
import json
from pathlib import Path

import fitz
import pytest

from composition.data.source import import_records
from composition.engine.fallback import AutoFallback
from composition.engine.renderer import render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, PageSpec, Template


def data(tmp_path, rows):
    path = tmp_path / "data.csv"
    path.write_text("Name\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return import_records(DataConfig(str(path)), tmp_path / "data.db")


def test_auto_keeps_primary_pixels_and_only_changes_missing_glyphs():
    template = Template(elements=[Element(value="Client {{Name}}", width_mm=150)])
    before = render_preview(template, {"Name": "Alice"})
    after = render_preview(template, {"Name": "Alice"}, auto_repair=True)
    with fitz.open(stream=before, filetype="pdf") as a, fitz.open(stream=after, filetype="pdf") as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples
    raw = render_preview(template, {"Name": "田"}, auto_repair=True)
    with fitz.open(stream=raw, filetype="pdf") as doc:
        spans = [s for block in doc[0].get_text("dict")["blocks"] for line in block["lines"] for s in line["spans"]]
        assert next(s for s in spans if "田" in s["text"])["font"].startswith("NotoSansCJK")
        assert next(s for s in spans if "Client" in s["text"])["font"].startswith("NotoSans-Regular")
    assert template.elements[0].font.family == "Noto Sans" and not template.elements[0].glyph_repairs
    with pytest.raises(CompositionError, match="U\\+7530"):
        render_preview(template, {"Name": "田"})


def test_auto_production_reports_exact_record_page_character_and_counts(tmp_path):
    store = data(tmp_path, ["Alice", "田田", "中文"])
    element = Element(value="{{Name}}", width_mm=150)
    template = Template(pages=[PageSpec(elements=[Element(value="Front")]), PageSpec(elements=[element])])
    before = template.to_dict()
    result = generate(ProductionJob(before, str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "completed", result.error
    assert result.generated_pages == 6 and result.successful_records == 3
    assert result.repaired_glyphs == result.font_scan["automatic_occurrences"] == 4
    assert result.repaired_records == 2
    assert result.font_scan["checked_records"] == 3 and result.font_scan["complete"]
    with Path(result.glyph_repair_report).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {r["Output page"] for r in rows} == {"4", "6"}
    assert {r["Template page"] for r in rows} == {"2"}
    assert {r["Character"] for r in rows} == {"田", "中", "文"}
    assert all(r["Mode"] == "Automatic" for r in rows)
    assert next(r["Occurrences"] for r in rows if r["Character"] == "田") == "2"
    with fitz.open(result.output_pdf) as doc:
        assert "田田" in doc[3].get_text() and "中文" in doc[5].get_text()
    assert template.to_dict() == before
    log = json.loads((Path(result.report_dir) / "job.json").read_text(encoding="utf-8"))
    assert log["auto_repair"] is True and log["font_scan"]["complete"]


def test_unresolved_font_scan_reports_all_records_in_one_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(AutoFallback, "select", lambda *args: None)
    store = data(tmp_path, ["田", "中中", "文"])
    template = Template(elements=[Element(value="{{Name}}")])
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "failed" and result.generated_files == 0
    assert result.font_scan["complete"] and result.font_scan["checked_records"] == 3
    assert result.font_scan["unresolved_occurrences"] == 4
    assert result.font_scan["unresolved_records"] == 3
    assert "checked all 3 records" in result.error
    with Path(result.glyph_repair_report).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {r["Record"] for r in rows} == {"1", "2", "3"}
    assert all(r["Mode"] == "Unresolved" for r in rows)
    assert not list((tmp_path / "out").rglob("*.pdf"))


def test_repeated_characters_discover_fallback_once_per_face(tmp_path, monkeypatch):
    original = AutoFallback.select
    seen = []
    def counted(self, char, primary):
        seen.append((char, primary.name))
        return original(self, char, primary)
    monkeypatch.setattr(AutoFallback, "select", counted)
    store = data(tmp_path, ["田田"] * 1000)
    template = Template(elements=[Element(value="{{Name}}")])
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "completed", result.error
    assert result.generated_pages == 1000 and result.repaired_glyphs == 2000
    assert seen == [("田", "Noto Sans Regular")]


def test_explicit_repairs_take_precedence_over_auto(tmp_path):
    store = data(tmp_path, ["田"])
    template = Template(elements=[Element(value="{{Name}}", vertical_align="center",
                        glyph_repairs={"U+7530": FontSpec(family="Noto Sans CJK HK", bold=True)})])
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "completed", result.error
    assert result.font_scan["automatic_occurrences"] == 0 and result.repaired_glyphs == 1
    with Path(result.glyph_repair_report).open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.DictReader(stream))["Mode"] == "Explicit"


def test_private_use_glyph_is_reported_for_review(tmp_path):
    store = data(tmp_path, ["\ue473"])
    template = Template(elements=[Element(value="{{Name}}", vertical_align="center")])
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "completed", result.error
    with Path(result.glyph_repair_report).open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["Code point"] == "U+E473" and row["Mode"] == "Automatic"
    assert "verify appearance" in row["Review note"] and "MingLiU" in row["Repair font"]


def test_invalid_primary_font_is_not_hidden_by_auto(tmp_path):
    store = data(tmp_path, ["田"])
    template = Template(elements=[Element(value="{{Name}}", font=FontSpec(file=str(tmp_path / "missing.ttf")))])
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out"), auto_repair=True))
    assert result.status == "failed" and "missing.ttf" in result.error


def test_designer_auto_preview_production_and_strict_switch(tmp_path):
    from PyQt6.QtWidgets import QApplication

    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_designer_controls import cleanup, wait
    app = QApplication.instance() or QApplication([])
    assert app is not None
    window = CompositionWindow()
    original_policy = window.auto_repair.isChecked()
    try:
        source = tmp_path / "source.csv"
        source.write_text("Name\n田\n中文\n", encoding="utf-8")
        window._start_import(DataConfig(str(source)))
        wait(lambda: window.import_worker is None and window.record_count == 2)
        window.add_element("text", "{{Name}}")
        primary = window.template.elements[0].font.family
        window.auto_repair.setChecked(False)
        window.tabs.setCurrentIndex(2)
        wait(lambda: "cannot render" in window.message.text())
        assert window.canvas.preview_item is None
        window.auto_repair.setChecked(True)
        wait(lambda: window.canvas.preview_item is not None)
        assert "glyph font substitution" in window.message.text()
        window.start_production(str(tmp_path / "production"))
        wait(lambda: window.production_worker is None)
        assert window.last_output and window.open_font_report_button.isEnabled()
        assert window.template.elements[0].font.family == primary
        report = json.loads((Path(window.last_output).parent / "job.json").read_text(encoding="utf-8"))
        assert report["auto_repair"] and report["generated_pages"] == 2
        assert report["font_scan"]["automatic_occurrences"] == 3
    finally:
        window.preferences.setValue("auto_glyph_repair", original_policy)
        cleanup(window)
