"""Read-only production presentation: missing values and audit scope stay explicit."""

import copy

import pytest

from composition.review.presentation import ReviewDashboardModel


def checked(*, count=2, marks=0, elements=None, kind="template"):
    return {
        "snapshot_id": "snap-1",
        "fingerprint": "source-1",
        "status": "checked",
        "complete": True,
        "summary": {
            "job_id": "job-1",
            "records": count,
            "pages": 4,
            "sheets": 2,
            "inserted_blanks": 0,
            "printing": "Duplex",
            "expected_barcodes": marks,
            "barcode_check_complete": True,
            "font_substitutions": 0,
            "output_dir": "C:/Production",
            "output_name": "production.pdf",
            "stock_sheets": {"LH_A": 2},
            "printer_profile": "Printer profile",
            "media_source": "project",
        },
        "issues": [],
        "context": {
            "kind": kind,
            "job": {"job_id": "job-1", "template": {"pages": [{"elements": elements or []}]}},
        },
    }


def production(review, *, expected=2, decoded=2, status="completed"):
    return {
        "snapshot_id": review["snapshot_id"],
        "fingerprint": review["fingerprint"],
        "job_id": "job-1",
        "phase": "finished",
        "result": {
            "job_id": "job-1",
            "status": status,
            "expected_pages": 4,
            "generated_pages": 4,
            "generated_files": 1,
            "output_pdf": "C:/Production/job-1/production.pdf",
            "expected_barcodes": expected,
            "rendered_barcodes": expected,
            "decoded_barcodes": decoded,
            "repaired_glyphs": 3,
            "repaired_records": 1,
            "font_scan": {"complete": True},
        },
    }


def values(model):
    return {m.key: m.value for m in model.metrics}


def test_no_job_and_missing_metrics_are_not_zero():
    model = ReviewDashboardModel.from_review(None)
    assert model.status == "not_checked"
    assert values(model)["mailpieces"] == "Not Available"
    assert model.planned_barcode.state == "Not Checked"
    review = checked()
    review["summary"].pop("records")
    review["summary"].pop("font_substitutions")
    model = ReviewDashboardModel.from_review(review)
    assert values(model)["mailpieces"] == "Not Available"
    assert model.fonts.state == "Not Available"


def test_real_zero_planned_pages_media_and_identity_remain_distinct():
    review = checked(count=0)
    original = copy.deepcopy(review)
    model = ReviewDashboardModel.from_review(review, confirmation_available=True)
    assert values(model)["mailpieces"] == "0"
    assert values(model)["planned_pages"] == "4"
    assert values(model)["actual_pages"] == "Not generated"
    assert values(model)["blank_backs"] == "0"
    assert values(model)["printing"] == "Duplex"
    assert "LH_A" in values(model)["stocks"]
    assert model.snapshot_id == "snap-1" and model.fingerprint == "source-1"
    assert review == original


@pytest.mark.parametrize(
    "flags,status",
    [
        ({"checking": True}, "checking"),
        ({"current": False}, "stale"),
        ({"cancelled": True}, "cancelled"),
        ({"confirmed": True}, "confirmed"),
        ({"confirmation_available": True}, "ready_to_confirm"),
    ],
)
def test_review_status_does_not_imply_published_output(flags, status):
    model = ReviewDashboardModel.from_review(checked(), **flags)
    assert model.status == status
    assert values(model)["actual_pages"] == "Not generated"
    assert model.final_barcode.state == "Not Checked"


def test_blocked_errors_and_warning_acknowledgement_are_independent():
    review = checked()
    review["status"] = "blocked"
    review["complete"] = False
    review["issues"] = [
        {"severity": "error", "action": "barcode", "reason": "Missing barcode"},
        {"severity": "warning", "action": "font", "reason": "Review substitution"},
    ]
    model = ReviewDashboardModel.from_review(review)
    assert model.status == "blocked" and model.errors == 1 and model.warnings == 1
    assert model.planned_barcode.state == "Failed"
    review = checked()
    review["issues"] = [{"severity": "warning", "reason": "Printer proof"}]
    assert ReviewDashboardModel.from_review(review).status == "warnings"
    assert (
        ReviewDashboardModel.from_review(review, acknowledged=True, confirmation_available=True).status
        == "ready_to_confirm"
    )


def test_no_barcode_needs_complete_evidence_before_not_applicable():
    review = checked()
    assert ReviewDashboardModel.from_review(review).planned_barcode.state == "Not Applicable"
    review["complete"] = False
    review["summary"]["barcode_check_complete"] = False
    model = ReviewDashboardModel.from_review(review)
    assert model.planned_barcode.state == "Incomplete"
    assert model.final_barcode.state == "Not Checked"


@pytest.mark.parametrize(
    "profile", [{"preset": "inserter_i25_18"}, {"preset": "generic", "layout_mode": "fixed"}]
)
def test_profile_plan_and_same_job_final_decode_are_separate(profile):
    review = checked(marks=2, elements=[{"type": "i25", "barcode_profile": profile}])
    model = ReviewDashboardModel.from_review(review)
    assert model.planned_barcode.state == "Passed" and model.final_barcode.state == "Not Checked"
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=production(review))
    assert model.status == "generated" and values(model)["actual_pages"] == "4"
    assert model.final_barcode.state == "Passed" and model.final_barcode.verified == 2
    assert model.final_barcode.unverified == 0
    assert model.fonts.count == 3 and model.fonts.records == 1


def test_partial_decode_is_incomplete_and_failed_decode_is_failed():
    review = checked(marks=2, kind="overlay")
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=production(review, decoded=1))
    assert model.final_barcode.state == "Incomplete"
    assert (
        model.final_barcode.expected == 2
        and model.final_barcode.verified == 1
        and model.final_barcode.unverified == 1
    )
    model = ReviewDashboardModel.from_review(
        review, confirmed=True, generation=production(review, decoded=1, status="failed")
    )
    assert model.final_barcode.state == "Failed" and model.status == "failed"


def test_direct_qr_is_not_claimed_as_fully_decoded_by_profile_counters():
    review = checked(
        marks=3,
        elements=[
            {"type": "i25", "barcode_profile": {"preset": "inserter_i25_18"}},
            {"type": "qr", "barcode_profile": {}},
        ],
    )
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=production(review))
    assert model.final_barcode.state == "Incomplete"
    assert "audit" in model.final_barcode.detail.lower()
    assert model.final_barcode.expected == 2  # final-stage denominator, not 3 planned marks


@pytest.mark.parametrize(
    "key,value", [("job_id", "other"), ("snapshot_id", "other"), ("fingerprint", "other")]
)
def test_mismatched_result_is_never_reused(key, value):
    review = checked(marks=2, kind="overlay")
    output = production(review)
    output[key] = value
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.final_barcode.state == "Not Checked" and values(model)["actual_pages"] == "Not generated"


def test_result_job_or_page_mismatch_fails_closed():
    review = checked(marks=2, kind="overlay")
    output = production(review)
    output["result"]["job_id"] = "other"
    assert ReviewDashboardModel.from_review(review, confirmed=True, generation=output).final_barcode.state == "Not Checked"
    output = production(review)
    output["result"]["expected_pages"] = 99
    assert ReviewDashboardModel.from_review(review, confirmed=True, generation=output).final_barcode.state == "Not Checked"


def test_missing_final_counters_and_unpublished_result_cannot_pass():
    review = checked(marks=2, kind="overlay")
    output = production(review)
    output["result"].pop("decoded_barcodes")
    assert ReviewDashboardModel.from_review(review, confirmed=True, generation=output).final_barcode.state == "Not Checked"
    output = production(review)
    output["result"]["generated_files"] = 0
    output["result"]["output_pdf"] = ""
    assert ReviewDashboardModel.from_review(review, confirmed=True, generation=output).status != "generated"


def test_running_and_stale_generation_cannot_be_current_authorization():
    review = checked(marks=2, kind="overlay")
    output = production(review)
    output["phase"] = "running"
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.status == "generating" and model.final_barcode.state == "Not Checked"
    model = ReviewDashboardModel.from_review(
        review, current=False, confirmed=True, generation=production(review)
    )
    assert model.status == "stale"
    assert model.final_barcode.state != "Passed"


def test_incomplete_font_scan_retains_actual_findings_without_claiming_completion():
    review = checked()
    review["complete"] = False
    review["status"] = "blocked"
    review["summary"].pop("font_substitutions")
    review["summary"]["font_scan"] = {"occurrences": 7, "records": 2, "complete": False}
    model = ReviewDashboardModel.from_review(review)
    assert model.fonts.state == "Incomplete" and model.fonts.count == 7 and model.fonts.records == 2
    assert model.fonts.pages is None
    assert "physical" in model.fonts.detail.lower()


def test_zero_final_counts_do_not_prove_direct_content_qr_was_verified():
    review = checked(marks=2, elements=[{"type": "qr", "barcode_profile": {}}])
    output = production(review, expected=0, decoded=0)
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.final_barcode.state == "Incomplete"


def test_generation_end_without_a_matching_job_is_not_reported_as_confirmed_success():
    review = checked()
    output = production(review)
    output.pop("result")
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.status == "outcome_unavailable"


def test_check_transport_failure_is_blocked_even_without_a_snapshot():
    model = ReviewDashboardModel.from_review(None, check_failed=True)
    assert model.status == "blocked" and model.final_barcode.state == "Not Checked"


def test_completed_reports_only_are_published_without_claiming_a_pdf():
    review = checked(count=0)
    review["summary"].update(pages=0, sheets=0, backend="reports")
    output = production(review, expected=0, decoded=0)
    for key in ("expected_barcodes", "rendered_barcodes", "decoded_barcodes"):
        output["result"].pop(key)
    output["result"].update(
        expected_pages=0,
        generated_pages=0,
        generated_files=0,
        output_pdf="",
        report_dir="C:/Production/job-1",
    )
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.status == "reports_published"
    assert values(model)["actual_pages"] == "0"
    assert "No PDF" in values(model)["published_output"]
    assert model.final_barcode.state == "Not Applicable"


def test_overlay_final_font_report_uses_existing_report_directory():
    review = checked(kind="overlay")
    review["summary"]["font_report"] = "C:/Review/glyph-repairs.csv"
    output = production(review)
    output["result"].pop("repaired_glyphs")
    output["result"].pop("repaired_records")
    output["result"].update(
        report_dir="C:/Production/job-1", font_scan={"complete": True, "occurrences": 3, "records": 1}
    )
    model = ReviewDashboardModel.from_review(review, confirmed=True, generation=output)
    assert model.fonts.count == 3
    assert model.fonts.reference_label == "output-page scan entries"
    assert model.fonts.report.replace("\\", "/") == "C:/Production/job-1/glyph-repairs.csv"


def test_absent_issue_results_do_not_manufacture_zero_counts():
    review = checked()
    review.pop("issues")
    review["complete"] = False
    model = ReviewDashboardModel.from_review(review)
    assert model.errors is None and model.warnings is None


def test_generation_binding_does_not_imply_formal_confirmation():
    review = checked(marks=2,kind="overlay")
    model = ReviewDashboardModel.from_review(review,generation=production(review))
    assert model.status != "generated"
    assert model.final_barcode.state == "Not Checked"
    assert values(model)["actual_pages"] == "Not generated"
