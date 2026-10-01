from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from composition.data.source import import_records
from composition.engine.renderer import render_preview
from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, Template


def styled_data(tmp_path, font_family):
    path = tmp_path / (font_family.replace(" ", "-") + ".xlsx")
    book = Workbook()
    sheet = book.active
    sheet.append(["Name"])
    sheet.append(["Alice"])
    sheet.append(["田"])
    for row in sheet:
        for cell in row:
            cell.font = Font(name=font_family, size=24, bold=True)
    book.save(path)
    book.close()
    return import_records(DataConfig(str(path)), path.with_suffix(".db"))


@pytest.mark.parametrize("family", ["Noto Sans", "Noto Sans CJK HK"])
def test_excel_cell_fonts_do_not_override_template_preview_or_production(tmp_path, family):
    stores = [styled_data(tmp_path, name) for name in ("Arial", "Microsoft YaHei")]
    assert stores[0].record(2) == stores[1].record(2) == {"Name": "田"}
    template = Template(elements=[Element(value="{{Name}}", font=FontSpec(family=family))])
    if family == "Noto Sans":
        for store in stores:
            with pytest.raises(CompositionError, match="Template font: Noto Sans; PDF face: Noto Sans Regular"):
                render_preview(template, store.record(2))
            result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out")))
            assert result.status == "failed" and result.error_record == 2
            assert result.generated_files == result.generated_pages == 0
            assert "font file: NotoSans-Regular.ttf" in result.error
            assert "Imported data supplies values only" in result.error
            report = json.loads((Path(result.report_dir) / "job.json").read_text(encoding="utf-8"))
            assert report["template_fonts"][0]["primary"]["family"] == family
            assert "imported data fonts ignored" in report["font_policy"]
        return
    previews = [render_preview(template, store.record(2)) for store in stores]
    with fitz.open(stream=previews[0], filetype="pdf") as first, fitz.open(stream=previews[1], filetype="pdf") as second:
        assert first[0].get_pixmap().samples == second[0].get_pixmap().samples
        assert "田" in first[0].get_text()
        assert first[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]["font"].startswith("NotoSansCJK")
    for store in stores:
        result = generate(ProductionJob(template.to_dict(), str(store.path), str(tmp_path / "out")))
        assert result.status == "completed", result.error
        assert result.successful_records == result.generated_pages == 2
        with fitz.open(result.output_pdf) as doc:
            assert "田" in doc[1].get_text()
