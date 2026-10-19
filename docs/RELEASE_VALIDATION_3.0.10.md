# Release Validation — 3.0.10

## Source and scope

Owner requested Windows upgrade updates only and direct public publication on
2026-10-19. Installer, Portable and macOS are explicitly out of scope. Public
publication is authorized; incomplete verification is not an accepted result.

| Item | Record |
|---|---|
| Version / tag | 3.0.10 / v3.0.10 |
| Repository / product workspace | andy846/PDFDocuEdit_Pro / `D:/Python_Project/PDFdocuEdit_Pro` |
| Current development branch | `codex/deep-search-restore-layout`, retained |
| Previous product HEAD | `bef974b4f555796ceb57d70cf7f7b8600176a554` |
| Frozen SHA / fingerprint | `796cd7dfbdac884f495a31c521c22e4f4f3cce50` / `90a9dccf8ed16777393209c759159584520636b512ec7cc032ae6fa2834a99c5` |
| Release ref | Existing `codex/windows-update-v3.0.8`; fast-forward only, no new branch or checkout |
| Native workflow / run headSha | [39279868398](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39279868398), same frozen SHA; Windows success, Mac intentionally skipped |
| Candidate / signed index / attachment hashes | Validated; signed `release-index.json` and all 10 public assets match |
| Local progress and evidence | `build/probes/release-v3.0.10/` |
| Release URL / publication | [v3.0.10](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.10); public, latest, non-prerelease; 2026-10-19T16:54:26Z |

The pre-existing remote release ref is reused to preserve the owner's single
local development line and avoid creating/switching branches. The unified native
workflow is dispatched with `release_scope=windows-update`. Existing public tags
and attachments are immutable. The local untracked operator profile is excluded
from staging, builds and publication; it is not read or changed.

## Acceptance

| Check | Status | Evidence |
|---|---|---|
| Metadata/source/release contracts | Passed | Local preflight 28 passed / 1 host symlink skip; Ruff/source checks passed; [source-quality run 39279867389](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39279867389) passed at frozen SHA |
| Windows complete isolated regression | Passed | 211 modules; 2988 passed, 3 skipped, 0 failures/errors; exact module set and evidence hash verified |
| Native Windows update-only packaging | Passed | Private and legacy ZIPs contain identical bytes; no installer/portable |
| Frozen login-ready / unauthenticated worker rejection | Passed | Real frozen launcher accepted before login in 13.64 s; composition, print and PDF operations workers rejected unauthenticated execution |
| Existing Launcher successive upgrades | Passed | Real frozen 3.0.3 → 3.0.9 → 3.0.10; original launcher and sentinel settings preserved; isolated local data and require-signin marker, no real credentials |
| Current candidate real-account login | Not Tested / Pending | Owner explicitly deferred until after publication; never marked passed |
| Candidate provenance / signed index / both signed update routes | Passed | Existing validators, original Ed25519 trust anchor, frozen SHA/fingerprint and identical ZIP hashes |
| Draft remote filenames / sizes / SHA256 | Passed | Existing publisher checked exact 10 assets, names/sizes/SHA256 before promotion |
| Operator acceptance matches frozen SHA | Upgrades passed; login exception recorded | Same SHA; windows_two_upgrades=true, windows_account_login=false; standard operator gate unchanged |
| Public tag / manifests / signatures / downloads | Passed | Tag resolves to frozen SHA; latest/public; both anonymous manifest signatures and ZIP download links verified; exact remote asset digests match |
| Installer / Portable / Mac | Out of scope | Explicit Windows update-only instruction |
| Physical printer / RIP / inserter / real customer jobs | Not tested | Software fixtures do not certify equipment |

Prior development regression reports are historical evidence, not substituted
for the frozen release candidate. Existing signing/publication validators are retained.

## Initial native attempt and test-timing diagnosis

Run [39274757369](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39274757369)
used `01d10da069a1e18ca935d0e85c2f540f98678849`. All 211 modules ran, with
one failure in the mixed-page inactive-navigation test; packaging did not start.
Its original result and logs are retained, not relabelled successful.

The isolated test and full document-window module passed locally, while a
repeated synthetic trace reproduced the immediate assertion failure. It recorded
`set_page(1)` queued in `_deferred_pdf_calls` while a native PDF reader held the
shared lock. Once the queued operation ran, both session and canvas correctly
reported page 1. Navigation intentionally avoids blocking the Qt thread.

The regression now waits for that actual completion with a bounded deadline,
retains every active/inactive page-size assertion, and adds deterministic active
and inactive tests holding the real lock from a worker thread. No product code,
navigation behavior or test expectation is weakened. The corrected test source
is committed and frozen again; a new complete native run is required. Local
trace evidence is under `build/probes/release-v3.0.10/`.

## Explicit owner acceptance arrangement

When asked about candidate-specific real-account login, the owner explicitly
instructed: “不用, 發佈更新包後我會自行更新, 到時再測試, 唔得會同你講”.
That login check remains Pending / Not Tested and must not be set true. After
native regression, package/signature/source validation, isolated successive
upgrades and exact remote draft verification, publication proceeds under this
recorded owner exception. The standard publisher's operator gate is unchanged;
the exception and actual publication operation are recorded separately.

## Timing and recovery

| Stage | Start / end / duration | Result / continuation |
|---|---|---|
| Source preparation | 15:02:58 → 15:04:41 UTC; initial freeze 1m42s | Test-only re-freeze at 15:41:43; product fingerprint unchanged |
| Windows native regression / packaging | Regression 15:42:30 → 16:11:40 (29m10s); native packaging 16:11:40 → 16:13:57 (2m17s) UTC | Successful run completed 16:14:36; first failed attempt preserved |
| Download / validation | Background resumed 16:45 UTC; candidate validated by 16:48 UTC | C temp lacked space; resumed same artifact with D-only task temp. GitHub incident had delayed reliable status: recovered timestamps showed actual execution earlier than queued API view |
| Signing | Completed about 16:48 UTC; seal command 8.2s | Existing owner key/trust anchor; no private material uploaded |
| Draft upload / remote verification | Started about 16:49 UTC; promoted 2026-10-19T16:54:26.613511+00:00 | Exact existing publisher checks; no overwrite |
| Operator acceptance | 2026-10-19T16:48:35.233816+00:00 → 2026-10-19T16:49:33.690522+00:00; 58.46s | Both upgrades passed; real login remains Pending by owner direction |
| Public release / post-publication verification | Published 2026-10-19T16:54:26Z; verified 2026-10-19T16:55:01.004026+00:00 | Both Windows signed routes passed; real-login exception remains explicit |

## Delivery

- Windows update: [v3.0.10 Release](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.10); existing Managed installations use Help → Check for Updates.
- Mac download: none for this version; the Windows-only latest limitation is
  documented in release notes. Installed Mac applications remain usable.
- Release gates passed except candidate real-account login, explicitly deferred by the owner. Physical equipment and real customer jobs remain Not Tested.

## Published Windows payload

Both update ZIPs: 360,083,068 bytes each; SHA256 `b000ee621514d9735a7fe97e9839adcdcce739ffb2308d6b9c84531797e01023`.
The signed index and both metadata/signature routes are attached to the Release.

Local audit records: `native-validation.json`, `upgrade-qa/result.json`,
`owner-publication-result.json`, `post-publication-validation.json`, signed index
and `progress.json` under the per-release probe directory. These local records,
keys, account settings and user profiles are not committed.
