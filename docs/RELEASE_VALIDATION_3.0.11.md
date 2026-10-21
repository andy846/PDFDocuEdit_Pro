# Release Validation — 3.0.11

## Source and scope

Owner authorized direct public Windows update-only publication on 2026-10-21
(Hong Kong). Workspace `D:/Python_Project/PDFdocuEdit_Pro`, local branch `main`.
Installer, Portable and macOS are explicitly out of scope.

| Item | Record |
|---|---|
| Version / tag | 3.0.11 / v3.0.11 |
| Frozen source | `a6d0b30c575ba0b6d1b9aa8e962d652f8fa9a783` |
| Source fingerprint | `a033c00a46528b8586e19cd4d1239a96dab77c9b1e17b4d77b2a41d08ab9e09c` |
| Product base | `f1ddd9e1717ee6be2a1f9c83d82c9c9c79e59ed6` |
| Publication ref | Existing `codex/windows-update-v3.0.8`, fast-forward only |
| Native run | [39464763633](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39464763633), exact frozen SHA |
| Source quality | [Passed run 39464763581](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39464763581) |
| Public release | [v3.0.11](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.11), latest, non-prerelease |
| Published UTC | 2026-10-20T17:56:51Z |

No new local branch or worktree was created; no branch switch or merge.
Remote main was not pushed. The existing publication ref preserves one local
main development line and avoids duplicate native regression. The untracked
operator profile was not read, staged or uploaded.

## Acceptance at publication

This table preserves the publication-time evidence. Subsequent owner acceptance
is recorded separately below.

| Check | Actual result |
|---|---|
| Source/release contracts | Refreeze: 27 passed / 2 host symlink/junction permission skips; repository Ruff and diff checks passed |
| Windows complete isolated regression | 216 exact tracked test modules; 3109 passed / 3 skipped; 0 failures/errors; evidence SHA verified |
| Windows native update-only package | Passed; private/legacy ZIPs have identical bytes; no installer/portable |
| Frozen login-ready / unauthenticated worker rejection | Passed; composition, print and PDF-operations admission checked |
| Original frozen Launcher upgrades | Passed: 3.0.3 → 3.0.10 → 3.0.11; original Launcher and settings preserved |
| Credential isolation | Passed; private local data, require-signin marker and blocked network; no real credentials |
| Real-account login | Pending / Not Tested; owner-directed post-publication test |
| Candidate provenance, index and update signatures | Passed using existing trust anchor and validators |
| Draft names/sizes/SHA256 | Passed; exact 10 assets checked by existing publisher |
| Public tag/latest and anonymous update routes | Passed; tag equals frozen SHA; both signatures and ZIP links verified |
| Installer / Portable / macOS | Out of scope |
| Physical printer / RIP / inserter / actual customer jobs | Not Tested |

The owner previously directed: “不用, 發佈更新包後我會自行更新, 到時再測試,
唔得會同你講”, and requested direct publication again for this release.
The source-specific exception is recorded separately. `windows_account_login=false`
remains unchanged; frozen login-ready is not real-account acceptance. The standard
operator gate was not changed. All other native, signing, upgrade, upload and
post-publication gates were completed. Development tests were not substituted
for the full frozen native candidate regression.

## Post-publication owner acceptance — 2026-10-22 (Hong Kong)

The owner explicitly confirmed that all three items below passed on the
**published v3.0.11**, replying “全部通過” to the question naming these items.
This is owner-reported real-world acceptance, not an additional automated test
run or agent-operated machine test.

| Check | Updated acceptance |
|---|---|
| Real-account login | Passed — owner-confirmed on 2026-10-22 |
| Physical printer / RIP / inserter | Passed — owner-confirmed on 2026-10-22 |
| Actual customer PDF workflows | Passed — owner-confirmed on 2026-10-22 |

The publication-time `windows_account_login=false` record and source-specific
exception remain historical evidence; they have not been rewritten to imply
pre-publication acceptance. Equipment models and individual job details were
not supplied and are not inferred.

This confirmation does not establish a unique cause for every intermittent
blank-tab incident. The later local Watermark close/reopen repair (`b8301da`)
and history temporary-file cleanup (`afaaeb6`) are not part of published
v3.0.11, and are not covered by this owner acceptance. Their separate reports
are [Watermark close/reopen](WATERMARK_CLOSE_REOPEN.md) and
[temporary PDF lifecycle](TEMP_PDF_LIFECYCLE.md).

## Stage timings (UTC)

| Stage | Start | End | Duration |
|---|---|---|---|
| Initial source preparation | 2026-10-20T16:44:33.185948+00:00 | 2026-10-20T16:45:50.462017+00:00 | 77.28 s |
| Initial regression — version failure | 2026-10-20T16:47:20Z | 2026-10-20T17:12:47Z | 1527.00 s |
| Full isolated regression | 2026-10-20T17:18:57Z | 2026-10-20T17:48:50Z | 1793.00 s |
| Native account release candidates | 2026-10-20T17:48:50Z | 2026-10-20T17:51:08Z | 138.00 s |
| download | 2026-10-20T17:51:45.164329+00:00 | 2026-10-20T17:53:12.858961+00:00 | 87.69 s |
| candidate-validation | 2026-10-20T17:53:12.860962+00:00 | 2026-10-20T17:53:14.096235+00:00 | 1.24 s |
| seal | 2026-10-20T17:53:14.098233+00:00 | 2026-10-20T17:53:19.150834+00:00 | 5.05 s |
| isolated-upgrades | 2026-10-20T17:53:19.151820+00:00 | 2026-10-20T17:53:55.960011+00:00 | 36.81 s |
| publication | 2026-10-20T17:55:04.210226+00:00 | 2026-10-20T17:56:52.418482+00:00 | 108.21 s |
| public-verification | 2026-10-20T17:56:52.420484+00:00 | 2026-10-20T17:57:04.381278+00:00 | 11.96 s |

## Initial candidate failure and correction

Initial candidate `477c959efb21c067caf97e3e2282f6720af221a2`,
run [39460312241](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39460312241),
ran all 216 modules: 3,108 passed, 3 skipped and one outdated-version contract
failure. Packaging did not start. The version contract, in-app release overview
and Windows file/installer version metadata were synchronized to 3.0.11; every
metadata assertion was preserved. No editing or production behavior changed.
The corrected source ran a complete new native regression. Initial failed logs
and artifacts are retained under the per-release probe directory, not relabelled.
Local refreeze preflight attempts first encountered restricted sandbox temporary
directory permissions; using a task-specific D-drive TEMP/TMP and fresh pytest
base directory yielded the recorded 27 passed / 2 host permission skips.

Total wall-clock from source preparation to anonymous verification:
4351.20 seconds.
Windows native validation ran once per frozen source. A local waiting-process bookkeeping repair
occurred before artifact download; it did not restart native tests or change
candidate evidence. Task temporary downloads used the D drive.

The first draft creation succeeded but its immediate authenticated list lookup
returned no matching draft, so publication stopped before uploading. A subsequent
read confirmed draft ID `418698473` and the exact frozen SHA; only publication
was resumed. Existing assets were verified, never overwritten; native tests,
signing and upgrade acceptance were retained. The initial publication log remains
available separately from the resumed log.

## Published payload and delivery

Both Windows ZIPs: 360,192,402 bytes each;
SHA256 `42fa4a00e85915dd239b79f81b4279c596a3e8d0463f360197a4197cf3d85681`.
Existing Managed installations use **Help → Check for Updates**.
No macOS download for this version; older Mac updaters may report missing Mac
assets on this Windows-only latest release. Installed Mac applications remain usable.

Local audit records under `build/probes/release-v3.0.11/`: `progress.json`,
`native-validation.json`, `upgrade-qa/result.json`, `owner-publication-result.json`,
`post-publication-validation.json`, signed index and per-stage logs. These local
records, keys, settings and user profiles are not committed.

Public version notes: [v3.0.11](RELEASE_NOTES_3.0.11.md).
