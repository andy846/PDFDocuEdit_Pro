"""Explicit programmatic review/confirmation using the GUI's production contract."""
from __future__ import annotations

from composition.template.model import CompositionError

from .authorization import ProductionAuthorization, ReviewSession, approve_snapshot
from .service import create_review


def approve_checked_contexts(contexts, directory, *, confirm, warnings_acknowledged=False, session=None):
    """CLI/batch callers must supply an explicit operator/automation decision."""
    if not callable(confirm) or not contexts:
        raise CompositionError("Explicit production confirmation is required.")
    session = session or ReviewSession.new()
    checked = [create_review(directory, context, session=session) for context in contexts]
    if any(not packet["complete"] or packet["status"] != "checked" for packet in checked):
        reasons = [issue["reason"] for packet in checked for issue in packet["issues"]]
        raise CompositionError("Production review blocked: " + "; ".join(reasons))
    if confirm(checked) is not True:
        raise CompositionError("Production was not confirmed.")
    receipts = []
    for packet in checked:
        context = packet["context"]
        receipt = {"directory": str(directory), "snapshot_id": packet["snapshot_id"], "context": context,
                   "acknowledge": bool(warnings_acknowledged)}
        receipt["authorization"] = approve_snapshot(directory, packet["snapshot_id"], context, session=session,
                                                    acknowledge=warnings_acknowledged)
        receipts.append(receipt)
    return ProductionAuthorization(receipts, session)
