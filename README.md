# PDFDocuEdit Pro V2.5.12

PDFDocuEdit Pro 是一套以 PyQt6 及 PyMuPDF 開發的桌面 PDF 工作空間，集中處理閱覽、整理、標註、搜尋、列印、格式轉換及批次文件工作。支援 Windows 及 macOS。

## V2.5.12 Bug fixes

- Improve low-resolution layouts across 40 dialogs; keep primary actions reachable.
- Fix narrow Inspector and Analysis Results panel layouts.
- Load large Merge PDF file lists in the background and reduce default merge save overhead.
- Use a shared Windows taskbar identity and relaunch through Launcher.exe.

See [release notes](docs/RELEASE_NOTES_2.5.12.md).

## V2.5.10 啟動與大型文件效能

- Welcome 重新設計；最近檔案使用快取，網路路徑在背景檢查。
- 開檔背景處理、虛擬化頁面與縮圖、按需載入全文分析。
- 修正長文件拖動縮圖捲軸後的頁碼位置偏差與空白預覽。
- 超過 1,000 頁的 Advanced Page Organizer 使用虛擬列表、背景準備、進度與安全取消。
- 加入 PERF 效能紀錄及大型文件回歸測試。

詳見 [版本說明](docs/RELEASE_NOTES_2.5.10.md) 與 [效能報告](docs/STARTUP_AND_OPEN_PERFORMANCE.md)。

## V2.5.9 閱覽與縮圖修正

- 移除文件分頁列上方額外白線。
- 大量頁面的縮圖介面按需建立，快速捲動優先載入可見頁並自動補齊。
- Continuous / Facing 持續捲動時定時刷新，不再等停止捲動。
- Facing 從第 1、2 頁開始並排；單數末頁獨立顯示。

## V2.5.8 表單、比較與快捷鍵

- **Utilities → Fill PDF form**：填寫既有 AcroForm、預覽常見公式計算、套用後一次 Undo；支援圖片及手寫簽名外觀。
- **Utilities → Compare PDFs**：並排查看文字／視覺差異、插刪頁、手動配對，以及背景運算與取消。
- **Preferences → Keyboard shortcuts**：自訂命令按鍵及作用範圍，檢查重複與多段快捷鍵前綴衝突。

簽名外觀不構成數位簽章；XFA 及未支援的腳本不會執行。詳見 [操作與實作說明](docs/IMPLEMENTATION_STAGES.md)。

## V2.5.7 navigation fixes

Page thumbnails, viewer navigation and page counts stay synchronized; fitting PDF pages are centered. See [fix details](docs/PAGE_NAVIGATION_FIX.md).

## V2.5.6 Advanced Page Organizer

智慧選頁、Reverse、Interleave、空白頁、批次裁切及 Extract／Split，整合暫存預覽與 Undo／Redo。修正旋轉內容、縮圖比例、空白頁崩潰及匯入圖層顯示問題。

詳見 [版本說明](docs/RELEASE_NOTES_2.5.6.md) 及 [Organizer 操作指南](docs/ADVANCED_ORGANIZER.md)。

## Portable updates

Windows managed portable builds now support **Help → Check for Updates**:
signed GitHub ZIP downloads, a fixed launcher, isolated versions, and automatic
startup rollback without an installer. The first deployment requires extracting
the Managed Portable ZIP and switching the shortcut to Launcher.exe.
See [免 Installer 更新與發佈指南](docs/PORTABLE_UPDATES.md).

Download the [V2.5.12 release](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v2.5.12). First deployments use the V2.5.12 Managed Portable package below; start Launcher.exe for managed updates.
Existing installations need the one-time managed portable transition before using in-app updates.

## V2.5.4 stability update

- Atomic rollback for page plans and page insertion; insertion preserves caller order and duplicates.
- Shared OCR language normalization and veraPDF discovery, including `VeraPDF/` and `verapdf/`.
- Runtime/build contract: Python 3.12.x. OCR is not bundled in the macOS build.
- Single and batch printing now prepare/rasterize pages in cancellable workers, with live progress. One page image is in flight at a time; printer interaction stays on the GUI thread. Cancel stops at the next safe checkpoint.
- Safe association unregister, settings null fallback, and public `PDFViewer.apply_theme()`.
- Windows Python 3.12.14: **389 collected/passed test cases across 35 test modules**. Ruff passes. CI already runs Windows full pytest, Ruff, and Linux/macOS core tests. Pillow is pinned to 11.3.0.

The current Windows x64 release is V2.5.12. Use the Managed Portable ZIP below for installer-free updates; matching SHA-256 files are included.

See [repair report](PROJECT_REVIEW_REPORT.md) and [release notes](docs/RELEASE_NOTES_2.5.4.md) for coverage and remaining limitations.

## Background printing follow-up (2026-09-07)

The next development step is complete on this source tree: background preparation/rendering, cooperative Cancel, one job per batch file, and automatic UI/resource restoration. Application editing controls are suspended while printing. Closing the batch dialog requests cancellation and hides it safely. The initial snapshot of an unsaved live document and native printer calls can still briefly block; pages already accepted by the driver may not be retractable.

See [background printing report](docs/BACKGROUND_PRINTING_REPORT.md). The background-printing report records its development checkpoint; the current release also includes the subsequent transaction and history improvements.

## 主要功能

### PDF 閱覽與導覽

- 單頁、連續頁、雙頁與封面雙頁版面
- 可延遲載入的頁面縮圖、快速跳頁、縮放及頁面尺寸（mm）顯示
- 水平或垂直 Split View，可同步頁碼與縮放比例
- Browse、Hand、Select Text 及 Magnifier 四種 Canvas 模式，可直接從主工具列切換
- 書籤、目錄、文件資訊及快捷鍵指南

### Document Inspector、Preflight 與 Smart Detection

- 每個文件 session 提供非模態 Analysis Panel，結果可跳頁、複製頁碼、匯出 CSV/XLSX、擷取或送往 Organizer
- Inspector 檢查 metadata、page boxes、字型、圖片 occurrence/effective DPI 及 colorspace
- General Office、Digital Print、Production Print 三組可編輯 preflight profile
- Exact/Near Blank、文字、圖片、vector、annotation、form、barcode 及 QR code detection
- 分析以 revision 標記；文件修改後舊結果會變成 stale，不能直接套用頁面操作
- PDF/A-1～4 與 PDF/UA-1/2 由離線 veraPDF Greenfield 驗證；PDF/UA 結果只代表 machine-verifiable checks
- PDF/X 僅提供 readiness checks，不宣稱正式 compliance

### 頁面整理

- 清晰的多頁 selection、鍵盤操作、插入線及 `N pages selected` 狀態
- Insert、Replace、Duplicate、Extract、Delete、Rotate、Restore 及重新排序
- 外部 PDF 插入／取代支援頁碼範圍與記憶體內密碼；Apply 為單一 Undo transaction
- 規則式頁碼範圍處理及縮圖式頁面管理
- 合併 PDF、疊加文件、壓縮與批次處理

### 標註與內容工具

- Typewriter、Text Box、Callout 可編輯 FreeText annotation
- Line、Arrow、Ellipse、Polygon、螢光、Underline、Strikeout、Squiggly、Ink、Rectangle、Note、Stamp
- Rubber Stamp 支援 14 款內建印章，以及可命名、重複使用及移除的自訂 PNG/JPG 或文字印章
- 每個工具可保存 stroke/fill/opacity/width/font defaults、Recent Colors 及命名 palette
- 區域文字擷取、條碼掃描、文件分析及診斷
- 深度搜尋及 Find/Open 文件搜尋

### 列印

- 單一及批次列印
- 頁面範圍、紙張、方向、彩色、雙面、份數、縮放、置中及偏移設定
- Draft 150、Standard 300、High 600 DPI 及 72–600 DPI 自訂列印質素
- 自動記住上一次列印設定

### 轉換與資料工具

- PDF、Office、文字、圖片及 PostScript 工作流程（視系統可用元件而定）
- Merge CSV / Excel 支援 `.csv`、`.xlsx` 及 Legacy Excel `.xls`
- 合併工作表固定命名為 `sheet1`，並保留數字型別、移除空白資料列

### 安全與私隱

- PDF 密碼及權限設定
- 本機桌面處理；文件不會因一般編輯流程自動上傳至雲端

## 支援格式

- 文件：PDF、PS、EPS、TXT
- 試算表：CSV、XLS、XLSX
- Office 轉換能力取決於 Microsoft Office 或 LibreOffice
- PostScript 轉換使用隨程式提供或系統安裝的 Ghostscript

## 下載

Windows 版本可於 [Releases](https://github.com/andy846/PDFDocuEdit_Pro/releases) 下載：

- 首次部署：[Managed Portable V2.5.12](https://github.com/andy846/PDFDocuEdit_Pro/releases/download/v2.5.12/PDFDocuEdit-Pro-v2.5.12-Managed-Portable-Windows-x64.zip)，解壓後執行 Launcher.exe。
- 後續更新：在程式內按 Help → Check for Updates；Update ZIP 是更新附件，不是首次部署包。
- 每個 ZIP 均附有同名 .sha256 校驗檔。V2.5.12 採用免 installer 發佈。已有 Managed Portable 的使用者可從 Launcher.exe 啟動後檢查更新。

### Windows release build

在 Windows x64 安裝 Python 3.12 及 Inno Setup 6 後，可執行
`scripts\build_windows.bat`。流程會先驗證 source、執行測試，再建立 PyInstaller
程式、Portable ZIP、Inno Setup 安裝檔及兩份 SHA-256 checksum。

正式簽署 build 可設定以下環境變數：

- `PDFDOCUEDIT_SIGNTOOL`：Windows SDK `signtool.exe` 完整路徑
- `PDFDOCUEDIT_CERT_SHA1`：Authenticode certificate thumbprint
- `PDFDOCUEDIT_TIMESTAMP_URL`：RFC 3161 timestamp URL（可省略）

設定後會簽署主程式、Setup 及 Uninstaller。Installer 會將 PDFDocuEdit Pro
註冊為 PDF、PS、EPS 的可選開啟程式，但不會未經使用者同意改寫 Windows
現有預設程式。


### PDF/A 與 PDF/UA 驗證（Windows / macOS）

Release build 固定 veraPDF Greenfield 1.30.2，並按平台封裝私人 Eclipse
Temurin JRE 21。驗證全程離線，clean machine 不需要 system Java。
`build_assets/verapdf/BUNDLE_INFO.json` 記錄來源 URL、版本、SHA-256、大小及
授權。正式建置可先執行 `python scripts/prepare_verapdf.py`，下載、驗證並
建立平台對應的 `VeraPDF/` bundle；script 會拒絕覆蓋既有 bundle。
`scripts/build.py` 會再檢查 launcher、JRE、manifest，並執行離線
`--version` smoke test；缺少或版本不符會中止 release build。

PDF/UA 報告只包含機器可驗證規則；沒有 XMP conformance claim 顯示
`Not declared`，不會自動當作 PDF/A-1b。PDF/X readiness 不等於 certification。

### OCR (Windows x64)

Conversion 面板提供 bundled Tesseract 5.5.3 英文／繁中 OCR，可抽取 UTF-8
文字或建立 searchable PDF，且不會取代原始檔。Release build 必須包含完整
`Tesseract/` runtime、`eng`、`chi_tra` 語言資料及 PDF config；缺少任一
必要資產時建置會直接失敗。

開發、測試及封裝可使用專案內的 `scripts/build.py` 建置腳本。

### Redaction save follow-up

Applied redactions now require a full garbage-collected save, including encrypted outputs and repeated saves. See the [redaction save report](docs/REDACTION_SAVE_REPORT.md) for reproduction and validation.

### V2.6 architecture preparation

Page, annotation, watermark and applied-redaction actions now use a shared transaction boundary. Undo/redo preserves the live document and history when preparation or restoration fails. Mutation/history coordination lives in `ui/mutation_controller.py`; migrated PDF and annotation outputs share `core/io_atomic.py`.

Windows Python 3.12.14 validation: **389 passed across 35 modules**, plus Ruff and source verification. See the [architecture report](docs/V2.6_ARCHITECTURE_REPORT.md) for detailed scope and remaining packaging/platform checks. These are historical V2.5.4 validation results.

## 版權

Copyright © 2026 Andy Leung. All rights reserved. PDFDocuEdit Pro is proprietary software. Unauthorized copying, modification, distribution, or commercial use of this software or its source code is prohibited.
