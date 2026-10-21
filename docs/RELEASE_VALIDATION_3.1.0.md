# Release Validation — 3.1.0

## Source and scope

Owner authorized v3.1.0, main synchronization and direct public Windows update-only
publication on 2026-10-22 (Hong Kong). Canonical workspace
`D:/Python_Project/PDFdocuEdit_Pro`, branch `main`; product base
`ea1030478c7b7277e34a4996eefb51c9a4346403`.

Windows private and legacy-compatible update packages only. Installer, Portable
and macOS are out of scope, not passed gates. No new branch/worktree or merge.
The operator profile is not read, staged or uploaded.

## Candidate and acceptance

This is the source-freeze record. Actual completion evidence is added on main
after publication without moving the frozen tag or overwriting public assets.

| Check | Status / evidence |
|---|---|
| Version / tag | 3.1.0 / v3.1.0 |
| Frozen SHA / source fingerprint | Pending — recorded in release progress after commit |
| Remote main ancestor / synchronization | Ancestor cfc19778 at preparation; push Pending |
| Source/release contracts | Pending |
| Windows complete isolated native regression | Pending |
| Windows update-only native build | Pending |
| Frozen login-ready / unauthenticated worker rejection | Pending |
| Original frozen Launcher two successive upgrades | Pending |
| Candidate real-account login | Pending / Not Tested |
| Candidate sources / signatures / exact draft assets | Pending |
| Public tag / latest / both Windows update routes | Pending |
| Installer / Portable / macOS | Out of scope |
| Actual customer workflows / physical printer / RIP / inserter | Not Tested on this candidate |

v3.0.11 owner acceptance is preserved in its own record and is not a v3.1.0
candidate test. No missing gate is inferred passed.

## Timing and continuation

Stage start/end times, full SHA, native run ID, source fingerprint, artifact
hashes and resumable state are retained in `build/probes/release-v3.1.0/`.
Source preparation, native testing/build, download, signature validation,
isolated upgrades, publication and public verification: Pending.

Main workflow: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).
Release notes: [3.1.0](RELEASE_NOTES_3.1.0.md).
