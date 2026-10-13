"""Exclusive production claims and recoverable, checksummed package publication."""
from __future__ import annotations

import contextvars
import copy
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import asdict, fields
from functools import wraps
from pathlib import Path

from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.io_atomic import atomic_output
from core.output_safety import contained_path, validate_identifier

_CURRENT = contextvars.ContextVar("production_journal", default=None)
_LOG = logging.getLogger(__name__)


def _write(path, value):
    with atomic_output(path) as staged:
        staged.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")


def _artifact_rows(folder):
    rows = []
    for file in sorted(folder.rglob("*")):
        if file.is_symlink() or getattr(file.lstat(), "st_file_attributes", 0) & 0x400:
            raise CompositionError("Production package contains a link or junction.")
        if file.is_file() and file.name != "completion.json":
            rows.append({"path": file.relative_to(folder).as_posix(), "size": file.stat().st_size, "sha256": file_hash(file)})
    return rows


def verify_package(final, identity, binding, expected_completion=""):
    try:
        final = Path(final)
        packet_file = contained_path(final, "completion.json")
        if expected_completion and file_hash(packet_file) != expected_completion:
            return None
        packet = json.loads(packet_file.read_text(encoding="utf-8"))
        if (packet.get("version") != 1 or packet.get("job_id") != identity or packet.get("binding") != binding
                or packet.get("result", {}).get("status") != "completed"):
            return None
        if not packet.get("artifacts") or packet["artifacts"] != _artifact_rows(final):
            return None
        # Every recorded absolute output must still belong to this package.
        result = packet["result"]
        if Path(result.get("report_dir", "")).resolve() != final.resolve():
            return None
        pdfs = [result.get("output_pdf")] + [f.get("output_pdf") for f in result.get("output_files", [])]
        from core.pdf_io import validate_pdf_file
        for raw in pdfs:
            if raw:
                path = Path(raw)
                if not path.resolve().is_relative_to(final.resolve()):
                    return None
                validate_pdf_file(path)
        return result
    except Exception:
        return None


class JobBusyError(CompositionError):
    """An existing OS-held claim must never be taken over by recovery."""


class JobJournal:
    def __init__(self, root, identity, binding):
        self.root = Path(root).resolve()
        self.identity = validate_identifier(identity)
        self.binding = binding
        self.final = contained_path(self.root, identity)
        self.directory = contained_path(self.root, ".production-state")
        self.path = contained_path(self.root, ".production-state", identity + ".json")
        self.record = {}
        self.existing = None

    def persist(self, state, **values):
        self.record.update(version=1, job_id=self.identity, binding=self.binding, state=state, **values)
        _write(self.path, self.record)

    @contextmanager
    def claim(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = contained_path(self.root, ".production-state", self.identity + ".lock")
        with lock_path.open("a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            locked = False
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                raise JobBusyError("This production job is already running. Wait for its result.") from exc
            try:
                if self.path.exists():
                    self.record = json.loads(self.path.read_text(encoding="utf-8"))
                    if self.record.get("binding") != self.binding:
                        raise CompositionError("Earlier production identity has different inputs. Review a new attempt.")
                if self.final.exists():
                    self.existing = verify_package(self.final, self.identity, self.binding, self.record.get("completion_sha256", ""))
                    if self.existing is None:
                        self.persist("Needs review", error="Published output lacks matching completion evidence.")
                        raise CompositionError("Existing output cannot be verified. Review a new attempt; it will not be overwritten.")
                    try:
                        self.persist("Committed", result=self.existing, completion_sha256=file_hash(self.final / "completion.json"))
                    except OSError as exc:
                        self.existing.setdefault("warnings", []).append("Verified output retained; state could not be saved: " + str(exc))
                elif self.record:
                    # A prior claim consumed approval. Never silently start another
                    # production attempt at the same destination after interruption.
                    quarantine = []
                    for pattern in ("." + self.identity + "-*", ".split-" + self.identity + "-*"):
                        for folder in self.root.glob(pattern):
                            if folder.is_dir():
                                checked = contained_path(self.root, folder.name)
                                target = contained_path(self.root, ".quarantine", folder.name)
                                target.parent.mkdir(exist_ok=True)
                                if not target.exists():
                                    os.rename(checked, target)
                                quarantine.append(str(target))
                    self.persist("Needs review", quarantine=quarantine, error="Previous attempt did not commit.")
                    raise CompositionError("Earlier attempt was interrupted or failed. Choose a new output folder and review a new attempt.")
                else:
                    self.persist("Running", result={}, error="")
                token = _CURRENT.set(self)
                try:
                    yield self
                finally:
                    _CURRENT.reset(token)
            finally:
                if locked:
                    lock.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def finish(self, result):
        if result.get("status") == "completed":
            return
        self.persist("Cancelled" if result.get("status") == "cancelled" else "Failed", result=result,
                     error=result.get("error", "Production did not complete."))


def _binding(authorization, identity):
    for receipt in authorization.receipts:
        body = authorization.session.verify(receipt["authorization"], "approval")
        if body["context"]["job"]["job_id"] == identity:
            return body["fingerprint"]
    raise CompositionError("Missing reviewed job identity.")


def production_claim(kind):
    def decorate(function):
        @wraps(function)
        def checked(job, *args, **kwargs):
            from composition.review.authorization import require_authorization
            authorization = require_authorization(kwargs.get("authorization"))
            try:
                authorization.require_job(kind, job, is_cancelled=kwargs.get("is_cancelled"))
            except Exception as exc:
                from composition.production.generator import JobCancelled
                if not isinstance(exc, JobCancelled):
                    raise
                from composition.overlay.model import OverlayResult
                from composition.production.model import JobResult
                model = JobResult if kind == "template" else OverlayResult
                return model(job.job_id, status="cancelled", error="Production cancelled before generation.")
            journal = JobJournal(job.output_dir, job.job_id, _binding(authorization, job.job_id))
            with journal.claim():
                if journal.existing is not None:
                    from composition.overlay.model import OverlayResult
                    from composition.production.model import JobResult
                    model = JobResult if kind == "template" else OverlayResult
                    return model(**{k: v for k, v in journal.existing.items() if k in {f.name for f in fields(model)}})
                notices = []
                observer = kwargs.get("progress")
                if observer is not None:
                    def progress(*values):
                        try:
                            observer(*values)
                        except Exception as exc:
                            message = "Progress notification failed: " + str(exc)
                            if message not in notices:
                                notices.append(message)
                    kwargs["progress"] = progress
                try:
                    value = function(job, *args, **kwargs)
                    value.warnings.extend(notices)
                    journal.finish(asdict(value))
                    return value
                except Exception as exc:
                    from composition.production.generator import JobCancelled
                    if isinstance(exc, JobCancelled):
                        from composition.overlay.model import OverlayResult
                        from composition.production.model import JobResult
                        model = JobResult if kind == "template" else OverlayResult
                        value = model(job.job_id, status="cancelled", error="Production cancelled before composition.")
                        journal.finish(asdict(value))
                        return value
                    try:
                        journal.persist("Needs review", error=str(exc))
                    except OSError:
                        _LOG.exception("Unable to persist production failure")
                    raise
        return checked
    return decorate


@contextmanager
def final_claim(authorization, identity, output_dir, outputs):
    """Own the final destination before rendering, including split intermediates."""
    authorization.require_output_plan(identity, output_dir, outputs)
    journal = JobJournal(output_dir, identity, _binding(authorization, identity))
    current = _CURRENT.get()
    if current is not None and current.final == journal.final and current.binding == journal.binding:
        yield current
        return
    with journal.claim():
        try:
            yield journal
        except Exception as exc:
            try:
                journal.persist("Needs review", error=str(exc))
            except OSError:
                _LOG.exception("Unable to persist final production failure")
            raise


def split_claim(function):
    @wraps(function)
    def checked(result, source, partitions, output_dir, pages_per_record, **kwargs):
        from composition.review.authorization import require_authorization
        authorization = require_authorization(kwargs.get("authorization"))
        with final_claim(authorization, result["job_id"], output_dir, partitions) as journal:
            if journal.existing is not None:
                return copy.deepcopy(journal.existing)
            value = function(result, source, partitions, output_dir, pages_per_record, **kwargs)
            journal.finish(value)
            return value
    return checked


def branch_binding(run, entry):
    return {"common": run["signature"], "batch_id": run["batch_id"],
            **{k: entry[k] for k in ("id", "source_id", "branch_id", "signature", "records")}}


def publication_binding(authorization, identity):
    context = next(c for c in authorization.contexts if c["job"]["job_id"] == identity)
    binding = context.get("binding", {})
    result = {"identity": context.get("identity", ""), "job_signature": binding.get("job_signature", "")}
    branch = binding.get("branch_approval")
    if branch:
        entry = next(j for j in branch["jobs"] if j["id"] == context["identity"])
        result["branch"] = branch_binding(branch, entry)
    return result


def verified_branch_output(result, expected):
    """A mutable recovery manifest cannot relabel an old checked package."""
    try:
        identity = validate_identifier(result["job_id"])
        folder = Path(result["report_dir"])
        folder = contained_path(folder.parent, folder.name)
        state = json.loads(contained_path(folder.parent, ".production-state", identity + ".json").read_text(encoding="utf-8"))
        if state.get("job_id") != identity or not state.get("completion_sha256"):
            return False
        if verify_package(folder, identity, state["binding"], state["completion_sha256"]) is None:
            return False
        packet = json.loads(contained_path(folder, "completion.json").read_text(encoding="utf-8"))
        return packet.get("production_binding", {}).get("branch") == expected
    except (KeyError, ValueError, OSError, TypeError):
        return False


def publish_package(staging, final, result, authorization):
    """A complete manifest travels with the package across its atomic rename."""
    journal = _CURRENT.get()
    if journal is None or journal.final != Path(final).resolve():
        raise CompositionError("No exclusive claim for this publication destination.")
    authorization.validate()
    final = contained_path(journal.root, journal.identity)
    if final.exists():
        raise CompositionError("Production output already exists; it will not be replaced.")
    context = next(c for c in authorization.contexts if c["job"]["job_id"] == journal.identity)
    packet = {"version": 1, "job_id": journal.identity, "binding": journal.binding,
              "variable_context":copy.deepcopy(context["job"].get("variable_context", {})),
              "result": copy.deepcopy(result), "artifacts": _artifact_rows(Path(staging)),
              "production_binding": publication_binding(authorization, journal.identity)}
    _write(Path(staging) / "completion.json", packet)
    completion = file_hash(Path(staging) / "completion.json")
    journal.persist("Publishing", staging=str(staging), completion_sha256=completion, result=result)
    try:
        os.rename(staging, final)
        journal.persist("Committed", staging="", result=result)
    except Exception as exc:
        if verify_package(final, journal.identity, journal.binding, completion) is None:
            raise
        # The atomic commit succeeded. A failed journal/notification write must
        # not cause the caller to discard or regenerate that verified output.
        warning = "Output published and verified; state/report write failed: " + str(exc)
        result.setdefault("warnings", []).append(warning)
        _LOG.warning(warning)
    return result


def publish_empty_report(job, source, summary, authorization, *, kind="template"):
    """Zero retained records still have one approved, atomic, idempotent report."""
    import tempfile

    from workflow.transforms import export_audit
    authorization.require_job(kind, job)
    raw = job if isinstance(job, dict) else asdict(job)
    identity = raw["job_id"]
    journal = JobJournal(raw["output_dir"], identity, _binding(authorization, identity))
    with journal.claim():
        if journal.existing is not None:
            return copy.deepcopy(journal.existing)
        with tempfile.TemporaryDirectory(prefix="." + identity + "-", dir=journal.root) as scratch:
            staged = Path(scratch) / "package"
            staged.mkdir()
            export_audit(source, staged)
            result = {"job_id": identity, "status": "completed", "input_records": 0, "successful_records": 0,
                "generated_pages": 0, "generated_files": 0, "output_pdf": "", "report_dir": str(journal.final), "error": "",
                "source_records": summary.get("input", 0), "excluded_records": summary.get("excluded", 0),
                "warnings": ["No records selected. No empty PDF was generated."]}
            if kind == "report":
                result.update(input_envelopes=0, original_envelopes=summary.get("input", 0), excluded_envelopes=summary.get("excluded", 0))
            _write(staged / "job.json", result)
            return publish_package(staged, journal.final, result, authorization)
