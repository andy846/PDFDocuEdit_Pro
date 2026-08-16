# P1 詳細規格 — 導航強化 + UI 命令/快捷鍵/復原歷史

> 隸屬：`docs/improvement-plan.md` 路線圖 P1
> 狀態：規格草案（尚未實作）
> 範圍：大綱（TOC）、書籤、搜尋結果面板、命令面板、快捷鍵速查、復原歷史

---

## 0. 總覽

P1 目標是「更快找到位置」與「更順手的操作」，全部**低風險**、可獨立驗收。核心結構決策是引入一個**導航面板容器 `NavPanel`**，把縮圖、大綱、書籤、搜尋結果統一放進 `DocumentWorkspace` 左側欄位；同時引入**命令註冊表 `Command`** 作為命令面板與快捷鍵速查的單一資料來源。

```
NavPanel（ui/nav_panel.py）
├─ 縮圖 ThumbnailPanel（既有，遷入）
├─ 大綱 OutlinePanel（新）
├─ 書籤 BookmarkPanel（新）
└─ 搜尋結果 SearchResultsPanel（新）

Command 註冊表（core/commands.py）
├─ CommandPalette（ui/command_palette.py，Ctrl+K）
└─ ShortcutsDialog（dialogs/shortcuts_dialog.py，Ctrl+/）

UndoHistoryDialog（dialogs/undo_history_dialog.py）
```

---

## 1. 共用基礎

### 1.1 `core/commands.py`（新）— 命令註冊表

純 Python（無 Qt 依賴），供命令面板、快捷鍵速查共用。

```python
@dataclass(frozen=True)
class Command:
    id: str                       # 唯一識別，如 "merge"
    label: str                    # 顯示名，如 "Merge PDFs…"
    shortcut: str                 # 顯示用，如 "Ctrl+K"（可為 ""）
    section: str                  # 分組："File"/"Edit"/"Tools"/"View"/"Navigate"/"Help"/"Panels"
    handler: Callable[[], None]   # 執行函式（閉包）
    enabled: Callable[[], bool] | None = None   # None = 永遠啟用
```

- `viewer._build_commands() -> list[Command]`：在建構期產生完整清單（見 §8），每個 handler 直接指向既有的 `_tool_requested`、`_open_dialog` 等。
- 過濾為**純函式**（利於測試）：`filter_commands(commands, query) -> list[Command]`，規則為**大小寫不敏感的子序列比對**（`query` 字元依序出現在 label 或 shortcut 中）。

### 1.2 `ui/nav_panel.py`（新）— 導航面板容器

取代 `DocumentWorkspace` 目前直接持有的 `ThumbnailPanel`，成為左側欄的統一容器。

```python
class NavPanel(QFrame):
    tabChanged = pyqtSignal(str)      # "thumbnails"|"outline"|"bookmarks"|"search"
    closed = pyqtSignal()             # 使用者關閉整個導航欄

    def __init__(self, animations_enabled=True, parent=None):
        self.thumbnails: ThumbnailPanel      # 既有，遷入
        self.outline: OutlinePanel           # 新
        self.bookmarks: BookmarkPanel         # 新
        self.search: SearchResultsPanel       # 新

    def show_panel(self, key: str) -> None   # 切換 tab + 顯示整個 NavPanel
    def active_key(self) -> str
    def toggle(self) -> None                 # 顯示/隱藏（Ctrl+T 用）
    def load_document(self, doc_path, page_count, password=None) -> None  # 開啟文件時
    def clear_document(self) -> None                                       # 關閉文件時
    def set_document_available(self, available: bool) -> None
    def refresh_icons(self) / def set_animations_enabled(self, enabled) -> None
```

**結構**：
- 頂部一條**圖示 tab 列**（`QToolBar` 或一排 `MotionIconButton`）：縮圖、大綱、書籤、搜尋；右側一個關閉鈕。
- 下方 `QStackedWidget` 裝四個面板。
- 固定寬度 `D.NAV_W = 240`（新增 token）。縮圖面板原本 `setFixedWidth(D.THUMBNAIL_W)`（140）改為**填滿容器**（移除固定寬、保留 `THUMBNAIL_WIDTH=110` 作為縮圖內文寬度）。
- 各子面板**不主動操控外部 splitter**（避免重蹈 `SidePanel`/`ContextPanel` 直接改 splitter 的耦合），顯示/隱藏由 `DocumentWorkspace` 統一控制 `NavPanel` 的 `setVisible`。

**既有行為遷移**：
- `DocumentWorkspace.toggle_thumbnails()` → 改呼叫 `nav_panel.show_panel("thumbnails")` 或 `nav_panel.toggle()`。
- `workspace.thumbnails` 的引用改為 `workspace.nav_panel.thumbnails`（viewer 內一併改）。

---

## 2. 大綱面板 `ui/outline_panel.py`（新）

### 2.1 目的
顯示 `engine.get_toc()`（已存在）的目錄樹，點擊跳頁。

### 2.2 介面

```python
class OutlinePanel(QFrame):
    jumpRequested = pyqtSignal(int)     # 零基底頁碼

    def load_toc(self, toc: list[tuple[int, str, int]]) -> None
    def clear(self) -> None
```

### 2.3 細節
- 用 `QTreeWidget`，單欄、無表頭。巢狀層級直接映射 `fitz` TOC 的 `level`（1 = 頂層，逐層縮排）。
- **頁碼轉換**：`fitz.get_toc()` 回傳 `[level, title, page]` 其中 `page` 是 **1 基底**；`jumpRequested` 一律發 **0 基底**（`page - 1`）。此轉換抽成純函式 `toc_to_zero_based(toc) -> list[tuple[int, str, int]]` 供單元測試。
- 空目錄 → 顯示「此文件沒有目錄」提示字樣（`QLabel`，`objectName="navEmpty"`）。
- 點擊 `itemClicked` → 解析 item 的 `UserRole`（0 基底頁）→ `jumpRequested.emit(page)`。
- 捲動：跳頁後不自動捲動樹（避免搶焦點）；可選「同步捲動」留待後續。

### 2.4 樣式/圖示
- 新增 icon `list-tree`（大綱 tab）、`bookmark`、`bookmark-plus`、`history`、`keyboard`、`command`（見 §10 圖示清單）。
- `QTreeWidget#outlineTree` QSS 沿用側欄樹樣式。

---

## 3. 書籤 `ui/bookmark_panel.py`（新）+ 設定持久化

### 3.1 目的
記住文件內位置，跨開啟持久化。

### 3.2 資料模型
- 每份文件一份書籤清單，以**原檔絕對路徑**為 key 存進 `SettingsManager`：
  ```json
  "bookmarks": {
    "/abs/path/doc.pdf": [ {"page": 0, "title": "第 3 章"}, ... ]
  }
  ```
- 頁碼用 **0 基底** 存（與 `goto_page` 一致）；顯示時 `page + 1`。

### 3.3 `core/settings.py`（修改）
- `DEFAULT_SETTINGS` 增加 `"bookmarks": {}`。
- 新增方法：
  ```python
  def get_bookmarks(self, path: str) -> list[dict]      # 依序回傳 [{"page":int,"title":str}]
  def set_bookmarks(self, path: str, items: list[dict]) -> None
  ```

### 3.4 介面

```python
class BookmarkPanel(QFrame):
    jumpRequested = pyqtSignal(int)
    addRequested = pyqtSignal()          # 以目前頁新增（標題由 viewer 以 QInputDialog 詢問）
    removeRequested = pyqtSignal(int)    # 依 row 移除

    def load_bookmarks(self, items: list[dict]) -> None
    def clear(self) -> None
```

### 3.5 細節
- `QListWidget`，每列顯示「第 N 頁 · 標題」（`icon("bookmark")`）。
- 工具列：`+`（新增目前頁書籤）、`-`（刪除選取）、（可選）改名。
- 預設標題：`第 N 頁` 或取自該頁 TOC 標題（若命中）。
- 捷徑 `Ctrl+D` 由 viewer 綁定 → 目前頁加書籤（`addRequested` 流程，彈 `QInputDialog` 填標題，Enter 確認）。

---

## 4. 搜尋結果面板 `ui/search_results_panel.py`（新）

### 4.1 目的
把目前**強制模態**的 `DocumentSearchDialog` 升級為**非模態、即時**的搜尋面板，並列出所有命中。

### 4.2 引擎擴充 `core/pdf_engine.py`（修改）

```python
@dataclass(frozen=True)
class SearchHit:
    page: int                  # 0 基底
    rects: list[fitz.Rect]     # 命中矩形（供 P2 高亮）
    context: str               # 命中處前後文（純文字）

def search_text_detailed(self, text, *, case_sensitive=False, whole_word=False,
                         pages=None) -> list[SearchHit]:
    ...
```
- 以 `page.search_for(text)` 取得矩形；`context` 由 `page.get_textbox(rect.expand(...))` 或 `get_text` 裁切產生。
- 大小寫/全字：先以 `search_for` 命中，再以 `page.get_textbox(rect)` 取出文字後過濾（若 PyMuPDF 版本旗標不足）。
- 大文件（> 50 頁）由 UI 層丟進 `FunctionTask` 背景執行（`progress`/`cancel` 沿用既有 `_run_task`）。

### 4.3 介面

```python
class SearchResultsPanel(QFrame):
    jumpRequested = pyqtSignal(int, list)   # (page, rects) — rects 供 P2 高亮，P1 先只用 page
    searchRequested = pyqtSignal(str)       # query 變更（viewer 接去跑背景搜尋）
    advancedRequested = pyqtSignal()        # 開啟既有 DocumentSearchDialog（自訂頁範圍等進階）

    def set_results(self, hits: list[SearchHit], total_matches: int) -> None
    def show_searching(self) -> None / def show_error(self, message: str) -> None
    def clear(self) -> None
```

### 4.4 細節
- 頂部 `QLineEdit`（placeholder「搜尋文件」）+ 選項（大小寫、全字 checkbox）+「進階…」按鈕。
- **防抖**：`QTimer` 單發 300ms，`textChanged` → 重啟計時 → 到時 `searchRequested.emit(query)`。
- 結果 `QListWidget`（或 `QTableWidget`：頁碼 | 命中數 | 前後文），點擊 → `jumpRequested.emit(page, rects)`。
- 狀態列文字：`在 N 頁找到 M 個命中`。
- 空查詢 → 清空結果、不搜尋。

### 4.5 與現有對話框的關係
- `search_document()`（Ctrl+F）**改為**開啟 NavPanel 的「搜尋」tab 並聚焦輸入框。
- 保留 `DocumentSearchDialog`，由面板「進階…」按鈕呼叫（涵蓋「自訂頁範圍」等進階選項）；視為相容保留，不做移除。

---

## 5. 命令面板 `ui/command_palette.py`（新）

### 5.1 目的
`Ctrl+K` 快速執行任何指令。

### 5.2 介面

```python
class CommandPalette(QDialog):
    commandTriggered = pyqtSignal(str)   # 執行後由 viewer 依 id 呼叫 handler

    def __init__(self, commands: list[Command], parent=None):
    def set_commands(self, commands: list[Command]) -> None
```

### 5.3 細節
- 無邊框、置中於主視窗（`Qt.Popup` 或 frameless `QDialog` + 陰影，沿用主題色）。
- `QLineEdit`（自動焦點）+ `QListWidget`：每列「圖示 + label + 右側 shortcut + section」。
- 過濾：`filter_commands()`（§1.1）；空查詢顯示全部（分組標題）。
- 鍵盤：`↑/↓` 選取、`Enter` 執行、`Esc` 關閉、`Ctrl+K` 再次按下也關閉。
- 停用項目（`enabled()` 回傳 False）灰顯並標原因（如「開啟 PDF 後可用」）。
- 執行：`commandTriggered.emit(command.id)` → viewer 依 id 找 handler 呼叫後關閉。

### 5.4 觸發
- viewer 以 `QShortcut(QKeySequence("Ctrl+K"), self)` 綁定（macOS 上 `Ctrl+K` 可改 `Meta+K`，依 `PlatformService.MACOS` 決定，spec 先以 `Ctrl+K` 為準並註明可調整）。

---

## 6. 快捷鍵速查表 `dialogs/shortcuts_dialog.py`（新）

### 6.1 介面
```python
class ShortcutsDialog(ToolDialog):
    def __init__(self, commands: list[Command], parent=None):
```
- 繼承既有 `ToolDialog`（geometry 記憶、淡入動畫、`SortableTableWidget` 排序/複製）。
- 表格三欄：`Command` / `Shortcut` / `Section`，用 `SortableTableWidget`。
- 頂部 `QLineEdit` 過濾（同 `filter_commands`）。
- `Ctrl+/` 綁定於 viewer 開啟。

---

## 7. 復原歷史 `dialogs/undo_history_dialog.py`（新）+ `core/undo.py`（修改）

### 7.1 目的
可視化 undo/redo 堆疊，點擊跳到任意快照。

### 7.2 `core/undo.py`（修改）
- 新增**唯讀**存取器（不改既有 LIFO 語意）：
  ```python
  @property
  def undo_count(self) -> int
  @property
  def redo_count(self) -> int
  def undo_descriptions(self) -> list[str]   # 舊→新（stack 底→頂）
  def redo_descriptions(self) -> list[str]   # 依還原順序
  ```

### 7.3 介面
```python
class UndoHistoryDialog(ToolDialog):
    undoToRequested = pyqtSignal(int)   # 目標「保留 undo 條數」→ 需 undo 的次數
    redoToRequested = pyqtSignal(int)   # 需 redo 的次數

    def __init__(self, undo_desc: list[str], redo_desc: list[str], parent=None):
```

### 7.4 細節
- `QListWidget` 由上而下：**redo 描述（灰、斜體）** → 「— 目前狀態 —」分隔列 → **undo 描述（正常）**（最新在最接近分隔列處）。
- 點擊 undo 項 → `undoToRequested.emit(n)`，`n` = 從目前位置需 undo 的步數（最新項 n=1）。
- 點擊 redo 項 → `redoToRequested.emit(n)`。
- viewer handler `_undo_to(n)` / `_redo_to(n)`：迴圈呼叫現有 `_undo()` / `_redo()` n 次（每次走 `_snapshot`/`_reopen_from_snapshot` 既有流程，自動同步縮圖/頁面/undo 狀態）。
- 選單「Edit → Undo History…」開啟。

---

## 8. `core/viewer.py` 整合清單

### 8.1 `_init_ui` / 建構期新增
- 新增成員：`self.nav_panel`（經 `workspace.nav_panel` 存取）、`self._commands`、`self._command_palette`、`self._shortcuts_dialog`、`self._undo_history_dialog`。
- 新增快捷鍵（`QShortcut`）：`Ctrl+K`（命令面板）、`Ctrl+/`（快捷鍵）、`Ctrl+D`（新增書籤）、（既有 `Ctrl+T` 改接 nav_panel）。

### 8.2 訊號接線（新增於 `_connect_signals`）
| 來源 | 訊號 | 目標 |
|---|---|---|
| `nav_panel.outline` | `jumpRequested` | `goto_page` |
| `nav_panel.bookmarks` | `jumpRequested` | `goto_page` |
| `nav_panel.bookmarks` | `addRequested` | `_add_bookmark` |
| `nav_panel.bookmarks` | `removeRequested` | `_remove_bookmark` |
| `nav_panel.search` | `searchRequested` | `_run_search` |
| `nav_panel.search` | `jumpRequested` | `_goto_search_hit` |
| `nav_panel.search` | `advancedRequested` | `search_document_advanced` |
| `nav_panel` | `tabChanged` | （選擇性）記錄最後開啟的面板 |
| `_undo_stack` | `changed` | `_update_undo_actions`（既有）+ 復原歷史對話框若開啟則刷新 |

### 8.3 方法增刪
- **修改**：`search_document()` → 開 NavPanel 搜尋 tab；新增 `search_document_advanced()` 承接原 `DocumentSearchDialog` 邏輯。
- **新增**：`_build_commands()`、`_show_command_palette()`、`_show_shortcuts()`、`_show_undo_history()`、`_run_search(query)`、`_goto_search_hit(page, rects)`、`_add_bookmark()`、`_remove_bookmark(row)`、`_undo_to(n)`、`_redo_to(n)`、`_load_navigation(doc)`、`_clear_navigation()`。
- **修改**：`_open_pdf()` 末尾呼叫 `_load_navigation(...)`（載入 TOC、書籤、重置搜尋）；`close_document()` 呼叫 `_clear_navigation()`；`goto_page()` 後同步 `nav_panel.thumbnails.set_current_page`（既有）與 `outline`（可選）。
- **修改**：`_toggle_thumbnails()` 改為操作 `nav_panel`。

### 8.4 `_build_commands()` 內容（初版清單）
涵蓋：File（Open/Search&Open/Save/Save As/Print/Close）、Edit（Undo/Redo/Search/Rotate/Insert/Delete/Extract/**Undo History**）、Tools（側欄全部 20 項工具，handler 走 `_tool_requested`）、View（切換工具面板/上下文面板/**導航面板（縮圖/大綱/書籤/搜尋）**/符合寬度/放大/縮小）、Navigate（前/後/首/末頁）、Help（Preferences/About/Shortcuts/Command Palette）。
- 每個 `enabled` 依 `engine.is_loaded()` 或 `side_panel` 既有可用性決定（文件工具在無文件時停用）。

---

## 9. 檔案變更總表

### 新增（8）
| 檔案 | 內容 |
|---|---|
| `core/commands.py` | `Command` dataclass + `filter_commands()` |
| `ui/nav_panel.py` | `NavPanel` 容器 |
| `ui/outline_panel.py` | `OutlinePanel` + `toc_to_zero_based()` |
| `ui/bookmark_panel.py` | `BookmarkPanel` |
| `ui/search_results_panel.py` | `SearchResultsPanel` |
| `ui/command_palette.py` | `CommandPalette` |
| `dialogs/shortcuts_dialog.py` | `ShortcutsDialog` |
| `dialogs/undo_history_dialog.py` | `UndoHistoryDialog` |

### 修改（8）
| 檔案 | 變更 |
|---|---|
| `core/pdf_engine.py` | `SearchHit` + `search_text_detailed()` |
| `core/undo.py` | `undo_count`/`redo_count`/`undo_descriptions`/`redo_descriptions` |
| `core/settings.py` | `bookmarks` 預設 + `get_bookmarks`/`set_bookmarks` |
| `core/viewer.py` | 接線、命令表、快捷鍵、導航載入/清除、搜尋/書籤/復原歷史 handler |
| `ui/workspace.py` | `thumbnails` → `nav_panel`，改 toggle/show 方法 |
| `ui/thumbnail_panel.py` | 移除固定寬、填滿 NavPanel（縮圖內文寬不變） |
| `ui/icons.py` | 新增 `list-tree`/`bookmark`/`bookmark-plus`/`history`/`keyboard`/`command` 圖示 |
| `styles/tokens.py` | 新增 `D.NAV_W`、`D.NAV_TAB_H` |

> 註：原 `improvement-plan.md` 5.3 寫的 `ui/undo_panel.py` 在本規格改為 `dialogs/undo_history_dialog.py`（改用對話框、更符合現有 `ToolDialog` 模式）。

---

## 10. 測試計畫

### 單元測試（pytest，無 Qt）
| 檔案 | 驗證 |
|---|---|
| `tests/test_toc.py` | `toc_to_zero_based` 的 1→0 基底轉換、層級保留 |
| `tests/test_search_detailed.py` | `search_text_detailed` 回傳 `SearchHit` 結構、頁碼、前後文；大小寫/全字過濾 |
| `tests/test_bookmarks.py` | `get_bookmarks`/`set_bookmarks` 的 round-trip 與預設值 |
| `tests/test_undo_history.py` | `undo_descriptions`/`redo_descriptions` 順序、count 一致性 |
| `tests/test_commands.py` | `filter_commands` 子序列比對（含大小寫、空查詢、shortcut 命中） |

### UI 冒煙（pytest-qt，選配引入 dev 依賴）
- NavPanel tab 切換、`show_panel` 顯示正確子面板
- CommandPalette 過濾 + Enter 觸發正確 handler

### 回歸
- `scripts/verify_source.py` + 全量 pytest 綠燈；既有 20 項工具、undo/redo、拖放開啟不受影響。

---

## 11. 驗收標準

1. **大綱**：開啟含 TOC 的 PDF → NavPanel「大綱」顯示樹 → 點擊任一條目跳到正確頁。
2. **書籤**：`Ctrl+D` 加書籤 → 關閉重開該文件書籤仍在 → 點擊跳頁、刪除生效。
3. **搜尋**：`Ctrl+F` 聚焦搜尋 tab → 輸入即時出結果 → 點擊跳頁、命中數正確；「進階…」仍能開舊對話框。
4. **命令面板**：`Ctrl+K` → 輸入 `merge` → 顯示「Merge PDFs…」→ Enter 執行。
5. **快捷鍵**：`Ctrl+/` 顯示全指令表、可排序/複製。
6. **復原歷史**：連做 3 次頁面操作 → Edit → Undo History → 列表顯示 3 步 → 點第 2 步文件還原到對應狀態。
7. **無回歸**：現有功能與測試全數通過。

---

*本規格為 P1 實作前的最終設計依據；確認後即可依序進入編碼。*

---

## 12. 實作紀錄（2026-08-14，已完成）

### 規格偏差
1. **復原歷史顯示順序**：規格 §7.4 寫「redo → 目前 → undo」；實作改為自然時間線「undo（最新在上）→ 目前 → redo」，語意更直覺。
2. **全字搜尋實作**：規格 §4.2 的「search_for + 矩形文字後過濾」在矩形只含子字串時無法判斷詞邊界；改以 `page.get_text("words")` 詞框比對（同列連續詞支援片語、標點自動剝離）。
3. **新面板文案**：為與既有英文介面一致，新元件一律使用英文文案（原規格範例用中文）。

### 順手修復的既有 bug（發現於整合測試）
1. **多步 undo/redo 損壞**：`_open_pdf()` 每次重開都清空 undo/redo 堆疊，導致 undo 一次後 redo 與二次 undo 失效。新增 `reset_history=False` 路徑，快照重開時保留歷史。
2. **列印崩潰**：`viewer.py` 缺 `QImage` import（PyQt6 遷移遺漏），列印即 `NameError`。
3. **SettingsManager 讀取副作用**：無參數建構時急切 `mkdir` 設定目錄（能力偵測等唯讀呼叫也被迫建目錄）；改為惰性解析 `config_dir_path()`，僅儲存時才建立。
4. **測試隔離**：`tests/conftest.py` 將 `QSettings` 重導至暫存目錄（原生格式在 macOS 寫入 `~/Library/Preferences`，沙箱/CI 不可寫）；`test_print_renderer` 補上 SettingsManager monkeypatch。

### 驗證結果
- `pytest`：56 passed
- `ruff check`：All checks passed
- `scripts/verify_source.py`：passed
- 應用程式（danger-full-access 模式）啟動無錯誤
