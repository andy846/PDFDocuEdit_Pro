# Recent updates: integration hardening

## Baseline and scope — 2026-10-18

Approved product worktree: `print-composition-v3/PDFdocuEdit_Pro`, branch
`codex/deep-search-restore-layout`, HEAD `a5cd66db8d071c6db733c1f10e4f926751b83a76`.
The public version remains 3.0.9. Existing uncommitted updates are retained.

| Area | Integration checks |
| --- | --- |
| PS opening | Content/converter-bound previews, independent editor copies, progress, cancellation, clear/disable races and private worker handoff. See [PS opening](POSTSCRIPT_OPENING.md). |
| Production console | Compact cards, fixed actions, error log and narrow/high-DPI layouts. See [console](COMPACT_PRODUCTION_UI.md). |
| Output limits and naming | Whole-envelope partitions, PDF/PS/JDF associations, part order, stock/duplex counts, actual byte limits and atomic publication. See [bounded output](BOUNDED_OUTPUT_REVIEW.md). |
| Command safety and dashboard | Current-mode dispatch, explicit missing/partial metrics, review/output identity and unchanged confirmation gates. See [M0/M4](M0_M4_REVIEW.md). |
| Designer page drafts | Add/Undo/Redo with incomplete paper assignments; invalid drafts remain editable, production validation remains strict. See [page drafts](DESIGNER_PAGE_DRAFTS.md). |
| Rotation and tools | Unrotated document coordinates, visible page boundaries, annotation transactions and save recovery. See [rotated tools](ROTATED_ERASER_BOUNDS.md). |
| Existing integrations | Visual Workflow, batch/branch execution, production authorization, opening/closing, search and print geometry regression. |

The withdrawn sheet-preview report is not treated as an outstanding defect.

## Fixes made during this review

### Independent cleanup of every pending PS preview

`core/postscript_cache.py`: if one staged PDF cannot be deleted, sink cleanup
continues through the other owned previews and releases their OS leases.
A copy failure followed by a deletion failure also releases its lease and
preserves the original copy error. In-memory pending references are cleared.
Files that remain locked are deferred to the existing owned-cache cleanup;
committed production files are never deleted by preview cleanup.

Two fault-injection cases failed before the fix and pass afterwards. Tests
also verify that a subsequent cache clear can remove the abandoned preview.

### Fallback process reaping after Windows tree-helper failure

`core/postscript_open.py`: failure to launch `taskkill`, or a helper timeout,
no longer skips the owned converter's bounded wait/kill/reap sequence or
replaces the original cancellation with a helper exception. Diagnostics contain
no document text or paths. The existing tree-stop path remains in use.

Both helper-failure cases failed before the fix and pass afterwards. Existing
real-subprocess cancellation and timeout tests continue to run. Fault injection
proves fallback reaping of the directly owned process; it does not establish
that arbitrary descendants can be terminated when Windows' tree helper itself
is unavailable. OS denial of process termination is not bypassed.

### Align legacy Split Workflow safety tests with the shared service

The initial combined run exposed three outdated boundary tests. They replaced
`workflow.batch.generate` / `workflow.pdf_pipeline.generate` entirely, thereby
replacing the shared `production_claim` guard as well. The bounded-output update
already moved final claims and verified replay into that shared service.
No duplicate publication or missing runtime claim was reproduced with the real
service in place; no production rule or lock implementation was changed here.

`tests/test_release_production_boundaries.py` now observes the actual Renderer /
OverlayRenderer boundary, preserves the protected service and compares every
published file recursively plus the complete output-part list after replay.
All eight runnable cases pass. A local mutation plugin then deliberately bypassed
the shared guard: all three relevant safety cases failed as expected. The plugin
exists only in ignored probe evidence and does not alter product source.

## Files changed in this pass

- `core/postscript_cache.py`: pending-preview cleanup and lease release.
- `core/postscript_open.py`: Windows tree-helper failure fallback and diagnostic.
- `tests/test_postscript_cache.py`: two owned-cleanup fault-injection regressions.
- `tests/test_postscript_open.py`: two Windows-helper failure regressions.
- `tests/test_release_production_boundaries.py`: align three stale tests with the shared claim boundary and strengthen artifact checks.
- This report: combined evidence, integration scope and acceptance boundaries.

## Verification

Final selected regression, including the corrected boundary-module recheck:
**2,831 passed, 0 failed, 0 errors, 4 skipped across 202 modules (2,835 cases)**.
A separate **52 UI cases passed at 200% scaling**. All 75 changed/new Python
files passed Ruff, report links resolve, and Git whitespace checks passed.

The initial run's three obsolete-test failures are retained in
`regression/result.json`; the successful replacement module is retained in
`boundary-recheck/result.json`. `final-result.json` maps each final module to
its actual evidence, without overwriting the initial run. Intentional RED and
mutation failures are evidence of test sensitivity, not final unresolved failures.

Skipped cases are three native macOS gates (bundle links/permissions, Keychain,
arm64 signing/install/update/rollback) and a file-symlink boundary case because
this Windows host lacks that permission. The directory-junction alternative ran
successfully. Local evidence is under `build/probes/recent-updates-hardening/`
and is not committed.

- RED evidence: `cleanup-red.xml` and `termination-red.xml`.
- Focused green: `ps-hardening-green.xml`, 37 passed.
- 200% scale: `high-dpi/result.json`, 52 passed in five fresh-process UI modules.
- Cross-feature regression: `regression/result.json`, modules listed separately
  in `modules.json`; each module runs in a fresh process to isolate Qt/native state.
- Static checks: all 75 changed/new Python files and Git whitespace checks.
- Legacy boundary recheck: `boundary-recheck/result.json`; sensitivity evidence:
  `boundaries-mutation-red.xml` (three intentional failures with the guard bypassed).
- One independent fresh-context review; its Windows termination finding was
  reproduced and fixed. No additional substantiated product integration finding.

## Boundaries and remaining acceptance

No new feature, public version, dependency, project-format, authorization rule,
PDF/barcode/media/sheet algorithm, release or branch integration is included.
No commit, merge, push or packaging is performed by this hardening pass.
Conversion flags, resolution and verification requirements are unchanged.

Windows automated tests use Qt offscreen, including light/dark and narrow-layout
cases. Native macOS, real high-DPI monitor interaction and physical printer/RIP
acceptance remain **Not Tested** in this pass. No new throughput claim is made:
large real-customer PS conversion benchmarks were not repeated. The running
owner application was not restarted or manipulated.
