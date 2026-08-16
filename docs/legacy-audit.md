# 舊版功能稽核報告（2026-08-14）

> 對照來源：`PDFdocuEdit_Pro_backup/PDFdocuEdit_Pro.py_backup`（13,763 行舊版單體）
> 目標：確認所有舊版功能已在新版（PyQt6 模組化）實作，圖示依循舊設定。

## TOOLS 全面移植（P0–P5 已完成，見 docs/tools-port-plan.md）

| 舊版版面 | 新版實作 | 狀態 |
|---|---|---|
| 頂部 File 選單（Encrypt/Decrypt/Open PostScript） | File 選單補齊 Encrypt PDF…、Decrypt PDF…、Open PostScript…（decrypt 僅加密檔啟用） | ✅ |
| 主工具列（9 個 30px 圖示） | ~~`ui/quick_toolbar.py`~~ **已按用戶要求移除**；相關快速鍵（Ctrl+L/R/E、Delete）保留於快捷鍵層 | ✅（快捷鍵） |
| 左側工具塢分組 | 側欄組名/順序對齊舊版：Page Operations / Annotate / Conversion / Utilities / Security | ✅ |
| Ordering Pages（文字序重排） | 側欄新工具「Order pages」→ ContextPanel Order Pages | ✅ |
| 底部 ROTATE + 頁碼輸入 + 角度下拉 | Rotate 選單新增「Rotate Page(s) from Page Box」子選單（90/180/270，支援 1-3,5 語法） | ✅ |
| 縮放滑桿（舊 100–300） | 底部縮放滑桿 25–400，與輸入框雙向同步 | ✅ |
| 檔案路徑｜頁數標籤 | 檔名標籤 + 全路徑｜頁數 tooltip | ✅ |
| 狀態列 emoji 訊息 | ✅ Loaded / 💾 Saved / 🔗 Merged / 🔄 Rotated / 🗑 Deleted / 🔀 Reordered 慣例統一 | ✅ |
| 側欄綠色 (#02F78E) | hover/選中 + 區標題用 legacy green（light 主題標題用深綠保可讀性）；pressed #FF6347 | ✅ |
| **渲染與視覺（2026-08-15）** | Continuous 快速滾動白畫面修復：可見頁**高優先**渲染 + 預取**限流**（MAX_PENDING_RENDERS=8），快速滾動不再被離屏頁積壓；所有彈出選單（QMenu + 下拉列表）**圓角 12px/10px + 微透明**（代理樣式設 WA_TranslucentBackground，主題色 rgba 246/255） | ✅ |
| 工具列快捷鍵 | Ctrl+L/R/E + Delete（WindowShortcut；Delete 喺輸入框聚焦時不觸發） | ✅ |
| **macOS 打包（2026-08-15）** | `dist/PDFDocuEdit Pro.app`（301MB，arm64，含 Ghostscript + Letterhead_Manager + 全依賴）+ `release/PDFDocuEdit-Pro-0.98b-macOS-arm64.zip`（131MB，含 sha256）；offscreen 啟動煙測零錯誤 | ✅ | 完整打包準備：spec 捆綁 **完整 Ghostscript**（bin/lib/Resource/iccprofiles）、pyzbar zbar DLL、Letterhead_Manager（**已遷移 PyQt6**）+ jinja2、comtypes（Windows 限定）；`_bundled_ghostscript()` 優先偵測捆綁版；`requirements-windows.txt`、`scripts/build_windows.bat`、`docs/windows-build.md`；macOS 實機 PyInstaller 驗證 build 成功（301MB，含全部內容，警告檔只有預期嘅 comtypes） | ✅ |
| **Deep Search 完整移植**（2026-08-15） | 舊版介面分佈 + 功能全數復刻：folder 列／選項列（Include Subfolder、**Include barcode content**、**Open 方式下拉**：新視窗=新分頁／目前視窗／系統預設）／搜尋列（**逗號多關鍵詞**、Enter 觸發）／狀態列（狀態 + **目前處理檔案** + **進度條**）／三個分頁（**Search Result** 4 欄可排序、**Preview** HTML 關鍵詞黃底高亮、**Error Message** 獨立錯誤表）／按鈕列（Clear all results、Export **HTML/TXT/CSV**、Open Selected Document、Auto column width）+ 表頭右鍵自動調寬；非模態、DeleteOnClose；`core/tools.deep_search` 支援多關鍵詞 + 條碼內容 + 進度回報。**第二輪打磨**：搜尋列置頂、主題 token 一致、結果列分離錯誤表 + item 存原始索引（**修復排序/錯誤交錯時開錯 PDF**）、搜尋中防重入、空資料夾提示、dialog 重用、關閉時停止動畫防 crash | ✅ |

## 已涵蓋（無需變更）

| 舊版 | 新版對應 |
|---|---|
| 開啟 PDF / PostScript（自動轉 PDF） | `load_file` ✓ |
| 拖放開啟 | `DocumentWorkspace` drop ✓（多檔開分頁，P4 增強） |
| 頁面操作：旋轉/插入（含空白頁、重複插入）/刪除規則/提取規則/分割 | ContextPanel + 對話框 ✓（規則式選頁保留） |
| Visual Organizer（縮圖拖曳重排視窗） | `VisualOrganizerDialog` ✓ |
| Ordering page sequence（文字序重排） | ContextPanel「Order Pages」✓ |
| 文件內搜尋 / 檔名搜尋 / Deep Search | NavPanel 搜尋 + SearchOpenDialog + DeepSearchDialog ✓。**搜尋整合（2026-08-15）**：獨立 DocumentSearchDialog 已合併入 Ctrl+F 搜尋面板——範圍選擇（All / Current page / Custom 範圍）、Match case、Whole word、結果列顯示每頁命中數，移除「Advanced…」按鈕及第二視窗 |
| 條碼/QR（單檔、多檔、DPI、類型） | `BarcodeScanDialog` 單一對話框支援多檔 ✓ |
| 轉檔：Office/TXT/PS→PDF、PDF→Word | 全數 ✓ |
| 合併 PDF / CSV-Excel / 覆蓋 / 壓縮 / 頁數報告 | 全數 ✓ |
| 批次列印（印表機/紙張/方向/偏移/雙面） | `BatchPrintDialog` ✓。**第三輪打磨（2026-08-15）**：左（檔案表 + 按鈕 + **即時列印進度 log**）右（Printer 組 + **Printer Preferences…** + Paper 組）分欄；非模態——Start 後對話框保持開啟、逐檔寫入 log（舊版行為）；頁數讀取快取（大量檔案唔會每次 refresh 重開 PDF）；無印表機時驗證提示；標籤/欄寬防裁切 | ✅ |
| **Deep Search 第三輪（2026-08-15）** | 開窗尺寸復刻舊版 **80% 螢幕**（下限 920×620 保證唔裁切） | ✅ |
| 加密/解密（AES-256、權限） | `EncryptDialog`/`DecryptDialog` ✓ |
| PDF Info（中繼資料/字型含嵌入狀態/圖片/頁面統計） | `DocumentInfoDialog`（General/Fonts/Images/Text 分頁）✓ |
| 文字區域提取（畫矩形→跨頁→Excel） | `TextExtractorDialog` ✓ |
| PDF Version Control（Letterhead Manager） | 能力偵測 + 啟動 ✓ |
| 多視窗 → 新版分頁取代（P4） | 分頁 + Ctrl+Tab ✓（舊 Window Management 對話框由分頁列取代） |

## 本輪補齊的缺口

| 功能 | 實作 |
|---|---|
| **README 對話框**（Help 選單） | `dialogs/readme_dialog.py`（內容更新為新版功能、英文） |
| **縮圖右鍵選單**（Insert/Delete/Extract/Rotate/Search/PDF Info 目前頁快操作） | `ThumbnailPanel` 自訂選單 + viewer `_handle_thumbnail_action` |
| **底部欄快速旋轉**（舊版 ROTATE+頁碼+角度列） | BottomBar「Rotate」選單按鈕（目前頁 90/180/-90 + Rotate Pages…） |
| **Save All**（舊版多檔全存） | File → Save All（儲存所有已修改分頁） |
| **Batch Read Barcode/QR Code 獨立工具** | 側欄新增 `barcode_batch`（batch_qrcode.png），不預載目前檔 |

## 圖示對齊（App_icon 資產）

| 工具 | 舊資產 | 狀態 |
|---|---|---|
| Compress PDFs | `compress.png` | ✅ 已切換（原 SVG） |
| PostScript to PDF | `postscript.png` | ✅ 已切換（原 File.png） |
| PDF version control | `version.png` | ✅ 已切換（原 SVG layers） |
| Barcode / QR code | `qrcode.png` | ✅ 已切換（原 SVG scan） |
| Batch Read Barcode | `batch_qrcode.png` | ✅ 新工具 |
| Organize pages | `visual_organize.png` | ✅ 已切換（原 sorting.png） |
| 其餘 22 工具 | 沿用既有 App_icon 資產 | ✅ 原本一致 |

## 驗證

- `pytest`：**109 passed**（本輪新增 17 支 `test_tools_port.py`），全綠
- `ruff`（全專案，含 backup/venv 排除）、`verify_source`、溢位稽核：全通過
- 300 頁 benchmark：scroll 24.3ms / zoom coalesced 24.8ms
- 應用程式啟動無錯誤
