# Release Validation — 3.1.3

Owner accepted the source features with “LTGM” and explicitly authorized Windows
update-only public release and main synchronization on 2026-10-30 (Hong Kong).
The owner separately confirmed: “沿用：先公開，登入保留 Pending”.
This is a directed publication exception, not a frozen-candidate login result.

Workspace: D:/Python_Project/PDFdocuEdit_Pro; branch main. Installer, Portable and
macOS are out of scope. Existing user data and credentials are excluded.

| Check | State |
| --- | --- |
| Frozen source / native run | Pending |
| Complete isolated Windows regression / build | Pending |
| Frozen login-ready / unauthenticated workers | Pending |
| Original Launcher two upgrades | Pending |
| Real-account login on new frozen candidate | Pending / Not Tested; owner will test after updating |
| Source feature review | Owner-confirmed “LTGM”; not independently confirmed manual candidate UAT |
| Signing / draft assets / public routes | Pending |
| Installer / Portable / macOS | Out of scope |
| Physical monitor transitions / printer / RIP / inserter | Not Tested on candidate |

Local popup validation: 133 related regressions, 22 extra DPI cases, 11 native
Windows UI tests and 36 native surface/pixel cases passed. Extract progress:
66 targeted cases passed. These are development checks; the complete frozen
release regression runs independently in native CI and is not inferred from them.

[Release notes](RELEASE_NOTES_3.1.3.md). [Release process](UNIFIED_RELEASE.md).
Final candidate evidence and timings will be completed here after publication;
the immutable tag retains its source-freeze record.

## Superseded first candidate

Main CI [40985033698](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/40985033698)
at `a80667b3793966cbf5e6717aa783baba5d7084bc` reported a native process crash
in `tests/test_measurement.py` after 15 passing cases. Its UI job had separately
passed 83 modules / 1,348 cases. Neither result is relabelled as evidence for a
later source. Native candidate run 40985034170 was cancelled as superseded.

The same crash reproduced locally. This mixed pure-metric/GUI module created
QApplication locally across tests instead of acquiring the existing session UI
fixture before its first overlay. Adding it to the existing UI registry made all
16 cases pass; no measurement assertions or product calculations changed. A
new CI-registry regression failed before that classification fix and passed
afterwards. Combined measurement/CI-plan checks: 29 passed; Ruff and source
verification passed. Failed logs and original run identities are retained under
build/probes/release-v3.1.3/. A new frozen SHA requires a fresh full candidate run.

## Superseded second candidate

Source `86f978606e10c85dda0b569830b1f9e228993c3c`, native run
[40987361295](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/40987361295),
completed all 228 modules but failed with native teardown access violations in
`test_multi_profile_scale_ui.py` and `test_review_fixes.py`. Main CI
[40987360866](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/40987360866)
was cancelled at its 30-minute Core job budget after 99 passing modules.
No candidate was signed or published from this attempt.

The two native faults were not uniquely reproduced locally, including repeated
runs with official CPython 3.12.10 and the existing Qt/pytest dependencies.
Investigation found test-owned Designer/Overlay windows were closed but retained
until QApplication teardown. Their shared test helpers now explicitly destroy
closed windows after worker retirement and tolerate Qt delete-on-close. Four new
regressions cover both helpers and deletion modes; they demonstrated missing
retirement and a deleted-wrapper query before the final guard. All 25 helper
consumer modules passed locally (328 cases, no skips). The combined four-module
check passed 25 cases. These results do not establish a unique production crash
cause and do not replace the fresh full native release gate.

The general Core CI job budget is now 60 minutes; native release remains 180.
No test modules, assertions or production checks were removed. Failed evidence,
local reproduction runs and source/run associations remain in the local release
probe directory. This harness/CI-only revision requires a fresh frozen candidate.

## Superseded third candidate and popup lifetime correction

Frozen source `22279f5683cba2eee9377d08b9857087233280e1` failed native run
[41008773757](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41008773757)
in `test_overlay_ui.py` and `test_p1_ui.py` during Qt teardown, after completing
all 228 modules. General main CI
[41008750942](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41008750942)
passed Core and source quality but failed the same P1 UI teardown. Previously
failing measurement, multi-profile and review-fix modules passed this attempt.
No candidate was signed or published.

P1 teardown reproduced locally on CPython 3.12.10. Three-process controls showed
the current shared filter crashing twice; the pre-popup theme passed all three.
Replacing the filter body with a no-op still crashed all three controls, so
removing drawing or alpha setup did not address the lifetime issue. The shared
application-owned filter was still watching hidden widget trees during native
application destruction. Binding each filter to its watched widget corrected
that ownership boundary. A native QObject tuple property retains its Python
virtual-method wrapper even when Qt discards a private dropdown wrapper; no
application-owned collection retains popup windows.

Three ownership regressions failed before the change. The final popup module
passed 14 cases, including private-wrapper reuse, geometry, alpha and interaction.
Four formerly failing modules each passed five fresh CPython 3.12.10 processes
(20 successful executions) without changing their original assertions. Earlier
harness retirement changes are retained as test ownership improvements; they
alone did not address all native application teardown faults. The final product
lifetime revision must pass a new complete candidate gate before publication.

Final lifetime revision development checks: 137 related regression cases; 42 native
Windows popup cases across three DPI settings; 36 native layered-surface/pixel
cases, all passed. These native images are component renders, not desktop
compositor screenshots. Ruff, source verification and whitespace checks passed.

## Superseded fourth candidate and retained-wrapper correction

Source `2ec07fa067d49b353c12a2c7e9566efb27aa6619`, native run
[41012293252](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41012293252),
completed 228 modules but failed native process teardown in detailed dialogs,
print preferences and tools-port checks. Main CI
[41012261436](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41012261436)
reported the same modules; source quality and both neutral-platform Core jobs
passed. The print-preference module reported 8 passing assertions and then
crashed at interpreter shutdown. Candidate download/signing/publication was
stopped; CI logs and full failure artifacts were retained.

Print preferences reproduced five consecutive failures on CPython 3.12.10.
Adding the shared application fixture and removing event-filter delivery at
exit did not resolve it; the pre-popup theme and disabling registration passed
controls. Retaining each Python filter wrapper in a coordinator registry until
its Qt destroyed signal passed five controls. Native PyObject-valued dynamic
properties are no longer used for filter ownership. Filters remain widget-owned;
the registry retains no watched widgets and prunes destroyed filter wrappers.

A fresh-process integration regression reproduces the 8-passed-then-native-crash
path before the change and passes afterwards. The popup suite now has 16 cases,
including discarded-menu/filter collection; related development checks total
139 cases. Four affected modules passed five separate CPython 3.12.10 processes
each. Native popup pytest passed 48 cases across three DPI settings; all 36
pixel/surface assertions passed. One custom native matrix process nevertheless
exited with an access violation after its assertions. Ten exact fresh-process
repeats (five per local/CI Python runtime) passed; that isolated probe exit cause
is not established and its failed log is retained. No extra shutdown workaround
was added on that evidence. This limitation remains separate from the new
complete source-bound candidate gate.

## Superseded fifth candidate and guarded application-QSS traversal

Source `8c4eed598d86896f1db020d02d8ba50717a60144`, native run
[41016371744](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41016371744),
completed 228 modules but failed PostScript UI and Profile Library UI. Main CI
[41016371213](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41016371213)
passed Windows Core, source quality and both neutral-platform Core jobs, but
failed Profile Library UI while restoring application QSS. The local publication
continuation stopped before candidate download/signing. No public package exists
from this attempt. The owner explicitly chose to retain and stabilize corners
before publication.

Independent review produced a deterministic native failure: create closed cyclic
widgets, clear their setup references and run Python GC inside a style polish
callback while Qt traverses its application widget snapshot. The native failure
also occurs with all popup registration disabled, so filter/child-list mutation
alone does not explain this mechanism. Holding the complete allWidgets wrapper
list until the native QSS call returns prevents the demonstrated failure. The
exact original Profile Library CI fault remains not uniquely diagnosed.

The final narrow helper in styles/theme.py retains that snapshot locally, calls
the existing Qt setter and releases references in finally. Both production QSS
callers and test application-QSS setup/restoration use it. Existing assertions,
CSS values and palette behavior remain unchanged. There is no global GC disabling,
new timer, deferred release or persistent widget collection. An initial direct
setter regression produced a native fault; guarded replacement/removal, collection
after return and exception propagation pass. Independent review found no blocker.
Fresh source-bound complete release gates are required for this new revision.

Final guarded-QSS development validation: 317 cases across 22 modules, no
failures/skips; 57 native Windows popup cases and 36 native surface/pixel cases
passed with normal process exit. The three new GC/exception cases also passed
on official CPython 3.12.10. Ruff, source verification, documentation links and
whitespace checks passed. Full startup cost has not been benchmarked; the local
widget snapshot is taken only for application stylesheet changes, not repaint.


## Superseded sixth candidate and pre-native popup shutdown

Source `6ce48774c2f46e5c9d23d7d775cce2fb4a36a18f`, native run
[41021591929](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41021591929),
completed 228 modules: 227 passed; Workflow settings navigation crashed after
its 13 assertions, before normal module completion. Main CI
[41021591508](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41021591508)
passed all 84 UI modules, source quality and neutral Core jobs, but encountered
the same Windows Core module failure. Publication remained stopped. A local
five-process control reproduced the native access violation once.

A Windows vectored-exception diagnostic captured the fault at
`sip.cp312-win_amd64.pyd+0x103e6`. Disassembly matches the installed PyQt6-sip
13.9.1 wrapper-map visitor; PyQt6's QApplication binding calls this visitor while
deleting remaining QObjects. Raw stack addresses are not a fully unwound symbolic
stack and do not uniquely explain every historical crash. A separate application
disposal control observed ChildRemoved filter callbacks after wrapper retirement
began, while Qt closingDown was still false. Callback argument conversion can
create SIP wrappers before the Python filter body runs.

The coordinator detaches filters and owned menu/destruction callbacks before
native cleanup, via aboutToQuit and a weakref finalizer for wrapper disposal
without an event loop. Registration and shared tooltip preparation stop first.
Cleanup is idempotent, retains no QApplication wrapper and neither deletes widgets
nor processes events/forces GC. Two subprocess regressions cover normal quit,
direct wrapper disposal, zero late callbacks, application collection, deleted
objects and repeated cleanup. The regression failed before the fix with late
ChildRemoved callbacks and passes afterwards. Independent review approved the
implementation and reran both cases.

The earlier reviewer workflow_destroy_events probe used an unavailable Qt enum
and is invalid diagnostic evidence; its abort is not a product-crash reproduction.
A repeated-module harness referenced a nonexistent profile module and returned
collection error 4, not a product regression. Both raw logs are preserved. Actual
profile-library tests remain in development QA. New complete source-bound release
gates are required before publication.


Early-retirement development verification: 332 passed across 23 isolated modules,
0 failed/skipped; 63 native Windows UI cases at actual DPR 1.0/1.5/2.0 and all
36 native layered-surface/pixel checks passed, with normal process exit. Workflow
settings also passed 12 fresh CPython 3.12.10 processes; print preferences passed
three. Ruff, source verification, five local documentation destinations and
whitespace checks passed. Physical monitor migration and packaged candidate
login remain separate, untested items. This evidence does not replace the new
complete frozen Windows candidate gate.
