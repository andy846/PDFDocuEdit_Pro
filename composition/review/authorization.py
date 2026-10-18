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
    if type(acknowledge) is not bool:
        raise CompositionError("Production warning acknowledgement must be a boolean.")
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
        if len(self.contexts) != len(self.receipts):
            raise CompositionError("Approval context changed.")
        for context, receipt in zip(self.contexts, self.receipts, strict=True):
            body = self.session.verify(receipt["authorization"], "approval")
            if context != body["context"]:
                raise CompositionError("Approval context changed.")
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
        self.require_destination(raw["output_dir"], raw["job_id"])
        self.started = True
        return matches[0]

    def require_destination(self, directory, job_id=None):
        from pathlib import Path

        from core.output_safety import contained_path
        contexts = [c for c in self.contexts if job_id is None or c["job"]["job_id"] == job_id]
        if not contexts:
            raise CompositionError("Missing approval for this production destination.")
        try:
            actual = Path(directory).resolve()
            for context in contexts:
                binding = context.get("binding", {})
                expected = Path(binding["output_anchor"])
                scope = Path(binding.get("output_root", str(expected)))
                checked = contained_path(scope, *expected.relative_to(scope).parts)
                if checked != expected or actual != expected:
                    raise ValueError("destination differs from its checked physical location")
            return expected
        except (KeyError, ValueError, OSError, TypeError) as exc:
            raise CompositionError("Production destination differs from approval or traverses a symlink/junction. Review again: " + str(exc)) from exc

    def require_execution_database(self, database):
        from pathlib import Path
        if (len(self.contexts) != 1 or not self.contexts[0].get("external_database")
                or Path(database).resolve() != Path(self.contexts[0]["external_database"]).resolve()):
            raise CompositionError("Execution extraction database differs from production review. Check again.")
        return self.contexts[0]["external_database"]

    def require_workflow(self, spec, selected=None):
        if any(spec.to_dict() not in (c.get("binding", {}).get("owner_spec"), c.get("binding", {}).get("execution_spec")) for c in self.contexts):
            raise CompositionError("Workflow differs from its production approval.")
        if selected is not None and {c.get("identity") for c in self.contexts} != set(selected):
            raise CompositionError("Approved production selection changed. Review every selected job again.")
        self.validate()
        self.started = True

    def require_branch(self, run):
        from workflow.production_review import branch_approval_binding
        expected = branch_approval_binding(run)
        if any(c.get("binding", {}).get("branch_approval") != expected for c in self.contexts):
            raise CompositionError("Branch selection or partial-production acknowledgement changed. Review again.")
        self.validate()

    def require_output_plan(self, job_id, directory, outputs):
        from pathlib import Path
        matches = [c for c in self.contexts if c["job"]["job_id"] == job_id]
        if (len(matches) != 1 or Path(matches[0]["job"]["output_dir"]).resolve() != Path(directory).resolve()
                or matches[0].get("outputs", []) != outputs):
            raise CompositionError("Output plan differs from its production approval.")
        self.require_destination(directory, job_id)
        self.validate()
        self.started = True
        return matches[0]

    def require_partition_refinement(self, job_id, directory, policy, parts, envelopes):
        """Runtime byte splits may refine, never replace, a reviewed logical plan."""
        from collections import Counter

        from composition.production.output_policy import MAX_PARTS, OutputPolicy
        matches=[c for c in self.contexts if c["job"]["job_id"]==job_id]
        if len(matches)!=1 or OutputPolicy.from_dict(matches[0]["job"].get("output_policy",{})).to_dict()!=policy.to_dict():
            raise CompositionError("Output policy differs from its production approval.")
        if not 1<=len(parts)<=MAX_PARTS:
            raise CompositionError("Invalid number of production parts.")
        outputs=matches[0].get("outputs",[])
        order={str(item["key"]):index for index,item in enumerate(outputs)} if outputs else {"":0}
        last_group=-1
        last_envelope=0
        seen=set()
        counts=Counter()
        for index,part in enumerate(parts,1):
            group=order.get(part.get("key",""),-1)
            if type(part.get("part")) is not int or part["part"]!=index or group<last_group or group<0:
                raise CompositionError("Production part numbering or group order changed.")
            if group>last_group:
                last_envelope=0
            membership=part.get("membership",[])
            if membership and membership[0]<=last_envelope:
                raise CompositionError("Production envelope order changed across parts.")
            if membership:
                last_envelope=membership[-1]
            last_group=group
            membership=part.get("membership",[])
            if not membership or len(membership)!=part.get("records") or membership!=sorted(membership):
                raise CompositionError("Invalid output envelope membership.")
            for ordinal in membership:
                if type(ordinal) is not int or not 1<=ordinal<=envelopes or ordinal in seen:
                    raise CompositionError("Output must contain each reviewed envelope exactly once.")
                seen.add(ordinal)
            counts[part.get("key","")]+=len(membership)
        if len(seen)!=envelopes:
            raise CompositionError("An output envelope is missing.")
        outputs=matches[0].get("outputs",[])
        if outputs and dict(counts)!={str(item["key"]):item["records"] for item in outputs}:
            raise CompositionError("Logical output groups differ from production review.")
        if outputs:
            import sqlite3
            from contextlib import closing
            from pathlib import Path
            database=matches[0]["job"].get("record_store") or matches[0].get("external_data")
            with closing(sqlite3.connect(Path(database).resolve().as_uri()+"?mode=ro",uri=True)) as db:
                db.execute("CREATE TEMP TABLE actual(ordinal INTEGER PRIMARY KEY,key TEXT)")
                db.executemany("INSERT INTO actual VALUES(?,?)",((ordinal,part["key"]) for part in parts for ordinal in part["membership"]))
                if db.execute("SELECT 1 FROM actual LEFT JOIN partitions USING(ordinal) WHERE partition_key IS NULL OR CAST(partition_key AS TEXT)!=actual.key LIMIT 1").fetchone():
                    raise CompositionError("Output crosses a reviewed logical group boundary.")
        self.require_output_plan(job_id,directory,outputs)

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
        from pathlib import Path
        context["job"]["output_dir"] = str(output_dir)
        context["binding"]["output_anchor"] = str(Path(output_dir).resolve())
        context["binding"]["output_root"] = context["binding"]["output_anchor"]
        child = object.__new__(ProductionAuthorization)
        child.session, child.receipts, child.contexts = self.session, self.receipts, [context]
        child.parent, child.started = self, True
        return child


def require_authorization(value):
    if not isinstance(value, ProductionAuthorization):
        raise CompositionError("Review and explicitly confirm production before generating.")
    return value
