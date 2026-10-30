# Release Validation — 3.1.3

## Source and scope

Owner replied “LTGM”, authorized direct Windows update-only public release and
main synchronization, and separately confirmed “沿用：先公開，登入保留 Pending”
on 2026-10-30 (Hong Kong). Canonical workspace D:/Python_Project/PDFdocuEdit_Pro,
branch main. No branch/worktree was created, switched or merged; no force push.
User Profile, private signing material, settings and customer files were excluded.

| Item | Completed evidence |
| --- | --- |
| Frozen source | `6fbdc41d3c27a152dea98fa392e82502b350d16b` |
| Source fingerprint | `9398fe2a4c7ae3740ad270c5cd3721bffbc2a0a8990bbeedcb3deb15a11249f8` |
| Feature commit / base | `aaf440fdcd04108a5f8ed19a9108351d4a4bb55f` |
| Main synchronization | Ordinary fast-forward from `0ec0765377cf1dfbc3dc5c1b4fa70378bf2728fe` |
| Native Windows run | [41048481115](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41048481115) |
| General main CI | [41048480195](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/41048480195) |
| Release | [v3.1.3](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.1.3), latest, non-prerelease |
| Published UTC | 2026-10-30T12:14:35Z |

## Acceptance and verification

| Check | Actual result |
| --- | --- |
| Initial release contracts | 28 passed / 1 host symlink-permission skip before lifetime follow-up |
| Final popup lifetime development checks | 332 targeted cases in 23 modules; 63 native DPI UI cases and 36 pixel assertions; deterministic GC/exception and early application-retirement regressions; 12 fresh Workflow repetitions; independent review, Ruff/source/links/whitespace passed |
| Frozen Windows full regression | 228 exact tracked modules; 3637 passed / 3 skipped; zero failures/errors |
| Three native-platform skips | macOS symlink/executable permissions, Keychain, and arm64 signing/bundle installation; not applicable to this Windows run |
| Update-only package | Passed; identical private/legacy ZIP contents, no installer/portable archives |
| Frozen login-ready and unauthenticated workers | Passed; all three worker admission modes verified |
| Original frozen Launcher upgrades | Passed: 3.0.3 → 3.1.2 → 3.1.3; original Launcher and settings preserved |
| Upgrade credential isolation | Passed; private local data, require-signin marker, blocked network |
| Owner review / public-release direction | Confirmed separately; exact source-bound direction retained |
| New frozen candidate real-account login | Pending / Not Tested; owner explicitly chose post-publication testing |
| Candidate source, font resources, manifest signatures | Passed using existing validators and trust anchor |
| Draft exact asset names/sizes/SHA256 | Passed; 10 assets |
| Public tag/latest and both anonymous Windows update routes | Passed; exact frozen SHA, signatures, ZIP availability |
| Installer / Portable / macOS build | Out of scope |
| Physical monitor changes, real customer PDF, printer/RIP/inserter on candidate | Not Tested |

`windows_account_login=false` remains in the source-bound operator record.
LTGM is retained as owner review sign-off; independent manual source UAT is not inferred.
The standard make-public gate was not modified. Promotion used the documented,
explicit owner-directed publication exception after every other native, source,
signing, upgrade and asset gate passed. No prior login or hardware acceptance
was relabelled as a test of this new candidate.

The complete candidate suite above is independent of development evidence:
133 related popup regressions, 22 extra DPI checks, 11 native Windows UI checks,
36 native edge cases and 66 extraction-progress checks. These counts are not
added to native full-regression totals. Main CI is recorded separately:

| General main CI job | Result |
| --- | --- |
| Source quality | success |
| Select test scope | success |
| Automated suite on Windows | success |
| Core tests on ubuntu-latest | success |
| UI interaction tests on Windows | success |
| Core tests on macos-14 | success |
| Affected tests and smoke on Windows | skipped |

## Superseded first candidate

At `a80667b3793966cbf5e6717aa783baba5d7084bc`, main CI run 40985033698
reported a native measurement-suite process crash after 15 passing cases;
its separate UI run passed 83 modules / 1,348 cases. Native run 40985034170 was
cancelled as superseded. The failure reproduced locally. The mixed metric/GUI
module had omitted the existing shared QApplication fixture; classifying it in
the existing UI registry made all 16 measurement cases pass. A new registry
regression failed before that fix and passed afterwards. Combined local checks:
29 passed, with all original measurement assertions and product calculations
unchanged. No test was removed or bypassed. The successful full candidate above
uses the new frozen SHA; first-attempt results were not relabelled or reused.
Original run identities, diagnostics and hash-verified checkpoints remain under
build/probes/release-v3.1.3/attempt-01/ and the retained main-core/main-ui folders.

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

## Timings (UTC)

| Stage | Start | End | Duration |
| --- | --- | --- | --- |
| Final source-freeze bookkeeping | 2026-10-30T11:29:41+00:00 | 2026-10-30T11:29:42.244606+00:00 | 1.24 s |
| Superseded native run 40985034170 (cancelled) | 2026-10-30T01:18:22Z | 2026-10-30T01:39:33Z | 1271.00 s |
| Superseded native run 40987361295 (failure) | 2026-10-30T01:41:52Z | 2026-10-30T02:11:47Z | 1795.00 s |
| Superseded native run 41008773757 (failure) | 2026-10-30T05:30:11Z | 2026-10-30T05:52:01Z | 1310.00 s |
| Superseded native run 41012293252 (failure) | 2026-10-30T06:08:04Z | 2026-10-30T06:40:50Z | 1966.00 s |
| Superseded native run 41016371744 (failure) | 2026-10-30T06:49:49Z | 2026-10-30T07:26:51Z | 2222.00 s |
| Superseded native run 41021591929 (failure) | 2026-10-30T07:41:11Z | 2026-10-30T08:18:15Z | 2224.00 s |
| Full isolated regression | 2026-10-30T11:31:10Z | 2026-10-30T12:04:09Z | 1979.00 s |
| Native account release candidates | 2026-10-30T12:04:09Z | 2026-10-30T12:06:15Z | 126.00 s |
| download | 2026-10-30T12:06:50.076475+00:00 | 2026-10-30T12:08:59.857537+00:00 | 129.78 s |
| candidate-validation | 2026-10-30T12:08:59.859594+00:00 | 2026-10-30T12:09:00.911880+00:00 | 1.05 s |
| seal | 2026-10-30T12:09:00.913879+00:00 | 2026-10-30T12:09:04.527272+00:00 | 3.61 s |
| isolated-upgrades | 2026-10-30T12:09:04.529252+00:00 | 2026-10-30T12:09:35.691939+00:00 | 31.16 s |
| publication | 2026-10-30T12:12:11.281498+00:00 | 2026-10-30T12:14:35.763457+00:00 | 144.48 s |
| public-verification | 2026-10-30T12:17:01.604835+00:00 | 2026-10-30T12:17:12.954510+00:00 | 11.35 s |

The final source-freeze row measures checkpoint bookkeeping only, not all local
investigation or QA. Earlier investigation, interrupted waits and failed-run time
are included in the overall wall-clock; superseded run durations remain separate.

Wall-clock from version preparation to anonymous verification:
39741.53 s.

## Delivery

Both Windows ZIPs: 360,280,903 bytes;
SHA256 `2cdbafdbc5f1dddc37e0259bae501bea61f5be73a14273ad2be19583cffa2a02`.
Existing Managed installations use **Help → Check for Updates**.
No new installer/portable/macOS files were made. Older latest-only Mac updaters
may report missing Mac assets; installed Mac apps remain usable.

Local run evidence, stage logs, signed index, upgrade reports and public checks
remain under build/probes/release-v3.1.3/. Private local artifacts are not committed.
Public release assets/tag remain immutable; this completion record is a separate
main documentation commit after the product source freeze.

[Release notes](RELEASE_NOTES_3.1.3.md).
[Popup development validation](POPUP_SMOOTH_EDGES_VALIDATION.md).
[Release process](UNIFIED_RELEASE.md).


## Publication continuation and verification runtime

The first draft creation succeeded, but its immediate authenticated list lookup
returned no draft. The exact-source empty draft was subsequently found and
verified before resuming uploads. The existing publisher reused that draft;
no candidate, signature or upgrade test was regenerated, and no public asset
was overwritten. Initial failure logs remain preserved locally.

The development interpreter (CPython 3.12.14) failed default TLS issuer validation
for anonymous release metadata. Official CPython 3.12.10 succeeded with default
TLS trust, without changing certificates, disabling verification or altering the
updater. Inspection of the signed ZIP's python312.dll confirmed FileVersion and
ProductVersion 3.12.10. The unchanged public verifier was rerun with that matching
runtime: all ten asset sizes/digests, exact tag/latest source, both anonymous
manifest signatures and both ZIP download endpoints passed. The development
interpreter trust discrepancy remains a local validation-environment limitation.
