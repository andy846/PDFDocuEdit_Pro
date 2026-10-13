# Release Validation — 3.0.6

Started 2026-10-13T00:13:36+00:00; release preparation in progress.
此模板不是驗收證據；未執行項目保持 Pending，不把舊結果自動填成 Passed。
主流程見 [GitHub 發布標準流程](UNIFIED_RELEASE.md)。

## 來源及產物

| 項目 | 記錄 |
|---|---|
| 版本 / Tag | Pending |
| Repository / Branch / 產品工作區 | Pending |
| 凍結完整 SHA / 來源 fingerprint | Pending |
| GitHub run ID / URL / run headSha | Pending |
| 候選 / 簽署目錄（不包含私鑰位置） | Pending |
| Windows / Mac 平台、Python / 工具鏈 / 依賴設定 | Pending |
| Candidate index / 原生回歸及 smoke 報告 | Pending |
| Signed release index hash / 附件 hash 清單 | Pending |
| Release URL / 公開時間 | Pending |

## 驗收

| 項目 | 狀態（Pending / Passed / Failed） | 證據、SHA及版本 |
|---|---|---|
| Windows 完整回歸 / 原生打包 | Pending | |
| Mac 原生發布計劃 / 原生打包 | Pending | |
| Windows frozen 登入及未登入 worker 拒絕 | Pending | |
| Mac frozen 登入 / Managed shell | Pending | |
| Windows v3.0.3 原 Launcher 連續兩次升級 | Pending | |
| Windows 候選真實帳戶登入 | Pending | |
| Mac 候選真實帳戶登入 | Pending | |
| Mac 候選離線重開 | Pending | |
| Mac 候選跨版本更新 | Pending | |
| 偏好 / 專案位置 / 原文件保留 | Pending | |
| 本輪改動的針對性實測 | Pending | |
| 簽章 / 來源 / 平台 / 帳戶項目 | Pending | |
| 草稿附件遠端 hash / 大小 / 名稱 | Pending | |
| operator-acceptance 與候選 SHA 一致 | Pending | |
| 公開 tag / manifests / 簽章 / 附件及三個更新入口 | Pending | |

## 耗時及續做

| 階段 | 開始 / 結束 | 耗時 | run / 產物 / 錯誤及續做 |
|---|---|---|---|
| 來源準備 | | | |
| Windows 回歸及打包 | | | |
| Mac 回歸及打包 | | | |
| 候選下載核對 | | | |
| 簽署 | | | |
| 草稿上傳及核對 | | | |
| 實機等待及驗收 | | | |
| 公開及發布後核對 | | | |

總 wall-clock：Pending。平行工作不把兩邊耗時相加當作發布總時間。
如重用證據，列出原 run/報告、吻合條件及驗證結果；不能只記「以前通過」。

## 交付及限制

- Windows 下載 / 更新方式：Pending
- Mac 下載 / 更新方式：Pending
- Mac Developer ID / 公證實際狀態：Pending
- 已知限制 / 未驗收能力：Pending
- 使用者交付結果：Pending

## Preparation ledger

- Product baseline: `e87e189fae55ba405e4642a9a5e28d0f331f719c`; all current P0 and unreleased UI/document changes included.
- Release branch: `codex/unified-release-v3.0.6`, linked macos-parity worktree. Default branch unchanged.
- Public baseline: v3.0.5 retained. A higher patch is used; no published attachment is replaced.
- Task 1: source/version/notes and native gate preparation — In progress.
- Task 2: native Windows/Mac candidates — Pending.
- Task 3: candidate collection/signing and Draft verification — Pending.
- Task 4: candidate operator acceptance — Pending; earlier version checks cannot fill these fields.
- Task 5: public release/post-public verification — Pending.
- Mac native plan retains existing gates and adds P0 authorization/output/recovery, Branch UI, live document windows and Overlay UI tests.

## Independent release review and fixes

Fresh reviewer inspected 4900521..4f959f7; no Critical or Minor findings, four Important issues accepted and fixed: PDF execution DB binding, batch destination/report containment, final split claim ordering, and recovered package-to-branch provenance. A changed report-directory reference is also rejected. Tests first reproduced all four issues; 17-module follow-up passed 227 cases with one Windows file-symlink permission skip. Native Mac plan now has 40 modules and includes that test. Complete candidate-native and operator gates remain Pending.

No second review or duplicate local full regression was dispatched; the next full suite is the mandatory frozen-source Windows CI gate. The signing key was checked against the existing trust anchor without exposing or uploading it. Previous v3.0.5 signed artifacts and the original v3.0.3 portable are available for the two-upgrade test: 3.0.3 → 3.0.5 → this 3.0.6 candidate, avoiding an extra QA build.


## Native attempt 1 — superseded candidate

- Source: d52bac2f7afe992bf1285fc929a45fff00e0379c; run [38329524321](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38329524321).
- Windows: 170 modules attempted; only tests/test_document_windows.py exceeded its unchanged 600-second limit. Other 169 modules reported 2,361 tests, three skips, zero failures/errors. No Windows candidate was built and nothing was signed or published.
- Mac: 40 modules, 639 passes/three skips; native account packaging/Managed shell/unauthenticated worker refusal passed. Source fingerprint 4c045a51ae857cab93755286e45b00b732c0ef833179e8016357c30e4ad8476b. Downloaded/verified artifact retained for diagnosis, superseded when source changes.
- Local targeted replay reproduced cumulative global QSS repolish slowness and a native access violation. Guarding identical QSS was not sufficient for actual theme changes while old fixture widget trees remained. Added explicit test fixture disposal and safe post-close deletion for secondary PDF windows. Existing assertions still cover cancellation, session ownership, saves and Undo; no test is skipped or disabled and the timeout is not increased.
- New unchanged-theme and widget-release regressions observed RED before respective source changes. All 20 document-window cases then passed in 39.51 seconds, including real theme synchronization. Ruff passed. Four additional related UI/entrypoint/handoff modules passed: 74 tests. A bounded 27-module cross-platform check also passed 318 cases; it is not a native candidate substitute.
- All native/operator/signature/publication gates for the final replacement SHA remain Pending. Old native success and prior operator exceptions cannot be relabelled to the new source.
