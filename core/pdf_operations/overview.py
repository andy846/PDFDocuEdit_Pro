"""Read-only overview composed from the existing PDF and font inspectors."""
from .analysis import PdfCancelled, analyse, check_cancel
from .model import PdfOptions


def analyze_overview(sources, *, password="", policy="print", progress=None, is_cancelled=None):
    from core.font_preflight.inventory import analyze

    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= 10000 or any(not isinstance(p, str) for p in sources):
        raise ValueError("Choose between 1 and 10,000 PDF source paths.")
    files = []
    for index, source in enumerate(sources, 1):
        check_cancel(is_cancelled)
        row = {"source": source, "status": "ANALYZED", "errors": {}}
        for section, callback in (
            ("pdf", lambda source=source, index=index: analyse(source, PdfOptions(operation="repair", annotations=False),
                                    password=password, is_cancelled=is_cancelled,
                                    progress=lambda done, total, message, index=index: progress(done, total, f"PDF {index}/{len(sources)} · {message}") if progress else None)),
            ("fonts", lambda source=source, index=index: analyze(source, password=password, policy=policy,
                                      is_cancelled=is_cancelled,
                                      progress=lambda done, total, message, index=index: progress(done, total, f"Fonts {index}/{len(sources)} · {message}") if progress else None)),
        ):
            try:
                row[section] = callback().to_dict()
            except PdfCancelled:
                raise
            except Exception as exc:
                check_cancel(is_cancelled)
                row["errors"][section] = str(exc)
                row["status"] = "NEEDS_REVIEW"
        if row.get("pdf") and row.get("fonts") and row["pdf"]["source_sha256"] != row["fonts"]["source_sha256"]:
            row.pop("pdf")
            row.pop("fonts")
            row["errors"] = {"source": "Source changed between checks. Analyze again."}
            row["status"] = "FAILED"
        if not row.get("pdf") and not row.get("fonts"):
            row["status"] = "FAILED"
        if row["status"] == "ANALYZED" and (row.get("pdf", {}).get("issues") or row.get("fonts", {}).get("issues") or
                not row.get("fonts", {}).get("complete", True) or any(f["status"] not in {"EMBEDDED", "BASE14_POLICY_EXEMPT"} for f in row.get("fonts", {}).get("resources", []))):
            row["status"] = "NEEDS_REVIEW"
        if row.get("pdf", {}).get("diagnostics", {}).get("qpdf", {}).get("status") in {"Error", "Warning", "Not checked"}:
            if row["status"] == "ANALYZED":
                row["status"] = "NEEDS_REVIEW"
        files.append(row)
    return {"kind": "analysis", "files": files}
