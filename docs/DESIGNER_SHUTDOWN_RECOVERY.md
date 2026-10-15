# Shared shutdown status and recovery

The top-level CloseStatusBar is owned by CloseLifecycle and inserted below the
command bar, outside PDF/Designer content and the work-control lock. It is hidden
normally, appears after the existing three-second waiting deadline, and appears
immediately on a failed/blocked close. It updates in place, independently of the
PDF InfoBar queue. The logo and native-style window controls stay enabled.

## Lifecycle boundary

ClosePhase distinguishes idle, preparing, waiting, cleaning, failed and closed.
All save confirmations and window-preference writes run before cancellation,
project closure or PDF-reader retirement. Every participating window completes
this preparation before application exit starts. A failed preparation revokes
close-specific approvals/locks, preserving document ownership, account access and
printing restrictions. Return to work dismisses the error and resets the attempt.

mark_teardown_started records the irreversible boundary before calling existing
cleanup. DocumentWindows.exit_teardown_started retains group history even when a
child closes and disappears from live_windows. Return to work is prohibited once
any participant has crossed that boundary. Existing project/session retirement
flags remain authoritative, so retries do not retire documents twice. A retry in
any participating window routes through the primary exit coordinator. Reentrant
close calls do not start another preflight; pending retries wait while a modal
window, such as Diagnostics, is active. A failure stops automatic retry until the
operator requests it.

No forced termination or blanket re-enable is introduced. A stuck native reader
can still delay shutdown, but its wait/failure state is visible in either mode,
including an empty Designer home. The original operator incident was not captured;
this fix addresses the reproducible paths, not an asserted unique cause.

## Diagnostics and verification

Fixed lifecycle stage names log numeric phase, local/group teardown, lock depth,
closing/exit flags, mode, project tab count, pending work/readers and modal presence.
Exception logs retain class and stack locations without exception payloads. No PDF
values, account data, credentials or source paths are added to status snapshots.

Targeted tests are in tests/test_close_status.py alongside existing error-recovery,
document-window and workspace-mode lifecycle suites. Generated PDFs, controlled
workers, faulted settings writes and one-time cleanup failures verify ownership
and recovery. UI checks use isolated settings, two themes, narrow windows and
200% scaling; normal work adds no visible chrome. Product README describes the
operator controls. No public version, save format, dependency or updater changes.

## Targeted evidence — 2026-10-16

Final isolated runs: close status 14 passed, error recovery 16 passed, document
windows 26 passed, workspace modes 38 passed; CI/source contracts 21 passed.
Targeted Ruff and diff checks passed. The original combined Qt run was stopped
and is not counted. Whole-branch review found three multi-window issues; each
was reproduced before repair and is covered by the final close-status suite.

Offscreen Windows UI probes verified light/dark at 100% and 200% within a
960 × 640 physical screen model. Failure controls were reachable, keyboard
Return to work succeeded, unsafe Return stayed hidden, and branding stayed
coloured. These probes use isolated settings and do not prove macOS/native
window-manager behavior or establish the original incident's exact trigger.
