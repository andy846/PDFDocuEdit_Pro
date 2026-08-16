# P2 詳細規格 — 畫布覆蓋層與檢視互動

> 隸屬：`docs/improvement-plan.md` 路線圖 P2（🅱 工作流）
> 狀態：規格草案 → 實作中
> 範圍：版面模式（單頁/連續/對開）、平移、文字選取複製、放大鏡、Fit Page / Actual Size、搜尋命中高亮

---

## 0. 目標與設計原則

把 `PdfCanvas` 從「單頁快照 QLabel」升級為可互動畫布，同時**保持既有公開 API 不變**，讓 viewer 的接線（`load_doc/set_page/set_zoom/fit_width/zoom_in/out/current_page/zoom_ratio/refresh/clear/update_theme`、`pageChanged/zoomChanged` 訊號）繼續可用。

**關鍵決策：**
1. **座標映射走比例換算**：`fitz` 的 `page.rect` 已含旋轉，`get_pixmap` 預設套用旋轉，因此 widget↔PDF 座標只是「顯示縮放比例」的線性換算，無需自管旋轉矩陣。
2. **連續/對開模式用虛擬捲動**：容器高度以「頁高估算值」佔位，只掛載可視範圍 ±buffer 的 `PageView`，大文件不會建立數千個 widget。
3. **渲染非同步化**：頁面圖用 `QThreadPool` 背景渲染（從 live `fitz.Document` 各別 `load_page`，符合 PyMuPDF 執行緒模型），以 generation 編號丟棄過期結果。
4. **選取文字**：框選 → 換算 PDF 矩形 → `page.get_text("words")` 交集 → 複製到剪貼簿，命中字框在覆蓋層反白。
5. **P1 整合**：搜尋結果點擊跳頁時，把 `SearchHit.rects` 交給覆蓋層高亮（填補 P1 預留的 `rects` 參數）。

---

## 1. 新增元件

### 1.1 `ui/page_overlay.py` — 頁面覆蓋層

單頁的繪製與互動核心，所有版面模式共用。

```python
class PageOverlay(QWidget):
    selectionChanged = pyqtSignal(int, list, str)   # (page, rects, extracted_text)

    def __init__(self, page_num: int, parent=None)
    def set_page_number(self, page_num: int) -> None
    def set_pixmap(self, pixmap: QPixmap) -> None          # 背景渲染結果
    def set_scale(self, points_per_widget_unit: float) -> None  # pdf 點 ÷ widget 像素
    def set_selection_rects(self, rects: list[fitz.Rect]) -> None   # 選取高亮
    def set_search_rects(self, rects: list[fitz.Rect]) -> None      # 搜尋命中高亮（黃色）
    def clear_highlights(self) -> None
    def widget_to_pdf(self, pos: QPointF) -> fitz.Point
    def pdf_rect_to_widget(self, rect: fitz.Rect) -> QRectF
    def set_select_mode(self, enabled: bool) -> None       # 十字游標
    # events: paintEvent（pixmap + 高亮 + 橡皮筋）、mousePress/Move/Release
```

- **純函式**（利於單元測試）：`scale_for_pixmap(page_rect, zoom, dpr)`、`widget_point_to_pdf(...)`、`extract_words_in_rect(page, rect) -> list[str]` 放在同模組。
- 橡皮筋：按下 → 移動 → 放開，繪製半透明 `primary_soft` 框；放開後由 caller（PdfCanvas）執行文字擷取並 `set_selection_rects`。
- `set_scale`：`points_per_widget_unit = page.rect.width / pixmap.deviceIndependentSize().width()`（含 DPR 邏輯）。
- 高亮色：選取 = `primary` 20% 透明度；搜尋命中 = 黃色（`#ffd54a` 30%），可用 `styles.theme.get_colors()` 的既有色。

### 1.2 `ui/page_view.py` — 頁面容器與渲染快取

```python
class PageView(QFrame):
    def __init__(self, page_num: int, page: fitz.Page, parent=None)
    # 含 PageOverlay + 陰影（QGraphicsDropShadowEffect）+ 頁碼 caption（QLabel，可關閉）
    def set_pixmap(self, pixmap) -> None
    def set_scale(self, ...) -> None
    def overlay(self) -> PageOverlay

class PageRenderCache:
    """LRU 快取：(doc_id, page_num, zoom_bucket, dpr) → QPixmap"""
    def __init__(self, limit: int = 16)
    def get(key) / def put(key, pixmap) / def clear()

def render_page_pixmap(doc, page_num, zoom, dpr) -> QPixmap   # 工作執行緒內呼叫
```

- caption 顯示「第 N 頁」（依 `doc.load_page(n).get_label()`），`objectName="pageCaption"`，QSS 控制樣式；viewer 可設定顯示與否（選單 View → Show Page Labels，預設開）。
- 陰影沿用現有 `PdfCanvas._shadow` 參數（blur 28 / offset 7）。

---

## 2. `ui/pdf_canvas.py` 重寫（保持 API）

### 2.1 公開 API（不變 + 新增）

不變：`load_doc(doc, zoom)`、`set_page(page, emit=True)`、`set_zoom(ratio, emit=True)`、`zoom_in/out`、`fit_width`、`refresh`、`clear`、`current_page`、`zoom_ratio`、`update_theme`、`pageChanged(int)`、`zoomChanged(float)`、`wheelEvent`（Ctrl+滾輪縮放）。

新增：
```python
LayoutMode = StrEnum("single", "continuous", "facing")
ToolMode = StrEnum("browse", "hand", "select", "magnifier")

set_layout_mode(mode, emit=True) / layout_mode
set_tool_mode(mode) / tool_mode            # 手型/選取/放大鏡；space 臨時手型
fit_page() / actual_size()
show_search_hits(page, rects)              # P1 搜尋命中高亮
textCopied = pyqtSignal(str)               # 選取複製（viewer 接去寫剪貼簿）
captionToggled?（用 viewer 直接呼叫 set_show_captions(show)）
```

### 2.2 版面結構

- 外層仍是 `QScrollArea`（widgetResizable=True）。
- 內容 = `QWidget#canvasContainer`，內放 `QSplitter`？否——**絕對定位容器**：
  - `self._pager = QWidget`（固定尺寸 = 計算出的總高 × 寬），`PageView` 以 `setGeometry/move` 放進去。
  - SINGLE：總尺寸 = 單頁尺寸；只掛 1 個 PageView。
  - CONTINUOUS：每頁估高 = `page.rect.height * zoom + caption + spacing`；頁序垂直排。
  - FACING：第 0 頁單獨置中；之後每對 (1,2)、(3,4) 一列，列高 = max(兩頁高)。
- 虛擬掛載：`scrollbar.valueChanged` / `resizeEvent` / 捲動事件 → 計算可視範圍 [first, last] → 掛載 ±2 頁、卸載其餘（pixmap 留在 `PageRenderCache`）。
- 滾動同步：目前頁 = 距 viewport 中心最近的已掛載頁；改變時 `pageChanged.emit`。
- `set_page(n)`：SINGLE → 重渲染該頁；CONTINUOUS/FACING → `ensureVisible` 捲到該頁（`scrollToPage`）。

### 2.3 渲染管線

- `_request_render(page_num)`：zoom bucket = `round(zoom*dpr, 3)`；cache 命中直接 `set_pixmap`；否則送 `QThreadPool` 背景渲染（`FunctionTask` 風格的自訂 QRunnable，帶 generation 檢查）。
- `refresh()` = 清該頁 cache + 重排可視頁。
- `set_zoom`：更新 scale、重排 pager 尺寸、重渲染可視頁（連續模式全部可視頁）。
- `clear()`：清 cache、pager、generation+1。

### 2.4 工具模式行為

- **browse**：點擊頁面 → 把該頁設為目前頁（SINGLE 無動作）；Ctrl+滾輪縮放；一般滾動。
- **hand**：拖曳平移（`scrollBy(-dx, -dy)`）；游標 ClosedHand/OpenHand。
- **select**：`PageOverlay` 橡皮筋 → 放開 → `extract_words_in_rect` → 若文字非空 → `set_selection_rects` + `textCopied`？否——選取只反白；複製在 Ctrl+C。viewer 側：canvas `selectionChanged` → 記住「目前選取文字」→ Ctrl+C（canvas keyPressEvent 轉發）→ `QApplication.clipboard()`。
- **magnifier**：滑鼠懸停（未按鍵）顯示浮動小窗（`QLabel`，2.5×，200×200，跟隨游標），離開頁面隱藏。放大圖取 `page.get_pixmap(clip=..., matrix=2.5*zoom*dpr)`，同步渲染（小區域，快）。
- **space 臨時手型**：`keyPressEvent`（viewport focus）→ 按下 Space 切 hand、放開回復。canvas 需 `setFocusPolicy(StrongFocus)`。

### 2.5 檢視預設

- `fit_width()`：`zoom = viewport.width() / page.rect.width`（FACING 以單頁寬計）。
- `fit_page()`：`zoom = min(vw/pw, vh/ph)`（扣除 caption/spacing）。
- `actual_size()`：`zoom = 1.0`。

---

## 3. `ui/bottom_bar.py`（修改）

- 「Fit」按鈕改為 `QToolButton` + `QMenu`（InstantPopup）：Fit Width / Fit Page / Actual Size。
- 新增版面模式 `QComboBox#layoutSelector`（Single page / Continuous / Facing），訊號 `layoutChanged(str)`。
- 新增 `zoomPercent` 同步不變（`set_zoom_percent`）。

---

## 4. `core/viewer.py`（修改）

- `_connect_signals` 新增：
  - `bottom_bar.fitPageClicked / actualSizeClicked / layoutChanged`
  - `workspace.canvas.selectionChanged` → `self._selection = text`
  - `workspace.canvas.textCopied` → 剪貼簿寫入（或由 canvas 直接寫，見 2.4；採 viewer 接訊號寫剪貼簿，canvas 保持無剪貼簿依賴）
- 快捷鍵/選單：View 選單新增 Single Page（Ctrl+1）/ Continuous（Ctrl+2）/ Facing（Ctrl+3）/ Fit Page（Ctrl+9）/ Actual Size（Ctrl+8）？→ 避免過多快捷鍵：只加選單 + 命令面板項目；快捷鍵 Ctrl+1/2/3 給版面模式。
- `_goto_search_hit(page, rects)` → `canvas.goto_page(page)` + `canvas.show_search_hits(page, rects)`。
- `_update_page_state` / `_page_changed` 不變（canvas 已發訊號）。
- `_build_command_registry` 新增：`view_single/continuous/facing`、`fit_page`、`actual_size`、`tool_hand`、`tool_select`、`tool_magnifier`（checkable 概念 → 命令執行為「切換」）、`toggle_page_labels`。
- 主題/動畫開關同步：`_set_motion_enabled`、`refresh_icons`、`update_theme` 傳給 canvas（既有 `update_theme` 已存在）。

---

## 5. 樣式（`styles/components.py`、`tokens.py`）

- `QLabel#pageCaption`：置中、次要色、小字。
- `QComboBox#layoutSelector`：同 themeSelector 樣式。
- 橡皮筋/高亮畫在 overlay（程式繪製，不走 QSS）。
- tokens：`PAGE_SPACING = 16`、`CAPTION_H = 24`、`MAGNIFIER_SIZE = 200`。

---

## 6. 測試計畫

| 檔案 | 驗證 |
|---|---|
| `tests/test_page_overlay.py` | `scale_for_pixmap`、`widget_point_to_pdf` 往返、`extract_words_in_rect` 對合成頁（含兩列文字）回傳正確文字與順序 |
| `tests/test_p2_ui.py` | 三種版面切換後 `layout_mode` 正確；CONTINUOUS 滾動 → `pageChanged` 同步；FACING 頁序排列（第 0 頁置中、其後成對）；`fit_page`/`actual_size` 縮放值；選取模式框選 → `selectionChanged` 文字正確；`show_search_hits` 高亮 rects 存留；zoom 後 scale 正確 |
| 回歸 | 既有 57 支全綠、`scripts/audit_overflow.py` 無溢位、`verify_source.py` 通過 |

---

## 7. 驗收標準

1. 版面模式三種可切（選單/命令面板/底部欄），連續模式滾動流暢且縮圖/頁碼同步；對開模式第 1 頁單獨置中。
2. Fit Width / Fit Page / Actual Size 皆正確；底部縮放 % 同步。
3. 手型工具拖曳平移；空白鍵臨時平移。
4. 選取工具框選文字 → 反白；Ctrl+C 複製出正確文字。
5. 搜尋面板點擊結果 → 跳頁且命中處黃色高亮。
6. 大文件（>200 頁）連續模式記憶體穩定（只掛可視頁）。
7. 既有功能無回歸、全測試綠燈、溢位稽核乾淨。

---

## 8. 實作順序

1. `ui/page_overlay.py` + `ui/page_view.py`（含純函式）
2. `ui/pdf_canvas.py` 重寫（SINGLE 先通，再 CONTINUOUS/FACING 虛擬捲動）
3. `ui/bottom_bar.py`（Fit 選單 + 版面選擇器）
4. `core/viewer.py` 接線 + 命令表/選單/快捷鍵
5. `styles/` 樣式與 tokens
6. 測試 2 支 + 全量回歸 + 稽核
7. 啟動驗證

*此規格為 P2 實作依據，開始編碼。*

---

## 9. 實作紀錄（2026-08-14，已完成）

### 規格偏差
1. **`scale_for_pixmap`**：實際 scale = `1/zoom`（DPR 由 QPixmap 的 `devicePixelRatio` 消化，不參與邏輯座標）；函式移除多餘的 `dpr` 參數。
2. **版面快捷鍵**：Ctrl+1/2/3（單頁/連續/對開）、Ctrl+8（實際大小）、Ctrl+9（符合頁面）、Ctrl+0（符合寬度）。
3. **工具切換 UI**：選單「View → Canvas Tool」以互斥 checkable 動作群組提供 Browse/Hand/Select/Magnifier；空白鍵臨時手型；Ctrl+C 複製選取文字（經 `textCopied` 訊號由 viewer 寫剪貼簿）。
4. **放大鏡**：`QLabel` ToolTip 彈窗 2.5×，跟隨游標，僅在 Magnifier 工具啟動時顯示。

### 驗證結果
- `pytest`：64 passed（新增 7 支：test_page_overlay 4 + test_p2_ui 3）
- `ruff check`：All checks passed
- `scripts/audit_overflow.py`：No text overflow detected
- `scripts/verify_source.py`：passed
- 應用程式啟動無錯誤
