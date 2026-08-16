# 舊版 TOOLS 全面移植打磨計劃（v2）

> 對照來源：`PDFdocuEdit_Pro_backup/PDFdocuEdit_Pro.py_backup`（13,763 行）
> 目標：舊版「全部 TOOLS」不論版面設計或舊有功能，完整、打磨地呈現在新版（PyQt6 模組化）。
> 原則：功能 100% 覆蓋；版面以新版設計系統（tokens/QSS）復刻舊版結構，不引入爆格回歸。

## 1. 舊版 TOOLS 完整盤點

### 1.1 頂部
| 區塊 | 內容 |
|---|---|
| File 選單按鈕 | Open PDF、Open PostScript、Open New Window (Ctrl+N)、Save、Save As、**Encrypt PDF、Decrypt PDF**、Print、Exit |
| Window 選單按鈕 | Window Management |
| Readme 按鈕 | show_readme（hover 綠色 #02F78E、Arial Black） |

### 1.2 主工具列（30px 圖示）
Open、Save、Save As、Save All ｜ Rotate Left (Ctrl+L)、Rotate Right (Ctrl+R) ｜ Delete Selected (Delete)、Extract Selected (Ctrl+E) ｜ Merge PDFs

### 1.3 左側工具塢（QGroupBox 分組，圓角 20px，標題綠色）
- **Page Operations**：Search Pages、Insert Pages、Delete Pages、Extract Pages、Ordering Pages、Split PDF、Visual Organizer
- **Conversion**：Pdf to Word、Batch Convert MS Office to PDF、Batch Convert TXT to PDF、Batch Convert PostScript to PDF
- **Utilities**：PDF Version Control、Statistical Page Count、Extract Text By Position、Merge Multiple PDF Files、PDF Form Overlay、Batch Print PDF Files、Deep Search PDFs、Merge CSV/Excel Files、Compress PDF SIZE、Read Barcode/QR Code、Batch Read Barcode/QR Code
- **Security**：Encrypt PDF、Decrypt PDF

### 1.4 底部資訊列
檔案路徑｜頁數標籤、頁面尺寸、頁碼 ｜ **ROTATE 按鈕 + 頁碼輸入框 + 角度下拉 (0/90/180/270)** ｜ 縮放滑桿（100–300）

### 1.5 狀態列訊息慣例
`✅ Loaded / 💾 Saved / 💾 Saved as / 🔗 Merged (MB) / 🔄 Rotated N pages / 🗑 Deleted N pages`

## 2. 新版現況對照（基線）

| 舊版 | 新版對應 | 狀態 |
|---|---|---|
| Open PDF / PostScript（.ps/.eps 自動轉） | `_open_dialog` 過濾器含 ps/eps + `load_file` | ✅ |
| Open New Window / Window Management | 分頁 + Tab 列（P4） | ✅（設計取代） |
| Save / Save As / Save All / Print | CommandBar + File 選單 | ✅ |
| **File 選單 Encrypt/Decrypt** | 只在側欄 Security 有 | ⚠️ 選單缺 |
| Readme | Help → README 對話框 | ✅ |
| **主工具列 9 個快速動作** | 無對應工具列（CommandBar 只有 Open/Save/SaveAs/Search/Print/Undo/Redo） | ❌ 版面缺 |
| Page Operations 7 工具 | 側欄 Pages 區（8 個，含新增 Rotate/Info） | ⚠️ 組名/順序異、缺 Order Pages 項目 |
| Conversion 4 工具 | 側欄 Convert 區 | ⚠️ 組名異 |
| Utilities 11 工具 | 側欄 Document tools 區（12 個，含 find_file） | ✅ 全齊，組名異 |
| Security 2 工具 | 側欄 Security 區 | ✅ |
| Search Pages（文字搜尋+高亮+進度） | Nav 搜尋面板 + Ctrl+F | ✅ |
| Ordering Pages（文字序重排） | ContextPanel「Order Pages」 | ⚠️ 只經右側面板，側欄無入口 |
| 底部 ROTATE + 頁碼輸入 + 角度下拉 | Rotate 選單（目前頁）+ Rotate Pages 對話框 | ⚠️ 指定頁碼快捷列缺 |
| 縮放滑桿 100–300 | 縮放輸入框（25–400）+ Ctrl+滾輪 | ⚠️ 滑桿缺 |
| 檔案路徑｜頁數標籤 | 檔名標籤 + /N 計數 | ⚠️ 全路徑/頁數提示缺 |
| 狀態列 emoji 訊息 | bottom bar status + info_bar | ⚠️ 慣例未統一 |
| 圖示資產（30 個） | App_icon 已對齊（前輪完成） | ✅ |

## 3. 落差清單 G1–G10（要做的實質變更）

- **G1 快速工具列**：新增 `ui/quick_toolbar.py`，置於 CommandBar 之下。**（已確認）6 個按鈕**＝Save All、Rotate Left、Rotate Right、Delete、Extract、Merge（圖示：save_all/rotate_left/rotate_right/delete/Extract-page/Merge-PDF.png，30px）；Open/Save/Save As 維持喺 CommandBar 不重複。Rotate L/R → 目前頁 ±90°；Delete/Extract → 若有縮圖多選預填範圍，否則開對話框；Save All、Merge 接既有 handler。
- **G2 側欄對齊舊版**：組名改為 Page Operations / Annotate（新功能保留）/ Conversion / Utilities / Security；Pages 區順序改為舊版：Search → Insert → Delete → Extract → **Order pages（新工具，接 `_show_context("sort")`）** → Organize pages（Visual Organizer）→ Split → Rotate → Info。
- **G3 File 選單補 Encrypt/Decrypt**（舊版位置：Save As 與 Print 之間）。
- **G4 底部 Rotate 快捷列**：Rotate 選單新增「Rotate Page(s) from Page Box」子選單 90°/180°/270°（CCW），作用於頁碼輸入框的數字（支援 1-3,5 區間語法），對齊舊版 ROTATE+頁碼+角度 UX。
- **G5 縮放滑桿**：底部縮放群組加入緊湊 QSlider（**（已確認）25–400**，對齊輸入框範圍，步距 25），與輸入框雙向同步（blockSignals 防回圈），舊版滑桿 UX 復刻。
- **G6 檔案資訊標籤**：`set_document_info` 加 path 參數 → 標籤顯示檔名、tooltip 顯示完整路徑｜頁數（舊版格式）。
- **G7 狀態訊息統一**：save/save as/save all/rotate/delete/reorder/merge/load 路徑輸出舊版 emoji 慣例至 bottom bar status + info_bar。
- **G8 側欄綠色復刻**（**已確認**：只做 hover/選中 + 區標題）：新增 token `ACCENT_LEGACY = #02F78E`；MotionNavButton hover/active 背景綠色、文字轉黑；CollapsibleSection 標題文字用綠色；pressed 保留 #FF6347；其餘主體配色維持新版設計系統。
- **G9 File 選單「Open PostScript…」獨立項目**：直接開 .ps/.eps 過濾器（行為與既有 load_file 一致）。
- **G10 工具提示/捷徑對齊**：快速工具列與側欄 tooltip 補舊版文字及捷徑（Ctrl+O/S/Shift+S/L/R/Delete/E），檢查並解決與新版快捷鍵衝突；Delete 用 `Qt.ShortcutContext.WindowShortcut` 綁定，避免輸入框誤觸發。

## 4. 執行階段

| 階段 | 內容 | 檔案 | 驗收 |
|---|---|---|---|
| **P0 基線** | 對照表入檔、pytest 92 全綠快照 | 本計劃 | 無回歸 |
| **P1 功能落差** | G3、G9、G2（Order pages 工具）、G4（Rotate 子選單+頁碼解析） | `core/viewer.py`、`ui/side_panel.py`、`ui/bottom_bar.py` | 手動冒煙 + 新測試 |
| **P2 版面落差** | G1 快速工具列、G5 縮放滑桿、G6 路徑提示 | `ui/quick_toolbar.py`(新)、`core/viewer.py`、`ui/bottom_bar.py` | 溢位稽核 0 問題 |
| **P3 視覺打磨** | G2 組名/順序、G8 綠色 hover、G7 訊息、G10 tooltip/捷徑 | `ui/side_panel.py`、`ui/motion.py`、`styles/tokens.py`、`styles/components.py`、`core/viewer.py` | 溢位稽核 + 視覺走查 |
| **P4 驗證** | 新增 `tests/test_tools_port.py`（17 案例：工具列按鈕/訊號、側欄順序、選單動作、滑桿同步、狀態訊息、Encrypt/Decrypt 選單）；pytest、ruff、verify_source、offscreen 稽核、benchmark | `tests/` | 全綠 |

## 執行狀態：✅ P0–P5 全部完成（111 tests 全綠；G1 快速工具列其後按用戶要求移除）

- P0 基線 92 綠 → P1 選單/Order Pages/Rotate 子選單 → P2 快速工具列/滑桿/路徑 tooltip → P3 組名順序/綠色/emoji 訊息/快捷鍵 → P4 19 新測試 → P5 文件更新。
- **G1 快速工具列已移除**（2026-08-15 用戶決定）：`ui/quick_toolbar.py` 刪除，版面/訊號/QSS/測試全部還原；Ctrl+L/R/E、Delete 快捷鍵保留。
| **P5 文件** | 更新 `docs/legacy-audit.md` → 完整 parity 矩陣；improvement-plan 記入 changelog | `docs/` | 文件與實作一致 |

## 5. 風險與約束

- QSS 高度/寬度爆格回歸 → 全部沿用 tokens，完成後跑 `scripts/audit_overflow.py`。
- QRunnable 內任何 BaseException 會 SIGABRT → 新異步任務 run() 一律捕捉 BaseException。
- 頁面變更操作（rotate/delete/save）須經 `DOCUMENT_LOCK`，保持 undo 快照先行。
- 滑桿↔輸入框同步須 blockSignals 防訊號回圈。
- 捷徑衝突（Ctrl+L/Ctrl+R/Delete/Ctrl+E）先 grep 現有 QKeySequence 再綁定。
- 全部 App_icon 資產已存在，無需新增圖檔；icon.ico 保留。

## 6. 交付物

1. `ui/quick_toolbar.py`（新）
2. `docs/tools-port-plan.md`（本文件）
3. 更新：`core/viewer.py`、`ui/side_panel.py`、`ui/bottom_bar.py`、`ui/motion.py`、`styles/tokens.py`、`styles/components.py`
4. `tests/test_tools_port.py`（新）
5. `docs/legacy-audit.md`（更新為完整 parity 矩陣）
