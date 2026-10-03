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
    value=asdict(result)
    value.update(log_version=1,job_type="pdf_overlay",source={"path":spec.source.path,
                 "sha256":spec.source.sha256,"pages":spec.source.pages},settings=asdict(spec.settings),
                 detection_review=spec.detection_review,
                 source_link=spec.source_link,
                 control_barcode_required=spec.requires_control_barcode,
                 required_barcode_scope=spec.required_scope if spec.requires_control_barcode else None,
                 barcode_profiles=[asdict(obj.profile) for obj in spec.objects if obj.profile])
    (directory/"job.json").write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (directory/"control.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        values=asdict(result)
        values.pop("warnings")
        values.pop("font_scan")
        values.update(source_sha256=spec.source.sha256,duplex=spec.settings.duplex,
                      control_barcode_required=spec.requires_control_barcode)
        row(writer,values.keys())
        row(writer,values.values())

    if spec.detection_review:
        with (directory/"detection.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            row(writer,["Envelope","Source start","Source end","Pages","Review","Warnings","Boundary evidence","End basis"])
            findings=sorted(spec.detection_review.get("findings", []), key=lambda finding: finding["page"])
            finding_pages=[finding["page"] for finding in findings]
            evidence = {e["page"]: e for e in spec.detection_review.get("evidence", [])}
            for index,(start,end) in enumerate(spec.settings.groups,1):
                messages=[f"Page {f['page']}: {f['message']}" for f in
                          findings[bisect_left(finding_pages,start):bisect_right(finding_pages,end)]]
                boundary = evidence.get(start, {})
                row(writer,[index,start,end,end-start+1,"Operator accepted","; ".join(messages),
                            "; ".join(boundary.get("matched", [])), boundary.get("end_basis", "operator_edited")])
