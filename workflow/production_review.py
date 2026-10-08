"""Adapters from checked workflow inputs to the shared composition review."""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path

from composition.production.model import ProductionJob
from composition.review.service import validate_snapshot
from composition.template.model import CompositionError


def batch_context(spec, job, root, *, owner_spec=None):
    from .batch import _signature
    signature, _, _, _ = _signature(spec, job)
    if job.status != "Ready" or not job.approved or not job.prepared_template or signature != job.signature:
        raise CompositionError("Check and explicitly approve this workflow job before production review.")
    identity = job.variable_context.get("namespaces", {}).get("job", {}).get("id")
    if not identity:
        raise CompositionError("Check this job again to reserve its production identity.")
    if (root / identity).exists() or (root / (identity + "-failed")).exists():
        raise CompositionError("This job already has output. Choose a different output folder before review.")
    prepared = ProductionJob(job.prepared_template, job.record_store, str(root), job_id=identity,
        auto_repair=bool(spec.node("compose").params.get("auto_repair", True)), output_name=job.output_name,
        variable_context=copy.deepcopy(job.variable_context))
    return {"kind": "template", "job": asdict(prepared), "label": job.name, "identity": job.id,
        "outputs": job.data_summary.get("outputs", []),
        "binding": {"owner_spec": (owner_spec or spec).to_dict(), "job_signature": signature,
                    "data_summary": copy.deepcopy(job.data_summary),
                    "files": [job.template_path, job.data_path, *job.snapshot_hashes]}}


def prepare_contexts(request, *, progress=None, is_cancelled=None):
    from .batch import BatchRun
    from .model import WorkflowRun, WorkflowSpec
    kind = request["review_kind"]
    spec = WorkflowSpec.from_dict(request["spec"])
    output = Path(request["output_dir"]).resolve()
    if kind == "batch":
        batch = BatchRun.from_dict(request["batch"])
        return {"contexts": [batch_context(spec, job, output / ("batch-" + batch.batch_id)) for job in batch.jobs
                             if job.approved and job.status == "Ready"]}
    if kind == "branch":
        from .branch_engine import _check_current, _location
        run = request["run"]
        _location(request["directory"], run)
        _check_current(spec, run)
        contexts = []
        for entry in run["jobs"]:
            if entry["approved"] and entry["status"] == "Ready":
                child = WorkflowSpec.from_dict(entry["spec"])
                batch = BatchRun.from_dict(entry["batch"])
                contexts.append(batch_context(child, batch.jobs[0],
                    output / ("batch-" + run["batch_id"]) / entry["id"], owner_spec=spec))
        return {"contexts": contexts}
    if kind == "pdf":
        from .engine import context_fingerprint
        from .pdf_pipeline import _produce
        run = WorkflowRun(**request["run"])
        if not run.accepted or run.fingerprint != context_fingerprint(spec, include_overlay=False):
            raise CompositionError("Check and accept the PDF workflow review first.")
        if Path(spec.node("output").params.get("directory", "")).resolve() != output:
            raise CompositionError("Apply the selected output folder before production review.")
        context = _produce(spec, run, Path(request["directory"]), progress=progress,
                           is_cancelled=is_cancelled, _review_only=True)
        return {"contexts": [context]}
    raise CompositionError("Unknown workflow production review kind.")


def validate_receipts(request, *, is_cancelled=None):
    """Validate settings/source bindings without changing any workflow approval."""
    from .batch import BatchRun, _signature
    from .model import WorkflowSpec
    receipts = request.get("production_reviews", [])
    spec = WorkflowSpec.from_dict(request["spec"])
    expected = {}
    output_node = spec.node("output")
    output = Path(request.get("output_dir") or (output_node.params.get("directory", "") if output_node else "")).resolve()
    if request["operation"] == "batch_run":
        batch = BatchRun.from_dict(request["batch"])
        for job in batch.jobs:
            if job.approved and job.status == "Ready":
                expected[job.id] = (_signature(spec, job)[0], output / ("batch-" + batch.batch_id))
        if set(request.get("approved", expected)) != set(expected):
            raise CompositionError("The approved job selection changed. Review every selected job again.")
    elif request["operation"] == "branch_run":
        from .branch_engine import _check_current
        run = request["run"]
        _check_current(spec, run)
        for entry in run["jobs"]:
            if entry["approved"] and entry["status"] == "Ready":
                child = WorkflowSpec.from_dict(entry["spec"])
                job = BatchRun.from_dict(entry["batch"]).jobs[0]
                expected[job.id] = (_signature(child, job)[0], output / ("batch-" + run["batch_id"]) / entry["id"])
    if expected and ({r["context"].get("identity") for r in receipts} != set(expected) or len(receipts) != len(expected)):
        raise CompositionError("The approved job selection changed. Review every selected job again.")
    if request["operation"] in ("batch_run", "branch_run") and not expected:
        raise CompositionError("No approved production jobs remain. Check and review again.")
    if request["operation"] == "run" and len(receipts) != 1:
        raise CompositionError("Review the current PDF production job before generating.")
    for receipt in receipts:
        context = receipt["context"]
        if context["binding"].get("owner_spec") != request["spec"]:
            raise CompositionError("Workflow settings changed. Review production again.")
        if expected:
            signature, folder = expected[context["identity"]]
            if signature != context["binding"].get("job_signature") or folder != Path(context["job"]["output_dir"]).resolve():
                raise CompositionError("Production job settings or output folder changed. Check again.")
        elif Path(context["job"]["output_dir"]).resolve() != output:
            raise CompositionError("Output folder changed. Review production again.")
        validate_snapshot(receipt["directory"], receipt["snapshot_id"], context,
                          warnings_acknowledged=receipt.get("acknowledge", False), is_cancelled=is_cancelled)


def workflow_state(window):
    state = {"spec": window.spec.to_dict(), "draft": window.draft_error}
    if hasattr(window, "batch"):
        state["batch"] = window.batch.to_dict()
    elif isinstance(window.run, dict):
        state["run"] = window.run
    else:
        state["run"] = {"accepted": window.run.accepted, "groups": window.run.groups,
                        "fingerprint": window.run.fingerprint, "data_set": window.run.data_set}
    return state


def pane_for(window):
    if hasattr(window, "production_review"):
        return window.production_review
    from composition.review.ui import ProductionReviewPane, ReviewController
    pane = ProductionReviewPane(window)
    window.tabs.addTab(pane, "Production Review")
    def edit(issue):
        if issue.get("action") == "source" and window.project_host:
            window.project_host.open_pdf_page(issue["path"], issue["page"])
            return
        controller = window.production_review
        selected = controller.pane.jobs.currentIndex()
        context = controller.contexts[max(0, selected)] if controller.contexts else None
        if context and context["kind"] == "template" and window.project_host:
            files = context.get("binding", {}).get("files", [])
            template = next((p for p in files if str(p).lower().endswith(".pdcx")), None)
            if template:
                project = window.project_host.open_project(template)
                if project and issue.get("object_id"):
                    for index, page in enumerate(project.template.pages):
                        if any(e.id == issue["object_id"] for e in page.elements):
                            project.tabs.setCurrentIndex(1)
                            project.select_template_page(index)
                            project.canvas.select_ids([issue["object_id"]])
                            project._show_properties(True)
                            break
                return
        window.tabs.setCurrentWidget(window.review_page)
        if issue.get("action") == "media" and window.spec.node("media_assignment"):
            window.select_node(window.spec.node("media_assignment").id)
        elif issue.get("object_id") and hasattr(window, "edit_overlay"):
            window.edit_overlay()
    controller = ReviewController(window, pane, lambda: workflow_state(window), edit)
    window.undo.indexChanged.connect(controller.invalidate)
    window.production_review = controller
    return controller


def open_workflow_review(window, request, continuation):
    controller = pane_for(window)
    controller.cancel()
    window.tabs.setCurrentWidget(controller.pane)
    controller.pane.status.setText("Preparing checked workflow production inputs…")
    request = copy.deepcopy(request)
    request["spec"] = window.spec.to_dict()
    if request["review_kind"] == "batch":
        request["batch"] = window.batch.to_dict()
    elif request["review_kind"] == "branch":
        request["run"] = copy.deepcopy(window.run)
    else:
        request["run"] = asdict(window.run)
    controller.rebuild = lambda: open_workflow_review(window, request, continuation)
    def prepared(result):
        if not result["contexts"]:
            controller.pane.status.setText("No approved production jobs. Check and approve jobs first.")
            return
        controller.start(result["contexts"], continuation)
    # Workflow request callbacks run after worker teardown and retain its reference.
    window.request({"operation": "production_review_prepare", "spec": window.spec.to_dict(),
        "directory": str(window.directory), **request}, prepared)
