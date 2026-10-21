# Watermark Discard / Reopen Reliability — 2026-10-21

## Confirmed failure and scope

Baseline: Windows v3.0.11 product source
`a6d0b30c575ba0b6d1b9aa8e962d652f8fa9a783`; canonical local main
`c62a6a4c2cc03c5bd23eb65b847cdd88bee147cd` adds release records only.

The owner narrowed the operation to **Apply Watermark → close without saving
(Discard) → open another PDF**. A real Qt Watermark dialog followed by a real
unsaved-changes QMessageBox reproduced an accepted/retired main window with
`PrivateApplication.exiting == false` and the old Viewer still retained.
The new regression failed on that assertion before the fix, then passed.

### Causal sequence

1. PrivateApplication previously scheduled `_closed()` when it first observed
   the main window's Close event, before the viewer handled that event.
2. The unsaved QMessageBox runs a nested Qt event loop. That loop executes the
   scheduled callback while the main window is still visible. The observer
   returns and may clear the pending close purpose.
3. Discard then completes reader retirement and hides the main window. There
   was no account-level subscription to that actual completion.
4. Account mode sets `quitOnLastWindowClosed(false)`. A hidden application can
   therefore remain alive, holding its single-instance/managed route. A later
   launch can reach the retired Viewer, whose document readers have been cleared.

This is a reproduced cause of the reported hidden-process/blank-viewer pattern,
not evidence that the source PDF is damaged. It is not a claim that every
historical blank-tab incident has the same cause, or that the owner's actual
customer file and real signed-in installation have been tested here.

## Repair and compatibility

- Account shutdown observes existing CloseLifecycle cancellation/failure/closed
  states. Final checks are queued after modal decisions and tied to their owning
  Viewer, so a late callback cannot act on a replacement window.
- A real Viewer is released only after its explicit closed flag. Recoverable
  cancellation preserves the document, pending requests and account restrictions.
- PDF entry points reject closing/retired windows before creating tabs or
  changing workspace mode.
- A newer external request received during Discard waits for safe retirement,
  then uses existing approved account admission to create a **fresh Viewer**.
  With no new request, the application exits normally. Logout, account change,
  revocation and update restart retain their existing precedence.
- Watermark preview cancellation, reader leases, mutation transactions and PDF
  rendering algorithms are reused. No forced reader release or process kill is
  introduced into the product.

The fresh-Viewer handoff is a deliberate refinement of the original plan: it
preserves incoming intent without changing the Launcher or IPC protocol and
without restarting authentication. It never reuses the retired document/window.
No new dependency, project format, public version, installer or release.

### Changed components

| File | Purpose |
|---|---|
| `auth/application.py` | Observe completed/canceled close lifecycle, preserve queued requests, retire the actual viewer before exit or new admission |
| `core/viewer.py` | Guard opening into a closing/retired window; record request and first-page delivery identifiers |
| `core/diagnostics.py`, `main.py` | Install bounded, sanitized process lifecycle file logging |
| `dialogs/annotation_dialogs.py`, `ui/watermark_preview.py` | Record preview/dialog completion without changing PDF mutation or reader ownership |
| `scripts/ci_plan.py` | Include the new real-viewer regression in existing Qt setup |
| `tests/test_watermark_close_reopen.py` | 21 integration/entry-guard cases, including actual process restart and deleted QObject callbacks |
| `tests/qa_watermark_restart.py` | Maintained synthetic cross-process QA helper |
| `tests/test_lifecycle_diagnostics.py` | Bounded logging, process identity and exception-value redaction |

Existing tests and production output algorithms remain unchanged.

## Diagnostics

The existing diagnostics location now contains `lifecycle.log`: 1 MiB per file,
two rotated backups. The dedicated channel records process ID, fixed lifecycle
stages, numeric request/session/generation values and sanitized failure frames.
It does not log PDF text, watermark text, customer values, exception messages,
document paths, credentials or account identifiers. Existing diagnostic levels
are retained. New events cover open requests, first-page delivery, Watermark
preview completion and account close/exit transitions.

Diagnostics are not a new task-history system. They are local and bounded;
startup continues if the log directory is unavailable. The process ID makes a
true new application launch distinguishable from activation of a hidden process.

## Verification

Local evidence: `build/probes/watermark-close-20261021/` (not committed).

| Check | Actual evidence |
|---|---|
| Original real-modal failure | `red.log`: expected failure; accepted close did not exit account application |
| Final account, lifecycle and diagnostic tests | `final-auth-close.log` / `final-auth-close.xml`: 43 passed in 50.85 s (21 existing account + 21 lifecycle + 1 diagnostics) |
| Separate source processes | `process-qa/result.json`: passed; two different PIDs; source unchanged; non-white page pixels verified |
| Final Windows frozen QA processes | `frozen-final-qa/result.json`: passed; two different frozen PIDs; source unchanged; another PDF visibly rendered |
| Final Qt 200% simulation | `dpi2-final.log`: 22 passed in 51.63 s (all new lifecycle and diagnostic cases) |
| Initial complete isolated regression | 218 modules; 3,108 passed, 1 assertion failure, 4 skipped; account module additionally crashed without JUnit. Original runner exit code 1, retained in `regression/result.json` |
| Consolidated coverage after account fix | Initial run plus isolated account rerun: 3,129 passed, 1 pre-existing PS failure, 4 skipped. This combines evidence; it is not a second all-module run or an all-green suite |
| Ruff / whitespace | Passed |
| Independent read-only review | No blocking findings; suggested real account-state cancellation coverage was added and passed |
| Real account login / actual customer PDF | Not Tested |
| Actual Windows display scaling / macOS | Not Tested; Qt scaling simulation is recorded separately |

Three native macOS checks (bundle links/permissions, Keychain and signed arm64
installation) are skipped on this Windows host. A Workflow file-symlink check
is also skipped because this host lacks file-symlink permission. These are not
reported as passing.

The frozen QA executable is a separate local harness importing the product
Viewer, account controller and single-instance router. It uses only synthetic
PDFs, a memory-backed synthetic approval and blocked network proxies. It is not
the signed shipping editor, an installer or a real-account acceptance result.
The source and frozen probes run real QApplication event loops and normal exit,
then start a different process and assert actual non-white page rendering.

Tests cover image-only/text PDFs at 0/90/180/270 degrees; Save/Discard/Cancel;
external open during a prompt; preview failure and delayed reader completion;
retired-window entry guards; locked cancellation and canceled account switching.
Existing tests cover multi-window, Split View, rollback, Undo/Redo and render
failure recovery. The complete suite uses the project's per-module isolated
runner; a native crash/timeout is not treated as a skip.
The maintained cross-process helper is `tests/qa_watermark_restart.py`, called
by the regression test; its initial local copy was also compiled for the frozen
QA check. It is not imported or enabled by the production entry point.

### Commands

Run from the canonical D-drive workspace with `.venv-dev` and task-owned TEMP/TMP:

```text
python -m pytest tests/test_watermark_close_reopen.py tests/test_lifecycle_diagnostics.py -q
python -m scripts.regression_suite --group all --output build/probes/watermark-close-20261021/regression
python -m ruff check .
git diff --check
```

Initial QA-only build failures (relative asset path and missing project workflow
hook) were preserved and corrected without changing production packaging or
dependencies. Early test-only fixture stalls were diagnosed from captured Qt
stacks and corrected; stalled runs are not reported as passed.

### Separate PS Workflow limitation

The complete run found a Windows failure in
`test_published_ps_first_open_reuses_interpreted_preview[workflow]`: a staged
`production.pdf` could not be released (`WinError 32`). An unchanged isolated
rerun reproduced it. A read-only import overlay of all modified production
modules from baseline `c62a6a4` reproduced the same failure with an equally long
fresh temporary path (`ps-baseline-matched-length.log`: 4 passed, 1 failed).
An even longer baseline path reported `unable to open database file` instead.
With shorter fresh temporary paths, both baseline and current code passed all
five cases (`ps-baseline.log`, `ps-current.log`). No source checkout, branch
switch, test weakening or production algorithm change was used for this check.

This establishes a pre-existing path-sensitive Windows Workflow failure; it
does not establish the underlying owner of the file handle or that every long
output path fails. The failed full-run evidence remains retained. It must not
be described as a completely passing full regression or a fixed PS limitation.

### Deferred callback regression found and corrected

The first full run also exposed a native failure in the existing account UI
module. A zero-timer lambda can outlive the C++ QObject even while its Python
wrapper is retained. Unlike a QObject-bound slot, it needs explicit deletion
checks. `_schedule_closed_check()` now checks both the application and owning
viewer with `sip.isdeleted()` before accessing state or executing `_closed()`.
Two new tests failed before this guard (`deleted-red.log`) and passed afterward;
the complete account/close/diagnostic rerun passed all 43 cases. Independent
follow-up review found no blocking issue. The first failed run remains retained.
The same per-module isolated runner then passed the existing account module
alone: 21 passed (`auth-isolated-final/result.json`).

## Owner UAT

Use `scripts/launch_dev.cmd` in the canonical D-drive workspace for the corrected
local source; installed public v3.0.11 remains unchanged until a later release.

1. Open a **copy** of the reported PDF and apply a text or image Watermark.
2. Close the main application and choose Discard. Confirm the application exits.
3. Double-click a different PDF, then the original; confirm actual page content,
   page navigation and editing work. Repeat via in-app Open and Recent.
4. Repeat with Save and Cancel. Save must retain the watermark; Cancel must keep
   the current document and editing history. Check Split View if normally used.
5. Try opening another PDF while the save prompt is displayed: Cancel resumes
   pending opening; Discard opens it in a fresh Viewer after retirement.
6. If an unexpected blank view remains, retain the process and copy only the
   relevant lifecycle log interval and visible error text for diagnosis. Do not
   overwrite the original PDF to test recovery.

No cache, account store, preferences or customer files were cleared as a repair.
