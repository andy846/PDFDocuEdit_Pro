# P5 詳細規格 — 收尾：縮圖拖曳排序、最近檔案預覽、效能調校

> 隸屬：`docs/improvement-plan.md` 路線圖 P5（最後階段）
> 狀態：規格草案 → 實作中

---

## 1. 縮圖拖曳排序

### 1.1 `ui/thumbnail_panel.py`（修改）
- `_list` 啟用內部拖曳：`setDragDropMode(InternalMove)`、`setDefaultDropAction(MoveAction)`、`setSelectionMode(SingleSelection)`、`setDragEnabled(True)`。
- 新訊號 `reorderRequested = pyqtSignal(list)`（新的頁序，0 基底）。
- 拖放完成（`model().rowsMoved`）→ 依每列 `UserRole` 的頁碼組出新順序 → emit。QListWidget 內部移動會自動更新顯示順序；為避免拖放中與畫布同步打架，拖放期間 `currentRowChanged` 的跳頁仍照舊（依 row 即頁碼——拖放後 row 與頁碼不再一致，故 rowsMoved 後強制重建列表）。

### 1.2 `core/viewer.py`（修改）
- `_wire_session` 新增：`nav.thumbnails.reorderRequested.connect(lambda order, s=session: self._handle_thumbnail_reorder(s, order))`。
- `_handle_thumbnail_reorder(session, order)`：
  ```python
  self._session = session
  if order == list(range(session.engine.page_count)): 重新載入縮圖後 return
  self._snapshot_before("Reorder Pages")
  session.engine.reorder_pages(order)
  session.engine.mark_modified()          # reorder_pages 已標記；保險
  session.canvas.refresh()
  self._reload_thumbnails(session)        # 重建縮圖（頁序已變）
  self._after_page_count_change()
  ```
- 已知限制（記錄於 spec）：書籤/大綱的頁碼在重排後不再指向原內容頁（書籤以索引存），本階段不做重映射。

### 1.3 命令表/選單
- 既有「Organize pages」視覺化工具已涵蓋；拖曳排序為快速操作，不新增命令。

## 2. 最近檔案縮圖預覽

### 2.1 `ui/workspace.py`（修改，EmptyState）
- 最近清單項目改為「縮圖圖示 + 檔名」：`QListWidgetItem`，`setIcon` 以背景渲染的首頁縮圖（約 36×50），預設以 file-text 圖示。
- 新 QRunnable `RecentThumbTask(path, scale)`：`fitz.open` → page 0 → `get_pixmap` → QImage → QPixmap → `finished(path, pixmap)` 訊號；捕 BaseException（沿用 P3 教訓）。
- `EmptyState.set_recent_files(paths)`：清空後逐項建 item + 排程任務；完成時**驗證 item 的 UserRole 仍等於該 path**（清單已重設則丟棄，防過期結果錯位）；以 QThreadPool.globalInstance() 執行。
- 檔案打不開/非 PDF → 保持預設圖示。

## 3. 效能調校

### 3.1 畫布 Ctrl+滾輪縮放合併（`ui/pdf_canvas.py`）
- `wheelEvent` Ctrl 分支改為 `_queue_zoom(target)`：記錄目標縮放，70ms 單發 `QTimer` 到期才 `set_zoom(target)`；連續滾輪刻度在窗口內合併成一次重建。
- 直接呼叫 `zoom_in/out/set_zoom/fit_*` 仍立即生效（非合併）。

### 3.2 連續捲動 sync 合併
- 非 Ctrl 滾輪後不再每次即時 `_sync_views()+_update_current_from_scroll()`，改 60ms 單發計時器合併（`_schedule_scroll_sync`）。scrollbar `valueChanged` 亦接同一排程（拖動捲軸也合併）。
- `_update_current_from_scroll` 延遲 ≤60ms，頁碼指示幾乎無感。

### 3.3 基準測試
- `scripts/benchmark_canvas.py`（新）：建立 N=300 頁文件 → 連續模式 → 量測「捲動 20 次後同步完成時間」與「10 次縮放合併後時間」；作為回歸參考（不進 pytest）。

## 4. 檔案變更
| 檔案 | 動作 |
|---|---|
| `ui/thumbnail_panel.py` | 拖曳排序 + reorderRequested |
| `core/viewer.py` | `_handle_thumbnail_reorder` + 接線 |
| `ui/workspace.py` | EmptyState 最近檔案縮圖任務 |
| `ui/pdf_canvas.py` | 縮放合併 + 捲動 sync 合併 |
| `scripts/benchmark_canvas.py` | 新增基準 |
| `tests/test_p5_ui.py` | 新增 |
| `docs/p5-spec.md` | 本文件 |

## 5. 測試計畫
| 測試 | 驗證 |
|---|---|
| `test_thumbnail_reorder_flow` | 直接呼叫 `_handle_thumbnail_reorder(session, [2,0,1])` → 引擎頁序改變、undo 還原、縮圖列表重建、目前頁同步 |
| `test_recent_thumbnail_task` | 建 3 檔 → `set_recent_files` → 等待 → item icon 非空；過期 path 更換後舊結果不套用 |
| `test_zoom_coalescing` | 連續 5 次 `_queue_zoom` → 只觸發一次 `set_zoom`（monkeypatch canvas.set_zoom 計數 + 手動觸發 timer） |
| 回歸 | 既有 81 支全綠、`audit_overflow.py`、`verify_source.py`、`benchmark_canvas.py` 可跑完 |

## 6. 驗收標準
1. 縮圖面板拖曳換序 → 頁面實際重排、undo 可撤、縮圖/畫布刷新。
2. 最近檔案清單顯示首頁縮圖，失效檔案顯示預設圖示。
3. 快速滾輪縮放不再卡頓（合併後單次重建）；連續捲動流暢。
4. 全測試綠燈、稽核乾淨、基準可執行、啟動正常。

## 7. 實作順序
1. 縮圖拖曳排序（panel + viewer）
2. 最近檔案縮圖（EmptyState）
3. 效能合併（canvas）
4. benchmark + 測試 + 全量回歸
5. 稽核 + 啟動驗證

*此規格為 P5 實作依據，開始編碼。*

---

## 8. 實作紀錄（2026-08-14，已完成）

### 規格偏差與實作決策
1. **拖曳排序實作**：以 `ReorderListWidget`（QListWidget 子類）覆寫 `dropEvent`，拖放完成後依 `UserRole` 頁碼讀出最終順序 emit `orderDropped` → panel 轉發 `reorderRequested`；viewer 走快照 → `engine.reorder_pages` → 畫布 refresh → 縮圖重建（`_reload_thumbnails`）。無效順序（重複/缺頁）不套用僅重建列表。
2. **最近檔案縮圖**：`_RecentThumbTask`（QRunnable，捕 BaseException）背景渲染首頁 0.08×；完成時以 path 對照目前清單（`_recent_items` + `row(item)`）丟棄過期結果；主題刷新不覆蓋已完成縮圖（`_thumb_done`）。
3. **效能合併**：Ctrl+滾輪縮放改 `_queue_zoom`（70ms 單發計時器合併，最後目標勝出）；連續捲動 sync 改 `_schedule_scroll_sync`（60ms），scrollbar `valueChanged` 同排程。直接呼叫 `set_zoom/zoom_in/out` 仍立即生效。
4. **基準**：`scripts/benchmark_canvas.py`，300 頁：20 次捲動+sync 24.5ms、10 次縮放合併 25.1ms。

### 驗證結果
- `pytest`：85 passed（新增 4 支 test_p5_ui），連續 5 次全綠
- `ruff check`：All checks passed
- `scripts/audit_overflow.py`：No text overflow detected
- `scripts/verify_source.py`：passed
- `scripts/benchmark_canvas.py`：可執行、數值合理
- 應用程式啟動無錯誤
