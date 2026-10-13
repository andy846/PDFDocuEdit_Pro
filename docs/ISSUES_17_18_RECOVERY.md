# Issues #17 and #18 — PDF activity and safe recovery

Scope: fixes against the current development branch, with v3.0.6 as the
reported reproduction version. No public version, project format, update key,
packaging or release change. The two issues have separate implementation commits.

## #18: duplicate-open activity

Confirmed cause: the queue showed Opening document before dispatch. Focusing an
already-open PDF returns without a FunctionTask, so its usual finished handler
never cleared the activity. This is a UI ownership defect, not a slow PDF reload.

The queue now owns a distinct activity token, finishes idempotently, and clears
only its own activity. FunctionTask activity also has an owner. Queue-to-task and
task-to-queue handoffs retain the busy indicator until actual work completes.
An unrelated task, legacy external activity or print operation is not replaced.
Duplicate paths retain the existing engine, dirty edits and tab/window identity;
load_file bypasses the discard prompt for a loaded duplicate. Path lookup keeps
existing Windows case normalization without introducing synchronous file probing.

Covered outcomes: repeated duplicates, mixed duplicate/new queue, detached
window focus, closed target, empty queue, missing file, denied access and
cancelled encrypted-PDF password prompt. Error/Cancelled feedback is retained.

## #17: operation recovery and shutdown

Controlled reproductions confirmed these independent defects:

- PdfCanvas accepted a timeout but did not enforce a deadline; thumbnail drain
  waited on the entire thread pool without a deadline.
- Shutdown disabled the complete window, including Windows' custom close button.
- Result/finished callback exceptions could cross a Qt signal boundary and abort
  a child test process (Windows exit code 3221226505).
- Cleanup flags could mark PDF retirement complete before a failing cleanup had
  installed all readers' retirement, causing a retry to skip a live document.
- Failed history installation synchronously closed its replacement engine even
  when replacement readers remained active; the new regression reproduced this.
- A failed multi-window save-confirmation left approvals from previous windows
  active. This also has a failing-before-fix regression.

### Reader and mutation ownership

Canvas/thumbnail drains have a real deadline (default 3 seconds), wait only for
owned reader leases, and retain running tasks when timing out. A timeout refuses
an edit rather than authorizing unsafe mutation. Reader scheduling is paused
across the drain/mutation/rebind interval. Scheduling a render does not itself
hold the global PDF mutex; actual MuPDF access keeps its existing lock.

Mutation failure rebinds every consumer of the restored source, including the
main canvas, same-source split and dependent comparison canvas, thumbnails and
annotation UI. Document state, dirty revision and history are preserved. History
restoration locks work controls while draining, detaches failed replacement
views without blocking, and retires replacement engines only after captured
leases finish. Successful replacement still drains previous readers before
closing the previous engine.

### Safe, observable close

CloseLifecycle locks work controls without disabling native/custom window
controls. An approved close cancels cooperative work and waits safely. Pending
reason and dependency counts are logged; after 3 seconds a persistent warning
explains the wait. Automatic retries then observe completion instead of repeatedly
re-entering save/close handling. The close control remains available to retry.
Completed dependencies trigger eventual close. Sessions are registered for
retirement individually only after their cleanup is installed. Failed save
preflight revokes partial approvals and restores work controls.

No QThread is forcibly terminated and no live-reader document is forcibly closed.
A genuinely permanent native operation cannot be safely interrupted by this
change; it remains an observable pending close, with the close control usable.

### Diagnostics and callback boundaries

Task/result/discard/finished/guard/batch callbacks have controlled exception
boundaries. Diagnostics record exception classes, cause-chain traceback
filenames/line numbers/function names, fixed stages, task/thread IDs and numeric
counts. They omit exception payloads, source lines and frame locals. Synthetic
private-value sentinels are asserted absent from logs. Queue dispatch has its
own boundary because duplicate-open callbacks may have no FunctionTask.

## Evidence and limitations

Tests use generated deterministic PDFs and controlled reader events. Red tests
were observed before fixes for the activity early returns, deadlines, disabled
close control, callback aborts, cleanup retry, history reader retirement and
partial exit approvals. Existing tests remain enabled; the workspace shutdown
assertion intentionally now requires an enabled window/close control and a locked
work area rather than disabling the entire window.

The original customer's redaction exception and a native deadlock have not been
reproduced. The fix addresses verified lifecycle defects, not a claim that every
native operation can be interrupted or every malformed PDF can be repaired.
No customer PDFs, signing keys or account secrets were used in these tests.

Targeted local verification uses scripts.regression_suite.run with one fresh
process per affected module; module logs and JUnit are retained locally under
artifacts/issue-17-18-targeted. New GUI modules are included in the existing UI
CI group without overlapping its cross-platform group. Final test counts and
CI URLs are recorded in the pull request.

Local final run: **214 passed, 0 skipped, 13 affected modules**, with Ruff and
diff whitespace checks passing. Final CI URLs/results are retained in the PR.
