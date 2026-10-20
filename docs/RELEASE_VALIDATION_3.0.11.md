# Release Validation — 3.0.11

## Source and scope

Owner authorized direct public Windows update-only publication on 2026-10-21
(Hong Kong). Product workspace: `D:/Python_Project/PDFdocuEdit_Pro`; local branch
`main`; product base `f1ddd9e1717ee6be2a1f9c83d82c9c9c79e59ed6`.
Installer, Portable and macOS are explicitly out of scope.

Reuse the pre-existing remote `codex/windows-update-v3.0.8` publication ref by
fast-forward only; no local branch/worktree creation or switch. This preserves
one local main development line and the existing release-CI deduplication.
The owner's untracked profile is not read, staged or uploaded.

Frozen SHA, fingerprint, run ID, stage timings and artifact paths will be recorded
in `build/probes/release-v3.0.11/progress.json` and finalized here after publication.

## Acceptance

| Check | Status |
|---|---|
| Source metadata / release contracts | Pending |
| Complete Windows native isolated regression | Pending — development tests do not replace this gate |
| Windows update-only candidate and frozen login-ready / worker admission | Pending |
| Exact candidate source / hash / signature checks | Pending |
| Original Launcher successive frozen upgrades | Pending |
| Current candidate real-account login | Pending / Not Tested — owner previously directed post-publication testing and now again requests direct publication |
| Draft remote asset checks | Pending |
| Public tag / both Windows signed routes / attachment hashes | Pending |
| Installer / Portable / macOS | Out of scope |
| Physical printer / RIP / inserter / customer jobs | Not Tested |

The owner's continuing arrangement is: “不用, 發佈更新包後我會自行更新, 到時再測試,
唔得會同你講”. Preserve a source-specific exception record; never mark login true.
All remaining native, signing, package, successive-upgrade and publication gates
remain required. Do not modify the standard acceptance gate to fabricate a pass.

Previous development evidence includes 644 affected regression tests and 60 at
200% Qt scaling for the final image/stamp patch, and earlier complete baseline
regression; none substitutes for this new frozen release candidate.

## Delivery

Release URL, hashes, actual native results and timing: Pending.
Public version notes: [v3.0.11](RELEASE_NOTES_3.0.11.md).
