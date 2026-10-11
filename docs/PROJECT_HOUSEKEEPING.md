# Project Folder 整理與封存

## 範圍及保留原則

2026-10-11 保守整理的對象是 `D:\Python_Project\PDFdocuEdit_Pro`。
其他 Git worktree 保留原狀；本次不切換、合併或同步產品分支。
最新開發版本另在其 worktree，本資料夾的整理不代表產品版本已升級。

保留 `.git`、所有 `.venv*`、`build` 既有內容、`dist`、`release`、`wheels`、
`Ghostscript`、`Tesseract`、`VeraPDF`、`build_assets`、`App_icon`、產品圖示及 Splash。
`.venv-312/pyvenv.cfg` 的 Python 來源在 `.venv-tools` 中，兩者有依賴關係，不能當作重複環境直接刪除。
`pyinstaller_prompt.txt` 被來源契約測試讀取，繼續留在根目錄。
更新私鑰、`secret`、本機設定和客戶檔案不搬移、不讀取内容、不加入封存。

## 檔案歸位

| 類別 | 固定位置 |
|---|---|
| 開發啟動 stdout／stderr 日誌 | `build/dev-launch/logs/` |
| 一次性 probe 腳本及產物 | `build/probes/` |
| 持續維護的檢查工具 | `scripts/` |
| 歷史審查及驗證文件 | `docs/archive/reviews/` |
| 本機整理封存及操作清單 | `build/maintenance/archive/<日期時間>/` |

程式本身的日誌仍使用既有 `core.resources.log_dir()`，不改日誌引擎。
日誌／probe／本機封存位於既有 Git 忽略的 `build/` 下，不提交或發布。
沒有定時刪除規則；大型打包產物、發布附件及開發環境需要獨立盤點。

## 本輪處理規則

- 第一層 `.designer-launch-*.log`、`launch_log*.txt`、`launch_err*.txt`：空檔刪除，非空檔本機封存。
- `probe_smart_layout.py`、`probe_smart_sample.py`、`probe_smart_ui_verify.py`：本機封存。
- `ANNOTATE_TOOLS_VERIFICATION_PLAN.md`、`PROJECT_REVIEW_REPORT.md`：移至文件封存區，內容保留並標示歷史基線。
- 清除本工作區閒置的 `.pytest_cache`、`.ruff_cache`、來源／測試目錄 `__pycache__` 及根目錄 `Thumbs.db`。
- 排除開發環境、打包目錄、原生工具、其他 worktree、連結及任何受 Git 追蹤的檔案。
- 正在使用／被鎖住的檔案略過，不強制終止應用程式。

清理先驗證絕對路徑。封存先複製，核對来源及副本 SHA256，再移除来源；同名不覆蓋。
本機 `manifest.json` 記錄原位置、封存位置、處理狀態、大小及 hash。
快取可重建，但不是驗收結果；不得以 `*.log` 遞迴規則刪除整個專案日誌。

## 歷史文件

- [Annotate Tools 歷史驗證及實施計劃](archive/reviews/ANNOTATE_TOOLS_VERIFICATION_PLAN.md)
- [V2.5／V2.6 準備階段專案審查報告](archive/reviews/PROJECT_REVIEW_REPORT.md)

歷史報告中的版本、測試數量和狀態維持原記錄，不代表目前產品驗收。
README 入口及文件內相對連結已隨移位調整；Git 保存原位置及內容。

## 還原方法

1. 查看本次 `build/maintenance/archive/<日期時間>/manifest.json`。
2. 非空日誌及 probe 保存在 `local/`，同一批另附 `restore-local.ps1`。
   在 PowerShell 使用 `& '<封存目錄>\restore-local.ps1'`。
3. 還原工具先核對 hash、來源路徑及缺少目標，只複製回本工作區，不覆蓋現有檔案、不刪除封存。
4. 空日誌、縮圖及 Python／測試快取不需還原，工具會按需要重新產生。
5. 受 Git 追蹤的歷史文件、README 及整理指引用本次獨立提交還原，
   例如 `git revert <整理提交SHA>`；不要使用 `reset --hard` 清除其他工作。

完整處理數量、略過原因及釋放空間見本機 `summary.json`，不把封存檔案計作已釋放空間。

## 2026-10-11 整理結果

13 個非空日誌及 3 個 probe 已本機封存，2 份歷史報告已歸入 reviews；16 個空日誌、25 個快取目錄及 Thumbs.db 已清除。釋放 24,493,838 bytes（約 23.36 MiB），沒有略過項目。18 份封存 hash、40 個文件連結及 9 個來源契約測試通過。

本機完整清單、摘要及還原工具位於 `build/maintenance/archive/20261011-135055/`。
既有 build/release/dist、所有開發環境、原生工具及其他 worktree 保留原狀。
