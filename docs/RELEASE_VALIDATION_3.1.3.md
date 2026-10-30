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
