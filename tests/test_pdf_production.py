"""Combined analysis must stay read-only, bounded and honest about coverage."""
import csv

import fitz
import pytest

from core.pdf_operations.analysis import PdfCancelled
from core.pdf_operations.overview import analyze_overview
from ui.pdf_production_workspace import PdfProductionWorkspace


def pdf(path):
    with fitz.open() as doc:
        doc.new_page().insert_text((20, 30), "Original searchable text")
        doc.save(path)
    return str(path)


def test_overview_batch_failure_isolation_and_source_preservation(tmp_path):
    good = pdf(tmp_path / "good.pdf")
    original = (tmp_path / "good.pdf").read_bytes()
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"invalid PDF")
    report = analyze_overview([good, str(bad)])
    assert report["kind"] == "analysis"
    assert report["files"][0]["pdf"]["page_count"] == 1
    assert report["files"][0]["fonts"]["resources"][0]["status"] == "BASE14_POLICY_EXEMPT"
    assert report["files"][1]["status"] == "FAILED" and report["files"][1]["errors"]
    assert (tmp_path / "good.pdf").read_bytes() == original


def test_overview_rejects_changed_source_between_inspectors(tmp_path, monkeypatch):
    import core.font_preflight.inventory as fonts
    original = fonts.analyze
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        result.source_sha256 = "different-input"
        return result
    monkeypatch.setattr(fonts, "analyze", changed)
    row = analyze_overview([pdf(tmp_path / "input.pdf")])["files"][0]
    assert row["status"] == "FAILED"
    assert "pdf" not in row and "fonts" not in row
    assert "Source changed" in row["errors"]["source"]


def test_overview_cancel_and_input_limits(tmp_path):
    path = pdf(tmp_path / "input.pdf")
    with pytest.raises(PdfCancelled):
        analyze_overview([path], is_cancelled=lambda: True)
    for paths in ([], "input.pdf", [42], [path] * 10001):
        with pytest.raises(ValueError):
            analyze_overview(paths)


def test_csv_summary_is_formula_safe_and_json_keeps_context(tmp_path):
    import json
    entry = {"section": "flatten", "kind": "production", "source": "=unsafe.pdf", "outdated": True,
             "settings": {"options": {"forms": True}},
             "result": {"files": [{"source": "=unsafe.pdf", "status": "failed", "error": "+unexpected"}]}}
    path = tmp_path / "report.csv"
    PdfProductionWorkspace.export_evidence(entry, path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[1][0] == "'=unsafe.pdf" and rows[1][-1] == "'+unexpected"
    path = tmp_path / "report.json"
    PdfProductionWorkspace.export_evidence(entry, path)
    assert json.loads(path.read_text(encoding="utf-8")) == entry
