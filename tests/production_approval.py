"""Explicit review/approve helpers for existing end-to-end production tests.

No validation bypass: blocked review raises ReviewBlocked and creates no PDF.
Negative authorization tests call the real entry points directly.
"""
from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

from composition.review.authorization import ProductionAuthorization, ReviewSession, approve_snapshot
from composition.review.service import create_review
from composition.template.model import CompositionError


class ReviewBlocked(CompositionError):
    def __init__(self, packet, folder=None):
        self.packet = packet
        self.diagnostics = {p.name: p.read_bytes() for p in Path(folder).glob("*.csv")} if folder else {}
        super().__init__("; ".join(i["reason"] for i in packet["issues"]) or "Production review blocked")


def review_contexts(directory, contexts, session, *, external_values=None):
    receipts = []
    for context in contexts:
        packet = create_review(directory, context, session=session, external_values=external_values)
        if not packet["complete"] or packet["status"] != "checked":
            raise ReviewBlocked(packet, Path(directory) / "production-review" / packet["snapshot_id"])
        context = packet["context"]
        receipt = {"directory": str(directory), "snapshot_id": packet["snapshot_id"], "context": context, "acknowledge": True}
        receipt["authorization"] = approve_snapshot(directory, packet["snapshot_id"], context, session=session, acknowledge=True)
        receipts.append(receipt)
    return receipts


def generate(job, **kwargs):
    from composition.production.generator import generate as engine
    if "authorization" in kwargs:
        return engine(job, **kwargs)
    with tempfile.TemporaryDirectory(prefix="test-production-review-") as directory:
        session = ReviewSession.new()
        receipts = review_contexts(directory, [{"kind": "template", "job": asdict(job)}], session)
        return engine(job, authorization=ProductionAuthorization(receipts, session), **kwargs)


def overlay_generate(job, **kwargs):
    from composition.overlay.generator import generate as engine
    if "authorization" in kwargs:
        return engine(job, **kwargs)
    with tempfile.TemporaryDirectory(prefix="test-overlay-review-") as directory:
        session = ReviewSession.new()
        receipts = review_contexts(directory, [{"kind": "overlay", "job": asdict(job)}], session, external_values=kwargs.get("external_values"))
        return engine(job, authorization=ProductionAuthorization(receipts, session), **kwargs)


def execute_batch(spec, run, output_dir, **kwargs):
    from workflow.batch import execute_batch as engine
    from workflow.production_review import prepare_contexts
    if "authorization" in kwargs:
        return engine(spec, run, output_dir, **kwargs)
    with tempfile.TemporaryDirectory(prefix="test-batch-review-") as directory:
        session = ReviewSession.new()
        request = {"review_kind": "batch", "spec": spec.to_dict(), "batch": run.to_dict(), "output_dir": str(output_dir)}
        contexts = prepare_contexts(request)["contexts"]
        receipts = review_contexts(directory, contexts, session)
        return engine(spec, run, output_dir, authorization=ProductionAuthorization(receipts, session), **kwargs)


def execute_routes(spec, run, directory, output, **kwargs):
    from workflow.branch_engine import execute_routes as engine
    from workflow.production_review import prepare_contexts
    if "authorization" in kwargs or run.get("target_id") or not any(j["approved"] and j["status"] == "Ready" for j in run["jobs"]):
        return engine(spec, run, directory, output, **kwargs)
    session = ReviewSession.new()
    request = {"review_kind": "branch", "spec": spec.to_dict(), "run": run, "directory": str(directory), "output_dir": str(output)}
    contexts = prepare_contexts(request)["contexts"]
    receipts = review_contexts(directory, contexts, session)
    return engine(spec, run, directory, output, authorization=ProductionAuthorization(receipts, session), **kwargs)


def execute(spec, run, directory, **kwargs):
    from workflow.engine import execute as engine
    from workflow.production_review import prepare_contexts
    if kwargs.get("until", "review") != "output" or "authorization" in kwargs:
        return engine(spec, run, directory, **kwargs)
    session = ReviewSession.new()
    request = {"review_kind": "pdf", "spec": spec.to_dict(), "run": asdict(run), "directory": str(directory),
               "output_dir": spec.node("output").params.get("directory", "")}
    contexts = prepare_contexts(request)["contexts"]
    receipts = review_contexts(directory, contexts, session)
    return engine(spec, run, directory, authorization=ProductionAuthorization(receipts, session), **kwargs)


def dispatch(request):
    from composition.designer.process import approval_session
    from composition.worker import dispatch as engine
    # UI transport simulations use the same private session as a real Worker.
    session = approval_session()
    if request["task"] in ("generate", "overlay_generate") and not request.get("production_review"):
        with tempfile.TemporaryDirectory(prefix="test-worker-review-") as directory:
            kind = "template" if request["task"] == "generate" else "overlay"
            receipts = review_contexts(directory, [{"kind": kind, "job": request["job"]}], session)
            return engine({**request, "job": receipts[0]["context"]["job"], "production_review": receipts[0]}, session=session)
    return engine(request, session=session)


def expect_blocked(action):
    """Return actual review evidence; never fabricate a production JobResult."""
    try:
        action()
    except ReviewBlocked as exc:
        assert exc.packet["status"] == "blocked" and not exc.packet["complete"]
        return exc
    raise AssertionError("Production was not blocked by review")
