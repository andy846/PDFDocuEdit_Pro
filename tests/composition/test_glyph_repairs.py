from __future__ import annotations

import csv
import json

import fitz
import pytest

from composition.data.source import import_records
from composition.engine.renderer import render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, Template
from composition.template.serializer import load_project, save_project


def element(value="Latin {{Name}} end"):
    return Element(value=value, width_mm=170, height_mm=20, vertical_align="center",
                   glyph_repairs={"U+7530": FontSpec(family="Noto Sans CJK HK")})


def spans(raw):
    with fitz.open(stream=raw, filetype="pdf") as doc:
        return [span for block in doc[0].get_text("dict")["blocks"]
                for line in block.get("lines", []) for span in line["spans"]]


def test_only_missing_character_uses_repair_and_primary_pixels_are_unchanged():
    repaired = Template(elements=[element()])
    normal = Template.from_dict(repaired.to_dict())
    normal.elements[0].glyph_repairs.clear()
    before = render_preview(normal, {"Name": "Alice"})
    after = render_preview(repaired, {"Name": "Alice"})
    with fitz.open(stream=before, filetype="pdf") as a, fitz.open(stream=after, filetype="pdf") as b:
        assert a[0].get_pixmap().samples == b[0].get_pixmap().samples
    raw = render_preview(repaired, {"Name": "\u7530"})
    parts = spans(raw)
    assert next(span for span in parts if "\u7530" in span["text"])["font"].startswith("NotoSansCJK")
    assert all("CJK" not in span["font"] for span in parts if "\u7530" not in span["text"])
    assert len({round(span["origin"][1], 3) for span in parts}) == 1
    # A configured repair never replaces a glyph already supplied by the primary font.
    repaired.elements[0].glyph_repairs["U+0041"] = FontSpec(family="Noto Sans CJK HK")
    assert all("CJK" not in span["font"] for span in spans(render_preview(repaired, {"Name": "Alice"})))


def test_unmapped_or_incompatible_repair_still_blocks_output():
    template = Template(elements=[element()])
    with pytest.raises(CompositionError, match="U\\+9999"):
        render_preview(template, {"Name": "\u9999"})
    template.elements[0].glyph_repairs["U+7530"] = FontSpec()
    with pytest.raises(CompositionError, match="Configured repair font cannot render"):
        render_preview(template, {"Name": "\u7530"})


def test_v1_migration_and_portable_repair_font(tmp_path):
    from composition.engine.assets import asset_root
    template = Template.from_dict({"template_version": 1, "elements": [{"value": "{{Name}}"}]})
    assert template.template_version == 2
    assert not template.elements[0].glyph_repairs
    template.elements[0].glyph_repairs["U+7530"] = FontSpec(
        family="Noto Sans CJK HK", file=str(asset_root() / "fonts/NotoSansCJKhk-Regular.otf"))
    target = save_project(template, tmp_path/"repairs.pdcx")
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["template_version"] == 2
    assert not saved["elements"][0]["glyph_repairs"]["U+7530"]["file"].startswith(str(asset_root()))
    loaded = load_project(target)
    assert loaded.elements[0].glyph_repairs["U+7530"].file.startswith(str(tmp_path))
    assert loaded.elements[0].font.family == "Noto Sans"


@pytest.mark.parametrize("key", ["田", "U+110000", "U+D800", "U+07530", "U+e473"])
def test_invalid_repair_codepoints_rejected(key):
    raw = Template(elements=[element()]).to_dict()
    raw["elements"][0]["glyph_repairs"] = {key: FontSpec().__dict__}
    with pytest.raises(CompositionError):
        Template.from_dict(raw)


def test_streamed_production_audits_only_repaired_records(tmp_path):
    source = tmp_path/"data.csv"
    source.write_text("Name\nAlice\n\u7530\u7530\nBob\n", encoding="utf-8")
    config = DataConfig(str(source))
    store = import_records(config, tmp_path/"records.sqlite")
    template = Template(elements=[element()], data=config)
    result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path/"output")))
    assert result.status == "completed", result.error
    assert result.successful_records == result.generated_pages == 3
    assert result.repaired_glyphs == 2
    assert result.repaired_records == 1
    with open(result.glyph_repair_report, encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["Record"] == "2" and rows[0]["Code point"] == "U+7530"
    assert rows[0]["Occurrences"] == "2"
    with fitz.open(result.output_pdf) as doc:
        assert "\u7530\u7530" in doc[1].get_text()
    assert result.warnings
