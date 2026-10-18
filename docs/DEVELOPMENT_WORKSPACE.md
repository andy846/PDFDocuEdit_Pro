# 固定開發工作區與 D 槽遷移

## 日常使用

**唯一日常開發／實測位置：`D:\Python_Project\PDFdocuEdit_Pro`。**

- 分支：`codex/deep-search-restore-layout`，繼續使用同一開發歷史。
- Python：`.venv-dev\Scripts\python.exe`（3.12.14）。
- Python 基底：D 槽既有 `.venv-tools\python\cpython-3.12-windows-x86_64-none`；需要保留。
- Codex 的 `PDFdocEdit Pro` 專案入口已核對為此 D 槽目錄。
- `dist`／`release` 保留原有歷史產物；本次最新版開發實測入口是下方的 `scripts\launch_dev.cmd`。
- C 槽 `print-composition-v3` worktree 暫時保留在 detached HEAD，僅作回退及保留歷史驗收證據。
  不再從該目錄日常開發／啟動，不將它當成最新版本來源。

### 啟動程式（Windows）

雙擊 `scripts\launch_dev.cmd`，或在 D 槽專案內執行：

```powershell
& .\scripts\launch_dev.cmd
```

也可傳入完整文件路徑（含空格需加引號）：

```powershell
& .\scripts\launch_dev.cmd "D:\Documents\Example Project.pdcx"
```

入口會使用本工作區 `.venv-dev` 的 Python、固定工作目錄及原有 `main.py`。
不依賴系統 PATH 或另一個 C 槽環境；背景 worker 繼承同一執行環境。
主程式視窗正常顯示，沒有額外 Python 控制台。每次啟動的 stdout/stderr
使用獨立檔名，放在 `build/dev-launch/logs/`，不覆蓋既有日誌。

只核對位置而不開啟程式：

```powershell
& .\scripts\launch_dev.cmd --check
```

若 `.venv-dev` 缺少，入口會停止並指出原因，不偷偷使用另一份 Python。
此入口是 Windows 開發用途，不改變正式安裝版、檔案關聯或 macOS 啟動方式。

### 環境重建

保留所有既有 `.venv*`；不要搬移虛擬環境。只有 `.venv-dev` 不存在時才建立：

```powershell
& .\.venv-tools\bin\uv.exe venv --python .\.venv-tools\python\cpython-3.12-windows-x86_64-none\python.exe --no-managed-python .venv-dev
& .\.venv-tools\bin\uv.exe pip install --python .\.venv-dev\Scripts\python.exe --cache-dir .venv-tools/cache --index-url https://pypi.org/simple -r requirements-windows.txt -r requirements-auth-windows.lock
& .\.venv-tools\bin\uv.exe pip check --python .\.venv-dev\Scripts\python.exe
```

原有 `.venv` 是歷史 macOS 環境，不作本 Windows 開發入口；保留不動。
本輪沒有修改依賴版本。D 槽既有原生工具保留，qpdf 會依現有 manifest 驗證。

## 遷移內容與保護

2026-10-19 遷移前，D 槽為 `0504292`，C 槽最新為 `fa13208`；兩邊共用 D 槽 `.git`。
D 槽只有一個獨有整理提交，已以本機 merge `39e6f1c` 整合，兩個原提交均為其祖先。
文件移位、歷史報告與最新版來源保留；程式碼沒有逐檔複製覆蓋。

`AGENTS.md` 同時保留發布規則、整理限制與固定工作區指引。README 的歷史報告連結
指向 `docs/archive/reviews/`。本次沒有修改產品引擎、正式版本號、main 或其他 worktree。
不推送、不打包、不發布。D 槽原有環境、原生工具、build/dist/release/wheels、
本機設定、金鑰與客戶文件均留在原位；沒有讀取或複製其私密內容。

Git 回退 bundle、SHA256 清單及原始 worktree 狀態保存在本機：
`build/maintenance/archive/d-drive-migration-20261019-030340/`。
詳細測試及遷移日誌：`build/probes/d-drive-migration/20261019-030340/`。
這些本機產物不提交 Git。先前 C 槽驗收產物仍保留在原位置，不整批複製客戶資料或暫存。

## 回退方法

先保存文件並正常關閉應用程式／worker；若任何工作目錄有未提交修改，先停止回退並保存修改。
核對備份 `manifest.json` 與 Git bundle 驗證記錄，不使用強制 checkout、reset 或 clean。

要暫時交回原工作區，先在 D 槽切回仍保留的 `codex/media-profile-library`，
再在 C 槽 `print-composition-v3` checkout `codex/deep-search-restore-layout`。
最新開發提交不會被刪除；回退只是交還分支 checkout，並非清除新提交。
C 槽保留原有啟動環境與產物，必要時可作診斷。

**不要在驗收前刪除 C 槽 worktree、任何 `.venv*` 或 `.venv-tools`。**
驗收完成後清理 C 槽必須另外盤點 ignored／本機檔案，確認驗收證據及私密資料的處理方式，
不可直接遞迴刪除或強制移除 worktree。

## 驗收證據

遷移後的完整回歸、原生 Windows UI、原生工具及啟動入口驗證結果列於本文後續驗收段落。
合成文件測試不代表實際打印機／插封機或客戶文件驗收。


### 2026-10-19 最終驗收結果

| 檢查 | 結果 |
|---|---|
| D 槽全新環境完整回歸 | 210 模組；2,930 通過、4 跳過、零失敗；程序退出碼 0 |
| 原生 Windows Qt 視窗測試 | 18 通過；包含開檔、操作、視窗及正常關閉 |
| 固定啟動入口測試 | 4 通過；亦已包含在全套回歸，不能重複加總 |
| 來源契約預檢 | 9 通過；亦包含在全套回歸 |
| Ruff／來源資源檢查／compileall／差異空白檢查 | 通過 |
| 文件連結與整理歷史 | 已核對；D/C 兩個原提交均保留在 merge 歷史 |
| 實際啟動 | 固定入口啟動 D 槽 main.py；D 槽 venv／Python 基底；可見主視窗有回應 |
| 產品來源與依賴 | 17 組 Git blob/tree 與遷移前 fa13208 完全一致 |
| main／其他 worktree | 原分支提交保持原狀；C 槽保留 detached 回退 |

四項跳過：macOS bundle 連結／權限、Keychain、arm64 簽署安裝／回退，以及本機
缺少 file-symlink 權限的一項發布安全測試。沒有刪除或放寬任何測試。
完整回歸各模組累計約 1,253 秒，包含獨立程序啟動；不是單一功能耗時。

原生工具：qpdf **12.4.2**（完整性 manifest 驗證通過）、Ghostscript **10.05.1**、
Tesseract **5.5.3.20260724**、VeraPDF **1.30.2** 均已實際啟動驗證，保留 D 槽原檔。
VeraPDF 使用程式原有的隨附 Java 啟動路徑；直接執行原始 bat 缺少系統 Java PATH
不代表程式內驗證器失效，亦沒有因此修改系統 PATH 或覆蓋工具。

2,000／8,000 頁合成文件背景掃描、重用索引與 UI heartbeat 測試通過：

| 頁數 | 初次掃描 | 重用索引 | 最大 heartbeat 間隔 |
|---|---:|---:|---:|
| 2,000 | 1.6712 秒 | 1.5850 秒 | 0.0822 秒 |
| 8,000 | 4.4899 秒 | 2.4254 秒 | 0.0973 秒 |

這是合成文件量度，不代表所有客戶文件速度。合成 PDF／PS 產出、Barcode/QC、
Production Review 授權、Editor、列印及 Visual Workflow 均包含在全套回歸。
macOS 實機、實際客戶文件及生產打印機／插封機本輪未驗收；沒有進行打包測試或發布。

### 可重現指令

在 D 槽專案內執行：

```powershell
& .\.venv-dev\Scripts\python.exe -m scripts.regression_suite --group all --output build/probes/d-drive-migration/20261019-030340/full-regression
& .\.venv-dev\Scripts\python.exe -m ruff check .
& .\.venv-dev\Scripts\python.exe scripts/verify_source.py
& .\.venv-dev\Scripts\python.exe -m compileall -q main.py core ui composition workflow scripts/launch_dev.py
git diff --check
```

原生 Windows 視窗驗收使用獨立程序，環境 `QT_QPA_PLATFORM=windows`：

```powershell
$env:QT_QPA_PLATFORM = "windows"
& .\.venv-dev\Scripts\python.exe -m pytest -q tests/test_ui_smoke.py --junitxml=build/probes/d-drive-migration/20261019-030340/native-windows-ui.xml
```

一次性獨立覆核沒有 Critical／Important／Minor 問題。啟動入口最初因模組尚未實作
而出現預期的 RED；第一次 GREEN 有一項測試誤用未解析的 JSON 路徑比較，修正測試
解析後 4 項全通過。離線安裝曾缺少快取，改由官方 PyPI 安裝既有鎖定版本後，67 個
套件相容性檢查通過；沒有改變依賴 pin。

本機證據包括 `qa-summary.json`、各模組 JUnit／log、`native-tools.json`、
`actual-startup.json`、`product-source-proof.json`、`final-review.md` 及遷移 ledger。
最終提交與乾淨狀態另記錄於本機 `delivery-manifest.json`；Git bundle SHA256 在備份 manifest。

本次新增本機提交：`39e6f1c`（保留整理歷史的 merge）、`de7a9ab`（固定啟動及環境說明），
另附本驗收報告提交。正式版本維持 **3.0.9**，未推送、未打包、未發布。
