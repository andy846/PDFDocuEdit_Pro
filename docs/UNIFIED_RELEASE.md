# PDFDocuEdit Pro — GitHub 發布標準流程

此文件是每次 GitHub Release 的操作依據，適用於後續所有版本。
它不是任何版本已發布或驗收完成的證據。收到「Release 最新版本到 GitHub」時，
先閱讀本文件及目前發布工具；按照以下階段執行並保留進度。

## 1. 固定原則及交付

- Windows x64 和 macOS Apple Silicon 使用同一版本、同一已提交來源及同一個 Release。
- 使用現有候選打包、驗證、簽署、發布及更新引擎，不另建發布途徑。
- 正式候選需要 Windows 完整隔離回歸和 Mac 原生發布測試計劃。
  同一候選完成後，不在本機重跑同一套完整測試。
- 只有來源、版本、依賴、工具鏈、打包設定、平台及驗收證據一致才可重用。
  現有流程未提供跨次執行的自動測試快取，不手工修改證據來略過測試。
- 公開附件不可覆蓋；修正使用較高版本。草稿允許核對後補傳缺少附件。
- 使用者明確要求 Release，即授權完成公開；不要再次要求相同發布許可。
  缺少實機結果、簽署憑證、平台產物或遇到工具阻擋時，保留草稿並明確報告。
- 每階段保存版本、完整 SHA、工作流程 run ID、開始/結束時間、產物位置和結果。
  最終交付版本、Release URL、兩平台下載入口、驗收摘要及限制。

## 2. 來源、版本及發布準備

1. 確認實際產品工作區、Git 分支、工作樹狀態及 remote。不要從較舊的另一個 checkout 打包。
2. 查核 GitHub 已公開版本、同版本草稿及 tag。新版本預設提升 patch；已確認的重大版本安排優先。
3. 核對 `core/resources.py`、`scripts/build.py`、`pyproject.toml` 及來源契約測試要求的版本。
   更新 README、程式內 README 及 `docs/RELEASE_NOTES_<VERSION>.md`。
   Splash 版本取自程式 metadata，不因提升版本修改圖片。
4. 更新的發布流程本身需一併提交。凍結所有產品修改，記錄 40 字元完整 SHA，再推送發布分支。
5. 建立本版本獨立的驗收記錄，沿用
   [驗收記錄模板](RELEASE_VALIDATION_TEMPLATE.md)，保存為 `docs/RELEASE_VALIDATION_<VERSION>.md`。

可使用以下只讀指令查核；先確認 `gh` 登入正確帳戶和 repository 權限：

```text
git status --short
git rev-parse HEAD
git remote -v
gh release list --repo andy846/PDFDocuEdit_Pro
```

**完成條件：**來源已提交、版本一致，待发布產品變更均包含在凍結 SHA。
凍結後如修改產品或打包輸入，更新 SHA 並使原候選失效。
簽署工具可以在受控電腦獨立修正，但不能把舊產物改標成新工具 SHA。

### 凍結版本與後續驗收紀錄

Tag 內的驗收文件代表來源凍結時的狀態，可能仍有 `Pending`；它不是最終交付證明。
完成發布後，在目前日常開發線的 `docs/RELEASE_VALIDATION_<VERSION>.md`
補齊同一候選的 CI、簽署、公開附件核對及後續使用者驗收，另行提交文件。
紀錄須能追溯凍結 SHA、候選 run、產物 hash 及驗收時間；
區分原發布門檻與發布後補錄，不把原有未通過欄位改成虛構的當時通過。
例如 [v3.0.11 驗收紀錄](RELEASE_VALIDATION_3.0.11.md) 包含發布後補錄。

不移動既有 tag、不覆蓋公開附件或簽署資料。讀取某版的最終狀態時，
應同時查核 main 上該版驗收文件及其提交歷史，而非只看 tag 內的模板。
若文件仍僅在本機 main，明確標示尚未同步 GitHub。

主線同步另需擁有人批准。先讀取遠端 main 的實際 SHA，核對它仍為本機 main
祖先及完整差異，批准後才以普通 fast-forward 推送；遠端已分叉時停止重新核對，
不得強推、自動合併或改動既有發布歷史。只補文件不觸發打包、提升版本或發布。

## 3. 雙平台驗收及原生打包

以下指令的 `<...>` 是必須替換的佔位值，不是可直接執行的參數。
使用現有 `.github/workflows/unified-release.yml`，確認發布分支已含最新工作流程：

```text
gh workflow run unified-release.yml --ref <發布分支> --repo andy846/PDFDocuEdit_Pro
gh run list --workflow unified-release.yml --branch <發布分支> --repo andy846/PDFDocuEdit_Pro
gh run watch <RUN_ID> --exit-status --repo andy846/PDFDocuEdit_Pro
```

派送前記錄該分支 SHA；取得 run ID 後確認 run 的 `headSha` 等於凍結 SHA。
同一版本已有正確且成功的候選 run，直接使用它，不重複派送。
沒有正確候選時才建立新 run。工作流程同時執行 Windows／Mac：

| 平台 | 自動驗收 | 候選產物 |
|---|---|---|
| Windows x64 | 完整隔離回歸、原生打包、frozen 登入/Managed 啟動、未登入 worker 拒絕 | Installer、Managed Portable、私人版更新及舊格式相容更新 |
| macOS arm64 | 原生來源品質/發布測試計劃、bundle/Managed shell smoke | Managed DMG、私人版更新 |

Windows 使用 `scripts.regression_suite --group all`；Mac 使用 `scripts.macos_test_plan`。
兩平台使用 `scripts.build_release_candidate`，候選文件記錄來源 fingerprint、
帳戶項目、測試證據及附件 hash。CI 不接收正式更新私鑰或真實帳戶憑證。
不要為了發布關閉測試、隱藏失敗或只保留部分回歸。

**時間管理：**兩平台目前已平行執行，Mac 有原生元件快取。
Windows 依賴快取及跨次測試結果自動重用尚未完成；不能把規劃當作現有功能。
本機針對性開發測試不替代此階段完整發布驗收，也毋須再額外做一遍本機完整回歸。

**完成條件：**兩平台 job 成功，回歸、登入入口及原生打包證據齊全。
Artifact upload 的 `always()` 可上傳失敗 job 的部分檔案；有 artifact 不等於通過。

## 4. 收集及驗證候選

```text
gh run download <RUN_ID> --name windows-x64-account-candidate --dir <WINDOWS下載目錄> --repo andy846/PDFDocuEdit_Pro
gh run download <RUN_ID> --name macos-arm64-account-candidate --dir <MAC下載目錄> --repo andy846/PDFDocuEdit_Pro
```

正常情況使用同一次 run，把兩邊 `release-candidate` 內容放入新的本版本候選目錄。
測試證據另外保留。必要附件包括：

- Windows Installer、Managed Portable、私人版 update ZIP、legacy 相容 update ZIP。
- Mac Managed DMG、私人版 update ZIP。
- 所有 `candidate-*.json`、對應 SHA256 附件及兩平台 candidate index。
- Windows `build/ci-release/result.json`、Mac `build/macos-tests/result.json`
  及 Mac release smoke 報告；保留原 run 作完整 log 來源。

同名附件若內容不同就停止，不默默覆蓋；不得混入客戶資料、私鑰、本機設定或任意檔案。
簽署器會驗證兩平台 index 的 version、SHA、fingerprint、帳戶項目、
附件大小/hash、包內 update 身分及來源 metadata。

**完成條件：**同一來源的兩平台候選齊全，現有候選驗證器可接受。

## 5. 受控簽署

在持有現有 Ed25519 私鑰的受控電腦執行，使用未存在的簽署輸出目錄：

```text
python -m scripts.unified_release seal --candidates <候選目錄> --output <全新簽署目錄> --version <VERSION> --commit <完整SHA> --key <私鑰路徑>
```

- 私鑰必須對應現有 `updates/trust.py` 公鑰；不能重新 keygen 或輪換公鑰來完成發布。
- 加密私鑰密碼由隱藏 prompt 輸入，不寫進指令、環境變數、文件或日誌。
- 私鑰保持在受控、非發布目錄；不傳至 CI、Build Kit 或 GitHub。
- `seal` 產生私人平台 manifests、legacy 相容 manifest、簽章及簽署 release index。
  `candidate-*.json` 是未簽候選，不能當成公開更新入口。
- 簽署失敗保留診斷檔，使用新的輸出目錄重試；沒有有效 index 的產物不可發布。

### 更新相容入口：每一個後續版本都要保留

| 使用者 | 必須提供的入口 |
|---|---|
| 原有 Windows v3.0.3 Managed Launcher | `update.json` / `update.sig` 及原有命名的 update ZIP |
| Windows 帳戶版 Managed Launcher | `update-windows-x64-private.json` / `.sig` 及私人版 update ZIP |
| Mac 帳戶版 Managed Launcher | `update-macos-arm64-private.json` / `.sig` 及 Mac update ZIP |

Legacy 和 private Windows ZIP 必須為相同程式內容。
舊 Launcher 不升級為新 schema；程式額外驗證已簽 `application_target`。
未知 Launcher、其他平台/帳戶項目及免登入包不可代用。

**完成條件：**簽章、附件及來源验证成功，完整簽署清單已產生。

## 6. 建立／接續 GitHub Draft

```text
python -m scripts.unified_release publish --folder <簽署目錄> --notes <RELEASE_NOTES檔案>
```

此步不公開。工具建立或接續相同 tag/SHA 草稿，只上傳清單中的附件，
並以 GitHub 回傳的 SHA256 digest 和大小核對。
已存在且一致的附件略過；缺少附件補傳。
不同附件、額外附件或不同來源的草稿會阻止執行；不使用 `--clobber`。
公開 Release 不可在此流程修改。

Release Notes 清楚分列 Windows 及 Mac。Mac 未具正式 Developer ID／公證時，
維持實際測試版定位，不宣稱已公證。

**完成條件：**草稿全部附件齊全，遠端 hash/大小/名稱與簽署清單一致。

## 7. 候選版本實機驗收

目前 `publish --make-public` 要求簽署目錄中有 `operator-acceptance.json`。
以下是未驗收模板：

```json
{
  "source_commit": "<完整候選SHA>",
  "windows_two_upgrades": false,
  "windows_account_login": false,
  "mac_account_login": false,
  "mac_offline_restart": false,
  "mac_cross_version_update": false
}
```

只有取得對應實測結果才能改成 `true`；缺一項或 SHA 不同都保留草稿。
在版本驗收記錄中登記平台、實際版本轉換、測試者確認及報告位置。
過去已確認的 Mac 登入/更新只證明被測版本，不能代填新版本或未測的離線項目。
只有工具明確支持、有足夠證據的重用才可沿用；目前工具仍要求本候選 SHA 的驗收。

### Windows

- 原有 frozen v3.0.3 Launcher，連續使用兩個不同較新 frozen editor 版本升級；
  確認 Launcher 不變、設定保留、啟動確認完成。
- 使用隔離測試安裝，不關閉或終止操作者現有程式。
- 候選帳戶登入成功，更新/首次安裝及本轮修改可用。
- 可使用現有 helper；第二個測試版本是 QA 專用，不能上傳正式 Release：

```text
python -m scripts.legacy_upgrade_smoke --baseline <原有V303_MANAGED_PORTABLE.zip> --updates <簽署候選目錄> <簽署QA後續版本目錄> --output <新的短路徑驗收目錄>
```

Windows 使用短 QA 路徑，避免原有 Launcher 的 MAX_PATH 限制。
不更改全域 OS 設定。另需真實帳戶登入結果，synthetic launcher smoke 不代替登入實測。

### Mac

草稿不會出現在正常 latest 更新檢查；先保存工作並退出，在 Apple Silicon Mac
以現有候選 helper 安裝相同簽署版本，再完成登入、離線重開及跨版本更新：

```text
python3 -m scripts.macos_candidate_upgrade --app "/Applications/PDFDocuEdit Pro.app" --folder <簽署Mac更新目錄> --report <mac-update-result.json>
```

目錄必須有同版本 Mac ZIP 和正式 `.json` / `.sig`，不能用 `candidate-*.json`。
Helper 使用 Python 3.12 及現有 cryptography；保持 Terminal 開啟，正常退出測試程式後保存報告。
報告證明更新/啟動，不自動證明真實登入及離線使用。
首次 Managed DMG 安裝及系統安全提示另按
[Mac 驗收操作說明](MAC_UPDATE_ACCEPTANCE.zh-HK.md)；該文件 v3.0.4 範例需換成當前版本。
不要全域關閉 Gatekeeper。

### 共同核對

保留偏好/專案路徑及原文件；核對本轮改動。
更新/登入核心改動時，追加錯誤平台或項目、無效簽章/損壞下載、取消保存、
下載中斷、啟動失敗回退、撤銷權限及憑證權限提示相關驗收。
沒有測過的 printer 或其他功能，不在 Release Notes 聲稱已實機驗收。

## 8. 公開及發布後核對

```text
python -m scripts.unified_release publish --folder <簽署目錄> --notes <RELEASE_NOTES檔案> --make-public
```

工具再次核對附件和實機驗收，公開為 latest、非 prerelease，
使既有 Windows latest-release 更新器可找到它。Mac 附件/UI 保留自身 preview 標示。
不新增強制自動安裝。

公開後：

1. 查核 Release 已公開、tag 解參照後的 commit 等於凍結 SHA、版本及 Notes 正確。
2. 從公開下載入口重新取得三組 manifest 和簽章，以現有 Manifest validator
   核對簽章、版本、平台、帳戶項目及 legacy `application_target`。
3. 核對所有公開附件名稱、大小/hash；主要 Installer、DMG/update ZIP 下載連結可用。
4. 核對 Windows 舊入口、Windows 帳戶入口及 Mac 帳戶入口均可用。
5. 完成版本驗收記錄，保存工作流程 run ID、測試/打包報告、簽署 index、
   遠端附件結果及實機確認。記錄文件可用獨立文件提交補齊，不改動已凍結產物 SHA。
6. 回覆版本、Release URL、Windows/Mac 下載及更新方式、驗收摘要、限制。
   若公開後核對失敗，立即報告具體問題，不宣稱發布成功。

已公開附件不得覆蓋。修正使用較高 patch 和新來源；
如需撤回/改變 latest 或其他破壞性處理，先提出具體處置及取得相應授權。

## 9. 失敗續做及時間管理

| 失敗位置 | 續做方式 |
|---|---|
| 測試失敗 | 修正產品後重新凍結 SHA，原產物失效；新候選重新完成發布 gates |
| 單平台打包失敗 | 同 SHA 重跑失敗 job；保留另一平台成功產物，驗證器核對相容後再合併 |
| 下載中斷 | 重下缺少/損壞 artifact，不重打包 |
| 簽署失敗 | 同候選、全新簽署輸出目錄重試，不重跑未變更產物測試 |
| 草稿上傳中斷 | 同簽署目錄重跑 publish，略過 hash 一致附件，只補傳缺件 |
| 實機結果未齊 | 保留草稿/產物，列出缺少項目，不能自動填 true |
| 公開後問題 | 保留已發布檔案，使用新版本修正 |

相同 run 的失敗 jobs 可用 `gh run rerun <RUN_ID> --failed --repo andy846/PDFDocuEdit_Pro`。
先檢查新舊 artifact，選成功平台的正確完整集合；若同名/內容無法確定，停止合併。
不得單以檔名或測試次數作重用依據。
目前候選工具部分 smoke 目錄要求全新；本機續跑須保存原證據並在乾淨 staging 執行，
不盲目清空整個 build/dist 或使用者資料。

記錄階段耗時：來源準備、Windows 驗收/打包、Mac 驗收/打包、下載、
簽署、上傳核對、實機等待、發布後核對。平行階段分別記錄，總耗時按實際 wall-clock。
分清機器運算與人工等待，優先改善真正最慢階段。

## 10. 維護與每次交付清單

发布工具或相容要求改變時同步更新此文件，保持說明與實際 CLI/gates 一致。
不因改文件而提升產品版本。文件更改只核對連結、指令與工具介面，不重跑產品完整回歸。

- [ ] 正確工作區、版本、凍結 SHA
- [ ] Windows／Mac 驗收及原生候選
- [ ] 三個更新入口及完整附件
- [ ] 受控簽署及完整 index
- [ ] 草稿遠端附件核對
- [ ] 本候選實機驗收及 operator-acceptance
- [ ] 公開及公開入口/簽章核對
- [ ] 完整版本記錄及使用者交付

## CI 重複工作控制

`codex/unified-release-v*` 分支由 `unified-release.yml` 執行 Windows 全部隔離回歸、Mac 原生計劃及兩邊打包。一般 `CI` 保留 Source quality，但不再重跑同分支的 focused tests；其他開發分支及 PR 的測試規則不變。這只消除重複執行，不略過正式原生 gate。


## 明確指定 Windows 更新專用發布

只有擁有人明確要求時使用；預設仍為雙平台完整發布。此模式不把缺少的 Mac／Installer／Portable 標成 Passed，不改更新信任或 Windows 測試門檻。

1. 使用 `codex/windows-update-v<VERSION>` 分支凍結來源；一般 CI 保留 Source quality，正式 Windows 全部隔離回歸交由 native workflow 執行一次。
2. 派送 `gh workflow run unified-release.yml --ref <分支> -f release_scope=windows-update --repo andy846/PDFDocuEdit_Pro`。Mac job 明確略過；Windows 仍跑完整回歸、PyInstaller、frozen login-ready 及未登入 worker 拒絕。
3. `scripts.build_release_candidate --updates-only` 不建立 Installer 或 Portable ZIP。僅在隔離 smoke 目錄建立測試用 Managed 樹；不是發布產物。
4. 收集 Windows candidate 後，沿用 `scripts.unified_release seal`，額外傳 `--scope windows-update`。簽署 index 綁定範圍及唯一 Windows 平台，候選只接受 private／legacy 更新 ZIP、各 SHA256 及兩份 candidate metadata。
5. Publish 沿用清單上傳／遠端 hash 核對。Windows update scope 的 operator gate 仍要求本 SHA 的 `windows_two_upgrades`、`windows_account_login`，不要求本輪未製作的 Mac。
6. 不上傳舊 Mac 包來冒充新版。舊 Mac updater 嚴格只讀 latest，故此 Windows-only latest 會提示缺少 Mac 附件；事先說明並在 Notes 記錄，已安裝 Mac 程式不受影響。後續雙平台版本提供新的 Mac 更新入口。
7. 其餘簽章、immutable attachments、測試證據、來源 SHA 及公開後核對保持本文件原有要求。未測項目不得代填 true；擁有人若另有明確發布例外，保留原始未完成記錄及具體指示。
