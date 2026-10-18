from dataclasses import asdict

import fitz
import pytest

from composition.pdf_source.detection import DetectionConfig
from composition.pdf_source.profile_library import new_profile, new_rule
from composition.template.model import CompositionError
from tests.composition.test_smart_mailpieces import Index


def api():
    from composition.pdf_source import multi_detection

    return multi_detection


def profile(*names):
    value = new_profile("eMPF")
    for name in names or ("Regular", "Reminder"):
        config = asdict(
            DetectionConfig(version=2, rules=[{"kind": "first_text", "terms": [name], "region_mm": None}])
        )
        value["rule_sets"].append(new_rule(name, config, template_id=name.upper()))
    return value


def index(*texts):
    return Index([[(30, text)] if text else [] for text in texts])


def test_exact_variable_groups_and_template_ids():
    report = api().detect_index(
        index("Regular", "continued", "Reminder", "continued", "continued", "Regular"), profile()
    )
    assert report["groups"] == [[1, 2], [3, 5], [6, 6]]
    assert [row["template_id"] for row in report["classifications"]] == ["REGULAR", "REMINDER", "REGULAR"]
    assert report["report_version"] == 3 and not report["accepted"]
    assert report["evidence"][-1]["end_basis"] == "pdf_end_inferred"


def test_shared_index_iterator_opened_once_for_all_rules():
    source = index("Regular", "Reminder")
    original = source.pages
    calls = []

    def pages():
        calls.append(True)
        yield from original()

    source.pages = pages
    assert api().detect_index(source, profile())["groups"] == [[1, 1], [2, 2]]
    assert len(calls) == 1


def test_unknown_first_page_is_retained_and_blocks_acceptance():
    report = api().detect_index(index("Unknown", "continued", "Regular"), profile())
    assert report["groups"] == [[1, 2], [3, 3]]
    assert report["classifications"][0]["classification_status"] == "unknown"
    assert report["unresolved"] and not api().can_accept(report)


def test_ambiguous_templates_are_not_selected_by_rule_order():
    value = profile("Regular")
    other = new_rule("Second", value["rule_sets"][0]["config"], template_id="SECOND")
    value["rule_sets"].append(other)
    report = api().detect_index(index("Regular"), value)
    row = report["classifications"][0]
    assert row["template_id"] == "" and row["classification_status"] == "ambiguous"
    assert set(row["candidates"]) == {"REGULAR", "SECOND"}
    assert not api().can_accept(report)


def test_two_rules_for_same_template_preserve_both_ids():
    value = profile("Regular")
    value["rule_sets"].append(new_rule("Alternative", value["rule_sets"][0]["config"], template_id="REGULAR"))
    row = api().detect_index(index("Regular"), value)["classifications"][0]
    assert row["template_id"] == "REGULAR" and len(row["rule_ids"]) == 2


def test_identity_change_is_not_a_boundary_and_customer_value_is_not_reported():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"].append(
        {"kind": "document_id", "fields": [{"label": "Account No."}]}
    )
    report = api().detect_index(
        index("Regular Account No.: SECRET001", "continued Account No.: SECRET002"), value
    )
    assert report["groups"] == [[1, 2]]
    assert "SECRET" not in str(report)
    assert "identity_without_start" in {f["code"] for f in report["findings"]}


def test_same_identity_can_start_two_mailpieces():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"].append(
        {"kind": "document_id", "fields": [{"label": "Account No."}]}
    )
    report = api().detect_index(index("Regular Account No.: 001", "Regular Account No.: 001"), value)
    assert report["groups"] == [[1, 1], [2, 2]]


def test_continuation_counter_contradicts_marker_without_automatic_split():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"].append({"kind": "page_number", "auto": True})
    report = api().detect_index(index("Regular Page 1 of 2", "Regular Page 2 of 2"), value)
    assert report["groups"] == [[1, 2]]
    assert not api().can_accept(report)
    assert any(f["code"] == "start_counter_conflict" and f["blocking"] for f in report["findings"])


def test_page_restart_primary_and_eof_single_mailpiece():
    value = profile("Regular")
    value["rule_sets"][0].update(
        primary="page_number",
        config=asdict(DetectionConfig(version=2, rules=[{"kind": "page_number", "auto": True}])),
    )
    report = api().detect_index(index("Page 1 of 2", "Page 2 of 2"), value)
    assert report["groups"] == [[1, 2]] and report["established"]
    assert api().can_accept(report)


def test_marker_terms_still_mean_and_and_blank_page_is_retained():
    value = profile("Regular")
    value["rule_sets"][0]["config"]["rules"][0]["terms"] = ["Regular", "Letter"]
    report = api().detect_index(index("Regular Letter", "", "Regular"), value)
    assert report["groups"] == [[1, 3]]
    assert any(f["code"] == "blank_page" for f in report["findings"])


def test_cancellation_is_not_a_success_report():
    with pytest.raises(CompositionError, match="cancel"):
        api().detect_index(index("Regular"), profile(), is_cancelled=lambda: True)


def test_profile_scan_reuses_spatial_extraction_and_binds_source(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for text in ["Regular", "continued", "Reminder"]:
            pdf.new_page().insert_text((30, 40), text)
        pdf.save(source)
    cache = tmp_path / "index.sqlite"
    first = api().scan_pdf(source, profile(), cache_path=cache)
    assert first["detection"]["source_sha256"] == first["source"]["sha256"]

    def forbidden(*a, **k):
        pytest.fail("A cached rule scan re-extracted PDF text")

    monkeypatch.setattr(fitz.Page, "get_text", forbidden)
    second = api().scan_pdf(source, profile("Reminder"), cache_path=cache)
    assert second["detection"]["groups"] == [[1, 2], [3, 3]]


def test_mixed_page_geometry_remains_explicitly_rejected(tmp_path):
    source = tmp_path / "mixed.pdf"
    with fitz.open() as pdf:
        pdf.new_page(width=595, height=842)
        pdf.new_page(width=612, height=792)
        pdf.save(source)
    with pytest.raises(CompositionError, match="geometry"):
        api().scan_pdf(source, profile(), cache_path=tmp_path / "index.sqlite")
