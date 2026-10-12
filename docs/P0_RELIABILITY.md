# P0 reliability and production authorization

Updated: 2026-10-13. Public application version remains 3.0.5.

## Document integrity

- Incremental saving requires a real backing file in the engine-owned working directory. Stream documents created by rollback/Undo use the existing non-destructive full-save path.
- Repeated insertion owns a mutation transaction. Outer transactions retain one snapshot, one revision and one Undo entry. Insertion, scale-copy and source failures restore the previous state.
- Existing encryption, permissions, redaction sanitation and atomic save policies remain in force.

## Production approval contract

Template, Overlay, PDF Workflow, Batch and Branch publishing now require `ProductionAuthorization`. An `approved` flag or unsigned snapshot is insufficient.

The GUI continues to use Production Review. Checked snapshot contents and SQLite evidence are authenticated with a per-process-session HMAC key. The key reaches workers only via their existing private stdin channel. It is not written to request files, projects or logs, and is unrelated to update-signing keys.

Confirmation signs the resolved job, source/template/prepared-data fingerprints, selected jobs, destination, output plan and warning acknowledgement. Branch approval also binds the complete routing selection and partial-production acknowledgement. Evidence expires for new starts after 24 hours and on application restart. Started jobs finish without a mid-job expiry interruption. Preview, step inspection and paper proofs do not publish production packages.

Headless callers use the same service, for example:

```python
from dataclasses import asdict
from composition.review.headless import approve_checked_contexts
from composition.production.generator import generate

# `confirm` must implement the caller's explicit operator/automation decision.
authorization = approve_checked_contexts(
    [{"kind": "template", "job": asdict(job)}], review_directory,
    confirm=confirm, warnings_acknowledged=True,
)
result = generate(job, authorization=authorization)
```

Use `workflow.production_review.prepare_contexts()` to construct workflow-bound contexts. Execution no longer auto-approves batch work. Existing headless external-value callbacks are checked with a streamed per-page digest; changed values prevent publication.

This protects request and project tampering. It is not a DRM boundary against software controlling the application's process/memory or rewriting its code.

## Output identity and recovery

Identifiers use the existing bounded ASCII batch/job rules; traversal, drive/UNC syntax and Windows reserved devices are rejected. Destination descendants cannot be symlinks/junctions. Checks apply before output directories are created and again at publication.

Each production root contains `.production-state/` journals and OS-held job locks. These are audit/recovery files, not leaked staging files. The OS releases the lock after process termination. Publishing includes `completion.json`, listing the identity, input binding and checksums of all package artifacts (PDF, PS, JDF, split output, CSV and JSON reports). Package commit uses the existing same-parent directory rename.

- Verified committed output is retained and skipped, never regenerated automatically.
- Missing/mismatched completion evidence blocks overwrite/retry.
- Interrupted scratch is isolated under `.quarantine/`; a new attempt requires a new destination and explicit review.
- A committed PDF survives later branch, notification, report or journal failure. The UI distinguishes those failures from failed composition.
- Cancelled/unfinished jobs lose approval and require recheck/review.
- Zero retained records use an approved atomic report-only package; no empty PDF is created.

Visual Workflow > Production > **Recover previous run...** accepts the prior `batch-...` folder. It verifies completion evidence, retains successful outputs, revokes approval and requires Check & Preview before remaining work. It does not take over a live OS-held claim. The portable `run.json` does not depend on old scratch datasets.

## Compatibility and tests

No public version, `.pdcx`, `.pdflow`, Overlay or barcode-profile version changes. Persisted booleans cannot resurrect approval. Recovery journals are runtime/output contracts, not template migrations.

Existing positive production tests now use explicit real review/approval helpers. Negative glyph, barcode, media and rule tests assert blocked review and no publication rather than expecting an unreviewed generator to begin processing. No engine bypass flag, skipped failures or reduced validation was added. Fault-injection tests separately cover actual composition failure, cancellation, post-rename failure, state/report failures and interrupted/repeated execution.

Development PS tests use the already available Ghostscript executable via PATH; no extra dependency was introduced. Windows native worker stdin (including pythonw), junction rejection and OS job locking are tested. macOS native validation remains a separate gate. No release or installer was produced by this work.
