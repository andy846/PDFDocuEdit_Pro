"""Font operations over the existing authenticated PDF worker transport."""

from .inventory import analyze
from .matching import evaluate_sources
from .service import analyze_batch, repair_batch, repair_job


def dispatch(request, secrets, *, progress=None, is_cancelled=None):
    shared = {
        "policy": request.get("policy", "print"),
        "password": secrets.get("password", ""),
        "progress": progress,
        "is_cancelled": is_cancelled,
    }
    if request["task"] == "font_analyze_batch":
        return analyze_batch(request["sources"], **shared)
    if request["task"] == "font_analyze":
        inventory = analyze(request["source"], **shared)
        return {"inventory": inventory.to_dict()}
    if request["task"] == "font_match":
        inventory = analyze(request["source"], **shared)
        decisions = evaluate_sources(
            request["source"],
            inventory,
            request.get("selections", {}),
            password=shared["password"],
            is_cancelled=is_cancelled,
        )
        return {"inventory": inventory.to_dict(), "matches": [m.to_dict() for m in decisions]}
    if request["task"] == "font_repair":
        if request.get("scan_only"):
            raise ValueError("Original Editor document is scan-only; repair is blocked.")
        return repair_job(
            request["source"],
            request["output_dir"],
            request.get("selections", {}),
            request.get("reference", ""),
            authorized_reference=request.get("authorized_reference") is True,
            **shared,
        )
    if request["task"] == "font_repair_batch":
        if request.get("scan_only"):
            raise ValueError("Scan-only source cannot be repaired.")
        return repair_batch(
            request["jobs"], request["output_dir"], progress=progress, is_cancelled=is_cancelled
        )
    if request["task"] == "font_catalogue":
        from fontTools.ttLib import TTFont

        from composition.engine.system_fonts import installed_font_files
        from core.pdf_operations.analysis import check_cancel

        from .matching import font_source

        names = set(request.get("names", []))
        candidates = []
        paths = installed_font_files()
        for index, path in enumerate(paths, 1):
            check_cancel(is_cancelled)
            try:
                if path.stat().st_size > 64 * 1024 * 1024:
                    continue
                with TTFont(path, lazy=True) as font:
                    face = font["name"].getDebugName(6)
                if face in names:
                    source = font_source(path)
                    candidates.append({"path": str(path), **source.report()})
            except Exception:
                continue
            if progress and index % 20 == 0:
                progress(index, len(paths), "Inspecting installed original-face candidates")
        return {"candidates": candidates}
    raise ValueError("Unknown font operation.")
