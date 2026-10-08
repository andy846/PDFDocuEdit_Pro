"""Small adapters for the shared runtime review pane; no rendering logic."""
from dataclasses import asdict

from composition.review.ui import ProductionReviewPane, ReviewController


def template_state(window):
    info = window._store()
    return {"template": window.template.to_dict(), "store": info.get("store", "") if info else "",
            "records": window.record_count, "auto_repair": window.auto_repair.isChecked(),
            "output_name": window.output_name_edit.text(), "invalid": window.content_invalid,
            "fonts_pending": sorted(window.font_requests)}


def template_pane(window):
    if hasattr(window, "production_review"):
        return window.production_review
    pane = ProductionReviewPane(window)
    window.stack.addWidget(pane)
    window.tabs.addTab("Production Review")
    def edit(issue):
        if issue.get("action") == "source" and window.project_host:
            window.project_host.open_pdf_page(issue["path"], issue["page"])
            return
        window.stack.setCurrentIndex(2)
        if issue.get("action") == "media":
            window.edit_print_media()
        elif issue.get("object_id"):
            for index, page in enumerate(window.template.pages):
                if any(e.id == issue["object_id"] for e in page.elements):
                    window.tabs.setCurrentIndex(1)
                    window.select_template_page(index)
                    window.canvas.select_ids([issue["object_id"]])
                    window._show_properties(True)
                    break
    controller = ReviewController(window, pane, lambda: template_state(window), edit)
    window.undo.indexChanged.connect(controller.invalidate)
    window.auto_repair.toggled.connect(controller.invalidate)
    window.output_name_edit.edit.textChanged.connect(controller.invalidate)
    window.production_review = controller
    return controller


def open_template_review(window, output):
    from composition.production.model import ProductionJob

    from .production_settings import confirm_i25_update
    if not confirm_i25_update(window, window.template.to_dict()):
        return
    controller = template_pane(window)
    info = window._store()
    if not info:
        return
    job = ProductionJob(window.template.to_dict(), info["store"], str(output),
                        auto_repair=window.auto_repair.isChecked(), output_name=window.output_name_edit.text())
    context = {"kind": "template", "job": asdict(job), "label": window.template.name}
    controller.rebuild = lambda: window.start_production(output)
    window.tabs.setCurrentIndex(4)
    window.stack.setCurrentWidget(controller.pane)
    def generate(receipts):
        window._launch_reviewed_production(receipts[0]["context"]["job"], receipts[0])
    controller.start([context], generate)


def overlay_state(window):
    return {"project": window.spec.to_dict() if window.spec else {},
            "auto_repair": window.auto_repair.isChecked(), "invalid": window.draft_error,
            "fonts_pending": bool(window.font_token)}


def overlay_pane(window):
    if hasattr(window, "production_review"):
        return window.production_review
    pane = ProductionReviewPane(window)
    window.tabs.addTab(pane, "Production Review")
    def edit(issue):
        if issue.get("action") == "source" and window.project_host:
            window.project_host.open_pdf_page(issue["path"], issue["page"])
            return
        window.tabs.setCurrentIndex(0)
        if issue.get("action") == "media":
            window.edit_print_media()
        elif issue.get("object_id"):
            window.canvas.select_ids([issue["object_id"]])
            window.selection_changed()
            window.inspector.show()
    controller = ReviewController(window, pane, lambda: overlay_state(window), edit)
    window.undo.indexChanged.connect(controller.invalidate)
    window.auto_repair.toggled.connect(controller.invalidate)
    window.production_review = controller
    return controller


def open_overlay_review(window, output):
    from composition.overlay.model import OverlayJob
    from core.variables import VariableContext
    controller = overlay_pane(window)
    job = OverlayJob(window.spec.to_dict(), str(output), auto_repair=window.auto_repair.isChecked())
    job.variable_context = VariableContext.for_job(input_path=window.spec.source.path,
        job_id=job.job_id, job_name=window.spec.name, sequence=1).to_dict()
    controller.rebuild = lambda: window.generate_pdf(output_dir=output)
    window.tabs.setCurrentWidget(controller.pane)
    controller.start([{"kind": "overlay", "job": asdict(job), "label": window.spec.name}],
        lambda receipts: window._launch_reviewed_overlay(receipts[0]["context"]["job"], receipts[0]))
