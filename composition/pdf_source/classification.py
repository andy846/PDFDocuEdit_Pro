"""Source-bound classification review assets, separate from reusable profiles."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from bisect import bisect_left, bisect_right
from pathlib import Path

from composition.production.model import now
from composition.template.model import CompositionError
from core.io_atomic import atomic_output
from core.output_safety import contained_path

from .detection import edit_boundary
from .model import EnvelopeSettings
from .multi_detection import can_accept, profile_digest, unresolved
from .planner import EnvelopePlan
from .profile_library import MAX_RULES, validate_profile

MAX_ASSET_BYTES = 32 * 1024 * 1024
ROW_KEYS = {
    "envelope_index",
    "start_page",
    "end_page",
    "page_count",
    "template_id",
    "rule_ids",
    "candidates",
    "classification_status",
    "review_status",
    "boundary_evidence",
}
REPORT_KEYS = {
    "report_version",
    "profile",
    "profile_sha256",
    "pages",
    "groups",
    "excluded_pages",
    "classifications",
    "findings",
    "evidence",
    "accepted",
    "edits",
    "established",
    "distribution",
    "message",
    "unresolved",
    "status",
}
DESCRIPTOR_KEYS = {
    "report_version",
    "required",
    "accepted",
    "accepted_at",
    "source_sha256",
    "groups",
    "excluded_pages",
    "pages",
    "profile_id",
    "profile_name",
    "profile_revision",
    "profile_sha256",
    "classification_asset",
    "template_ids",
    "template_map",
}


def _digest(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def validate_report(report):
    try:
        if (
            not isinstance(report, dict)
            or set(report) - REPORT_KEYS - {"source_sha256", "accepted_at"}
            or not REPORT_KEYS <= set(report)
            or type(report["report_version"]) is not int
            or report["report_version"] != 3
            or type(report["accepted"]) is not bool
            or report["excluded_pages"]
        ):
            raise CompositionError("Invalid classified mailpiece report.")
        profile = validate_profile(report["profile"], for_scan=True)
        if profile_digest(profile) != report["profile_sha256"]:
            raise CompositionError("Detection profile changed since scanning.")
        if "source_sha256" in report and not _digest(report["source_sha256"]):
            raise CompositionError("Invalid classification source identity.")
        groups = report["groups"]
        if not groups:
            raise CompositionError("No classified mailpieces.")
        EnvelopePlan(report["pages"], EnvelopeSettings(groups=groups))
        rows = report["classifications"]
        if not isinstance(rows, list) or len(rows) != len(groups):
            raise CompositionError("Classification count differs from the envelope plan.")
        rules = {item["rule_id"]: item["template_id"] for item in profile["rule_sets"]}
        templates = set(rules.values())
        for i, (row, (start, end)) in enumerate(zip(rows, groups, strict=True), 1):
            if (
                not isinstance(row, dict)
                or set(row) != ROW_KEYS
                or [row["envelope_index"], row["start_page"], row["end_page"], row["page_count"]]
                != [i, start, end, end - start + 1]
                or row["classification_status"] not in {"matched", "manual", "unknown", "ambiguous"}
                or row["review_status"] not in {"needs_review", "manual", "accepted"}
            ):
                raise CompositionError("Classification does not match the authoritative envelope ranges.")
            for key, allowed in (("rule_ids", set(rules)), ("candidates", templates)):
                if (
                    not isinstance(row[key], list)
                    or len(row[key]) > MAX_RULES
                    or any(v not in allowed for v in row[key])
                ):
                    raise CompositionError("Unknown classification template or rule.")
            if row["classification_status"] in {"matched", "manual"}:
                if row["template_id"] not in templates:
                    raise CompositionError("Unknown classified template.")
                if row["classification_status"] == "matched" and (
                    not row["rule_ids"] or any(rules[key] != row["template_id"] for key in row["rule_ids"])
                ):
                    raise CompositionError("Matched template conflicts with its rule evidence.")
            elif row["template_id"]:
                raise CompositionError("Unresolved classifications cannot assert a TemplateID.")
            if (
                not isinstance(row["boundary_evidence"], list)
                or len(row["boundary_evidence"]) > 4
                or any(
                    v not in {"first_text", "page_number", "document_id", "operator"}
                    for v in row["boundary_evidence"]
                )
            ):
                raise CompositionError("Invalid boundary evidence.")
        if (
            not isinstance(report["findings"], list)
            or len(report["findings"]) > report["pages"] * (MAX_RULES * 4 + 6) + 10
            or not isinstance(report["evidence"], list)
            or len(report["evidence"]) != len(groups)
            or not isinstance(report["edits"], list)
            or len(report["edits"]) > 100000
        ):
            raise CompositionError("Invalid or oversized classification audit.")
        for finding in report["findings"]:
            if (
                not isinstance(finding, dict)
                or set(finding) - {"page", "code", "message", "blocking", "rule_id", "resolution"}
                or type(finding["page"]) is not int
                or not 1 <= finding["page"] <= report["pages"]
                or not isinstance(finding["message"], str)
                or len(finding["message"]) > 1000
                or type(finding["blocking"]) is not bool
                or finding.get("resolution", "") not in {"", "operator_review"}
                or finding.get("rule_id", "") not in set(rules) | {""}
            ):
                raise CompositionError("Invalid classification finding.")
        for item, start in zip(report["evidence"], [g[0] for g in groups], strict=True):
            if (
                not isinstance(item, dict)
                or set(item) != {"page", "matched", "end_basis"}
                or item["page"] != start
                or item["end_basis"]
                not in {"next_start_inferred", "pdf_end_inferred", "printed_sequence", "operator_edited"}
                or not isinstance(item["matched"], list)
                or len(item["matched"]) > 3
                or any(v not in {"first_text", "page_number", "document_id"} for v in item["matched"])
            ):
                raise CompositionError("Invalid classification start evidence.")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CompositionError):
            raise
        raise CompositionError("Invalid classification review.") from exc
    return report


def _refresh(report):
    report["accepted"] = False
    report.pop("accepted_at", None)
    report["unresolved"] = unresolved(report)
    report["status"] = "unresolved" if report["unresolved"] else "needs_review"
    return report


def classify(report, index, template_id):
    validate_report(report)
    if not 0 <= index < len(report["groups"]):
        raise CompositionError("Select a mailpiece.")
    if template_id not in {r["template_id"] for r in report["profile"]["rule_sets"]}:
        raise CompositionError("Choose a configured template.")
    value = copy.deepcopy(report)
    row = value["classifications"][index]
    row.update(
        template_id=template_id,
        rule_ids=[],
        candidates=[template_id],
        classification_status="manual",
        review_status="manual",
    )
    resolved = []
    for finding in value["findings"]:
        if row["start_page"] <= finding["page"] <= row["end_page"] and finding["blocking"]:
            finding["resolution"] = "operator_review"
            resolved.append({"page": finding["page"], "code": finding["code"]})
    value["edits"].append(
        {
            "action": "classify",
            "start_page": row["start_page"],
            "end_page": row["end_page"],
            "template_id": template_id,
            "resolved": resolved,
            "at": now(),
        }
    )
    return _refresh(value)


def edit_report(report, index, *, split_page=None, merge_previous=False):
    validate_report(report)
    value = edit_boundary(report, index, split_page=split_page, merge_previous=merge_previous)
    for finding in value["findings"]:
        finding.pop("resolution", None)
    old_rows = report["classifications"]
    old_starts = [row["start_page"] for row in old_rows]
    old_ends = [row["end_page"] for row in old_rows]
    value["classifications"] = []
    value["evidence"] = []
    prior_evidence = {e["page"]: e for e in report["evidence"]}
    for i, (start, end) in enumerate(value["groups"], 1):
        originals = old_rows[bisect_left(old_ends, start):bisect_right(old_starts, end)]
        row = copy.deepcopy(originals[0])
        row.update(
            envelope_index=i,
            start_page=start,
            end_page=end,
            page_count=end - start + 1,
            review_status="needs_review",
        )
        if len(originals) > 1:
            candidates = sorted({r["template_id"] for r in originals if r["template_id"]})
            row.update(
                template_id="",
                rule_ids=[],
                candidates=candidates,
                classification_status="ambiguous" if candidates else "unknown",
            )
        elif start != originals[0]["start_page"]:
            row.update(
                template_id="",
                rule_ids=[],
                candidates=[],
                classification_status="unknown",
                boundary_evidence=["operator"],
            )
        value["classifications"].append(row)
        value["evidence"].append(
            copy.deepcopy(
                prior_evidence.get(start, {"page": start, "matched": [], "end_basis": "operator_edited"})
            )
        )
    return _refresh(value)


def validate_descriptor(value, source, groups, exclusions):
    if (
        not isinstance(value, dict)
        or set(value) != DESCRIPTOR_KEYS
        or value["report_version"] != 3
        or value["required"] is not True
        or value["accepted"] is not True
        or value["source_sha256"] != source.sha256
        or value["pages"] != source.pages
        or value["groups"] != groups
        or value["excluded_pages"] != exclusions
        or exclusions
        or not _digest(value["profile_sha256"])
        or not isinstance(value["accepted_at"], str)
        or not isinstance(value["profile_id"], str)
        or type(value["profile_revision"]) is not int
        or not isinstance(value["profile_name"], str)
    ):
        raise CompositionError("Source, groups or accepted classification changed. Scan and review again.")
    known = value["template_ids"]
    mapping = value["template_map"]
    if (not isinstance(known, list) or not 1 <= len(known) <= MAX_RULES
            or len(set(known)) != len(known)
            or any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", t) for t in known)
            or not isinstance(mapping, list) or len(mapping) != len(groups)
            or any(not isinstance(t, str) or t not in known for t in mapping)):
        raise CompositionError("Invalid classified TemplateID mapping.")
    asset = value["classification_asset"]
    if (
        not isinstance(asset, dict)
        or set(asset) != {"path", "sha256"}
        or not _digest(asset["sha256"])
        or not isinstance(asset["path"], str)
        or not 1 <= len(asset["path"]) <= 4096
    ):
        raise CompositionError("Invalid classification asset reference.")
    EnvelopePlan(source.pages, EnvelopeSettings(groups=groups))


def accept_report(report, directory):
    validate_report(report)
    if not _digest(report.get("source_sha256")) or not can_accept(report):
        raise CompositionError("Resolve every unknown template / boundary conflict before accepting.")
    value = copy.deepcopy(report)
    value.update(accepted=True, accepted_at=now())
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    if len(payload) > MAX_ASSET_BYTES:
        raise CompositionError(
            "Classification audit exceeds 32 MB. Export the draft and split the source job."
        )
    digest = hashlib.sha256(payload).hexdigest()
    target = contained_path(directory, digest[:20] + ".mailpieces.json")
    if not target.exists():
        with atomic_output(target, overwrite=False) as temporary:
            temporary.write_bytes(payload)
    elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise CompositionError("Existing classification asset changed.")
    profile = value["profile"]
    return {
        "report_version": 3,
        "required": True,
        "accepted": True,
        "accepted_at": value["accepted_at"],
        "source_sha256": value["source_sha256"],
        "groups": value["groups"],
        "excluded_pages": [],
        "pages": value["pages"],
        "profile_id": profile["profile_id"],
        "profile_name": profile["name"],
        "profile_revision": profile["revision"],
        "profile_sha256": value["profile_sha256"],
        "classification_asset": {"path": str(target), "sha256": digest},
        "template_ids": sorted({r["template_id"] for r in profile["rule_sets"]}),
        "template_map": [r["template_id"] for r in value["classifications"]],
    }


def load_report(descriptor):
    try:
        asset = descriptor["classification_asset"]
        path = Path(asset["path"])
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise CompositionError("Linked classification assets are not supported.")
        with path.open("rb") as stream:
            payload = stream.read(MAX_ASSET_BYTES + 1)
        if len(payload) > MAX_ASSET_BYTES or hashlib.sha256(payload).hexdigest() != asset["sha256"]:
            raise CompositionError("Classification evidence changed or exceeds its size limit.")
        report = validate_report(json.loads(payload))
        profile = report["profile"]
        if (
            report["accepted"] is not True
            or not can_accept(report)
            or any(
                descriptor[key] != report[key]
                for key in (
                    "groups",
                    "pages",
                    "excluded_pages",
                    "source_sha256",
                    "accepted_at",
                    "profile_sha256",
                )
            )
            or descriptor["profile_id"] != profile["profile_id"]
            or descriptor["profile_name"] != profile["name"]
            or descriptor["profile_revision"] != profile["revision"]
            or descriptor["template_ids"] != sorted({r["template_id"] for r in profile["rule_sets"]})
            or descriptor["template_map"] != [r["template_id"] for r in report["classifications"]]
        ):
            raise CompositionError("Classification evidence belongs to another source / profile / review.")
        return report
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, CompositionError):
            raise
        raise CompositionError("Classification evidence is unavailable or invalid.") from exc


def rows_for_spec(spec):
    if spec.detection_review.get("report_version") != 3:
        return []
    if not hasattr(spec, "_classification_rows"):
        validate_descriptor(
            spec.detection_review, spec.source, spec.settings.groups, spec.settings.excluded_pages
        )
        spec._classification_rows = load_report(spec.detection_review)["classifications"]
    return spec._classification_rows


def copy_asset(descriptor, directory):
    """Copy only the accepted, text-free audit; never the spatial PageIndex."""
    load_report(descriptor)
    result = copy.deepcopy(descriptor)
    asset = result["classification_asset"]
    source = Path(asset["path"])
    target = contained_path(directory, asset["sha256"][:20] + ".mailpieces.json")
    if not target.exists():
        with atomic_output(target, overwrite=False) as temporary:
            temporary.write_bytes(source.read_bytes())
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != asset["sha256"]:
                raise CompositionError("Classification changed during saving.")
    elif hashlib.sha256(target.read_bytes()).hexdigest() != asset["sha256"]:
        raise CompositionError("Saved classification asset changed.")
    asset["path"] = str(target)
    return result


def remap_report(descriptor, source, groups, selected, directory, *, original_groups=None):
    original = load_report(descriptor)
    if original_groups is None or original_groups != original["groups"]:
        raise CompositionError("Original mailpiece boundaries changed since classification. Reopen Auto Detect and review again.")
    if not isinstance(selected, list) or len(selected) != len(groups):
        raise CompositionError("Missing original-envelope classification mapping.")
    EnvelopePlan(source.pages, EnvelopeSettings(groups=groups))
    value = copy.deepcopy(original)
    rows, evidence, findings = [], [], []
    old_evidence = {e["page"]: e for e in original["evidence"]}
    for i, ((start, end), old_index) in enumerate(zip(groups, selected, strict=True), 1):
        if type(old_index) is not int or not 1 <= old_index <= len(original["groups"]):
            raise CompositionError("Unknown original envelope in classification mapping.")
        old = original["classifications"][old_index - 1]
        if end - start + 1 != old["page_count"]:
            raise CompositionError(
                "Source page counts changed within a classified mailpiece; review it again."
            )
        row = copy.deepcopy(old)
        row.update(envelope_index=i, start_page=start, end_page=end)
        rows.append(row)
        first = copy.deepcopy(old_evidence[old["start_page"]])
        first["page"] = start
        evidence.append(first)
        for finding in original["findings"]:
            if old["start_page"] <= finding["page"] <= old["end_page"]:
                finding = copy.deepcopy(finding)
                finding["page"] += start - old["start_page"]
                findings.append(finding)
    value.update(
        source_sha256=source.sha256,
        pages=source.pages,
        groups=copy.deepcopy(groups),
        classifications=rows,
        evidence=evidence,
        findings=findings,
    )
    value["edits"].append(
        {
            "action": "workflow_map",
            "original_source_sha256": original["source_sha256"],
            "selected": selected,
            "source_groups": original["groups"],
            "at": now(),
        }
    )
    return accept_report(value, directory)



def export_index(report, path, *, is_cancelled=None):
    """Export review evidence, including unresolved types, without accepting it."""
    import csv

    from composition.production.generator import _csv_value, check_cancel

    validate_report(report)
    target = Path(path).with_suffix(".csv")
    profile = report["profile"]
    with atomic_output(target) as temporary:
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["EnvelopeIndex", "StartPage", "EndPage", "PageCount", "TemplateID", "MatchedRuleID", "BoundaryEvidence", "ReviewStatus", "Accepted", "ProfileName", "ProfileRevision", "SourceSHA256"])
            for row in report["classifications"]:
                check_cancel(is_cancelled)
                values = [row["envelope_index"], row["start_page"], row["end_page"], row["page_count"], row["template_id"],
                          "; ".join(row["rule_ids"]), "; ".join(row["boundary_evidence"]), row["classification_status"],
                          str(report["accepted"]), profile["name"], profile["revision"], report.get("source_sha256", "")]
                writer.writerow([_csv_value(value) for value in values])
    return target
