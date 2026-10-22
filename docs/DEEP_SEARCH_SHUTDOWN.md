# Deep Search paused-job shutdown repair

Date: 2026-10-22. Workspace: `D:\Python_Project\PDFdocuEdit_Pro`, local `main`,
`.venv-dev`. Baseline: `ba47bb5a88b53c340b1925a05f3c96af1d6924a2` (3.1.0).

## Confirmed cause

The paused worker in [SearchRuntime](../core/deep_search_runtime.py) waits on a
`Condition` until Resume or Cancel wakes it. This is intentional: pause retains
the search snapshot and results. `cancel()` already clears the pause request
and calls `notify_all()` correctly.

The missing link was owner shutdown. Deep Search uses its own child
`QThreadPool`, plus result-query and report-export tasks. The
[Viewer close handler](../core/viewer.py) previously waited for other tool jobs
but did not close or wait for Deep Search. A parent window closing does not
perform the child dialog's cooperative cleanup. Opening a result in the current
window also deliberately hides the dialog rather than stopping its job.

Consequently, the main window could accept close while the worker remained
paused. Qt/process teardown then had a live thread pool to drain; the paused
worker had no cancellation wake-up. Even when the operator had just closed the
search dialog, the main window could accept shutdown before its asynchronous
cleanup completed. This explains the disappearing UI with a surviving process.

Baseline regression: four close routes (visible, hidden, current-window result
opening and search-close immediately followed by main-close) all accepted main
close with live ownership. The close-status counter also omitted that job:
**5 failed, 1 passed** before the fix. Failure cleanup explicitly cancelled the
orphaned worker so the regression runner itself would not hang.

## Repair

- After all discard/preferences preflight checks pass, Viewer explicitly closes
  its Deep Search dialog, including hidden dialogs. The existing cancel path
  wakes paused workers. Main close is deferred until all owned jobs are done.
- [DeepSearchDialog](../ui/deep_search_dialog.py) reports search, query and export
  ownership. It also checks the native search pool's active count: a queued
  `finished` callback alone is not proof that `QRunnable.run()` has returned.
- A single-shot 25 ms timer only runs during pending close. It checks ownership
  without blocking the GUI, deleting live worker resources or forcing threads
  to terminate. It also covers the native tail after the last finished signal.
- Closing prevents a new search from starting. SQLite and its temporary
  directory are released only after background work has finished.
- [CloseLifecycle](../ui/close_lifecycle.py) includes these jobs in counts and
  readiness. The existing delayed status bar identifies Deep Search if shutdown
  takes more than three seconds, then closes automatically when safe.
- Cancelling the application's unsaved-changes prompt leaves the paused search
  intact and resumable. Multi-window exit uses the same per-window ownership.

No new worker, dependency, version change, branch/worktree, push or release.
The pre-existing `BOCHK.pdmp` remains excluded and untouched.

## Verification

Windows / Python 3.12 / PyMuPDF 1.26.6; synthetic PDFs only.

| Check | Result |
|---|---|
| New shutdown regression | 14 passed |
| Existing relevant regression, 9 modules | 126 passed |
| Actual Qt event-loop process exits | 8 successful child-process runs, included above |
| Standard and 200% DPI | Each of four process routes ran at both scales |
| Ruff / source verification / whitespace | Passed |
| Customer workstation / released executable / macOS | Not Tested for this repair |

The process probe waits for a real search to pause, requests shutdown, runs
the Qt event loop to completion, checks worker completion and temporary cleanup,
destroys owned widgets and then returns from the OS process. Each route is
immediately run in a fresh process again; the test fails on timeout or nonzero
exit rather than relying on fixture cleanup to claim success.

Additional cases hold query/export/native-pool work open, check that the GUI
keeps responding, repeat close, check delayed status, and verify that storage
remains alive until work releases. A secondary PDF window with a hidden paused
search is also covered during application-wide exit.

Existing regression modules: `test_deep_search`, `test_deep_search_detailed`,
`test_deep_search_responsive`, `test_search_task_lifecycle`, `test_close_status`,
`test_error_recovery_lifecycle`, `test_document_windows`, `test_ci_plan`,
`test_source_contract` (all `tests/*.py`). They ran through the existing
`scripts.regression_suite.run()` in separate processes. An initial combined
two-module run had one layout-size assertion failure; the unchanged entire
responsive module passed in its own process, matching project QA conventions.
The full product release suite was not run for this focused repair.

Local logs and JUnit: `build/probes/deep-search-shutdown-20261022/`.

```powershell
$env:PYTHONUTF8='1'
$env:TEMP='D:\Python_Project\PDFdocuEdit_Pro\build\probes\ds-tmp'
$env:TMP=$env:TEMP
.venv-dev/Scripts/python.exe -m pytest tests/test_deep_search_shutdown.py -q
.venv-dev/Scripts/python.exe -m ruff check core/viewer.py ui/deep_search_dialog.py ui/close_lifecycle.py ui/close_status.py scripts/ci_plan.py tests/test_deep_search_shutdown.py tests/qa_deep_search_shutdown.py
.venv-dev/Scripts/python.exe scripts/verify_source.py
git diff --check
```

## Owner UAT / remaining limits

1. Start a folder search, pause it, then close Deep Search and immediately close
   the application. Verify its process disappears and the app opens again.
2. Repeat after opening a result in the current PDF window (which hides search),
   and with Deep Search in a secondary PDF window.
3. Cancel an unsaved-document exit prompt. Verify the search remains paused and
   Resume continues the original search.

A native PDF read or barcode decode already in progress must still reach its
cooperative checkpoint; the fix does not force-kill it or promise a bounded
decode duration. During that wait, the existing shutdown status remains available.
No searching/layout redesign or broader task architecture change is included.
