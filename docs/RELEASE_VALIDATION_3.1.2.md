# Release Validation — 3.1.2

Owner confirmed source feature UAT on `3b710c594b9ac8b7cd20b248468ba4e30dc77de3`
and authorized direct public Windows update-only release and main synchronization
on 2026-10-29 (Hong Kong). Canonical workspace: D:/Python_Project/PDFdocuEdit_Pro,
local main. Installer, Portable and macOS are explicitly out of scope.

This is the source-freeze record, not proof that publication already completed.
The final record on main will be updated from actual candidate evidence after
publication without moving the tag or changing frozen artifacts.

| Item | Actual status |
|---|---|
| Version / tag | 3.1.2 / v3.1.2 |
| Product base | `3b710c594b9ac8b7cd20b248468ba4e30dc77de3` |
| Frozen SHA / fingerprint | Pending source commit |
| Main fast-forward | Pending; remote main checked as ancestor |
| Source feature UAT | Owner confirmed 已驗收 |
| Local release contracts | Pending |
| Windows complete isolated native regression | Pending |
| Native Windows update-only package / frozen login-ready | Pending |
| Existing frozen Launcher two upgrades | Pending |
| Candidate real-account login | Pending / Not Tested independently |
| Candidate source/signature/asset verification | Pending |
| Draft upload / exact remote hashes | Pending |
| Public tag/latest / both anonymous Windows update routes | Pending |
| Installer / Portable / macOS artifacts | Out of scope |
| Physical printer / RIP / inserter / packaged customer workflows | Not Tested on this candidate |

The source acceptance predates this frozen candidate. It is recorded separately
from real-account candidate login, which must not be fabricated as passed. The
owner's direct-publication direction and any explicit publication exception
remain source-bound in the local progress record; all other gates still apply.

Progress, stage times and evidence: build/probes/release-v3.1.2/ (local only).
Release notes: [3.1.2](RELEASE_NOTES_3.1.2.md).
Process: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).

## Superseded first candidate checks

Main CI run 40793773821 at `b9f4a7421c04e9683841278b9f28fe998d086e55`
failed two Windows UI cases. The page-raster case observed an idle worker before
its debounced replacement started. Extending the debounce reproduced the same
failure locally; the test now waits for page 4's committed raster and the timer,
without removing its drawing-safety or geometry assertions (16 module tests pass).
The Organizer auto-scroll failure was not reproduced in targeted or full-module
local runs (10 module tests pass); its code and assertions remain unchanged.
Both failures and original diagnostics are retained locally. This candidate is
superseded; publication requires new exact-source full native and main CI passes.
