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
| Source feature UAT | Owner-confirmed “LTGM”; separate from candidate login |
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
