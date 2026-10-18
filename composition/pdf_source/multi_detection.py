"""Thin multi-rule resolver over the existing spatial index and signal functions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict

from composition.production.generator import check_cancel
from composition.template.model import CompositionError

from .model import EnvelopeSettings
from .planner import EnvelopePlan
from .profile_library import validate_profile
from .smart_detection import index_pdf, signal_values


def profile_digest(profile):
    value = validate_profile(profile)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def unresolved(report):
    return sum(
        row["classification_status"] in {"unknown", "ambiguous"} for row in report["classifications"]
    ) + sum(bool(f.get("blocking")) and not f.get("resolution") for f in report["findings"])


def can_accept(report):
    return bool(
        report and report.get("report_version") == 3 and report.get("groups") and not unresolved(report)
    )


def detect_index(index, profile, *, progress=None, is_cancelled=None):
    profile = validate_profile(profile, for_scan=True)
    pages = index.metadata()["pages"]
    if type(pages) is not int or pages < 1:
        raise CompositionError("No source pages to classify.")
    rulesets = [(item, {r["kind"]: r for r in item["config"]["rules"]}) for item in profile["rule_sets"]]
    previous_ids = {}
    starts, rows, evidence, findings = [], [], [], []
    active_rules = set()
    previous_counter = None
    seen_pages = 0

    def warn(page, code, message, *, blocking=False, rule_id=""):
        findings.append(
            {"page": page, "code": code, "message": message, "blocking": blocking, "rule_id": rule_id}
        )

    for number, lines in index.pages():
        check_cancel(is_cancelled)
        if number != seen_pages + 1 or number > pages:
            raise CompositionError("Page index is incomplete or out of order.")
        seen_pages = number
        eligible, values, matched = [], {}, []
        for item, rules in rulesets:
            key = item["rule_id"]
            marker, ident, issue, counter = signal_values(lines, rules)
            changed = ident is not None and key in previous_ids and ident != previous_ids[key]
            values[key] = (marker, ident, issue, counter)
            primary_hit = (
                marker
                if item["primary"] == "first_text"
                else bool(counter and counter[0] == 1 and 1 <= counter[0] <= counter[1])
            )
            if primary_hit and item["primary"] == "page_number" and "first_text" in rules and not marker:
                primary_hit = False
            if primary_hit and marker and counter and counter[0] != 1:
                warn(
                    number,
                    "start_counter_conflict",
                    "First-page marker contradicts a continuation counter; resolve the boundary.",
                    blocking=True,
                    rule_id=key,
                )
                primary_hit = False
            if primary_hit:
                eligible.append(item)
                matched.extend(
                    [
                        name
                        for name, hit in (
                            ("first_text", marker),
                            ("page_number", bool(counter and counter[0] == 1)),
                            ("document_id", ident is not None),
                        )
                        if hit
                    ]
                )
            elif changed and key in active_rules:
                warn(
                    number,
                    "identity_without_start",
                    "Identity changed without valid first-page evidence; review the boundary.",
                    blocking=True,
                    rule_id=key,
                )
            if ident is not None:
                previous_ids[key] = ident
        if number == 1 or eligible:
            if starts and previous_counter and previous_counter[0] != previous_counter[1]:
                warn(
                    number - 1,
                    "incomplete_sequence",
                    "Previous mailpiece ends before its declared final page.",
                    blocking=True,
                )
            starts.append(number)
            template_ids = sorted({item["template_id"] for item in eligible})
            status = "matched" if len(template_ids) == 1 else "ambiguous" if template_ids else "unknown"
            rows.append(
                {
                    "envelope_index": len(rows) + 1,
                    "start_page": number,
                    "end_page": number,
                    "page_count": 1,
                    "template_id": template_ids[0] if status == "matched" else "",
                    "rule_ids": [item["rule_id"] for item in eligible],
                    "candidates": template_ids,
                    "classification_status": status,
                    "review_status": "needs_review",
                    "boundary_evidence": sorted(set(matched)),
                }
            )
            evidence.append(
                {"page": number, "matched": sorted(set(matched)), "end_basis": "next_start_inferred"}
            )
            active_rules = {item["rule_id"] for item in eligible}
            previous_counter = None
            if not eligible:
                warn(
                    number,
                    "unmarked_start",
                    "Source begins without a matching template. Classify before accepting.",
                )
            if len(set(matched)) == 1:
                warn(
                    number,
                    "single_signal",
                    "Boundary has one primary signal; inspect representative neighbours.",
                )
        if active_rules:
            # One physical printed counter stage; never combine incompatible counters.
            counters = {values[key][3] for key in active_rules if values[key][3] is not None}
            if len(counters) > 1:
                warn(
                    number,
                    "conflicting_counters",
                    "Matching rule sets disagree on the printed counter.",
                    blocking=True,
                )
            elif counters:
                counter = next(iter(counters))
                current, total = counter
                if not 1 <= current <= total:
                    warn(number, "invalid_page_number", "Invalid printed page counter.", blocking=True)
                elif previous_counter and (
                    current != previous_counter[0] + 1 or total != previous_counter[1]
                ):
                    warn(
                        number,
                        "page_sequence",
                        "Printed page sequence is missing, duplicated or inconsistent.",
                        blocking=True,
                    )
                previous_counter = counter
                evidence[-1]["end_basis"] = "printed_sequence"
            for item, rules in rulesets:
                if item["rule_id"] not in active_rules:
                    continue
                _, ident, issue, counter = values[item["rule_id"]]
                if "page_number" in rules and counter is None:
                    warn(
                        number,
                        "missing_page_number",
                        "No unique configured printed counter.",
                        rule_id=item["rule_id"],
                    )
                if issue:
                    warn(
                        number, issue, "Configured identity is missing or ambiguous.", rule_id=item["rule_id"]
                    )
        if not lines:
            warn(number, "blank_page", "Blank/textless page retained in its mailpiece.")
        if progress and (number % 100 == 0 or number == pages):
            progress(number, pages, f"Evaluating {len(rulesets)} rule sets · page {number:,} / {pages:,}")
    if seen_pages != pages:
        raise CompositionError("Page index is incomplete.")
    if previous_counter and previous_counter[0] != previous_counter[1]:
        warn(
            pages,
            "incomplete_sequence",
            "Final mailpiece ends before its declared final page.",
            blocking=True,
        )
    groups = [[start, starts[i + 1] - 1 if i + 1 < len(starts) else pages] for i, start in enumerate(starts)]
    EnvelopePlan(pages, EnvelopeSettings(groups=groups))
    for row, (start, end) in zip(rows, groups, strict=True):
        row.update(end_page=end, page_count=end - start + 1)
        if end - start + 1 > 100:
            warn(
                start,
                "abnormal_length",
                "Mailpiece exceeds 100 source pages; check the missing-start possibility.",
            )
    if evidence[-1]["end_basis"] == "next_start_inferred":
        evidence[-1]["end_basis"] = "pdf_end_inferred"
    report = {
        "report_version": 3,
        "profile": profile,
        "profile_sha256": profile_digest(profile),
        "pages": pages,
        "groups": groups,
        "excluded_pages": [],
        "classifications": rows,
        "findings": findings,
        "evidence": evidence,
        "accepted": False,
        "edits": [],
        "established": any(row["template_id"] for row in rows),
        "distribution": dict(Counter(str(min(4, b - a + 1)) for a, b in groups)),
        "message": "Review classifications and exceptions; saving a profile never accepts boundaries.",
    }
    report["unresolved"] = unresolved(report)
    report["status"] = "unresolved" if report["unresolved"] else "needs_review" if findings else "consistent"
    return report


def scan_pdf(path, profile, *, cache_path, expected_sha256=None, progress=None, is_cancelled=None):
    profile = validate_profile(profile, for_scan=True)
    source, index = index_pdf(
        path, cache_path, expected_sha256=expected_sha256, progress=progress, is_cancelled=is_cancelled
    )
    try:
        report = detect_index(index, profile, progress=progress, is_cancelled=is_cancelled)
        report["source_sha256"] = source.sha256
        return {"source": asdict(source), "detection": report}
    finally:
        index.close()
