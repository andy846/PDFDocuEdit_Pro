# PDFDocuEdit Pro — 功能與介面互動改進設計計畫

> 版本：v0.1（設計草案，尚未實作）
> 範圍：內容編輯與註釋、畫布互動、多文件工作區、導航強化、UI/UX 潤色
> 原則：優先「漸進式」融入現有架構，不推翻既有 `core/` + `ui/` + `dialogs/` 分層。

---

## 0. 現況架構摘要（設計的落地基礎）

| 層 | 檔案 | 職責 |
|---|---|---|
| 入口 | `main.py` | `PDFDocuEditApplication` → `PDFViewer` |
| 文件引擎 | `core/pdf_engine.py` | `PdfEngine`：無介面 PyMuPDF 包裝（開啟/儲存/頁面操作/加密/搜尋/TOC） |
| 工具函式 | `core/tools.py` | 轉檔、合併、覆蓋、壓縮、條碼等純函式 |
| 背景任務 | `core/tasks.py` | `FunctionTask`（QThreadPool + 進度 + 取消） |
| 復原 | `core/undo.py` | `UndoStack`：快照式 undo/redo（深度 20） |
| 能力偵測 | `core/capabilities.py` | 選用功能（Office/Ghostscript/zbar…）偵測 |
| 設定 | `core/settings.py` | `SettingsManager` |
| 主視窗 | `core/viewer.py` | `PDFViewer`（QMainWindow，1614 行）：串接所有 UI |
| UI 元件 | `ui/*.py` | CommandBar / InfoBar / TaskBar / SidePanel / ContextPanel / BottomBar / ThumbnailPanel / PdfCanvas / Workspace |
| 對話框 | `dialogs/*.py` | `ToolDialog` 基底 + 各工具對話框 |
| 樣式 | `styles/*.py` | 主題色盤（`theme.py`）、間距符記（`tokens.py`）、QSS（`components.py`） |

**關鍵整合點（設計會反覆用到）：**

1. `PDFViewer` 目前**單文件**導向：`self.engine`、`self._undo_stack`、`self._page`、`self.workspace.canvas` 一對一綁定。
2. `PdfCanvas` 目前是「`QScrollArea` → 容器 `QWidget` → 圖片 `QLabel`」的**靜態快照**，沒有覆蓋層、沒有滑鼠事件處理、沒有座標映射。
3. 復原系統是**整檔快照**（`UndoStack.push` 會在每次破壞性操作前複製一份 temp PDF），因此任何「修改了 `fitz.Document`」的新功能，只要沿用 `_snapshot_before()` 即可免費獲得 undo/redo。
4. `PdfEngine` 已具備 `get_toc()`、`get_page_labels()`、`search_text()`，但 UI 未接上。
5. 樣式系統以 `get_color()` 讀取主題色、`styles/tokens.py` 的 `S/R/F/D` 提供統一尺寸，新 UI 元件應沿用。

---

## 1. 🅰 內容編輯與註釋（最大功能缺口）

### 1.1 目標
讓應用程式名副其實地「編輯」PDF 內容：在頁面上畫重點、加註解、繪圖、蓋章、浮水印、遮蔽，並能填寫 AcroForm 表單與插入簽名。

### 1.2 新增模組

**`core/annotations.py`（新）** — 註釋引擎，純函式、無 Qt 依賴（利於單元測試）：
- `add_highlight(doc, page, quads/rects, color)` — 底層用 `page.add_highlight_annot(quads)`
- `add_underline / add_strikeout / add_squiggly` — 對應 `fitz` 註釋 API
- `add_note(doc, page, point, text, icon)` — 便利貼 `page.add_text_annot`
- `add_freetext(doc, page, rect, text, fontsize, color)` — 文字方塊 `page.add_freetext_annot`
- `add_ink(doc, page, points, color, width)` — 手繪 `page.add_ink_annot`
- `add_line / add_rect / add_circle / add_polygon` — 形狀
- `add_stamp(doc, page, rect, image_path)` — 圖片圖章 `page.add_stamp_annot`
- `add_watermark_text / add_watermark_image` — 以 `page.insert_text` + 透明 `fill_opacity`，或 `page.insert_image` + `overlay=False` 置於內容下方
- `redact(doc, page, rects, apply=True)` — `page.add_redact_annot(rect)` + `page.apply_redactions()`
- `insert_image(doc, page, rect, image_path)` — 插入圖片（簽名）
- `list_annotations(doc, page)` / `remove_annotation(doc, page, index)` — 用 `page.annots()` 讀取/管理

> **範圍決策**：AcroForm 表單填寫（`page.widgets()`）與「直接修改頁面文字」**本次不做**（後者需 redact+insert 重建、易失真）。

### 1.3 座標映射（畫布互動的基礎，供 🅱 共用）
新增 **`ui/page_overlay.py`（新）** — 自訂 `QWidget`，取代 `PdfCanvas` 內部的純 `QLabel`：
- 持有目前頁面的 `fitz.Rect`、旋轉、縮放與 DPR
- 提供雙向轉換：**PDF 點座標 ↔ 螢幕像素座標**（考慮 `page.rotation` 與 `fitz.Matrix` 縮放）
- 覆蓋層繪製：現有註釋、選取高亮、繪製中的形狀、遮蔽框

### 1.4 工具模式（Tool Mode）
在 `PdfCanvas` 上新增「工具模式狀態機」：
```
None（瀏覽）→ Highlight / Underline / Note / Freehand / Rectangle / Redact / Stamp / Signature / Image
```
- 滑鼠事件：`mousePress` 記錄起點、`mouseMove` 即時繪製預覽、`mouseRelease` 提交註釋
- 文字導向工具（Highlight/Underline/Strikeout）會先以 `page.get_text("dict")` 命中文塊，按**文字矩形**（而非自由框）產生註釋
- 每個提交動作：`_snapshot_before("Highlight")` → 呼叫 `core/annotations.py` → `canvas.refresh()` → `_sync_modified_state()`

### 1.5 UI 落地
- `SidePanel` 新增「註釋/編輯」區段（section），項目：Highlight、Underline、Strikeout、Note、Freehand、Rectangle、Redact、Stamp、Signature、Image
- `ContextPanel` 新增對應的面板頁：顏色、線寬、字級、透明度、圖章/簽名來源選擇
- 註釋屬性（改色/刪除）透過右鍵選單或 ContextPanel

### 1.6 影響檔案
- 新增：`core/annotations.py`、`ui/page_overlay.py`、`ui/annotation_toolbar.py`（或融入 CommandBar）、`dialogs/annotation_dialogs.py`（圖章/簽名/浮水印選項）
- 修改：`core/pdf_engine.py`（薄包裝註釋操作與 `get_form_fields`）、`ui/pdf_canvas.py`（改為覆蓋層）、`ui/side_panel.py`、`ui/context_panel.py`、`core/viewer.py`（接線）

---

## 2. 🅱 畫布互動（連續捲動/雙頁/平移/選取）

### 2.1 目標
從「單頁快照檢視」升級為流暢、可操作的觀看與選取體驗。

### 2.2 頁面配置模式（Layout Mode）
`PdfCanvas` 新增 `LayoutMode` 枚舉並支援：
- `SINGLE`（單頁，現況）
- `CONTINUOUS`（連續捲動：所有頁垂直排列）
- `FACING`（雙頁對開：第一頁單獨、其後左右對開）

實作：以垂直 `QScrollArea` + 每頁一個 `PageView`（`page_overlay.PageOverlay`），惰性渲染（只渲染可見頁 ±1，類似 `ThumbnailPanel` 的 `_render_visible_thumbnails` 策略，並用 `QThreadPool` 背景渲染大圖）。

### 2.3 工具模式
- **平移（Hand）**：按住空白鍵或選取手工具，拖曳捲動
- **選取（Select）**：框選 → 反白；文字選取 → 用 `page.get_text("dict")` 命中 → 支援**複製文字**（`Ctrl+C`，補上目前完全沒有的「複製」能力）
- **放大鏡（Magnifier）**：懸停時以高倍率在浮動小窗顯示局部（可先以 tooltip 精簡版實作）

### 2.4 檢視預設
- 新增 `Fit Page`（符合頁面）與 `Actual Size`（100%）按鈕/選單，與現有 `Fit Width` 並列
- 底部欄與選單同步

### 2.5 影響檔案
- 新增：`ui/page_overlay.py`（與 🅰 共用）、`ui/page_view.py`（連續/對開的單頁容器）
- 修改：`ui/pdf_canvas.py`（大幅）、`ui/bottom_bar.py`（縮放預設按鈕）、`core/viewer.py`（模式切換、選取複製）

---

## 3. 🅲 多文件工作區（分頁 + 並排比較）

### 3.1 目標
同時開啟多份文件，用分頁切換或並排比較。

### 3.2 核心重構：抽出「文件會話」
新增 **`core/document_session.py`（新）** — `DocumentSession` 類別，把目前散落在 `PDFViewer` 的單文件狀態封裝成一個物件：
```
DocumentSession:
    engine: PdfEngine
    undo_stack: UndoStack
    display_path: Path
    page: int
    canvas: PdfCanvas
    thumbnails: ThumbnailPanel
    def load(path), save(), close(), ...
```
`PDFViewer` 從「持有單一 engine」改為「持有 sessions 集合 + 目前 session」。

### 3.3 分頁（Tab）
- `ui/workspace.py` 的中央區塊改為 `QTabWidget`（或自訂 tab bar），每個 tab 對應一個 `DocumentSession`
- Tab 標題顯示檔名 + 修改標記（`*`），中鍵/關閉鈕關閉，拖放可開新 tab
- 快捷鍵：`Ctrl+Tab` / `Ctrl+Shift+Tab` 切換

### 3.4 並排比較（Split View）
- 在分頁內支援「水平分割」：**同一文件**開第二個 `PdfCanvas`，共享同一份 `fitz.Document`，兩者頁面/縮放各自獨立或同步（toggle）
- 跨文件並排列為後續增強（需 P4 多文件重構完成後）

### 3.5 風險與順序
這是**最具侵入性**的變更（觸及 `viewer.py` 幾乎所有方法）。建議排在 🅰/🅱 之後、以「文件會話」重構先行，並以大量現有功能回歸測試確保不壞。

### 3.6 影響檔案
- 新增：`core/document_session.py`、`ui/tab_bar.py`
- 修改：`core/viewer.py`（大規模）、`ui/workspace.py`

---

## 4. 🅳 導航強化（大綱/書籤/搜尋結果）

### 4.1 目標
在大型文件中更快定位。

### 4.2 目錄大綱面板（Outline/TOC）
- 新增 `ui/outline_panel.py` — `QTreeWidget` 顯示 `engine.get_toc()`（`[level, title, page]`）
- 點擊 → `goto_page(page)`；可折疊；放在側邊欄下方或與縮圖面板同一個 tab 容器
- 引擎已支援，成本低、CP 值高

### 4.3 書籤（Bookmarks）
- 在 `DocumentSession` 記憶書籤（頁碼 + 可選標題），持久化到設定（`settings`）
- `ui/bookmark_panel.py` 列出書籤，支援新增/刪除/跳轉；在指令列與選單加「新增書籤」快捷鍵（`Ctrl+D`）

### 4.4 搜尋結果面板
- 現況 `search_document()` 是逐頁找；改為 `SearchResultsPanel`：
  - 用 `engine.search_text()` 取得「頁碼 → 命中矩形」列表
  - 面板列出「頁 N — 上下文片段」，點擊跳頁並在 `PageOverlay` 反白命中矩形
  - 支援「全部高亮」開關
- 保留 Ctrl+F 的即時輸入，結果即時更新（對大檔可在背景執行緒跑，用 `FunctionTask`）

### 4.5 縮圖拖曳排序
- `ThumbnailPanel` 支援拖曳縮圖改變頁序 → 呼叫 `engine.reorder_pages()`（引擎已備），並走 `_snapshot_before` 流程

### 4.6 影響檔案
- 新增：`ui/outline_panel.py`、`ui/bookmark_panel.py`、`ui/search_results_panel.py`
- 修改：`ui/thumbnail_panel.py`（拖曳）、`core/viewer.py`（接線）、`core/settings.py`（書籤持久化）

---

## 5. 🅴 UI/UX 潤色

### 5.1 命令面板（Command Palette）
- 新增 `ui/command_palette.py` — `Ctrl+K` 彈出：`QLineEdit` + `QListWidget`，列出**所有**動作（選單動作 + 側欄工具 + 檢視指令）
- 模糊搜尋（子序列比對即可）、鍵盤上下/Enter、顯示快捷鍵
- 資料來源：由 `PDFViewer` 註冊一個「動作表」（label + shortcut + callback + 啟用條件），避免手動重複維護

### 5.2 快捷鍵速查表
- `Ctrl+/` 顯示快捷鍵總覽對話框（`ui/shortcuts_dialog.py`），由同一「動作表」自動產生

### 5.3 復原歷史面板
- `UndoStack` 已存 `description`，新增「列出 undo/redo 描述」的只讀清單
- `ui/undo_panel.py` 顯示歷史，點擊可跳到指定快照（需 `UndoStack` 支援按索引還原——目前是 LIFO，需小幅擴充 `snapshots()` 存取器）
- 選單「編輯 → 復原歷史」

### 5.4 其他細節
- 最近檔案附縮圖（在 `EmptyState` 的 recent list 用背景執行緒渲染首頁縮圖）
- 空狀態/入門引導微調、工具提示補充快捷鍵
- 狀態列與 InfoBar 的動畫回饋微調

### 5.5 影響檔案
- 新增：`ui/command_palette.py`、`ui/shortcuts_dialog.py`、`ui/undo_panel.py`
- 修改：`core/viewer.py`（動作表、快捷鍵）、`core/undo.py`（歷史存取器）、`ui/workspace.py`（最近檔案縮圖）

---

## 6. 分階段路線圖（依賴關係）

| 階段 | 內容 | 依賴 | 風險 |
|---|---|---|---|
| **P1** | 🅳 導航（大綱/書籤/搜尋結果面板）+ 🅴 命令面板/快捷鍵/復原面板 | 低（引擎已備） | 低 |
| **P2** | 🅱 畫布覆蓋層 + 座標映射 + 連續/雙頁/平移/選取複製 | `PageOverlay` 為 🅰 前置 | 中 |
| **P3** | 🅰 註釋與內容編輯（分批：先 highlight/note/redact/stamp，再 freehand/watermark/form） | P2 的覆蓋層 | 中 |
| **P4** | 🅲 多文件分頁 + 並排（先 `DocumentSession` 重構，再 tab，再 split） | P1–P3 穩定後 | **高** |
| **P5** | 收尾：拖曳排序、最近檔案縮圖、效能調校、回歸測試 | — | 低 |

> 建議先做 P1 建立「動作表」與「面板容器」基礎，讓後續功能有統一註冊與顯示管道。

---

## 7. 測試策略

- 引擎層（`core/annotations.py`、`document_session.py`、TOC/書籤）：用 `tests/` 既有 pytest 架構加**純單元測試**（不需 Qt），以 `fitz.open()` 建立記憶體 PDF 驗證頁數、註釋數量、TOC、表單值
- UI 層（`PageOverlay` 座標映射、命令面板過濾）：`pytest-qt`（若未引入可加入 dev 依賴）或抽離純邏輯（座標轉換、模糊匹配）做單元測試
- 回歸：`scripts/verify_source.py` + 現有測試全綠；多文件重構（P4）前先補快照測試鎖定既有行為

---

## 8. 已確認決策（2026-08-14）

1. ✅ **註釋範圍**：先做視覺註釋 + 遮蔽 + 圖章/簽名；AcroForm 表單填寫本次不做。
2. ✅ **並排比較**：先做「同文件並排」（共享引擎）；跨文件並排留待 P4 之後。
3. ✅ **文字編輯**：註釋/遮蔽即可，不做直接修改頁面文字。
4. ✅ **優先順序**：同意 P1 → P2 → P3 → P4 路線圖。

---

*本文件為設計草案，決策已鎖定；下一階段可展開 P1 的詳細規格或進入實作。*

