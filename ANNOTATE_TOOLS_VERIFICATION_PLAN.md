# PDFdocuEdit Pro — Annotate Tools 驗證報告與可執行實施計畫

驗證日期：2026-08-29
驗證範圍：目前工作樹中的 active PyQt6 codebase；不包含 `backup/` 舊版實作。
驗證方式：靜態呼叫鏈追蹤、offscreen UI 檢查、針對性 pytest、完整 pytest。
本文件先整理驗證證據與實施計畫，並持續記錄已完成的實作批次。

## 1. 驗證基線

| 項目 | 驗證結果 |
|---|---|
| Active 架構 | `main.py` → `core/viewer.py` → `ui/workspace.py` → `ui/document_session.py` → `ui/pdf_canvas.py` |
| `core/viewer.py` | 5,035 行；`PDFViewer` 直接方法 206 個（AST 計數） |
| `core/annotations.py` | 613 行；無 Qt import，核心操作整體清楚且有 `DOCUMENT_LOCK` |
| Python 約束 | `pyproject.toml` 要求 `>=3.12,<3.13` |
| 套件版本 | `PyQt6==6.8.1`、`PyMuPDF==1.26.6`；本機 `.venv-build` 實際載入版本一致 |
| 工具數 | `ui/side_panel.py:226-244` 共 19 個 Annotate 工具 |
| freetext workaround | `core/annotations.py:293-301` 明確綁定 PyMuPDF 1.26 行為 |
| Undo | 完整 PDF 快照，`MAX_UNDO_DEPTH = 20`（`core/undo.py:13`） |
| 針對性測試 | 最新 Line/Arrow 批次 28 passed：P3 UI、overlay interaction |
| 完整測試 | 最新 251 passed in 474.52s |
| 測試環境限制 | 完整測試是在現有 Python 3.11.3 `.venv-build` 執行；它不符合專案宣告的 Python 3.12 執行時，CI 仍應補跑 3.12 |

工作樹在審查開始前已有使用者變更：`Splash.png`、`PROJECT_REVIEW_REPORT.md`、`launch_err2.txt`、`launch_log2.txt`；本次未改動這些檔案。

### P0 實施進度（2026-08-29）

| Issue | 狀態 | 已交付 |
|---|---|---|
| ANN-001 | 完成 | 主/副 canvas 共用 wiring；secondary 同步 tool、style、stamp/image options；annotation mutation 同時刷新兩 pane |
| ANN-002 | 完成 | defaults controls 以 QSignalBlocker 原子載入；切換工具不再污染前一工具設定 |
| ANN-003 | 完成 | markup、ink、line、arrow、rect、ellipse、polygon 建立時貫穿 opacity；shape 貫穿 fill |
| ANN-004 | 完成 | undo/redo snapshot reopen 後恢復 page、zoom、layout、scroll 與 split state，並刷新 annotation list |
| ANN-005 | 完成 | Width 改為 0.5–20.0 的 QDoubleSpinBox；form field 與 label 一起顯隱 |
| ANN-006 | 完成 | 新增 11 個 regression cases；source verification、Ruff 與完整 244 tests 通過 |
| ANN-101 | 部分完成 | signature 有獨立 kind/dispatch；annotation list 移除 index fallback，只接受 stable xref。集中 geometry validator 仍屬 P1 |
| ANN-007 | 完成 | Line/Arrow 改為方向保真的兩點拖曳；即時顯示線條、箭頭與端點控制點，預覽同步顏色、粗細、透明度，不再使用 normalized 方框 |

本輪沒有宣稱完成 Canvas selection、inline editing、局部 cache invalidation、document-level manager、command-object undo、redaction review、XFDF/Flatten、數位簽章、vector watermark 或 tablet 支援；它們仍按後續 issues 排程。

### 工程基線實施進度（2026-08-29）

| Issue | 驗證 | 狀態／已交付 |
|---|---|---|
| ENG-001 CI 缺失 | 確認；repo 原先沒有 workflow | 完成：新增 Python 3.12、Linux/macOS/Windows offscreen test matrix，以及獨立 Ruff job |
| ENG-002 Splash 大小寫 | 確認；tracked asset 是 Splash.png，runtime/spec/verify 使用小寫 | 完成：所有 active runtime、build、verify 路徑統一為 Splash.png，並新增 case-sensitive source contract |
| ENG-003 Pillow 版本 | 確認；兩份 manifest 都固定 10.4.0 | 完成：統一固定 Pillow==11.3.0；這是支援 Python 3.12 的最後一個 11.x release |
| ENG-004 live document thread safety | 確認；多個 PdfEngine reader 與 PDFCanvas GUI reader 未使用 render worker 的共用鎖 | 完成：engine open/readers、canvas layout/selection/render completion、annotation list 統一使用 DOCUMENT_LOCK；新增真正跨 thread 的阻塞測試 |
| ENG-005 zbarimg 退出碼 | 原報告不成立；上游定義 4=沒有找到條碼，1=影像處理錯誤 | 產品碼無須改動；新增 return code 4 回傳空結果、return code 1 拋出 ToolError 的回歸測試 |

## 2. Bug 逐項驗證

狀態定義：

- **確認**：目前呼叫鏈可以直接證明問題存在。
- **確認（潛在）**：正常 UI producer 通常不會觸發，但公開核心入口缺少防護。
- **部分確認**：底層機制存在，但原報告對可達性、範圍或影響的描述過大。

### B01 — Split canvas 註解路徑不完整

**狀態：確認；建議 P0。原描述低估範圍。**

- `_wire_session()` 只連接 `session.canvas` 的 `annotationRequested`、`noteRequested`、context menu 等信號（`core/viewer.py:712-730`）。
- `DocumentSession.set_split()` 在稍後才動態建立 `split_canvas`，只連 page/zoom 同步信號（`ui/document_session.py:58-72`）。
- `_set_canvas_tool()`、`_set_annot_style()`、`_set_annot_image()` 也只更新 `workspace.canvas`（`core/viewer.py:1287-1294`, `2615-2628`, `2798-2799`）。

因此 secondary canvas 不只是「事件可能被丟棄」：它預設仍停在 Browse，且不會同步工具模式、樣式、圖片來源或 annotation handler。若其他程式碼直接替 secondary 設定工具，其信號仍無 consumer。

### B02 — 工具 defaults 交叉污染

**狀態：確認；建議 P0。**

- `_activate_annotation_tool()` 在切換 canvas tool 前呼叫 `set_annotation_defaults()`（`core/viewer.py:2585`, `2596`）。
- `set_annotation_defaults()` 逐一 `setValue()` / `setCurrentText()`，沒有 `QSignalBlocker`（`ui/context_panel.py:434-447`）。
- 控制值變動會發出 `annotationStyleChanged`；handler 以「當下 canvas tool」作為 defaults key（`core/viewer.py:2615-2628`）。

載入新工具 defaults 時，變動信號會把新值的一部分寫回前一個工具的槽；實際污染內容取決於哪些控制值發生變化。

### B03 — Fill 建立時失效

**狀態：確認；建議 P0。**

- Rect、ellipse、polygon 的 `AnnotationOp` 沒附帶 `AnnotationStyle`，只帶 color/width（`ui/pdf_canvas.py:542-550`, `585-594`, `646-653`）。
- `apply_annotation()` 對這三種工具只把 stroke/width 傳給 helper（`core/annotations.py:455-466`）。
- `add_rect()`、`add_circle()`、`add_polygon()` 沒有 fill 參數（`core/annotations.py:188-199`, `233-258`）。
- FreeText 是例外：它有完整 style，建立時 fill 有效。

### B04 — Opacity UI 與實際建立不一致

**狀態：確認；建議 P0。原報告需要更正：UI 路徑中 arrow 也不會收到使用者 opacity。**

- Opacity control 永遠可見；`set_annotation_tool()` 從未切換 `_annot_opacity` 或其 form label（`ui/context_panel.py:510-542`）。
- Markup、ink、rect、line、ellipse、polygon helpers 都沒有設定 opacity（`core/annotations.py:114-258`）。
- `add_arrow()` 本身能消費 style opacity，但 canvas 建立 arrow op 時沒有附上 style，`apply_annotation()` 會重建 opacity=1.0 的預設 style（`ui/pdf_canvas.py:528-539`, `core/annotations.py:442`, `461-462`）。
- 目前只有 FreeText 的正常 UI 建立路徑會貫穿 opacity。
- QFormLayout 的 Font、Font size、Alignment widgets 被隱藏時，對應 label 沒有一起隱藏。

### B05 — `signature` 是不可達且不完整的 kind

**狀態：確認；短期 P1，真正簽名另列 feature epic。**

- SIGNATURE 與 IMAGE 都發出 `kind="image"`（`ui/pdf_canvas.py:622-631`）。
- `AnnotationOp.description()` 和 viewer 檔案選擇邏輯認得 `signature`，但 `apply_annotation()` 沒有 signature branch（`core/annotations.py:88`, `439-487`; `core/viewer.py:2821`）。
- 現有 UI 的「Signature image」可插入圖片，但不會產生獨立 signature operation，更不是數位簽章。

### B06 — index/xref fallback

**狀態：部分確認；建議 P2 defensive cleanup，不是目前可達的 P0。**

- `refresh_annotation_list()` 確實使用 `entry.get("xref", entry["index"])`（`ui/context_panel.py:597`）。
- `remove_annotation()` 也明確禁止把 list index 當 xref（`core/annotations.py:370-387`）。
- 但目前唯一 producer `list_annotations()` 只要 append entry 就一定同時寫入 `xref`；取不到 xref 的 annotation 會被 skip（`core/annotations.py:341-364`）。

所以 fallback 是危險且矛盾的程式碼，但依目前 producer 不會命中。仍應移除，避免未來資料來源或錯誤處理改動後出現 silent no-op。

### B07 — Undo/Redo 重設頁面且清單過期

**狀態：確認；建議 P0。**

- Undo/Redo 重新開啟整份 snapshot（`core/viewer.py:1907-1993`）。
- `_complete_pdf_open()` 呼叫 `canvas.load_doc()`；`load_doc()` 固定 `_page = 0`（`core/viewer.py:1604-1616`; `ui/pdf_canvas.py:263-272`）。
- `_complete_pdf_open()` 沒呼叫 `_refresh_annotate_list()`，而 `load_doc()` 也不 emit pageChanged。
- split canvas 同樣固定到第 0 頁。

現有 UI 測試只在第 0 頁驗證 undo，沒有捕捉頁面與清單狀態回歸。

### B08 — Width 控制會把 1.5 量化成 2

**狀態：確認；建議 P0/P1 quick fix。**

- 控制為 `QSpinBox`，範圍 1–6（`ui/context_panel.py:277-280`）。
- defaults 載入時 `round(float(...))`（`ui/context_panel.py:437`）。
- 核心預設則是 1.5（`core/annotations.py:48`, `64`）。

### B09 — 兩套 recent colors 儲存

**狀態：確認；建議 P1。**

- `SettingsManager.DEFAULT_SETTINGS["annotation_recent_colors"]` 沒有任何 reader/writer（`core/settings.py:38`）。
- 實際使用的是 Qt `QSettings` key `annotations/recent_colors`（`ui/context_panel.py:386-400`）。
- recent colors 只灌入 `QColorDialog` custom slots，主面板沒有動態 recent swatches。

### B10 — 色碼 fallback 與 swatch 同步

**狀態：部分確認；建議 P1。**

- `_rgb()` 只接受 `#RRGGBB`；非法值或 `#AARRGGBB` 會靜默回落 yellow（`core/annotations.py:98-107`）。
- QColorDialog recent storage 使用 `HexArgb`，但使用者真正選取後 `_current_color` 使用 `color.name()` 的 `#RRGGBB`，所以 recent storage 本身目前不會直接把 HexArgb 送進 core。
- settings 被手動修改、未來重用 recent 值或外部 API 傳入時仍會 silent fallback。
- 載入選中 annotation 時只更新 `_current_color`，不更新 swatch checked state，也不顯示 custom color 狀態（`ui/context_panel.py:553-572`）。

### B11 — 新增註解造成全 cache invalidation

**狀態：部分確認；建議 P1 performance issue。**

- 每次新增、刪除、編輯 annotation 都呼叫 `session.canvas.refresh()`。
- `refresh()` 清空整個 `PageRenderCache`、拆除現有 PageView、重新 layout（`ui/pdf_canvas.py:307-313`）。
- Continuous/facing layout 會掃過全部頁面計算 rows/size（`ui/pdf_canvas.py:706-780`）。
- 但實際高解析 rerender 只建立可見頁與 buffer 頁（`ui/pdf_canvas.py:783-916`），原報告「重建所有頁面 pixmap」不精確。

機制足以造成可見區閃爍及之後捲動時的 cache miss；影響程度應用 benchmark 與大文件 UI 測試量化。

### B12 — Zoom 會丟失進行中的 ink/polygon/marquee

**狀態：確認；建議 P1。**

- 進行中筆畫與 polygon points 存在 PageOverlay instance（`ui/page_overlay.py:102-106`）。
- `set_zoom()` 直接 `_teardown_views()` 後重建（`ui/pdf_canvas.py:437-449`）。
- 舊 overlay 被刪除，沒有 commit、cancel 通知或 state transfer；marquee 同樣受影響。

### B13 — Context menu 無 annotation awareness，polygon 右鍵被吃掉

**狀態：確認；建議 P1。**

- `_show_canvas_menu()` 只含 copy/navigation/zoom/page/bookmark/print/info，沒有 annotation actions（`core/viewer.py:1336-1448`）。
- Polygon mode 在 mousePressEvent 捕捉右鍵、完成 polygon 並 accept（`ui/page_overlay.py:280-288`），因此該手勢不會開 canvas context menu。

### B14 — `apply_annotation()` 幾何輸入防護不足

**狀態：確認（潛在）；建議 P1。**

- Rect/ellipse/freetext/stamp/image 直接 `rects[0]`，line/arrow 直接 `points[0:2]`（`core/annotations.py:455-485`）。
- Viewer 只在 `op.rects` 非空時驗證 rect；空 tuple 會繞過（`core/viewer.py:2847-2857`）。
- 正常 canvas producer 會建立所需幾何，但 core API、測試、未來 controller 或 plugin 可傳入 malformed op。
- 例外會在 viewer 被轉成 error toast，snapshot 已經先建立，形成無意義的 undo entry。

### B15 — Swatch QSS、顏色來源與 theme token 不一致

**狀態：確認；建議 P2 cleanup。**

- QSS selector 是 `QToolButton#swatchButton`，實際 widget 是 `QPushButton`（`styles/components.py:614-620`; `ui/context_panel.py:242-247`）。
- 每個 swatch 另有 inline stylesheet，所以 selector 錯誤目前主要是維護問題。
- `core.annotations.ANNOT_COLORS` 與 `ui.context_panel.SWATCHES` 分開定義，RGB 值並不完全相同。
- `styles/tokens.py` 沒有 annotation/UI selection border token；checked border 固定 `#555`。

建議只把「UI 邊框/對比色」做成 theme token；PDF 寫入用的 annotation palette 應是 theme-independent 的共享產品色盤，避免 dark/light theme 改變文件內容色彩。

## 3. 測試缺口驗證

原報告的「`test_annotations.py` 8 個 + `test_p3_ui.py` 8 個」正確，但「polygon、undo 整合完全沒有測試」不正確。

現況：

- Polygon 有 core helper test、PageOverlay interaction test、P3 end-to-end triangle test。
- Annotation undo 至少有 highlight-add undo 與 note-remove undo；其他頁面操作也有 undo tests。
- 缺的是 annotation undo 的狀態完整性，而不是完全沒有 undo integration test。

仍缺少的高價值測試：

1. Squiggly 建立與 PDF subtype。
2. Arrow 建立、line ends、使用者 opacity/style 貫穿。
3. Ellipse 建立、fill、opacity。
4. Typewriter FreeText 的無框外觀與 opacity/font。
5. `update_annotation()` 對 text、stroke、fill、opacity、width 的更新。
6. Rect/polygon/markup/ink/line 的 create-time fill/opacity。
7. Split canvas 的 tool/style/signal parity。
8. 切換工具時 defaults 不交叉污染。
9. Undo/redo 保留頁碼、zoom/layout/scroll anchor，並刷新 annotation list。
10. Malformed `AnnotationOp` 在 snapshot 前被明確拒絕。
11. Annotation list item 永遠使用 stable xref。
12. Width 0.5 step round-trip 與 custom/recent color round-trip。

## 4. UI/UX 與功能建議驗證

| 原建議 | 結論 | 實作注意事項 |
|---|---|---|
| 16. Canvas hit-test/選取/移動/縮放 | 缺口確認 | 需先建立 `(page, xref)` selection model；各 annotation subtype 的 move/resize 規則不同，應分階段交付 |
| 17. FreeText/note inline edit | 缺口確認 | 現在分別用 `QInputDialog.getMultiLineText/getText`（`core/viewer.py:2830-2839`, `2887`） |
| 18. Annotation context menu | 缺口確認 | 應和 B13、selection model 同一 epic |
| 19. 預覽保真 | 缺口確認 | marquee/preview 固定 theme primary、預設 pen；line/arrow/stamp/redact 沒 subtype preview |
| 20. Delete 刪 annotation | 缺口確認 | Delete 目前固定進入 Delete Pages flow（`core/viewer.py:3561-3568`, `3727-3731`） |
| 21–24. Options panel | 缺口確認 | 與 B02/B04/B08/B09/B10/B15 合併實作 |
| 25. Annotation list 升級 | 缺口確認 | 現在只有當頁、固定字串、無 jump/highlight/filter/search |
| 26. 自動同步清單 | 部分已有 | create/remove/edit/page/tab 已刷新；undo/redo/open-complete 缺失，手動 Refresh 仍存在 |
| 27. 快捷鍵/命令面板 | 部分確認並需更正 | 19 個工具其實都已出現在 palette 的 `Tools` section；另有 11 個重複語義的 `Annotate` commands，且該 section 少 8 個。19 個工具都沒有預設 shortcut |
| F1. 樣式完整性 | 缺口確認 | 先建立單一 style pipeline，再擴充 dash/line ends/note icon/bold/italic |
| F2. 真正簽名 | 缺口確認 | 可視簽名圖片與 cryptographic digital signing 必須拆成兩個 scope；後者需證書、增量儲存、驗證與依賴評估 |
| F3. XFDF/FDF/JSON/摘要/Flatten | 缺口確認，但前提需更正 | 本機 PyMuPDF 1.26.6 沒有 XFDF/FDF import/export API；不可宣稱原生支援。`Document.bake()` 可作 Flatten 基礎 |
| F4. Command-object undo | 建議成立 | 先限定 annotation operations；redaction commit 與 save boundary 必須定義清楚 |
| F5. 安全 redact | 缺口確認 | 現在 `add_redact_annot()` 後立即 `apply_redactions()`（`core/annotations.py:317-321`） |
| F6. Watermark 重構 | 問題確認 | 文字先 rasterize 成 PNG，再 fit 到頁面 60%；實體字號大多被 fit 比例抵消（`core/annotations.py:510-596`） |
| F7. 文件級管理器 | 缺口確認 | 可與建議 25 合併為單一 document annotation model/panel epic |
| F8. Tablet/pressure | 缺口確認 | repo 無 `QTabletEvent`、pressure 或 palm rejection |

## 5. 可執行 Issues

Size 使用 S/M/L/XL，表示相對工程量而非工時承諾。

### Phase P0 — 正確性與資料/狀態一致性

#### ANN-001 — 建立 canvas wiring/parity 層

- Priority/Size：P0 / M
- 對應：B01
- Scope：抽出 `_wire_canvas(session, canvas, role)`；secondary 建立時接上 annotation/note/context signals；工具、樣式、圖片、stamp、cursor mode 同步到兩個 canvas。
- 設計：`DocumentSession` 發出 secondary canvas created/removed signal，或由 viewer 的 split toggle 明確呼叫 wire/unwire；避免重複 connect。
- Acceptance：任一 split pane 可建立所有 19 種工具所需操作；事件帶回正確 session/page；切換工具與 style 後兩 pane 一致；關閉 split 不殘留 signal。
- Tests：split before/after tool activation、兩 pane note/rect、style parity、remove split 後無 duplicate handler。
- Dependencies：無。

#### ANN-002 — 原子化 annotation tool/style state

- Priority/Size：P0 / M
- 對應：B02、B08 的一部分
- Scope：使用 `QSignalBlocker` 批次載入 controls；用明確 `_active_annotation_tool`/controller state 保存 defaults，不再以 canvas 當暫存真相；完成載入後只發出一次完整 style。
- Acceptance：A→B→A 切換不改寫任一工具 defaults；載入 controls 不產生中間 style writes；主/副 canvas 同步拿到同一 immutable style。
- Tests：每個欄位值不同的兩工具交替切換；監聽 signal count；settings round-trip。
- Dependencies：建議與 ANN-001 共用 canvas collection API。

#### ANN-003 — 貫穿 create-time fill/opacity/style

- Priority/Size：P0 / L
- 對應：B03、B04、F1 基礎
- Scope：Canvas 對所有可樣式化 op 都附完整 `AnnotationStyle`；core helpers 接收 style；rect/ellipse/polygon 設 fill，markup/ink/line/arrow/shape 設 opacity；明確定義不支援的欄位並在 UI 隱藏。
- Acceptance：使用者按下建立時的外觀與 Options 一致；save/reopen 後 stroke/fill/opacity/width 不變；FreeText 現有 workaround 不回歸。
- Tests：逐 kind parameterized PDF assertion；透明度 0/0.5/1；無 fill 與有 fill；arrow line-end。
- Dependencies：ANN-002。

#### ANN-004 — Undo/redo 保留 view state 並同步 annotation model

- Priority/Size：P0 / M
- 對應：B07
- Scope：snapshot reopen 前保存 page、zoom、layout、scroll anchor、split pane page/zoom；open 完成後恢復；最後刷新 annotation list/selection/thumbnail。
- Acceptance：在第 N 頁 undo/redo 後仍位於第 N 頁；主/副 pane 狀態不跳 0；list 與實際 PDF annotation 數量/內容一致。
- Tests：第 2+ 頁 add/remove/edit + undo/redo；continuous scroll anchor；split sync on/off。
- Dependencies：ANN-001；可先只處理 page/list 再補 scroll anchor。

#### ANN-005 — 修正 Options field contract

- Priority/Size：P0 / S
- 對應：B04 labels、B08、建議 21–22
- Scope：Width 改 `QDoubleSpinBox(0.5..20, step=0.5)`；signal 改 float；每種 tool 定義可見欄位；使用 `labelForField(field).setVisible()` 同步 label。
- Acceptance：1.5 round-trip 不變；所有孤兒 labels 消失；Opacity 只在實際支援的 kind 顯示；keyboard/accessibility label 保持有效。
- Tests：tool×field visibility matrix、width boundary/step/default round-trip。
- Dependencies：ANN-003 的 capability matrix。

#### ANN-006 — 補齊 P0 annotation regression suite

- Priority/Size：P0 / M
- 對應：測試缺口 1–12
- Scope：新增 parameterized core tests 與最小 offscreen UI tests；先以失敗測試固定 B01/B02/B03/B04/B07/B08，再修實作。
- Acceptance：新 tests 在舊實作上可重現問題、修復後通過；Python 3.12 CI 跑完整 233+ tests。
- Dependencies：與 ANN-001～005 並行建立，最後整合。

### Phase P1 — 輸入體驗、效能與管理能力

#### ANN-101 — 集中驗證 AnnotationOp 與 stable identity

- Priority/Size：P1 / M
- 對應：B05 short-term、B06、B14
- Scope：在 snapshot 前執行 kind-specific geometry validation；未知 kind/空幾何回傳 typed error；list item 只接受 xref，缺 xref 則 skip/disable；清除 unreachable fallback。
- Acceptance：malformed op 不建立 undo entry、不進 PyMuPDF、不只靠 IndexError toast；刪除/更新只用 stable xref。
- Tests：每 kind invalid geometry；missing/stale xref；unknown/signature kind。
- Dependencies：ANN-002；未來 controller 可承接 validator。

#### ANN-102 — 局部 invalidation 與 annotation refresh benchmark

- Priority/Size：P1 / M
- 對應：B11
- Scope：新增 `invalidate_pages(page_numbers)`；只清除受影響頁的 cache/view/thumbnail；watermark 等多頁操作傳入明確頁集合。
- Acceptance：單頁 annotation 不清除其他頁 cache；可見頁不白屏；大文件新增 annotation 的 UI latency 與重繪數有可重複 benchmark。
- Tests：cache key preservation、render request count、100/500 頁 benchmark；encrypted doc fallback。
- Dependencies：ANN-003 可提供 affected pages。

#### ANN-103 — 進行中互動的 zoom policy

- Priority/Size：P1 / S/M
- 對應：B12
- Scope：在 zoom/layout rebuild 前採一致策略：禁止/延遲 zoom、明確 cancel 並提示，或把 PDF-space points transfer 到新 overlay。Ink 建議 commit/cancel；polygon 建議 transfer。
- Acceptance：任何 zoom gesture 都不會無聲丟資料；Escape 可取消；狀態轉移後預覽座標正確。
- Tests：ink/polygon/marquee 中途 ctrl-wheel、slider、fit-width。
- Dependencies：無；若做 state transfer，可依賴 ANN-201 selection model。

#### ANN-104 — 保真 drawing preview

- Priority/Size：P1 / M
- 對應：建議 19
- Scope：PageOverlay 接收 active style；line/arrow 畫線形；shape 套 stroke/fill/width/opacity；redact 畫斜線/遮罩；stamp/image 顯示 aspect frame；ink 使用實際 width/color。
- Acceptance：commit 前後主要外觀一致；dark/light theme 可辨識；preview 不改變 PDF 輸出色。
- Tests：QImage pixel/snapshot tests 或 deterministic painter state tests。
- Dependencies：ANN-002/003。

#### ANN-105 — Annotation list model 與自動同步

- Priority/Size：P1 / L
- 對應：建議 25–26、F7 基礎
- Scope：建立 document-level annotation model，欄位含 page/xref/kind/text/title(author)/creationDate/modDate；filter/search；點擊 jump + overlay highlight；移除 Refresh button；所有 mutation/undo/redo/open/page change 發 model event。
- Acceptance：跨頁可搜尋/篩選；點列跳正確頁並高亮 xref；新增/刪除/編輯/undo/redo 後無手動 refresh；stale xref 安全移除。
- Tests：多頁/多 subtype、metadata 缺失、跳頁、事件次數、undo parity。
- Dependencies：ANN-004、ANN-101；ANN-201 共用 selection model。

#### ANN-106 — 統一 annotation colors 與 recent colors

- Priority/Size：P1 / M
- 對應：B09、B10、B15、建議 23–24
- Scope：單一 theme-independent palette；嚴格解析 `#RRGGBB` 與可選 `#AARRGGBB`，非法值回傳 validation error；recent colors 統一到 `SettingsManager`；面板顯示動態 swatches；selected annotation 同步 checked/custom state；UI border 使用 theme token。
- Acceptance：沒有兩套 RGB 定義或兩套 storage；非法色不靜默變黃；recent/custom/default round-trip；dark/light selected border 對比達標。
- Tests：parser、settings migration、swatch state、theme contrast smoke test。
- Dependencies：ANN-002。

#### ANN-107 — 整理 Annotate commands 與快捷鍵

- Priority/Size：P1 / M
- 對應：建議 27
- Scope：每工具只註冊一個 command，section 為 Annotate；移除 Tools/Annotate 語義重複；19 個 command 都提供可自訂、無衝突的 default shortcut；side panel tooltip 從 registry 取值。
- Acceptance：palette 中 19 個且僅 19 個 annotation tool commands；無 duplicate handler；shortcut editor 可修改/恢復；輸入框 focus 時不誤觸。
- Tests：command IDs/section/count、shortcut uniqueness、override round-trip、palette filtering。
- Dependencies：無。

### Phase P1/P2 Epic — Canvas 原生選取與編輯

#### ANN-201 — Annotation selection/hit-test foundation

- Priority/Size：P1 / L
- 對應：建議 16、20；B13 前置
- Scope：以 `(page, xref)` 表示 selection；載入 annot rect/vertices；z-order aware hit-test；hover、selected outline；Delete 在有 annotation selection 時刪 annotation，否則保留 page-delete flow。
- Acceptance：常見 subtype 可 hover/select；重疊時有確定選擇規則；selection 與 list 同步；鍵盤 Delete 不再誤刪頁。
- Tests：rotation/zoom 座標、重疊、stale xref、Delete routing。
- Dependencies：ANN-101、ANN-105 model 可共用。

#### ANN-202 — Annotation context menu 與 polygon 手勢重設

- Priority/Size：P1 / M
- 對應：B13、建議 18
- Scope：annotation hit 時提供 Edit/Delete/Copy Style；空白處維持 canvas menu；polygon 改用 Enter/double-click 完成、Esc 取消，或對右鍵明確二選一，不再隱式衝突。置前/置後需先確認 PDF annotation appearance/z-order 可行性。
- Acceptance：右鍵 selected annotation 顯示正確 actions；polygon completion 與 context menu 均可達；action 使用 xref。
- Tests：menu composition、polygon right-click policy、delete/edit callbacks。
- Dependencies：ANN-201。

#### ANN-203 — Move/resize handles（分 subtype 交付）

- Priority/Size：P1/P2 / XL
- 對應：建議 16
- Scope A：rect/ellipse/freetext/stamp/image move + 8 handles。Scope B：line/arrow endpoint handles、polygon vertices。Scope C：markup/ink 的限制與 UX。
- Acceptance：拖曳以 PDF coordinates 儲存；undo/redo 可逆；rotation/zoom 正確；不支援 resize 的 subtype 明確不顯示 handles。
- Tests：每 scope 的 geometry round-trip、page bounds、undo/redo。
- Dependencies：ANN-201、ANN-301 command undo 可先後分階段。

#### ANN-204 — Inline FreeText/note editor

- Priority/Size：P1 / L
- 對應：建議 17
- Scope：在 overlay 上放置 editor；新建/雙擊既有 annotation 共用；Enter/Ctrl+Enter/Escape/focus-loss 行為明確；note 使用 anchored popover。
- Acceptance：無 modal dialog；zoom/scroll 後 editor 位置穩定；commit 只有一個 undo step；IME/多行可用。
- Tests：new/edit/cancel、IME smoke、zoom/scroll、undo。
- Dependencies：ANN-201；style 來自 ANN-003。

### Phase P2 — 文件互通、安全工作流與架構

#### ANN-301 — Annotation command-object undo

- Priority/Size：P2 / XL
- 對應：F4
- Scope：先為 add/remove/update/move/resize 定義 command + inverse payload；annotation history 不再序列化整份 PDF；其他 page operations 暫留 snapshot stack；定義混合 history 與 save boundary。
- Acceptance：annotation undo O(operation payload)，不複製整份 PDF；20-depth 限制不再造成 annotation history 的大檔成本；redo 完整；redact apply 有獨立不可逆/快照政策。
- Tests：混合 annotation/page commands、save/reopen、memory/disk benchmark、stale xref remap。
- Dependencies：ANN-101、ANN-203；先寫 architecture decision record。

#### ANN-302 — Redaction mark/review/apply workflow

- Priority/Size：P2 / L
- 對應：F5
- Scope：預設只 `add_redact_annot`；文件級 review list；使用者明確 Apply All/Selected 時才 `apply_redactions`；提供 images/graphics/text policy 與預覽；apply 前最後確認。
- Acceptance：標記可刪除/移動/undo；未 apply 不破壞內容；apply 後敏感文字/圖像策略符合選項；保存前明確狀態提示。
- Tests：mark only、cancel、selected/all apply、image policy、search/extraction 確認內容移除。
- Dependencies：ANN-105、ANN-301 policy decision。

#### ANN-303 — 可視簽名與數位簽章拆分

- Priority/Size：P2 / L + discovery
- 對應：B05、F2
- Scope A：把現有功能正式命名 `signature_image`，保留透明 PNG 外觀與可編輯 placement。Scope B discovery：評估 certificate store/PFX、signature widget、incremental save、驗證、時間戳與 pyHanko 等依賴後另開實作票。
- Acceptance：UI/internal kind 不再假裝數位簽章；數位簽章 scope 有 threat model、依賴與跨平台決策後才承諾。
- Tests：signature image kind dispatch；已簽文件修改警告；未來 crypto interoperability fixtures。
- Dependencies：ANN-101、ANN-203；crypto 部分需 ADR。

#### ANN-304 — Annotation import/export、摘要與 Flatten

- Priority/Size：P2 / XL
- 對應：F3、F7
- Scope 0 discovery：定義 XFDF/FDF 支援矩陣與第三方依賴；不可假設 PyMuPDF 原生支援。Scope 1：版本化 JSON schema + summary report。Scope 2：XFDF subset。Scope 3：以 `Document.bake(annots=True, widgets=...)` 實作 Flatten，保留副本/確認。
- Acceptance：round-trip 支援矩陣明確；未知 subtype 不靜默丟失；Flatten 另存新檔且結果無 annotations、視覺一致；摘要依頁/作者/類型可輸出。
- Tests：golden PDFs、JSON schema migration、XFDF interoperability、flatten visual diff。
- Dependencies：ANN-105 document model；先完成 discovery ticket。

#### ANN-305 — Vector watermark

- Priority/Size：P2 / L
- 對應：F6
- Scope：文字改為向量 text/shape；真正的 font size、color、opacity、rotation/position；另評估 removable watermark annotation subtype，不能與 content watermark 混為同一承諾。
- Acceptance：不同 font size 產生可量測的 PDF-space 字高差；文字可選擇/搜尋（若 content 模式）；大頁面不失真；可移除模式有 stable identity。
- Tests：尺寸/旋轉/透明度、save/reopen、visual diff、Unicode/font fallback。
- Dependencies：rotation API spike；ANN-304 flatten 可共用輸出測試。

#### ANN-306 — Tablet pressure 與 palm rejection

- Priority/Size：P2 / L
- 對應：F8
- Scope：處理 `QTabletEvent` pressure/eraser/device type；pressure curve/smoothing；touch/pen arbitration；無 tablet 時保留 mouse path。
- Acceptance：pressure 影響筆寬且輸出可重現；palm touch 不產生 stroke；eraser 行為明確；跨平台 fallback。
- Tests：synthetic tablet event/unit mapping；至少 Windows 實機 QA matrix。
- Dependencies：ANN-003 style pipeline、ANN-103 interaction state。

#### ANN-307 — 抽出 `ui/annotate_controller.py`

- Priority/Size：P2 / L
- 對應：工程觀察
- Scope：把 tool activation/defaults、canvas wiring、op validation/dispatch、annotation model refresh 從 `PDFViewer` 抽出；viewer 僅協調 session/chrome；不要在 P0 修復前做大搬移。
- Acceptance：controller 可在 fake session/canvas 下單測；viewer annotation methods 明顯縮減；無 core→ui 新反向依賴；所有 regression tests 通過。
- Tests：controller unit tests + existing UI smoke。
- Dependencies：ANN-001～107 穩定 API 後執行；可先抽小介面，不做一次性大改。

#### ENG-001 — 清理 tracked backup artifacts

- Priority/Size：P2 / S
- 對應：附帶工程觀察
- 驗證更正：`backup/` 目前不是 10 個，而是 12 個受 git 追蹤檔案，合計約 2.42 MB。
- Scope：先確認保存/稽核需求；移到 release archive、Git LFS、獨立歷史 repo，或保留單一 migration reference；更新 README/`.gitignore`。
- Acceptance：active source 搜尋與打包不再掃入舊 monolith；仍有可追溯 archive；不直接破壞使用者需要的歷史。
- Dependencies：產品/法遵決策；這是另票，不與 annotation code change 混在同一 PR。

## 6. 建議交付順序

1. **P0 regression harness**：先讓 B01/B02/B03/B04/B07/B08 測試失敗。
2. **State correctness**：ANN-001、ANN-002、ANN-004。
3. **Style correctness**：ANN-003、ANN-005。
4. **Hardening**：ANN-101、ANN-106，關閉 phantom/fallback/malformed inputs。
5. **Performance and commands**：ANN-102、ANN-103、ANN-104、ANN-107。
6. **Selection foundation**：ANN-105、ANN-201、ANN-202，再做 move/resize/inline edit。
7. **P2 workflows**：redaction、command undo、signature、interop/flatten、watermark、tablet。
8. **Architecture extraction**：API 穩定後完成 ANN-307，避免把行為修復與大規模搬檔綁在同一批 review。

## 7. 建議 PR 切分與完成門檻

每個 PR 應符合：

- 一個主要 issue；避免 P0 修復與 God Class 大重構同 PR。
- 先有能重現問題的 regression test。
- `pytest` 全套在 Python 3.12、PyQt6 6.8.1、PyMuPDF 1.26.6 通過。
- Annotation PDF fixtures 另存於 pytest temp dir，不提交隨機 binary output。

## 8. P1/P2 實施狀態（2026-08-29）

本次交付以「可操作、可測試、可安全回復」為門檻；XL 架構票不以局部補丁冒充完成。

| Issue | 狀態 | 已交付 / 尚待完成 |
| --- | --- | --- |
| ANN-101 | ✅ 完成 | typed validation、kind/geometry/style 檢查、stable xref、錯誤不進 snapshot。 |
| ANN-102 | 🟡 主要功能完成 | `invalidate_pages()` 已局部清 cache/render；仍待 100/500 頁 benchmark 與 thumbnail 細分。 |
| ANN-103 | ⏳ 待實施 | zoom 中途 ink/polygon 的 transfer/cancel policy 尚未完成。 |
| ANN-104 | 🟡 主要功能完成 | line/arrow 線形、shape style、opacity/fill、redact 斜線預覽；仍待 stamp/image 外觀與像素快照測試。 |
| ANN-105 | ✅ 完成 | 全文件清單、搜尋、類型篩選、metadata、跨頁跳轉／高亮、自動同步；移除手動 Refresh。 |
| ANN-106 | 🟡 部分完成 | 嚴格色碼 parser 與 selected swatch 同步完成；recent colors 尚待移入 `SettingsManager` 並顯示動態色票。 |
| ANN-107 | ✅ 完成 | palette 僅 19 個 Annotate commands、無重複、19 個無衝突預設快捷鍵，使用者 override 優先。 |
| ANN-201 | ✅ 完成 | `(page, xref)` selection、z-order hit-test、Line 精準命中、list/canvas 同步、Delete 優先刪註解。 |
| ANN-202 | 🟡 主要功能完成 | 註解右鍵 Edit/Delete、空白 canvas menu、polygon 右鍵不再彈 menu；Copy Style／z-order 待補。 |
| ANN-203 | 🟡 Scope A/B 部分完成 | rect/ellipse/freetext/stamp/image 可移動及四角縮放；Line/Arrow 可直接拖線及調兩端；8 handles、polygon vertices、限制型 subtype UX 待補。 |
| ANN-204 | 🟡 部分完成 | 既有 Note/FreeText 可雙擊畫布內編輯且單一 undo；多行、IME、Escape/cancel、新建共用 editor 待補。 |
| ANN-301 | ⏳ 待架構實施 | 仍使用文件快照 Undo；需先完成混合 command/snapshot ADR，不能在 redact 安全性上冒進。 |
| ANN-302 | 🟡 安全主流程完成 | 新增只建立 Redact mark；文件級明確確認後才 Apply All；取消不破壞內容。Selected Apply 與 policy UI 待補。 |
| ANN-303 | 🟡 Scope A 完成 | internal kind 已正式拆為 `signature_image`；憑證/PFX/時間戳/驗證屬 crypto discovery，尚未實作。 |
| ANN-304 | 🟡 Scope 1/3 完成 | 版本化 JSON round-trip、未知 subtype 明列 skipped、Markdown 摘要、另存 Flatten 副本；XFDF subset 待 interoperability fixtures。 |
| ANN-305 | 🟡 content mode 完成 | 文字浮水印改為真正向量文字，字號、旋轉、顏色、透明度有效且可搜尋；removable annotation mode 待補。 |
| ANN-306 | ⏳ 待實機設計 | Tablet pressure/palm rejection 尚未實作。 |
| ANN-307 | ⏳ 待架構實施 | Controller 抽取延後到 selection/undo API 穩定，避免在同批引入 God Class 大搬移風險。 |
- 影響 appearance 的變更需 save/reopen assertion；UI 變更需 offscreen test，視覺細節另做人工 QA。
- 任何 destructive operation（redact/flatten/sign）需另存/確認/undo policy 明確。
- 若修改 PyMuPDF workaround，必須加 1.26.6 regression fixture，並在升版 issue 中獨立驗證。

P0 階段完成定義：

- Split panes 均可建立 annotation，且 style/tool parity。
- Tool defaults 不互相污染。
- UI 顯示的 fill/opacity/width 在建立時真實生效。
- Undo/redo 不跳頁，annotation list 不過期。
- 新增的 regression tests 與原 233 tests 在 Python 3.12 全部通過。
