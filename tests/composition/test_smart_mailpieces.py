from __future__ import annotations

from dataclasses import asdict

import fitz
import pytest

from composition.pdf_source.detection import DetectionConfig
from composition.pdf_source.smart_detection import (
    analyze_pdf,
    detect_index,
    scan_pdf,
    spatial_lines,
    teach_pdf,
)
from composition.template.model import CompositionError


class Index:
    def __init__(self, texts):
        self.texts = texts

    def metadata(self):
        return {"pages": len(self.texts)}

    def pages(self):
        for number, rows in enumerate(self.texts, 1):
            yield number, [{"text": text, "box": [10, y, 200, y+10]} for y, text in rows]


def cfg():
    return DetectionConfig(version=2, rules=[
        {"kind": "first_text", "terms": ["Dear"], "region_mm": [0, 8, 80, 8]},
        {"kind": "document_id", "fields": [{"label": "MPF Account No."}, {"label": "ORSO Account No."}]},
    ])


def letter(first, key="001"):
    return ([(30, "Dear customer")] if first else [(150, "Continuation Dear in body")]) + [
        (60, f"MPF Account No. : {key}"), (80, f"ORSO Account No. ： 00{key}")]


def fixture_pdf(path, offset=0, marker_shifts=False):
    with fitz.open() as pdf:
        for i, first in enumerate([True, False, True, False, False, True]):
            page = pdf.new_page()
            if first:
                page.insert_text((30, 70+(12*(0 if i<2 else 1 if i<5 else 2) if marker_shifts else 0)), "Dear customer")
            else:
                page.insert_text((30, 200), "Continuation Dear in body")
            key = "001" if i < 2 else "002" if i < 5 else "003"
            key = str(int(key)+offset).zfill(3)
            page.insert_text((30, 100), "MPF Account No.")
            page.insert_text((220, 100), ": " + key)
            page.insert_text((30, 120), "ORSO Account No.")
            page.insert_text((220, 120), ": 00" + key)
        pdf.save(path)
    return path


def test_spatial_join_separate_blocks_and_compound_ids():
    lines = spatial_lines([(10, 60, 90, 70, "Account No.", 0, 0), (180, 60, 220, 70, ": 0001", 1, 0)])
    assert lines[0]["text"] == "Account No. : 0001"
    result = detect_index(Index([letter(True), letter(False), letter(True, "002"), letter(False, "002")]), cfg())
    assert result["groups"] == [[1, 2], [3, 4]]
    assert not result["findings"]
    assert [e["end_basis"] for e in result["evidence"]] == ["next_start_inferred", "pdf_end_inferred"]
    assert "001" not in str(result)


def test_blank_pages_and_repeated_recipient_are_retained():
    result = detect_index(Index([letter(True), [], letter(True)]), cfg())
    assert result["groups"] == [[1, 2], [3, 3]]
    assert {f["code"] for f in result["findings"]} >= {"blank_page", "repeated_identity"}


def test_no_signal_does_not_report_one_successful_envelope():
    result = detect_index(Index([[(30, "Unrelated text")]]*3), cfg())
    assert not result["established"] and not result["groups"]
    assert "Unable to establish" in result["message"]


def test_missing_first_marker_and_missing_identity_require_review():
    result = detect_index(Index([letter(True), letter(False, "002"), [(30, "Dear customer")]]), cfg())
    assert result["groups"] == [[1, 1], [2, 2], [3, 3]]
    assert {f["code"] for f in result["findings"]} >= {"missing_start_marker", "missing_identity"}


@pytest.mark.parametrize("counter", ["Page {n} of 3", "第 {n} 頁，共 3 頁", "{n}/3"])
def test_counter_formats_and_missing_pages(counter):
    config = DetectionConfig(version=2, rules=[{"kind": "page_number", "auto": True}])
    good = detect_index(Index([[(30, counter.format(n=i))] for i in [1, 2, 3]]), config)
    assert good["groups"] == [[1, 3]] and not good["findings"]
    bad = detect_index(Index([[(30, counter.format(n=i))] for i in [1, 3]]), config)
    assert "page_sequence" in {f["code"] for f in bad["findings"]}


def test_analyze_then_rescan_uses_disk_index_without_text_extraction(tmp_path, monkeypatch):
    path = fixture_pdf(tmp_path/"source.pdf")
    cache = tmp_path/"pages.sqlite"
    value = analyze_pdf(path, cache)
    assert value["suggestions"]
    config = DetectionConfig(**value["suggestions"][0]["config"])
    assert len(config.rules[1]["fields"]) == 2
    def unexpected(*args, **kwargs):
        raise AssertionError("Cached rescan extracted PDF text again")
    monkeypatch.setattr(fitz.Page, "get_text", unexpected)
    result = scan_pdf(path, config, cache_path=cache, expected_sha256=value["source"]["sha256"])
    assert result["detection"]["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert not result["detection"]["findings"]


def test_teach_static_region_and_reject_continuation_match(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    value = teach_pdf(path, tmp_path/"pages.sqlite", 1, 2, [8, 19, 70, 8])
    assert value["config"]["rules"][0]["terms"] == ["Dear"]
    assert value["detection"]["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert "customer" not in str(value["config"])
    with pytest.raises(CompositionError, match="continuation"):
        teach_pdf(path, tmp_path/"pages.sqlite", 1, 3, [8, 19, 70, 8])


def test_source_change_and_cancel_clear_partial_index(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    with pytest.raises(CompositionError, match="changed"):
        analyze_pdf(path, tmp_path/"wrong.sqlite", expected_sha256="0"*64)
    with pytest.raises(CompositionError, match="cancel"):
        analyze_pdf(path, tmp_path/"cancelled.sqlite", is_cancelled=lambda: True)
    assert not (tmp_path/"cancelled.sqlite").exists()


def test_untrusted_config_rejects_unexpected_options():
    value = asdict(cfg())
    value["rules"][0]["python"] = "exec()"
    with pytest.raises(CompositionError):
        DetectionConfig(**value).validate()


def test_all_signals_require_agreement_and_never_hide_conflicts():
    config = cfg()
    config.combine = "all"
    good = detect_index(Index([letter(True), letter(False), letter(True, "002")]), config)
    assert good["groups"] == [[1, 2], [3, 3]]
    bad = detect_index(Index([letter(True), letter(False, "002")]), config)
    assert not bad["groups"] and bad["status"] == "unresolved"
    assert "conflicting_signals" in {f["code"] for f in bad["findings"]}


def test_teach_two_independent_identity_regions(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    result = teach_pdf(path, tmp_path/"pages.sqlite", 1, 2, [8, 19, 70, 8],
                       [[8, 29, 100, 8], [8, 36, 100, 8]])
    fields = result["config"]["rules"][1]["fields"]
    assert len(fields) == 2 and fields[0]["region_mm"] != fields[1]["region_mm"]
    assert result["detection"]["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert not result["detection"]["findings"]


def test_cancellation_after_extraction_removes_partial_index(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf")
    cache = tmp_path/"pages.sqlite"
    cancelled = []
    with pytest.raises(CompositionError, match="cancel"):
        analyze_pdf(path, cache, progress=lambda *args:cancelled.append(True), is_cancelled=lambda:bool(cancelled))
    assert not cache.exists()


def test_auto_marker_region_covers_observed_address_block_shifts(tmp_path):
    path = fixture_pdf(tmp_path/"source.pdf", marker_shifts=True)
    cache = tmp_path/"cache.sqlite"
    analyzed = analyze_pdf(path, cache)
    config = DetectionConfig(**analyzed["suggestions"][0]["config"])
    result = scan_pdf(path, config, cache_path=cache)["detection"]
    assert result["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert not result["findings"]
