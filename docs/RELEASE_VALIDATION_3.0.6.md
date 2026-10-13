# Release Validation — 3.0.6

Started 2026-10-13T00:13:36+00:00; published 2026-10-13T05:30:09Z.
已公開最新正式 Release；尚未執行的實機項目保持 Pending，不把發布指示或舊版本結果當作驗收通過。
主流程見 [GitHub 發布標準流程](UNIFIED_RELEASE.md)。

## 來源及產物

| 項目 | 記錄 |
|---|---|
| 版本 / Tag | 3.0.6 / v3.0.6 — Public / latest |
| Repository / Branch / 產品工作區 | andy846/PDFDocuEdit_Pro / codex/unified-release-v3.0.6 / macos-parity linked worktree |
| 凍結完整 SHA / 來源 fingerprint | a7bea706311b8542888c46f877ce65be63efb467 / f5a0a638af809846919e2af0a7f8e88e1df8422c60e9f311d9bb707c554ec01f |
| GitHub run ID / URL / run headSha | [38334792978](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38334792978) / frozen SHA matches |
| 候選 / 簽署目錄（不包含私鑰位置） | D:/Python_Project/PDFdocuEdit_Pro/build/probes/release-v3.0.6-38334792978/{candidates,signed} |
| Windows / Mac 平台、Python / 工具鏈 / 依賴設定 | windows-latest x64 / macos-14 arm64, Python 3.12, committed platform/auth requirement locks and native bundles |
| Candidate index / 原生回歸及 smoke 報告 | candidate-windows-x64.json / candidate-macos-arm64.json; downloaded native result.json and Mac smoke reports; provenance/hash checks Passed |
| Signed release index hash / 附件 hash 清單 | f24e2373341c6cd7927ff16877cb61093e1db138ad0c1623ff1d8efb807f045b; index has 18 attachments plus signed index pair (20 total) |
| Release URL / 公開時間 | [v3.0.6](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.6); 2026-10-13T05:30:09Z |

## 驗收

| 項目 | 狀態（Pending / Passed / Failed） | 證據、SHA及版本 |
|---|---|---|
| Windows 完整回歸 / 原生打包 | Passed | 170 modules; 2,378 pass / 3 platform skips, 0 failures; frozen SHA / run 38334792978 |
| Mac 原生發布計劃 / 原生打包 | Passed | 40 modules; 642 pass / 3 platform skips, 0 failures; frozen SHA / same run |
| Windows frozen 登入及未登入 worker 拒絕 | Passed | Real frozen launcher/login-ready acknowledgement and all 3 unauthenticated worker entries blocked; not real-account acceptance |
| Mac frozen 登入 / Managed shell | Passed | Login shell + Managed handshake/duplicate/direct-version routing + worker blocking; real_account_tested=false |
| Windows v3.0.3 原 Launcher 連續兩次升級 | Passed | build/Q6/result.json: actual 3.0.3 → 3.0.5 → 3.0.6; launcher SHA172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522 and preferences unchanged |
| Windows 候選真實帳戶登入 | Pending | |
| Mac 候選真實帳戶登入 | Pending | |
| Mac 候選離線重開 | Pending | |
| Mac 候選跨版本更新 | Pending | |
| 偏好 / 專案位置 / 原文件保留 | Passed (isolated upgrade) | Actual two-upgrade sentinel/settings check passed; not a real-account operator acceptance |
| 本輪改動的針對性实測 | Passed (automated); operator Pending | Final native suites and targeted regressions passed; customer production/printer acceptance not claimed |
| 簽章 / 來源 / 平台 / 帳戶項目 | Passed | Existing trust anchor; both source fingerprints/project identities and all three production Manifest/archive validators Passed |
| 草稿附件遠端 hash / 大小 / 名稱 | Passed | Draft 411295768: all 20 names/sizes/GitHub SHA256 digests match signed index; draft-validation.json |
| operator-acceptance 與候選 SHA 一致 | Passed (identity); operator Pending | SHA matches; only proven windows_two_upgrades=true. Four real candidate account/Mac checks remain false |
| 公開 tag / manifests / 簽章 / 附件及三個更新入口 | Passed | public-verification.json: exact tag SHA/latest release; 20 names/sizes/digests; unauthenticated metadata/signature downloads and all 3 signature validators passed; installer/DMG/3 update archives HTTP 206 |

## 耗時及續做

| 階段 | 開始 / 結束 | 耗時 | run / 產物 / 錯誤及續做 |
|---|---|---|---|
| 來源準備 | | | |
| Windows 回歸及打包 | 02:00:09Z / 02:24:02Z | 23m53s | Run 38334792978; regression 16m44s / packaging 5m27s |
| Mac 回歸及打包 | 02:00:13Z / 02:10:02Z | 9m49s | Same run/source; regression 5m39s / packaging 2m57s |
| 候選下載核對 | | | |
| 簽署 | | | |
| 草稿上傳及核對 | | | |
| 實機等待及驗收 | Pending | Not machine execution time | Four candidate checks remain pending; owner directed one-time publication |
| 公開及發布後核對 | Published 05:30:09Z | See evidence timestamps | Release 411295768; public-verification.json passed |

開始至公開 wall-clock：5h16m33s，包含診斷、等待及續做；不是原生打包耗時。最終雙平台 CI 02:00:05Z–02:24:03Z，23m58s。平行工作不把兩邊耗時相加當作發布總時間。
如重用證據，列出原 run/報告、吻合條件及驗證結果；不能只記「以前通過」。

## 交付及限制

- Windows：[x64 安裝程式](https://github.com/andy846/PDFDocuEdit_Pro/releases/download/v3.0.6/PDFDocuEdit-Pro-v3.0.6-Setup-Windows-x64.exe)；Managed 版本使用 Check for Updates。
- Mac：[Apple Silicon Managed DMG](https://github.com/andy846/PDFDocuEdit_Pro/releases/download/v3.0.6/PDFDocuEdit-Pro-v3.0.6-Managed-macOS-arm64-Private.dmg)；現有 Managed 登入版使用 Check for Updates。
- Mac Developer ID / 公證實際狀態：ad-hoc 簽署，未完成 Apple Developer ID／公證；Apple Silicon/macOS 13+ 測試版。
- 已知限制 / 未驗收能力：本版 Windows 真實帳戶登入、Mac 登入／離線重開／跨版本更新待補驗；不聲稱打印機／DFE 實機驗收。OCR 及 Intel 不在本輪 Mac 範圍。
- 使用者交付結果：[v3.0.6](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.6) 已公開且為 latest；20 個附件及三個更新入口核對完成。

## Historical preparation ledger (before final native acceptance)

- Product baseline: `e87e189fae55ba405e4642a9a5e28d0f331f719c`; all current P0 and unreleased UI/document changes included.
- Release branch: `codex/unified-release-v3.0.6`, linked macos-parity worktree. Default branch unchanged.
- Public baseline: v3.0.5 retained. A higher patch is used; no published attachment is replaced.
- Task 1: source/version/notes and native gate preparation — In progress.
- Task 2: native Windows/Mac candidates — Pending.
- Task 3: candidate collection/signing and Draft verification — Pending.
- Task 4: candidate operator acceptance — Pending; earlier version checks cannot fill these fields.
- Task 5: public release/post-public verification — Pending.
- Mac native plan retains existing gates and adds P0 authorization/output/recovery, Branch UI, live document windows and Overlay UI tests.

## Independent release review and fixes (pre-freeze record)

Fresh reviewer inspected 4900521..4f959f7; no Critical or Minor findings, four Important issues accepted and fixed: PDF execution DB binding, batch destination/report containment, final split claim ordering, and recovered package-to-branch provenance. A changed report-directory reference is also rejected. Tests first reproduced all four issues; 17-module follow-up passed 227 cases with one Windows file-symlink permission skip. Native Mac plan now has 40 modules and includes that test. Complete candidate-native and operator gates remain Pending.

No second review or duplicate local full regression was dispatched; the next full suite is the mandatory frozen-source Windows CI gate. The signing key was checked against the existing trust anchor without exposing or uploading it. Previous v3.0.5 signed artifacts and the original v3.0.3 portable are available for the two-upgrade test: 3.0.3 → 3.0.5 → this 3.0.6 candidate, avoiding an extra QA build.


## Native attempt 1 — superseded candidate

- Source: d52bac2f7afe992bf1285fc929a45fff00e0379c; run [38329524321](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38329524321).
- Windows: 170 modules attempted; only tests/test_document_windows.py exceeded its unchanged 600-second limit. Other 169 modules reported 2,361 tests, three skips, zero failures/errors. No Windows candidate was built and nothing was signed or published.
- Mac: 40 modules, 639 passes/three skips; native account packaging/Managed shell/unauthenticated worker refusal passed. Source fingerprint 4c045a51ae857cab93755286e45b00b732c0ef833179e8016357c30e4ad8476b. Downloaded/verified artifact retained for diagnosis, superseded when source changes.
- Local targeted replay reproduced cumulative global QSS repolish slowness and a native access violation. Guarding identical QSS was not sufficient for actual theme changes while old fixture widget trees remained. Added explicit test fixture disposal and safe post-close deletion for secondary PDF windows. Existing assertions still cover cancellation, session ownership, saves and Undo; no test is skipped or disabled and the timeout is not increased.
- New unchanged-theme and widget-release regressions observed RED before respective source changes. All 20 document-window cases then passed in 39.51 seconds, including real theme synchronization. Ruff passed. Four additional related UI/entrypoint/handoff modules passed: 74 tests. A bounded 27-module cross-platform check also passed 318 cases; it is not a native candidate substitute.
- All native/operator/signature/publication gates for the final replacement SHA remain Pending. Old native success and prior operator exceptions cannot be relabelled to the new source.


## Final candidate native stages

- Windows: 2026-10-13T02:00:09Z–02:24:02Z; regression 02:01:18Z–02:18:02Z, native packaging 02:18:02Z–02:23:29Z.
- Mac: 2026-10-13T02:00:13Z–02:10:02Z; regression 02:01:04Z–02:06:43Z, native packaging 02:06:43Z–02:09:40Z.
- Source quality CI and native gates are same frozen source; no repeated local complete suite. Artifact collection/signing completed after continuation; preserve actual CI end times separately from waiting/continuation time.
- GitHub Draft 411295768 created with exact frozen SHA; all 20 attachments transferred and remote digests verified. At Draft completion, publication awaited four candidate operator checks; see the later owner decision below.


## Draft completion record / remaining operator checks

- [候選實機操作說明](RELEASE_TESTING_3.0.6.zh-HK.md); only remaining required checks: Windows candidate real-account login, Mac candidate real-account login, offline restart and cross-version update.
- Native build success and past-version confirmations do not fill these four booleans. At this historical Draft stage, v3.0.6 was not yet public; the later one-time owner decision is recorded below. v3.0.5 remains unchanged.
- Windows isolated candidate launcher: D:/Python_Project/PDFdocuEdit_Pro/build/Q6/PDFDocuEditPro/Launcher.exe. Original settings preserved in the actual two-upgrade gate.
- Draft API visibility was briefly delayed immediately after creation; read-only follow-up found the exact Draft/SHA and existing publish safely resumed. No duplicate draft or overwrite was performed.
- Native Mac remains Apple Silicon/macOS 13+ preview, ad-hoc signed, not Apple notarized. No real-printer/DFE performance claim.


## One-time owner decision and public verification

- After disclosure of the four pending candidate operator checks, the owner explicitly instructed **「公開吧」**. This authorized publication of this exact verified Draft, not a claim that those tests passed.
- At 2026-10-13T05:30:09Z, Release **411295768** / **v3.0.6** was made public and latest, bound to frozen source **a7bea706311b8542888c46f877ce65be63efb467**.
- One-time audit: `build/probes/release-v3.0.6-38334792978/owner-release-decision.json`. Public notes disclose the four Pending checks. Shared release tools, normal gates and operator-acceptance booleans remain unchanged. No permanent publication exception was added.
- Public verification: same folder `public-verification.json` has `passed=true`. Tag SHA and latest identity match; all 20 remote asset names/sizes/SHA256 match the signed index. Eight metadata/signature files downloaded without authentication match signed originals; all three update-route signature validators pass. Installer, DMG and three update archives return HTTP 206 for public Range download.
- Windows actual v3.0.3 → v3.0.5 → v3.0.6 upgrade evidence remains Passed. Windows real-account login and Mac real-account login/offline restart/cross-version update remain Pending. Earlier user reports for other versions are not reused.
- Post-publication repository documentation is updated separately with `[skip ci]`; release binaries/tag/source stay frozen. No default-branch merge, public attachment overwrite, key rotation or save-format change.
