# Release Validation — 3.0.9

## Scope and source

Owner explicitly requested Windows upgrade packages only and direct public publication. Installer, Portable and macOS are out of scope. The owner previously acknowledged that company printer proof must wait for the company environment.

| Item | Evidence |
|---|---|
| Version / tag | 3.0.9 / v3.0.9 |
| Frozen product SHA | `95c839e13c39947e962fa4d47f5d584087614320` |
| Source fingerprint | `0dba4a6ad5f5c44e943f4a0ffe372408ff805d4869f33a6e235dbf12dfa41f2c` |
| Development branch | `codex/deep-search-restore-layout`, retained |
| Release ref | Existing `codex/windows-update-v3.0.8` fast-forwarded to frozen SHA; no new branch, old tags/assets unchanged |
| Native run | [38768837841](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38768837841), frozen head SHA verified |
| Source quality | [38768838312](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38768838312), passed |
| Local evidence | `build/probes/release-v3.0.9/` in the product worktree |
| Signed index SHA256 | `e289c04adb601dd855032ab3cb5f4bdb3e5ebe47196cc23f41fcaf9ef397bad8` |
| Attachments | Two identical Windows update ZIPs, checksums, private/legacy signed manifests and signed index; 10 files total |
| Public release / routes | [v3.0.9](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.9), public/latest/non-prerelease, 2026-10-15T17:10:42Z |

## Acceptance

| Check | Status | Evidence |
|---|---|---|
| Windows complete isolated regression | Passed | Exact 187-module source list; 2,612 passed, 3 existing skips, zero failures/errors; `windows/build/ci-release/result.json` |
| Native application and update archives | Passed | Windows runner completed PyInstaller and both archives; embedded commit/version/fingerprint/account target validated locally |
| Complete native CI job | Failed at QA infrastructure | Frozen QA `Get-CimInstance Win32_Process` query timed out after 15 seconds; complete regression passed before packaging |
| Missing frozen-login check recovered locally | Passed | Same unchanged native archive; real pre-login readiness in 2.59 seconds; `native-qa-recovery.json` |
| Unauthenticated worker admission | Passed | Candidate executable rejected composition, print and PDF-operations worker flags |
| QA Launcher provenance | Passed | Existing signed v3.0.7 Managed Launcher; launcher/auth/update runtime source unchanged; SHA256 `a8b7057add8bc5772baacedca6955d1895abab215a146f822aaa403d32ffa7d0` |
| Original Launcher successive upgrades | Passed | 3.0.3 -> 3.0.8 -> 3.0.9; `D:/Python_Project/PDFdocuEdit_Pro/build/Q9/result.json` |
| Launcher and test settings preservation | Passed | Original Launcher SHA256 `172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522`; sentinel preferences preserved |
| Signatures, provenance and archive integrity | Passed | Existing candidate/sealed validators, same public key/account project; `native-validation.json`, `seal-validation.json` |
| Current-candidate real-account login | Pending | Pre-login readiness does not prove actual login; `signed/operator-acceptance.json` keeps false |
| Company printer / DFE proof | Pending | Owner to test at company; simulated/PDF output is not hardware evidence |
| Remote draft attachments | Passed | All 10 exact names, sizes and SHA256 matched signed index; `remote-draft-validation.json` |
| Public release / routes | Passed | Frozen tag SHA, all 10 public assets and hashes, both anonymously verified signed Windows manifests, both update ZIP HEAD downloads; `post-publication-validation.json` |
| Installer / Portable / Mac | Out of scope | Explicit owner instruction; none built or uploaded |

## Recovery and process

The native full regression passed once, 16:27:21–16:57:42 UTC (30m 21s). Packaging completed before the CI process-query timeout. The uploaded artifact preserved both original ZIPs, checksums, candidate manifests and all regression rows; the final candidate index had not been written.

A one-off local recovery verified the clean frozen source, exact test-module coverage, every successful native row, archive hashes, embedded fingerprint and account identity. It extracted the same unchanged native application into a fresh short QA directory, verified the previous signed Managed Launcher and actually performed the missing login-ready and worker-denial checks. Launcher build logic and runtime are unchanged; the update packaging script's only differences from v3.0.7 concern update-only output selection. The normal candidate-record and sealed validators bound the recovered results. The CI failure is retained, not relabelled green; no repeated full regression, replacement binary or fabricated result was used.

Local require-signin markers prevented credential-store reads; proxy isolation prevented account access. No actual credentials were used or modified. Only the harness's own empty children were stopped; the user's application and documents were untouched. The successive upgrade harness used separate fresh QA directories and the allowlisted original Launcher.

Preparation: 28 source/release/CI contracts passed and full Ruff passed. Development evidence includes 115 shutdown checks and 81 printing checks; native full regression remains the release evidence. This release includes the printing paper/live-geometry fixes, compact Deep Search layout and shared shutdown status/recovery.

## Owner-directed publication and limits

The owner explicitly requested direct public Windows update-only publication. `owner-publication-instruction.json` preserves the exact instruction. The normal publisher validates the sealed draft and all remote names/sizes/SHA256 before the explicit publication operation. Its normal operator gate is unchanged; no untested acceptance field is set true. Actual-account login remains false and hardware proof pending.

The latest Windows-only release has no Mac manifest; old Mac update checks may report a missing Mac attachment. Installed Mac applications remain usable. No old Mac package is relabelled. First installation can use the [v3.0.7 Managed installation](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.7), then update. The unknown original Designer lock incident trigger is not claimed as uniquely identified.

Any documentation follow-up records evidence without changing the frozen binary SHA, signed assets or public version.

## Publication completion

Published 2026-10-15T17:10:42Z under the owner's direct-publication instruction. The public tag resolves to the frozen product SHA, all ten remote attachments match the signed index, both private and legacy routes resolve signed v3.0.9, and both public ZIP links return success. No Installer, Portable or Mac attachment is present. Actual-account login remains false in operator acceptance; company printer proof is pending.

This documentation-only follow-up does not alter frozen product provenance or signed release assets.
