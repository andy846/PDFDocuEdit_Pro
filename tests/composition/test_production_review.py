import copy
import csv
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from composition.production.generator import generate
from composition.production.model import ProductionJob
from composition.review.service import create_review, preview_sheet, review_rows, validate_snapshot
from composition.template.model import CompositionError, DataConfig, Element, FontSpec, PageSpec, Template
from tests.composition.test_inserter_production import template_for
from tests.composition.test_pdf_overlay_models import make_source


def context(tmp_path, template):
    return {"kind": "template", "job": asdict(ProductionJob(template.to_dict(), "", str(tmp_path / "output"))),
            "label": "Review test"}


def check(tmp_path, template):
    result = create_review(tmp_path / "work", context(tmp_path, template))
    assert result["status"] == "checked", result["issues"]
    return result


def test_duplex_review_preview_matches_real_generation_and_decode(tmp_path):
    result = check(tmp_path, template_for(pages=3, count=2))
    assert (result["summary"]["pages"], result["summary"]["sheets"], result["summary"]["inserted_blanks"]) == (8, 4, 2)
    assert result["summary"]["expected_barcodes"] == 4
    rows = review_rows(tmp_path / "work", result["snapshot_id"], envelope=2)
    assert [p["job_sheet"] for p in rows["pages"]] == ["3", "3", "4", "4"]
    assert [p["blank"] for p in rows["pages"]] == [False, False, False, True]
    payloads = [b["payload"] for p in rows["pages"] for b in p["barcodes"]]
    assert [s[2:4] for s in payloads] == ["02", "03"]
    preview = preview_sheet(tmp_path / "work", result["snapshot_id"], 7)
    assert len(preview["images"]) == 2 and preview["images"][1]["page"]["blank"]
    assert all(Path(p["image"]).is_file() for p in preview["images"])
    assert not (tmp_path / "output").exists()
    assert not list((tmp_path / "work").rglob("*.pdf"))
    with pytest.raises(CompositionError, match="Acknowledge"):
        validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"])
    validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"], warnings_acknowledged=True)
    produced = generate(ProductionJob(**result["context"]["job"]))
    assert produced.status == "completed", produced.error
    assert produced.job_id == result["summary"]["job_id"]
    assert produced.generated_pages == result["summary"]["pages"]
    with Path(produced.report_dir, "barcodes.csv").open(encoding="utf-8-sig") as stream:
        decoded = list(csv.DictReader(stream))
    assert [r["Payload"] for r in decoded[2:]] == payloads


def test_pagination_search_and_sheet_rollover(tmp_path):
    result = check(tmp_path, template_for(pages=1, count=101, duplex=False))
    first = review_rows(tmp_path / "work", result["snapshot_id"])
    second = review_rows(tmp_path / "work", result["snapshot_id"], offset=50)
    assert first["total"] == 101 and len(first["rows"]) == len(second["rows"]) == 50
    assert second["rows"][0]["envelope"] == 51
    for number, expected in ((100, "9999"), (101, "0000")):
        page = review_rows(tmp_path / "work", result["snapshot_id"], envelope=number)["pages"][0]
        assert page["barcodes"][0]["payload"].startswith(expected)


def test_without_barcode_and_variable_output_identity(tmp_path):
    template = Template(pages=[PageSpec(elements=[Element(value="Hello")]), PageSpec()],
                        record_mode="generated", generated_count=2, media={"duplex": True})
    raw = context(tmp_path, template)
    raw["job"]["output_name"] = "{{job.id}}.pdf"
    result = create_review(tmp_path / "work", raw)
    assert result["status"] == "checked", result["issues"]
    assert result["summary"]["output_name"] == raw["job"]["job_id"] + ".pdf"
    assert result["summary"]["expected_barcodes"] == 0
    validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"])
    changed = copy.deepcopy(result["context"])
    changed["job"]["template"]["name"] = "Changed"
    with pytest.raises(CompositionError, match="Settings changed"):
        validate_snapshot(tmp_path / "work", result["snapshot_id"], changed)


def test_missing_front_barcode_is_blocked_without_publishing(tmp_path):
    template = template_for()
    template.pages[2].elements.clear()
    result = create_review(tmp_path / "work", context(tmp_path, template))
    assert result["status"] == "blocked" and not result["complete"]
    assert result["issues"][0]["severity"] == "error"
    assert result["issues"][0]["envelope"] == 1
    assert result["summary"]["pages"] == 8
    assert not (tmp_path / "output").exists()
    with pytest.raises(CompositionError, match="Complete"):
        validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"])


def test_cancel_retains_completed_rows_but_cannot_confirm(tmp_path):
    cancelled = False
    def progress(*_):
        nonlocal cancelled
        cancelled = True
    raw = context(tmp_path, Template(record_mode="generated", generated_count=220))
    result = create_review(tmp_path / "work", raw, progress=progress, is_cancelled=lambda: cancelled)
    assert result["status"] == "cancelled" and not result["complete"]
    assert not (tmp_path / "output").exists()
    with pytest.raises(CompositionError, match="Complete"):
        validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"])


def test_overlay_no_barcode_and_source_hash_change_with_identical_stat(tmp_path):
    from composition.overlay.model import EnvelopeSpec, OverlayJob
    from composition.pdf_source.model import EnvelopeSettings
    from composition.pdf_source.source import inspect_source
    source = make_source(tmp_path / "source.pdf", 6)
    settings = EnvelopeSettings(pages_per_envelope=3, duplex=True)
    spec = EnvelopeSpec(inspect_source(source, settings), settings)
    result = create_review(tmp_path / "work", {"kind": "overlay", "job": asdict(OverlayJob(spec.to_dict(), str(tmp_path / "output")))})
    assert result["status"] == "checked", result["issues"]
    assert result["summary"]["pages"] == 8
    assert result["summary"]["expected_barcodes"] == 0
    assert len(preview_sheet(tmp_path / "work", result["snapshot_id"], 7)["images"]) == 2
    stat = Path(source).stat()
    content = Path(source).read_bytes()
    Path(source).write_bytes(content.replace(b"%PDF-1.7", b"%PDF-1.6"))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(CompositionError, match="stale"):
        validate_snapshot(tmp_path / "work", result["snapshot_id"], result["context"])


def test_jump_large_envelope_pages_is_bounded(tmp_path):
    result = check(tmp_path, Template(pages=[PageSpec() for _ in range(72)], record_mode="generated", generated_count=1))
    rows = review_rows(tmp_path / "work", result["snapshot_id"], output_page=65)
    assert rows["envelope"] == 1 and rows["page_offset"] == 50
    assert rows["pages"][0]["output_page"] == 51 and len(rows["pages"]) == 22


@pytest.mark.parametrize("backend", ["canon_prismasync", "postscript"])
def test_media_pairs_and_blank_conflicts_follow_existing_plan(tmp_path, backend):
    from tests.composition.test_media_duplex_sheets import four_page_template
    template = four_page_template(backend)
    result = check(tmp_path, template)
    assert result["summary"]["backend"] == backend
    assert result["summary"]["stock_sheets"] == {"LH_A": 3, "LH_B": 3}
    rows = review_rows(tmp_path / "work", result["snapshot_id"], envelope=1)
    assert [p["stock"] for p in rows["pages"]] == ["LH_A", "LH_A", "LH_B", "LH_B"]
    assert not list(tmp_path.rglob("*.ps")) and not list(tmp_path.rglob("*.jdf"))
    template.media["assignments"]["2"] = "LH_B"
    result = create_review(tmp_path / "work", context(tmp_path, template))
    assert result["status"] == "blocked" and "same Stock" in result["issues"][0]["reason"]


def test_ten_thousand_records_checked_without_whole_pdf_or_gui_pages(tmp_path):
    result = check(tmp_path, Template(record_mode="generated", generated_count=10_000))
    assert result["summary"]["pages"] == 10_000
    rows = review_rows(tmp_path / "work", result["snapshot_id"], offset=9950)
    assert rows["total"] == 10_000 and len(rows["rows"]) == 50
    assert rows["rows"][-1]["envelope"] == 10_000
    assert not (tmp_path / "output").exists()
    assert not list((tmp_path / "work").rglob("*.pdf"))


def test_font_preflight_locates_record_and_reports_explicit_auto_repair(tmp_path):
    from composition.data.source import import_records
    from composition.engine.assets import asset_root
    source = tmp_path / "data.csv"
    source.write_text("Name\nAlice\n田\n", encoding="utf-8")
    data = DataConfig(path=str(source))
    store = import_records(data, tmp_path / "records.sqlite")
    element = Element(value="{{Name}}", font=FontSpec(family="Noto Sans", file=str(asset_root()/"fonts"/"NotoSans-Regular.ttf")))
    model = Template(elements=[element], data=data)
    raw = {"kind": "template", "job": asdict(ProductionJob(model.to_dict(), str(store.path), str(tmp_path / "out")))}
    failed = create_review(tmp_path / "work", raw)
    assert failed["status"] == "blocked"
    issue = failed["issues"][0]
    assert issue["envelope"] == 2 and issue["object_id"] == element.id and issue["field"] == "Name"
    raw["job"]["auto_repair"] = True
    result = create_review(tmp_path / "work", raw)
    assert result["status"] == "checked", result["issues"]
    assert result["summary"]["font_substitutions"] == 1
    assert Path(result["summary"]["font_report"]).is_file()
    assert not (tmp_path / "out").exists()
