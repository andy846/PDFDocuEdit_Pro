# Release Validation — 3.0.8

## Scope

Owner requested **Windows Managed update packages only**. Installer, Portable and macOS builds/uploads are out of scope. Two signed Windows routes share identical application archives; no old Mac package is relabelled.

## Frozen source and evidence

| Item | Evidence |
|---|---|
| Version / tag | 3.0.8 / v3.0.8 |
| Branch | codex/windows-update-v3.0.8 |
| Frozen product SHA | `33db7affbb77212134878c4815e82ffac4b2a307` |
| Source fingerprint | `47328bfb41104c355858548e911987e942c9843fde3bb5c6a2f3544dc5af9b90` |
| Native run | [38659777253](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38659777253), frozen head SHA verified |
| Local evidence | `build/probes/release-v3.0.8-38659777253/` in the product worktree |
| Signed index SHA256 | `1319e76489bdf6790ebb5eb90346be1d6a72a60f54395db1bed8c56dcd2891e9` |
| Attachments | 8 declared files plus signed index/signature = 10; Windows update ZIPs, checksums and signed manifests only |
| Release | GitHub draft; public publication pending |

## Acceptance

| Check | Status | Evidence |
|---|---|---|
| Windows complete isolated regression | Passed | 184 modules; 2,577 passed, 3 existing skips; zero failures/errors; native `windows/build/ci-release/result.json` |
| Native application / two update archives | Passed | Windows runner completed PyInstaller and archive packaging; embedded commit/version/fingerprint/target validated locally |
| CI complete job | Failed at QA infrastructure | `Get-CimInstance Win32_Process` timed out after 15s during empty frozen-login child lookup; not a regression or product assertion failure |
| Missing frozen-login gate recovered locally | Passed | Same unchanged native archive; actual frozen login-ready handshake in 2.59s; `native-qa-recovery.json` |
| Unauthenticated worker admission | Passed | Composition, print and PDF-operation worker flags rejected by actual candidate executable in isolated environment |
| QA Launcher provenance | Passed | Existing signed v3.0.7 Managed launcher; source for launcher, updates and auth unchanged; SHA256 `a8b7057add8bc5772baacedca6955d1895abab215a146f822aaa403d32ffa7d0` |
| Original Launcher two upgrades | Passed | 3.0.3 → 3.0.7 → 3.0.8; `D:/Python_Project/PDFdocuEdit_Pro/build/Q8/result.json` |
| Launcher / settings preservation | Passed | Original SHA256 `172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522`; sentinel preferences preserved |
| Signatures / provenance / archive integrity | Passed | Existing candidate and sealed validators; unchanged public key and account project |
| Current-candidate real-account login | Pending | Not established by pre-login QA. `signed/operator-acceptance.json` keeps this false |
| Remote draft attachments | Passed | All 10 exact remote names/sizes/SHA256 match signed index; `remote-draft-validation.json`, 2026-10-15 01:02:53 UTC |
| Public publication / public routes | Pending | Await current-candidate login acceptance or explicit owner exception |
| Installer / Portable / Mac | Out of scope | Explicit owner instruction |

## Recovery and process

The full regression passed once (00:25:10–00:52:12 UTC, 27m 02s). Native build completed before CI's process-query timeout. The uploaded artifact contained the original two application ZIPs, checksums, candidate manifests and complete regression report; the final candidate index was not written before timeout.

A local one-off recovery harness verified the frozen source, clean worktree, all native regression rows, archive hashes, embedded source fingerprint and account target. It extracted that unchanged native app into a fresh QA directory, used the previous signed Managed launcher, and actually ran the missing login/worker checks. Local credential-store reads were blocked by an isolated require-signin marker; no actual credentials were used or modified. The existing candidate-record helper and normal sealed validator then bound those real results. CI is still recorded as failed; its status is not presented as green. No repeated full regression, binary rebuild or fabricated test result was used.

Preparation: 26 release/source contracts passed, full Ruff and source verification passed. Independent review caught an indentation error in the new candidate packaging path; it was fixed and checked before freezing this SHA.

Only empty QA child processes were stopped; the user's running application and work were untouched. Actual-account login remains a distinct operator check. Any documentation follow-up records evidence without relabelling frozen artifacts as the newer documentation commit.

## Limits

The latest Windows-only release has no Mac update manifest; older Mac update checks will report a missing Mac attachment. Existing Mac installation remains usable. Installer/Portable users needing first installation can use [v3.0.7](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.7) and then update.

The reported customer PS throughput problem remains uncharacterised; v3.0.8 improves progress visibility, not a proven conversion speed cause. Printer/inserter hardware proof, new real-account login and this version's Mac operation are not claimed.
