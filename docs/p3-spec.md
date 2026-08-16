# P3 詳細規格 — 註釋與內容編輯

> 隸屬：`docs/improvement-plan.md` 路線圖 P3（🅰 工作流）
> 狀態：規格草案 → 實作中
> 已鎖定決策：視覺註釋 + 遮蔽 + 圖章/簽名/圖片/浮水印；**不做** AcroForm 表單、**不做**直接改頁面文字。

---

## 0. 架構原則

1. **引擎純函式**：`core/annotations.py` 全部是 `(doc, page, ...)` 純函式，無 Qt 依賴，直接單元測試。
2. **UI 不碰文件簿記**：畫布只收集操作並發 `annotationRequested(AnnotationOp)` 訊號；viewer 統一負責 `_snapshot_before`（undo）→ 套用 → `engine.mark_modified()` → `canvas.refresh()`（重新渲染，`get_pixmap` 預設含註釋）→ `_sync_modified_state()`。
3. **座標映射沿用 P2**：`PageOverlay.widget_to_pdf` 已就緒；文字類工具（高亮/底線/刪除線/波浪線）用 `words_intersecting` 取字框做 quads。
4. **遮蔽必須確認**：遮蔽為不可逆（apply_redactions 移除底層內容），套用前彈確認對話框。

---

## 1. `core/annotations.py`（新）

### 1.1 資料模型
```python
@dataclass(frozen=True)
class AnnotationOp:
    kind: str          # highlight|underline|strikeout|squiggly|note|ink|rect|line|circle|polygon|redact|stamp|image
    page: int
    rects: tuple[fitz.Rect, ...] = ()
    points: tuple[tuple[float, float], ...] = ()
    text: str = ""
    color: tuple[float, float, float] = (1.0, 0.85, 0.1)
    width: float = 1.0
    stamp_kind: str = "Draft"
    image_path: str = ""
```

### 1.2 函式（全部回傳 None，直接改 doc）
| 函式 | 實作 |
|---|---|
| `add_highlight/underline/strikeout/squiggly(doc, page, rects, color)` | `page.add_*_annot(quads=_rects_to_quads(rects))`，`set_colors` 含 stroke/fill |
| `add_note(doc, page, point, text, icon="Note")` | `page.add_text_annot(point, text, icon=icon)` |
| `add_ink(doc, page, points, color, width)` | `page.add_ink_annot([list(points)])`，`set_border(width=width)` |
| `add_rect(doc, page, rect, color, width)` | `page.add_rect_annot(rect)` + border |
| `add_line(doc, page, p1, p2, color, width)` | `page.add_line_annot(p1, p2)` |
| `add_circle(doc, page, rect, color, width)` | `page.add_circle_annot(rect)` |
| `add_polygon(doc, page, points, color, width)` | `page.add_polygon_annot(points)` |
| `add_stamp(doc, page, rect, stamp_kind)` | `page.add_stamp_annot(rect, stamp=STAMP_IDS[stamp_kind])` |
| `redact(doc, page, rects)` | 每個 rect `add_redact_annot` → `page.apply_redactions()` |
| `insert_image(doc, page, rect, image_path)` | `page.insert_image(rect, filename=...)` |
| `add_watermark_text(doc, pages, text, fontsize=64, opacity=0.25, rotation=45, color)` | `page.insert_textbox(rect, text, ..., fill_opacity=opacity, rotate=rotation, overlay=True)`（以頁中心矩形） |
| `add_watermark_image(doc, pages, image_path, opacity=0.25)` | Pillow 先做透明（`Image.putalpha`）存暫存 → `page.insert_image(rect, overlay=True)` |
| `list_annotations(page) -> list[dict]` | `page.annots()` 轉 `{kind, rect, index}` |
| `remove_annotation(page, index)` | `page.delete_annot(page.annots()[index])` |
| `apply_annotation(doc, op)` | 依 `op.kind` 分派上表（viewer 的單一入口） |

- `STAMP_IDS`：14 種標準橡皮圖章（Draft/Approved/Final/Confidential/AsIs/…），零圖片資產。
- `_rects_to_quads(rects)`：`fitz.Quad(rect)` 列表。

---

## 2. `ui/pdf_canvas.py` 擴充（修改）

### 2.1 ToolMode 新增
`HIGHLIGHT / UNDERLINE / STRIKEOUT / NOTE / INK / RECT / REDACT / STAMP / SIGNATURE / IMAGE`。

### 2.2 新增訊號
```python
annotationRequested = pyqtSignal(object)   # AnnotationOp
noteRequested = pyqtSignal(int, object)    # (page, fitz.Point) — viewer 彈輸入框後再組 op
```
- HIGHLIGHT/UNDERLINE/STRIKEOUT/RECT/REDACT：框選（沿用 `PageOverlay` 橡皮筋，cursor=Cross）。
- NOTE：單擊 → `noteRequested`；游標 `PointingHand`。
- INK：按下拖曳收集點（覆蓋層即時畫折線預覽）→ 放開組 op。
- STAMP/SIGNATURE/IMAGE：拖曳矩形 → 組 op（STAMP 固定比例 1:0.35；SIGNATURE/IMAGE 自由比例）。

### 2.3 預覽
`PageOverlay` 新增 `set_preview(dict | None)`（`{"kind": "ink"|"rect", "points": ..., "rect": ..., "color": ...}`），paintEvent 疊畫。放開後清空。

### 2.4 事件路由修改
`eventFilter` 依 `ToolMode` 分支：既有 browse/hand/magnifier/select 行為不變；新工具把滑鼠事件轉給「作用中頁」的 overlay 處理（overlay 擴充：ink/rect 收集 + 預覽，既有 marquee 複用）。

---

## 3. `ui/context_panel.py`（修改）

### 3.1 新頁「annotate」（key="annotate"）
- **顏色**：6 個互斥色票按鈕（黃 #ffd54a、綠 #81c784、青 #4dd0e1、粉 #f48fb1、橘 #ffb74d、紅 #e57373），預設黃。
- **線寬**：`QSpinBox` 1–6（ink/rect/線）。
- **圖章**：`QComboBox`（14 種），`AdjustToContentsOnFirstShow`。
- **簽名/圖片來源**：唯讀 `PathLineEdit` + Browse（PNG/JPG）；未選時第一次使用會跳檔案對話框。
- **目前頁註釋管理**：`QListWidget` 列出本頁 `list_annotations`（類型 + 摘要），「Remove」按鈕刪除選取、「Refresh」更新；雙擊跳轉（未來）。
- 訊號：`annotationColorChanged(str)`、`annotationWidthChanged(int)`、`stampKindChanged(str)`、`imagePathChanged(str)`、`removeAnnotationRequested(int)`。
- 新增 `show_tool("annotate", ...)` 支援（既有 `show_tool` 泛用，僅需建頁）。

---

## 4. `ui/side_panel.py`（修改）

新區段 `("annotate", "Annotate", (...))`：
`highlight`（螢光筆）、`underline`、`strikeout`、`note`（便利貼）、`ink`（手繪）、`rect`（矩形）、`redact`（遮蔽）、`stamp`（圖章）、`signature`（簽名）、`image`（圖片）。
全部屬 `DOCUMENT_TOOLS`（無文件停用）。

---

## 5. `ui/icons.py`（修改）

新增：`highlighter`、`underline`、`strikethrough`、`message-square`、`pen-line`、`square`、`eraser`、`stamp`、`image`、`signature`（Lucide 風格路徑）。

---

## 6. `core/viewer.py`（修改）

- `_connect_signals`：`canvas.annotationRequested → _handle_annotation`、`noteRequested → _handle_note_request`；`context_panel` 各訊號 → 更新 `self._annot_*` 狀態。
- `_tool_requested` 新增映射：highlight…image → `_activate_annotation_tool(key)`：
  ```python
  self._set_canvas_tool(key)        # canvas tool mode
  self._show_context("annotate")    # 右側選項頁
  self.side_panel.set_active_tool(key)
  ```
- `_handle_annotation(op)`：`_snapshot_before(op.kind.title())` → `apply_annotation(doc, op)` → `engine.mark_modified()` → `canvas.refresh()` → `_sync_modified_state()`；REDACT 前 `QMessageBox` 確認（說明不可逆）。
- `_handle_note_request(page, point)`：`QInputDialog.getText` → 組 `AnnotationOp(kind="note", ...)` → `_handle_annotation`。
- 簽名/圖片首次使用：無圖片路徑 → `QFileDialog.getOpenFileName`。
- `_show_watermark_dialog()`：`WatermarkDialog` → `_run_task` 背景套用（大文件），on_result 提示；undo：浮水印套用前 `_snapshot_before`。
- `PdfEngine.mark_modified()`（新增公開方法）。
- 命令表新增：`annot_highlight/underline/strikeout/note/ink/rect/redact/stamp/signature/image/watermark`（document 啟用）。

---

## 7. `dialogs/annotation_dialogs.py`（新）

`WatermarkDialog(ToolDialog)`：
- 模式 radio：Text / Image
- Text：文字、字級（24–200）、不透明度滑桿（5–100%）、旋轉（0/45/90）
- Image：圖片選擇 + 不透明度
- 頁面範圍：All / Current / 自訂（沿用 parse_page_range 語法，由 viewer 解析）
- 回傳 `details` dict。

---

## 8. 樣式

- 色票按鈕 `QPushButton#swatchButton[checked="true"]` 邊框主色。
- 註釋列表沿用 `navList` 樣式。

---

## 9. 測試計畫

| 檔案 | 驗證 |
|---|---|
| `tests/test_annotations.py` | 合成頁上逐一呼叫：每種註釋後 `page.annots()` 數量+1 且型別正確；`redact` 後底層文字消失（`get_text` 不含）；`insert_image` 後 `page.get_images()` 非空；浮水印文字/圖片後內容存在；`list/remove_annotation` 往返 |
| `tests/test_p3_ui.py` | 工具模式切換 → `canvas.tool_mode`；模擬 `_handle_annotation`（highlight）→ 註釋數+1、`is_modified` True、undo 可還原；NOTE 流程（跳過 QInputDialog 直接組 op）；REDACT 走 `_handle_annotation` 前確認（monkeypatch QMessageBox.question → Yes）；ContextPanel annotate 頁訊號；命令表含新鍵 |
| 回歸 | 既有 64 支全綠、`audit_overflow.py` 乾淨、`verify_source.py` 通過 |

---

## 10. 驗收標準

1. 側欄 Annotate 區 10 工具；選取後右側出現選項頁、畫布游標改變。
2. 高亮/底線/刪除線框選文字 → 對應註釋按字框產生（非純矩形）；undo 可撤。
3. 便利貼點擊 → 輸入文字 → 出現圖示，點開可讀。
4. 手繪/矩形照顏色與線寬繪製。
5. 圖章拖曳產生標準橡皮圖章；簽名/圖片插入圖片。
6. 遮蔽：確認後文字永久移除且頁面顯示黑塊（refresh 後）。
7. 浮水印（文字/圖片、不透明度、頁面範圍）正確套用；undo 可撤。
8. 註釋管理列表可移除註釋。
9. 既有功能無回歸、全測試綠燈、溢位稽核乾淨。

---

## 11. 實作順序

1. `core/annotations.py` + `PdfEngine.mark_modified`
2. `ui/page_overlay.py` 預覽 + `ui/pdf_canvas.py` 工具模式與 op 收集
3. `ui/context_panel.py` annotate 頁 + `ui/side_panel.py` 區段 + `ui/icons.py`
4. `core/viewer.py` 接線 + `dialogs/annotation_dialogs.py` + 命令表
5. 樣式
6. 測試 2 支 + 全量回歸 + 稽核
7. 啟動驗證

*此規格為 P3 實作依據，開始編碼。*

---

## 12. 實作紀錄（2026-08-14，已完成）

### 規格偏差與實作決策
1. **浮水印改走 PIL 渲染**：`insert_textbox` 的 `rotate` 僅接受 90° 倍數，斜向浮水印改以 Pillow 渲染文字（含 alpha 不透明度）→ PNG → `insert_image`，支援任意旋轉與不透明度；系統字型以候選清單尋找。
2. **執行緒安全**（重大發現）：PyQt6 在**任何例外穿透 `QRunnable.run()` 時會 qFatal 中止整個程序**（SystemExit 等 BaseException 不受 `except Exception` 保護）。三個 worker（畫布渲染、縮圖、FunctionTask）全部改為捕 BaseException；另新增 `DOCUMENT_LOCK`（RLock）序列化 live 文件存取（渲染 vs save/close/註釋），`engine.close()` 亦納入鎖保護，並在關閉/重開文件前 `wait_for_renders()`。
3. **undo 快照改用記憶體序列化**：原 `_snapshot_before` 複製磁碟 temp 檔，無法捕捉未儲存的記憶體修改（多步 undo 內容失真）；改為 `engine.snapshot()` 序列化 live 文件，多步 undo/redo 現可精確還原每一狀態。
4. **PyMuPDF 弱引用陷阱**：`annot.set_colors/update` 需在建立它的 Page 物件存活期間呼叫（annot 對父頁是弱引用）；所有 `add_*` 在操作期間持有 page 參照。
5. **遮蔽（redact）確認**：套用前 QMessageBox 確認不可逆；遮蔽後文字永久移除。
6. **註釋管理**：ContextPanel「annotate」頁含 6 色票、線寬、14 種標準橡皮圖章、簽名/圖片來源、目前頁註釋列表（移除/重新整理）。

### 驗證結果
- `pytest`：75 passed（新增 11 支：test_annotations 6 + test_p3_ui 5），連續 10 次全綠（曾隨機中止，已根除）
- `ruff check`：All checks passed
- `scripts/audit_overflow.py`：No text overflow detected
- `scripts/verify_source.py`：passed
- 應用程式啟動無錯誤
