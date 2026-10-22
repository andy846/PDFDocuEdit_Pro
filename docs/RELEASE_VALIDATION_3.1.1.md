# Release Validation — 3.1.1

## Source and authorization

Owner confirmed acceptance of the running `0e25c15` source and explicitly
authorized direct public Windows update-only v3.1.1 and main synchronization
on 2026-10-23 (Hong Kong). Canonical workspace:
`D:/Python_Project/PDFdocuEdit_Pro`, local `main`.

Product baseline: `0e25c156544dfc7a9e0cfec28b56c6dc4b09058d`, whose tracked tree
equals `a0487dee17de7ce9693b667106c03c0bd43100ba`. The PyMuPDF 2.0 compatibility
experiment was reverted. PyMuPDF remains 1.26.6.

Remote main verified as ancestor: `991b6b34a09fde5a05e637c1cada4e0e10f7a6cc`.
No new branch/worktree, merge, force push or existing tag movement is authorized.
The pre-existing operator profile and private/local files remain excluded.

| Check | Status / evidence at source freeze |
|---|---|
| Owner source UAT | Passed, owner replied “已驗收” after testing `0e25c15` |
| Source preparation / metadata checks | Passed: 16 local release contract tests; Ruff and source verification |
| Exact frozen SHA / source fingerprint | Pending; candidate index and local progress bind the full values |
| Main ordinary fast-forward | Pending |
| Windows full isolated native regression | Pending |
| Native update-only package / frozen admission smoke | Pending |
| Original Launcher two upgrades | Pending |
| New frozen candidate real-account login | Pending / Not Tested independently |
| Owner-directed direct publication | Explicitly authorized; preserve truthful untested candidate login evidence |
| Signing / draft exact asset hashes | Pending |
| Public tag/latest / private and legacy update routes | Pending |
| Installer / Portable / macOS | Out of scope |
| Physical printer / RIP / inserter on this candidate | Not Tested |

The owner's source acceptance is not relabeled as an independently observed login
to a frozen package that did not yet exist. Preserve the existing owner-directed
publication arrangement and keep `windows_account_login=false` where untested;
do not change validators or fabricate a passed gate.

## Timings and delivery

Pending. Each stage, native run, frozen SHA, hashes, source-bound owner direction,
isolated upgrade reports and public verification will be recorded separately
under `build/probes/release-v3.1.1/` and summarized here after completion.

The tag retains this freeze-time record. Final evidence is appended on main
without moving the immutable release tag or replacing public assets.

Release notes: [v3.1.1](RELEASE_NOTES_3.1.1.md).
Process: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).
