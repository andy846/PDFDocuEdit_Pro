# P4 詳細規格 — 多文件分頁與同文件並排

> 隸屬：`docs/improvement-plan.md` 路線圖 P4（🅲 工作流，最高風險項）
> 狀態：規格草案 → 實作中
> 已鎖定決策：並排先做「同文件」；跨文件並排列為後續。

---

## 0. 目標

一次開啟多份 PDF，以分頁切換；同一份文件可開雙畫布並排。這是全專案**最具侵入性**的重構（`viewer.py` 目前 1600+ 行全是單文件假設），策略重點是**以相容介面最小化 diff**。

## 1. 核心設計

### 1.1 `ui/document_session.py`（新）— 文件會話

```python
class DocumentSession(QObject):
    def __init__(self, animations_enabled: bool, parent=None):
        self.engine = PdfEngine()
        self.undo_stack = UndoStack(self)
        self.display_path: Path | None = None
        self.page = 0
        self.nav_panel = NavPanel(animations_enabled)   # 縮圖/大綱/書籤/搜尋（每分頁一組）
        self.canvas = PdfCanvas()                        # 主畫布
        self.split_canvas: PdfCanvas | None = None       # 並排第二畫布（同 doc）
        self.tab_widget = QSplitter(Horizontal)          # [nav_panel | canvas_area]
        self.canvas_area = QSplitter(Horizontal)         # [canvas] 或 [canvas | split_canvas]
        # nav_panel 預設隱藏；split_canvas 延遲建立
    def set_split(self, enabled: bool) -> None
    @property tab_title(self) -> str   # "name" 或 "name *"
    def close(self) -> None            # wait renders → engine.close
```

- 兩個畫布共享同一 `fitz.Document`（渲染由 `DOCUMENT_LOCK` 序列化，P3 已備）。
- 並排畫布的 `pageChanged/zoomChanged` **不接** chrome（只接主畫布）。

### 1.2 `ui/workspace.py`（重構）— 分頁容器

```
DocumentWorkspace
├─ QStackedWidget
│   ├─ EmptyState（原樣）
│   └─ QTabWidget（closable、movable、documentMode）
│       └─ 每 tab = session.tab_widget
```
- 新訊號：`tabCloseRequested(object)`（session）、`tabChanged(object)`（session）。
- `create_tab(session)` / `close_tab(session)` / `session_at(index)` / `set_current_session(session)`。
- **相容屬性**：`canvas` → 目前 tab 的 session.canvas；`nav_panel` → 目前 tab 的 session.nav_panel（無 tab → 回傳 None）。既有測試與 menu 接線靠這兩個屬性不變。
- 既有方法 `show_document / show_thumbnails / toggle_thumbnails / show_nav_tab / set_recent_files / refresh_icons / set_animations_enabled / dragEnter/Leave/Drop` 保留語意。

### 1.3 `core/viewer.py`（全面 session 化）

**相容屬性**（讀寫都支援，指向目前 session；無 session 時讀取回傳 None）：
```python
@property engine(self) -> PdfEngine | None      # setter 拋錯（唯讀；指派改走 session）
@property _display_path(self) -> Path | None    # setter 寫 session.display_path
@property _page(self) -> int                    # setter 寫 session.page
@property _undo_stack(self) -> UndoStack | None
```
- `_open_pdf(session, path, display_path, *, reset_history, announce)` — 原邏輯改 session 域。
- `load_file(path)` → 目前 session 載入（無 session 則建立）；`open_in_new_tab(path)` → 新 session + tab + 切換。
- 拖放多檔：第一檔載入目前 tab，其餘 `open_in_new_tab`（取代舊的「只加最近檔案」）。
- Search & Open：`open_in_new_window` 改為開新分頁；對話框按鈕文案改「Open in New Tab」。
- `close_document()` = 關目前分頁；最後一個分頁關閉 → EmptyState。
- `closeEvent`：逐 session 確認未儲存 → 取消任務 → wait renders → engine.close。
- `Ctrl+Tab` / `Ctrl+Shift+Tab`（QShortcut）切換分頁；`Ctrl+T` 維持縮圖開關；`Ctrl+W` 關目前分頁。
- 分頁切換 `_on_tab_changed(session)`：同步 bottom_bar（檔名/頁數/目前頁/縮放/版面）、side_panel 可用性、context_panel 頁數、undo 動作、視窗標題、修改標記、tab 文字、註釋列表、命令列狀態。
- 所有既有 handler（頁面操作/轉檔/搜尋/書籤/註釋/浮水印/列印/undo）以「作用中的 session」執行；nav/canvas 訊號接線改以 `lambda …, s=session` 捕獲來源 session（搜尋結果面板、縮圖、大綱、書籤、畫布註釋）。
- `_build_command_registry` 新增：`tab_next`、`tab_prev`、`tab_close`、`tab_new`（Open…）、`view_split`（Toggle Split View）。

### 1.4 同文件並排

- View 選單「Split View」（checkable）→ `session.set_split(True/False)`。
- 開關時保留各自頁面/縮放；兩個畫布各自捲動。
- 底部欄/縮圖只跟主畫布同步。

## 2. 檔案變更總表

| 檔案 | 動作 |
|---|---|
| `ui/document_session.py` | 新增 |
| `ui/workspace.py` | 重構（分頁容器 + 相容屬性） |
| `core/viewer.py` | 全面 session 化 + 分頁邏輯 |
| `dialogs/search_open_dialog.py` | 按鈕文案 New Window → New Tab |
| `tests/test_p4_ui.py` | 新增 |
| `docs/p4-spec.md` | 本文件 |

## 3. 測試計畫

| 測試 | 驗證 |
|---|---|
| `test_open_multiple_tabs_and_switch` | 開兩檔 → tab 數 2、切換後 bottom_bar 檔名/頁數/undo 狀態、視窗標題同步、tab 文字含修改標記 |
| `test_close_tab_confirm_and_last_tab_empty` | 關分頁（未儲存 → monkeypatch question Discard）→ tab 數減一；最後一個關閉 → EmptyState 顯示 |
| `test_per_session_undo_isolation` | 文件 A 旋轉、切到 B、undo B → 只影響 B；切回 A 頁數不變 |
| `test_split_view_same_document` | `session.set_split(True)` → split_canvas 存在且 load_doc 同文件；關閉還原 |
| `test_compat_properties` | `workspace.canvas` / `workspace.nav_panel` / `window.engine` / `window._page` 指向目前 session |
| 回歸 | 既有 75 支全綠（相容屬性保障）、`audit_overflow.py`、`verify_source.py` |

## 4. 驗收標準

1. 拖放/開啟多檔 → 多分頁；分頁可關（×/Ctrl+W）、可拖曳排序、Ctrl+Tab 切換。
2. 每分頁獨立 undo/縮放/頁面/搜尋/書籤/大綱；切換後 chrome 全同步。
3. 未儲存分頁關閉有確認；最後分頁關閉回空狀態。
4. Split View 同文件雙畫布並排，各自捲動縮放。
5. 既有全部功能無回歸、75+ 測試全綠、稽核乾淨、啟動正常。

## 5. 實作順序

1. `ui/document_session.py`
2. `ui/workspace.py` 分頁容器 + 相容屬性
3. `core/viewer.py` session 化（分批：生命週期 → 頁面操作 → 工具 → 搜尋/導航 → 註釋）
4. 分頁切換/關閉/快捷鍵/並排
5. `test_p4_ui.py` + 全量回歸
6. 稽核 + 啟動驗證

*此規格為 P4 實作依據，開始編碼。*

---

## 6. 實作紀錄（2026-08-14，已完成）

### 規格偏差與實作決策
1. **`DocumentSession` 置於 `ui/document_session.py`**（非 core/）：它同時持有引擎（core）與畫布/nav 面板（ui），屬 UI 層編排物件。
2. **相容介面策略**：`PDFViewer.engine` 屬性在無文件時回傳一個 idle `PdfEngine`（非 None），讓既有 100+ 處 `engine.xxx` 呼叫免改；`_display_path`/`_page` 為讀寫屬性轉發目前 session；`workspace.canvas`/`workspace.nav_panel` 為屬性解析目前分頁。既有 75 支測試因此全數不動。
3. **session 參數可選**：`_handle_annotation/_run_search/_add_bookmark` 等以 `session=None` 預設取目前 session，保留直接呼叫相容性。
4. **並排（split）**：`session.set_split()` 動態增刪第二個 `PdfCanvas` 共享同一 `fitz.Document`；獨立頁面/縮放；只有主畫布驅動 chrome。
5. **分頁互動**：QTabWidget（closable/movable/documentMode）、Ctrl+Tab/Ctrl+Shift+Tab、拖放多檔開新分頁、Search&Open 的「New Window」改「New Tab」、Ctrl+W 關目前分頁、最後分頁關閉回空狀態。
6. **關閉流程**：closeEvent 逐 session 確認未儲存 → 取消任務 → `session.close()`（wait renders → engine.close）。

### 驗證結果
- `pytest`：81 passed（新增 6 支 test_p4_ui），連續 5 次全綠
- `ruff check`：All checks passed
- `scripts/audit_overflow.py`：No text overflow detected
- `scripts/verify_source.py`：passed
- 應用程式啟動無錯誤
