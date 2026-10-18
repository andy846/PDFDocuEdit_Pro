"""Envelope production reports; copied source text is never put into job logs."""
from __future__ import annotations

import csv
import json
from bisect import bisect_left, bisect_right
from dataclasses import asdict

from composition.production.generator import _csv_value


def row(writer, values):
    writer.writerow([_csv_value(value) for value in values])


def write_summary(directory,result,spec):
    review = spec.detection_review
    if review.get("report_version") == 3:
        from composition.pdf_source.classification import load_report
        review = load_report(review)
    value=asdict(result)
    settings=asdict(spec.settings)
    if spec.media.get("enabled"):
        settings["duplex"]=spec.media["duplex"]
    value.update(log_version=1,job_type="pdf_overlay",source={"path":spec.source.path,
                 "sha256":spec.source.sha256,"pages":spec.source.pages},settings=settings,media=spec.media,
                 detection_review=spec.detection_review,
                 source_link=spec.source_link,
                 control_barcode_required=spec.requires_control_barcode,
                 required_barcode_scope=spec.required_scope if spec.requires_control_barcode else None,
                 barcode_profiles=[asdict(obj.profile) for obj in spec.objects if obj.profile])
    if spec.customer_profile:
        value["customer_production_profile"] = spec.customer_profile
    if review.get("report_version") == 3:
        value["mailpiece_classification"] = {
            "profile_id": review["profile"]["profile_id"], "profile_name": review["profile"]["name"],
            "profile_revision": review["profile"]["revision"], "profile_sha256": review["profile_sha256"],
            "source_sha256": review["source_sha256"], "accepted_at": review["accepted_at"],
            "edits": review["edits"], "template_counts": dict(__import__("collections").Counter(r["template_id"] for r in review["classifications"]))}
        with (directory/"classifications.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            row(writer, ["EnvelopeIndex", "EnvelopeSeq", "StartPage", "EndPage", "PageCount", "TemplateID", "MatchedRuleID", "BoundaryEvidence", "ReviewStatus", "ProfileID", "ProfileRevision", "SourceSHA256"])
            for r in review["classifications"]:
                row(writer, [r["envelope_index"], spec.settings.sequence(r["envelope_index"]), r["start_page"], r["end_page"], r["page_count"],
                             r["template_id"], "; ".join(r["rule_ids"]), "; ".join(r["boundary_evidence"]),
                             "Operator accepted (" + r["classification_status"] + ")", review["profile"]["profile_id"], review["profile"]["revision"], review["source_sha256"]])
    (directory/"job.json").write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (directory/"control.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        values=asdict(result)
        values.pop("warnings")
        values.pop("font_scan")
        values.update(source_sha256=spec.source.sha256,duplex=settings["duplex"],
                      control_barcode_required=spec.requires_control_barcode)
        row(writer,values.keys())
        row(writer,values.values())

    if spec.detection_review:
        with (directory/"detection.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            row(writer,["Envelope","Source start","Source end","Pages","Review","Warnings","Boundary evidence","End basis"])
            findings=sorted(review.get("findings", []), key=lambda finding: finding["page"])
            finding_pages=[finding["page"] for finding in findings]
            evidence = {e["page"]: e for e in review.get("evidence", [])}
            for index,(start,end) in enumerate(spec.settings.groups,1):
                messages=[f"Page {f['page']}: {f['message']}" for f in
                          findings[bisect_left(finding_pages,start):bisect_right(finding_pages,end)]]
                boundary = evidence.get(start, {})
                row(writer,[index,start,end,end-start+1,"Operator accepted","; ".join(messages),
                            "; ".join(boundary.get("matched", [])), boundary.get("end_basis", "operator_edited")])
