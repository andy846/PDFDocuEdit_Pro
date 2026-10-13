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

## Fix traceability

| Item | Isolated fix commit | Main verification |
| --- | --- | --- |
| C1 | `f776797` | Ordinary/encrypted rollback, Save/Save As, further edits, Undo/Redo and failed close/restore |
| H1 | `6a6cdf7` | Direct/nested insertion, duplicate pages, first/middle/final insertion and scale-copy faults, one successful commit |
| H7 | `fa5e9c3` | Forged identities, traversal/drive/UNC/reserved names, nested identity mismatch, junction containment |
| H8 | `eabc79a` | Missing/tampered/expired evidence, resource changes, raw worker/engine calls, session-private stdin, partial approval |
| H9 | `872ab7a` | Generation/cancellation/post-commit faults, all-artifact checksums, process-held claims, retained output and portable recovery |

## Windows verification evidence (2026-10-13)

The final regression uses `scripts/regression_suite.py --group all`, the repository's existing per-module process isolation. This retains every selected test and individual JUnit/log evidence; Qt application/style state is not shared between modules. An earlier single-process run was stopped after increasingly slow UI execution; it is not counted as a successful gate.

Targeted fault-injection covers rollback/save for encrypted and ordinary PDFs, direct/nested repeated insertion, output traversal/junctions, authenticated review and private worker stdin, cancellation, post-commit journal/report failure, checksummed recovery and OS-exclusive job locks. Security and PS/JDF/duplex cases passed as a 77-test group; the final suite also includes these cases.

Windows layout checks used isolated preferences at 960 x 640, 100% and 200% scaling, light and dark themes. The recovery control remained within the production page. This is offscreen/native Qt layout evidence, not a macOS or printer acceptance result.

Synthetic local smoke measurements (not a release performance baseline):

| Fixture | Records / output pages | Review | Generation | Peak memory |
| --- | --- | --- | --- | --- |
| Plain fixed one-page template | 1,000 / 1,000 | 0.844 s | 1.747 s | Composer 93.1 MiB; assembler 18.0 MiB |
| Three CSV inputs / two template branches | 100 / 100 | 1.595 s | 4.421 s including review | 102.2 MiB |

These measurements ran alongside regression work. They demonstrate functional bounded smoke workloads, not unchanged speed, large-network-file performance or printer compatibility. No pre-change same-machine performance comparison is claimed.

Local evidence is retained under `D:/Python_Project/PDFdocuEdit_Pro/build/`: `p0-final-regression/`, `p0-layout-*.png`, `p0-composition-smoke.json/20261013-015158/benchmark.json`, and `p0-branch-smoke.json`.

### Final result

Final applicable regression evidence covers all 169 modules: **2,365 passed, 3 existing native-macOS cases skipped, 0 remaining failures/errors** (2,368 total after the added regression cases). Ruff and working diff whitespace checks pass.

The original complete isolated run retained three failures: two external-open routing tests used unconstrained mocks that invented a window manager, and a real Branch UI regression treated a new recipe's stale marker as a previous run without identity. The routing tests now cover both single-window and active-window destinations. The Branch UI only marks an existing run stale; the worker's identity validation remains strict. A new regression test was observed failing before this minimal fix. Rechecking the seven affected/safety modules passed **81 tests**. Original failure logs remain retained; `p0-final-validation.json` records both the original run and final per-module rechecks without rewriting evidence.

The three unchanged skips require native macOS bundle permissions/symlinks, Keychain and arm64 signed install/update/rollback. They do not constitute macOS acceptance. Windows offscreen Qt operations, native worker stdin and junction/OS-lock checks are complete for this scope. No installer build, release or default-branch merge was performed.

## v3.0.6 release-review hardening

One independent whole-branch review found four additional boundaries not exercised by the earlier development suite. Each was reproduced against real approval/production using synthetic fixtures before fixing: an unreviewed extraction DB reference, unapproved batch destinations/report links, split recomposition before claiming the final output, and a mutable recovery manifest relabelling old output after a template change.

Review now freezes physical output anchors; batch and report paths are checked before writes and publication uses the same destination contract. PDF Workflow rejects a replacement extraction database and consistently reads its signed source. Split workflows hold the final exclusive claim before rendering and retain verified committed packages without re-rendering. Completion evidence stores the approved branch/source/template binding, checked again during recovery and completed-output retention. Older packages lacking this branch proof remain on disk and require review rather than automatic trust.

The observed regression run was 6 failing cases plus 1 unavailable Windows file-symlink case. After fixing, all 17 related modules passed (227 passed, 1 existing host-capability skip in the new boundary module). A further guard mutation test proved the report-reference check fails when removed and passes when restored. Native macOS release gates include the boundary module, including the file-symlink case; Windows complete native release validation is still required at the newly frozen candidate SHA. This addendum does not claim v3.0.6 has been published or passed operator acceptance.
