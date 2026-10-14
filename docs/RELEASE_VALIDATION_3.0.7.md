# Release Validation — 3.0.7

## Status

Native candidates, signing and all 20 remote attachments passed. **Published as latest on 2026-10-14 01:46:04 UTC (09:46:04 Hong Kong).**
Real-account Windows/Mac login, Mac offline restart and Mac cross-version update remain Pending.
The [standard release procedure](UNIFIED_RELEASE.md) normally requires current-candidate operator results. After the four outstanding checks were explicitly disclosed, the repository owner instructed “Release”. This release-specific publication instruction overrides the wait for those checks; it does not supply test results. `operator-acceptance.json` remains unchanged: the four untested checks stay false. No prior-version results are substituted.

## Frozen source and evidence

| Item | Evidence |
|---|---|
| Version / tag | 3.0.7 / v3.0.7 |
| Repository / branch | andy846/PDFDocuEdit_Pro / codex/unified-release-v3.0.7 |
| Product workspace | Existing print-composition-v3 linked worktree |
| Frozen product SHA | `ea046836faf8b19eaea004b91a2176e9f1cfc711` |
| Source fingerprint | `1beebae1c24064b10dd6da9ef77018cd0ae3b98484e5d8c3f5e54b19a078cfd5` |
| Native run | [38492470140](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38492470140); headSha equals frozen source |
| Local staging | `build/probes/release-v3.0.7-38492470140/` in the product workspace |
| Candidate evidence | `windows/release-candidate/candidate-windows-x64.json`, `macos/release-candidate/candidate-macos-arm64.json` |
| Regression reports | `windows/build/ci-release/result.json`, `macos/build/macos-tests/result.json` |
| Signed index SHA256 | `60b3f860ac75ee84703f3c810770170c6a2b8b73911dab6f683d931185f327ba` |
| Attachments | 18 files declared in signed index plus index and signature = 20; all 20 remote names/sizes/SHA256 digests verified |
| Public Release | [v3.0.7](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.7); published at 2026-10-14T01:46:04Z |

## Acceptance

| Check | Status | Measured evidence |
|---|---|---|
| Windows complete isolated regression | Passed | 176 modules; 2,469 passed, 3 existing skips, 0 failures/errors |
| Windows native packaging | Passed | Installer, Managed portable, private and legacy-compatible update ZIPs in native candidate |
| Mac native release plan / packaging | Passed | 42 modules; 684 passed, 3 existing skips, 0 failures/errors; Managed DMG/update ZIP |
| Windows frozen login-ready / worker admission | Passed | Real frozen Launcher, accepted before login; three unauthenticated worker routes blocked |
| Mac frozen login / Managed shell | Passed | Login shell, handshake, duplicate/direct launch routing, unauthenticated admission blocked |
| Windows original v3.0.3 Launcher, two upgrades | Passed | 3.0.3 → 3.0.6 → 3.0.7; `D:/Python_Project/PDFdocuEdit_Pro/build/Q7/result.json` |
| QA Launcher / preferences preservation | Passed | Launcher SHA256 `172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522` unchanged; preferences sentinel preserved |
| Windows candidate real-account login | Pending | Operator confirmation required; synthetic smoke does not establish this |
| Mac candidate real-account login | Pending | Operator confirmation required |
| Mac candidate offline restart | Pending | Operator confirmation required |
| Mac candidate cross-version update | Pending | Signed candidate helper report and operator confirmation required |
| Signatures / provenance / account project | Passed | Existing sealed validator; both candidates share source/version/fingerprint/account target; unchanged update trust anchor |
| Remote attachment names / sizes / hashes | Passed | Publisher completed successfully; independent API comparison verified all 20; `remote-draft-validation.json` |
| Operator acceptance complete | Pending | `signed/operator-acceptance.json`: only Windows two upgrades true; other four false; frozen SHA matches |
| Public tag / downloads / three update routes | Passed | Frozen tag SHA correct; latest/non-prerelease; all 20 remote names/sizes/hashes match; three anonymously downloaded manifest/signature pairs pass existing production validator; all six binary download HEAD requests succeed |

## Timing

Times below are UTC, measured from GitHub run metadata; Windows/Mac ran in parallel.

| Stage | Start / end | Elapsed |
|---|---|---|
| Native dispatch | 2026-10-14 00:51:00 | |
| Windows native regression and build | 00:51:04 / 01:23:59 | 32m 55s |
| Mac native regression and build | 00:51:07 / 01:01:45 | 10m 38s |
| Download / signing | Completed; candidates and signed files retained | No separate stage timings inferred |
| Draft upload / remote verification | Completed; `remote-draft-validation.json` records verification UTC | Measured end recorded; separate upload start not inferred |
| Operator checks | Four current-candidate checks remain untested; owner requested publication after disclosure | Pending |
| Publication / public verification | 2026-10-14 01:46:04 / 01:46:53.804 UTC | ~50s from publication to verification; `post-publication-validation.json` |

## Preparation and limits

Preparation contracts were observed failing before changes: version remained 3.0.6 and the Mac native plan omitted error recovery / queued-open lifecycle modules. The existing gates were updated; no tests or assertions disabled. Scoped preparation verification: 21 contracts plus one in-app README construction test passed; full Ruff and diff whitespace checks passed. Independent review: no actionable findings after fixing the stale in-app README. Full candidate regressions above ran once per platform; no redundant local full regression was run.

Windows x64 account-enabled Managed builds; macOS 13+ Apple Silicon ad-hoc signed testing build, **not Apple notarized**. Intel/Mac OCR, physical printer/inserter proof and antivirus vendor clearance are not claimed. Customer-specific native deadlock was not reproduced; generic lifecycle faults were fixed and tested. No customer files or account credentials were included in release artifacts. Existing user test applications were not terminated; upgrade smoke owned only its empty QA child processes.

Any follow-up documentation commit records these results without relabeling the frozen artifacts as that newer commit.

## Publication evidence

- `owner-publication-instruction.json`: exact latest human instruction, context and four pending checks; not an operator-test result.
- `post-publication-validation.json`: release ID/tag/source/latest status, 20 assets, three manifests/signatures and six publicly accessible binary downloads.
- Existing unified publisher was rerun in draft mode for complete sealed/remote verification. The owner-directed final publication used GitHub release edit, keeping the standard automated operator gate and acceptance JSON unchanged. No program logic, update keys or public attachments were altered.
- Windows Managed updates can check the Windows legacy or account manifest. Mac account Managed updates use the Mac manifest; source/non-Managed installations still require the corresponding Managed installer. Unknown old launchers remain subject to the existing route checks.
