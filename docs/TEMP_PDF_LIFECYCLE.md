# Editor temporary PDF cleanup — 2026-10-21

## Confirmed defect and repair

Baseline: local main `b8301da` (Watermark close/reopen reliability repair).
The investigation reproduced three retired sessions leaving three owned Undo
PDFs behind, including after QObject deletion. Working copies were removed.
`DocumentSession.close()` previously retired readers/engine/thumbnail snapshots
without clearing its `UndoStack`.

The session now checks the existing engine transaction guard, then calls the
existing `UndoStack.clear()` on the UI thread before detaching readers. An
active history restore also rejects this operation through the stack's existing
idle check. Rejection leaves history, live document and retirement state intact.
Approved close entry points already defer active mutations and ask Save/Discard/
Cancel before retiring a session. Cancel preserves the document and history.

History files are independent immutable copies. Rendering uses the engine's own
working copy; history restore copies its target into a new engine. Clearing
history therefore does not force reader release. The existing `after_readers`
mechanism still delays working-copy and thumbnail cleanup until owned readers
finish. Repeated session close remains idempotent.

No new public interface, dependency, PDF format or Undo depth change. No PS
cache changes, global Temp sweep, startup scan or old-file recovery system.

## Deletion failure and ownership

Only paths held by this session's Undo/Redo stack are removed. Source PDFs,
other sessions and unrelated temporary files are not scanned or deleted.
Existing snapshot cleanup logs a deletion error and leaves the file in place;
it does not force-unlock it or prevent safe document close. Such a failure is
not a successful deletion and does not gain automatic retry/recovery here.

Existing historical files remain untouched. The photographed `tmp*.pdf` list
belongs to another Windows user/machine and has not been attributed conclusively
to this version. Filenames alone are not sufficient ownership evidence.

## Verification

Local evidence is retained under `build/probes/session-temp-cleanup-20261021/`.

- `red-lifecycle.log`: owned history remained after close before the fix.
- `red-mutation.log`: direct close during a mutation failed to reject before the
  explicit engine guard. Both failures are retained.
- The first attempted red run hit sandbox TEMP permission errors; that run is
  not treated as a product failure or passing test. Subsequent tests use D-drive
  task-owned TEMP/TMP.
- New lifecycle tests cover Undo and Redo cleanup on the UI thread, repeated
  close, active mutation/restore rejection, held reader leases, locked deletion,
  actual Save/Discard/Cancel dialogs for tab/window close, and other-tab history.
- A 50-cycle synthetic open/edit/close test checks no growth in remaining PDFs,
  unchanged source SHA-256 and preservation of an unrelated PDF sentinel.
- Existing regression modules cover history, mutation/annotation transactions,
  close status, multiple windows, accounts, Watermark restart and queued opens.

Results: the 11-module isolated regression passed 203 tests, with no failures,
errors or skips (`regression/result.json`). Its first lifecycle module ran the
initial 12 cases. After the review added the direct-mutation guard case, the
final lifecycle (13) and mutation (24) modules passed all 37 tests together in
24.47 seconds (`final-targeted.xml`). Independent follow-up review found no
remaining blocker. Ruff, whitespace and the canonical development-launcher
check passed. These are targeted regressions; the entire repository suite was
not rerun for this bounded repair.

These tests use synthetic PDFs and isolated settings. This change does not
constitute real-account, customer-PDF, macOS or physical-printer acceptance.
It is a local source repair, not an installer or public release.

## Manual UAT

Use the canonical D-drive development launcher and a copy of a test PDF:

1. Rotate or annotate, then Undo once so both history directions can be used.
2. Cancel closing: the page, Undo and Redo must remain usable.
3. Close with Discard, then repeat with Save. Reopen and verify the intended
   saved state; no old history should reappear for the new session.
4. Keep a second edited tab open while closing the first; its history must stay.

Do not clear the Windows Temp folder as a workaround or use old-file deletion
as evidence that the lifecycle defect is repaired.
