"""Serial PDF batch adapter: approve analyses, isolate failures, preserve successes."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from composition.production.model import new_job_id
from core.io_atomic import atomic_output
from core.variables import VariableContext, plan_outputs

from .analysis import PdfCancelled, analyse, check_cancel
from .model import PdfOperationPlan
from .service import execute


def analyse_batch(sources, options, *, passwords=None, progress=None, is_cancelled=None):
    if not sources or len(sources) > 10000:
        raise ValueError("Select between 1 and 10,000 PDFs.")
    rows = []
    for index, source in enumerate(sources, 1):
        check_cancel(is_cancelled)
        try:
            plan = analyse(source, options, password=(passwords or {}).get(str(source), ""), is_cancelled=is_cancelled)
            rows.append({"source": str(source), "plan": plan.to_dict(), "error": ""})
        except PdfCancelled:
            raise
        except Exception as exc:
            rows.append({"source": str(source), "plan": None, "error": str(exc)})
        if progress:
            progress(index, len(sources), f"Analyzed file {index}/{len(sources)}")
    return rows


def execute_batch(analyses, output_dir, output_name, *, passwords=None, progress=None, is_cancelled=None):
    identity = new_job_id()
    root = Path(output_dir).expanduser().resolve() / ("batch-" + identity)
    frozen_at = datetime.now().astimezone()
    contexts = [VariableContext.for_job(input_path=row["source"], job_id=f"{identity}-{i:04d}", batch_id=identity, sequence=i, frozen_at=frozen_at)
                for i, row in enumerate(analyses, 1)]
    # One complete plan before any publication, including blocked items. This
    # detects collisions introduced by Windows sanitisation as well as case.
    names = plan_outputs(contexts, output_name, root, sources=[row["source"] for row in analyses])
    root.mkdir(parents=True, exist_ok=False)
    results, cancelled = [], False
    for index, (row, (_, naming)) in enumerate(zip(analyses, names, strict=True), 1):
        if is_cancelled and is_cancelled():
            cancelled = True
        if cancelled:
            result = {"source": row["source"], "status": "cancelled", "error": "Not processed after cancellation."}
        elif not row.get("plan") or row.get("error"):
            result = {"source": row["source"], "status": "failed", "error": row.get("error", "Analysis unavailable.")}
        else:
            try:
                password = (passwords or {}).get(row["source"], "")
                result = execute(PdfOperationPlan.from_dict(row["plan"]), root, password=password,
                                 output_password=password if row["plan"]["encrypted"] else "",
                                 job_id=f"{identity}-{index:04d}", output_name=naming.value,
                                 is_cancelled=is_cancelled)
            except PdfCancelled as exc:
                cancelled = True
                result = {"source": row["source"], "status": "cancelled", "error": str(exc)}
            except Exception as exc:
                result = {"source": row["source"], "status": "failed", "error": str(exc)}
        if not result.get("report_dir"):
            with atomic_output(root / f"{index:04d}-failed.json", overwrite=False) as temp:
                temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        if progress:
            progress(index, len(analyses), f"Finished file {index}/{len(analyses)} · {result['status']}")
    summary = {"batch_id": identity, "status": "cancelled" if cancelled else
               "completed" if all(r["status"] == "completed" for r in results) else "needs_review",
               "files": results, "report_dir": str(root)}
    with atomic_output(root / "control.csv") as temp, temp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Source", "Output", "Status", "Changes", "Warnings", "Error"])
        for result in results:
            values = [result["source"], result.get("output_pdf", ""), result["status"],
                      json.dumps(result.get("changes", []), ensure_ascii=False),
                      "; ".join(result.get("warnings", [])), result.get("error", "")]
            writer.writerow(["'" + v if v.startswith(("=", "+", "-", "@")) else v for v in values])
    with atomic_output(root / "batch.json") as temp:
        temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
