"""Session-authenticated production approval; independent of Qt and editor state.

Keys travel only through the worker private input channel. This protects against
request/project tampering, not a hostile program controlling the local process.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import asdict

from composition.template.model import CompositionError


def _encoded(value):
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


class ReviewSession:
    def __init__(self, identity, key, *, clock=time.time):
        if not isinstance(identity, str) or len(identity) != 32 or not isinstance(key, bytes) or len(key) != 32:
            raise CompositionError("Invalid production approval session.")
        self.identity, self._key, self.clock = identity, key, clock

    @classmethod
    def new(cls, *, clock=time.time):
        return cls(uuid.uuid4().hex, secrets.token_bytes(32), clock=clock)

    @classmethod
    def from_private(cls, raw):
        try:
            return cls(raw["id"], bytes.fromhex(raw["key"]))
        except (TypeError, ValueError, KeyError) as exc:
            raise CompositionError("Invalid private approval channel.") from exc

    def private_payload(self):
        return {"id": self.identity, "key": self._key.hex()}

    def seal(self, payload):
        body = {"session": self.identity, **copy.deepcopy(payload)}
        return {**body, "mac": hmac.new(self._key, _encoded(body), hashlib.sha256).hexdigest()}

    def verify(self, sealed, kind):
        try:
            body = {k: v for k, v in sealed.items() if k != "mac"}
            expected = hmac.new(self._key, _encoded(body), hashlib.sha256).hexdigest()
            if (body.get("session") != self.identity or body.get("kind") != kind
                    or not isinstance(sealed.get("mac"), str) or not hmac.compare_digest(expected, sealed["mac"])):
                raise ValueError("signature")
            return body
        except (TypeError, ValueError, AttributeError) as exc:
            raise CompositionError("Production approval is missing, altered or from a previous session. Review again.") from exc

    def seal_snapshot(self, packet, rows_hash):
        return self.seal({"kind": "review", "packet": packet, "rows_sha256": rows_hash})

    def verify_snapshot(self, packet, rows_hash):
        seal = packet.get("seal")
        body = self.verify(seal, "review")
        if body["packet"] != {k: v for k, v in packet.items() if k != "seal"} or body["rows_sha256"] != rows_hash:
            raise CompositionError("Checked snapshot was altered. Review again.")


def approve_snapshot(directory, identity, context, *, session, acknowledge=False, is_cancelled=None):
    from .service import validate_snapshot
    if not isinstance(session, ReviewSession):
        raise CompositionError("A private production approval session is required.")
    packet = validate_snapshot(directory, identity, context, warnings_acknowledged=acknowledge,
                               is_cancelled=is_cancelled, session=session)
    return session.seal({"kind": "approval", "id": uuid.uuid4().hex,
        "issued": session.clock(), "expires": session.clock() + 24 * 60 * 60,
        "directory": str(directory), "snapshot_id": identity, "context": context,
        "fingerprint": packet["fingerprint"], "acknowledge": bool(acknowledge)})


class ProductionAuthorization:
    def __init__(self, receipts, session):
        if not isinstance(session, ReviewSession) or not isinstance(receipts, list) or not receipts:
            raise CompositionError("Review and explicitly confirm production before generating.")
        self.session, self.receipts = session, copy.deepcopy(receipts)
        self.contexts = []
        self.started = False
        self.parent = None
        seen = set()
        for receipt in self.receipts:
            if not isinstance(receipt, dict):
                raise CompositionError("Malformed production approval.")
            body = session.verify(receipt.get("authorization"), "approval")
            if body["id"] in seen:
                raise CompositionError("Duplicate production approval.")
            seen.add(body["id"])
            for key in ("directory", "snapshot_id", "context", "acknowledge"):
                if body[key] != receipt.get(key):
                    raise CompositionError("Production approval binding was altered.")
            self.contexts.append(copy.deepcopy(body["context"]))
        self.validate()

    def validate(self, *, is_cancelled=None):
        from .service import validate_snapshot
        if self.parent is not None:
            return self.parent.validate(is_cancelled=is_cancelled)
        for receipt in self.receipts:
            body = self.session.verify(receipt["authorization"], "approval")
            if not self.started and not body["issued"] <= self.session.clock() < body["expires"]:
                raise CompositionError("Production approval expired. Review again.")
            packet = validate_snapshot(body["directory"], body["snapshot_id"], body["context"],
                warnings_acknowledged=body["acknowledge"], is_cancelled=is_cancelled, session=self.session)
            if packet["fingerprint"] != body["fingerprint"]:
                raise CompositionError("Production review changed. Review again.")

    def require_job(self, kind, job, *, is_cancelled=None):
        raw = asdict(job) if not isinstance(job, dict) else job
        def same_job(context):
            candidate = copy.deepcopy(raw)
            # Review resolves derived job counters before signing. They are not
            # editable settings; legacy headless callers may omit these keys.
            if kind == "template":
                current = candidate.get("variable_context", {}).get("namespaces", {}).get("job", {})
                expected = context["job"].get("variable_context", {}).get("namespaces", {}).get("job", {})
                if "records" in expected:
                    current.setdefault("records", expected["records"])
                current.setdefault("id", candidate.get("job_id"))
            return context["job"] == candidate
        matches = [c for c in self.contexts if c["kind"] == kind and same_job(c)]
        if len(matches) != 1:
            raise CompositionError("Production job or destination differs from its approval. Review again.")
        self.validate(is_cancelled=is_cancelled)
        self.started = True
        return matches[0]

    def require_workflow(self, spec, selected=None):
        if any(spec.to_dict() not in (c.get("binding", {}).get("owner_spec"), c.get("binding", {}).get("execution_spec")) for c in self.contexts):
            raise CompositionError("Workflow differs from its production approval.")
        if selected is not None and {c.get("identity") for c in self.contexts} != set(selected):
            raise CompositionError("Approved production selection changed. Review every selected job again.")
        self.validate()
        self.started = True

    def require_output_plan(self, job_id, directory, outputs):
        from pathlib import Path
        matches = [c for c in self.contexts if c["job"]["job_id"] == job_id]
        if (len(matches) != 1 or Path(matches[0]["job"]["output_dir"]).resolve() != Path(directory).resolve()
                or matches[0].get("outputs", []) != outputs):
            raise CompositionError("Output plan differs from its production approval.")
        self.validate()
        self.started = True
        return matches[0]

    def for_jobs(self, identities):
        chosen = [r for r in self.receipts if r["context"].get("identity") in set(identities)]
        if {r["context"].get("identity") for r in chosen} != set(identities):
            raise CompositionError("Missing approval for selected jobs.")
        child = object.__new__(ProductionAuthorization)
        child.session, child.receipts = self.session, copy.deepcopy(chosen)
        child.contexts = [copy.deepcopy(r["context"]) for r in chosen]
        child.parent, child.started = None, self.started
        child.validate()
        return child

    def for_staging(self, kind, job, output_dir):
        """Only trusted engines derive an in-memory grant for their owned scratch."""
        context = copy.deepcopy(self.require_job(kind, job))
        context["job"]["output_dir"] = str(output_dir)
        child = object.__new__(ProductionAuthorization)
        child.session, child.receipts, child.contexts = self.session, self.receipts, [context]
        child.parent, child.started = self, True
        return child


def require_authorization(value):
    if not isinstance(value, ProductionAuthorization):
        raise CompositionError("Review and explicitly confirm production before generating.")
    return value
