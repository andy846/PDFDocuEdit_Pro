"""Frozen Mac acceptance with generated data and existing production services."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


def main(argv):
    import fitz
    from PyQt6.QtWidgets import QApplication

    from composition.engine.barcode_profiles import BarcodeProfile
    from composition.media.model import PrinterProfile, default_media
    from composition.production.model import ProductionJob
    from composition.template.model import Element, PageSpec, Template
    from core.pdf_runtime import qpdf_executable
    from core.printing import (
        PrintJob,
        PrintRenderSettings,
        PrintSession,
        prepare_print_job,
        render_print_page,
    )

    output = Path(argv[0]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setApplicationName("PDFDocuEdit-Mac-QA")
    import core.viewer as viewer_module
    from core.settings import SettingsManager
    viewer_module.SettingsManager = lambda: SettingsManager(output / "settings.json")
    viewer = viewer_module.PDFViewer()
    viewer.resize(960, 640)
    viewer.show()
    viewer._mode_controller.set_animations_enabled(False)
    viewer._mode_controller.request_mode("designer")
    app.processEvents()
    viewer.grab().save(str(output / "designer.png"))
    viewer._mode_controller.request_mode("pdf")
    app.processEvents()
    viewer.grab().save(str(output / "workspace.png"))

    counter = 0
    def worker(request):
        nonlocal counter
        counter += 1
        file = output / f"request-{counter}.json"
        events = output / f"events-{counter}.jsonl"
        request = {**request, "events_file": str(events)}
        file.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run([sys.executable, "--composition-worker", str(file)],
                                   capture_output=True, timeout=180)
        rows = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
        errors = [r for r in rows if r["event"] == "error"]
        if completed.returncode or errors:
            raise RuntimeError(f"Frozen worker failed: {errors}; {completed.stderr[-2000:]!r}")
        return next(row["result"] for row in rows if row["event"] == "result")

    version = subprocess.check_output([str(qpdf_executable()), "--version"], text=True).strip()
    catalogue = worker({"task": "fonts"})
    if not any(face["usable"] for face in catalogue["faces"]):
        raise RuntimeError("Mac installed font inventory is empty.")
    profile = BarcodeProfile.inserter().to_dict()
    template = Template(pages=[PageSpec(elements=[Element(type="i25", width_mm=100, height_mm=14,
                        barcode_profile=profile)]) for _ in range(3)], record_mode="generated",
                        generated_count=2, media={"duplex": True})
    job = ProductionJob(template.to_dict(), "", str(output / "production"))
    context = {"kind": "template", "job": asdict(job)}
    reviewed = worker({"task": "production_review_check", "directory": str(output / "review"), "context": context})
    if reviewed["status"] != "checked" or (output / "production").exists():
        raise RuntimeError(f"Frozen review failed or published output: {reviewed['issues']}")
    worker({"task": "production_review_validate", "directory": str(output / "review"),
            "snapshot_id": reviewed["snapshot_id"], "context": reviewed["context"], "acknowledge": True})
    generated = worker({"task": "generate", "job": reviewed["context"]["job"],
                       "production_review": {"directory": str(output / "review"),
                           "snapshot_id": reviewed["snapshot_id"], "context": reviewed["context"], "acknowledge": True}})
    if generated["status"] != "completed" or generated["generated_pages"] != 8 or generated["decoded_barcodes"] != 4:
        raise RuntimeError(f"Frozen I25 generation failed: {generated}")

    media = default_media()
    media["printer_profile"] = asdict(PrinterProfile(profile_version=2, backend="postscript", family="generic",
        mappings={s["id"]: {"media_type": s["id"]} for s in media["stocks"]}))
    ps_template = Template(pages=[PageSpec(elements=[Element(value="Mac production")]) for _ in range(3)],
                           record_mode="generated", generated_count=2, media=media)
    ps = worker({"task": "generate", "job": asdict(ProductionJob(ps_template.to_dict(), "", str(output / "ps")))})
    if ps["status"] != "completed" or not list(Path(ps["report_dir"]).glob("*.ps")):
        raise RuntimeError(f"Frozen PostScript output failed: {ps}")
    # The persistent print worker must restore POSIX streams in the .app.
    session = PrintSession()
    try:
        prepared = prepare_print_job(PrintJob(generated["output_pdf"], "QA", "qa"), session=session)
        settings = PrintRenderSettings(72, 600, 850, 0, 0, 0, 1, True, 0, 0)
        page, _, _ = render_print_page(prepared, 0, settings)
        if page.isNull():
            raise RuntimeError("Frozen print page is empty.")
    finally:
        session.close()
    with fitz.open(generated["output_pdf"]) as pdf:
        if len(pdf) != 8:
            raise RuntimeError("Output cannot be reopened.")
    host = viewer._mode_controller.host
    for project in list(host.projects):
        host.close_project(project, approved=True)
    viewer.close()
    app.processEvents()
    (output / "result.json").write_text(json.dumps({"status": "passed", "platform": sys.platform,
        "qpdf": version, "font_faces": len(catalogue["faces"]), "production": generated, "postscript": ps}, indent=2), encoding="utf-8")
    return 0
