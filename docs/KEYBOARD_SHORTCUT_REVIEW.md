# Keyboard Shortcuts Review

此更新基於 v3.0.2 開發版本，不變更公開版本或專案格式。

## 常用操作（Windows 預設）

| 操作 | 快捷鍵 | 作用位置 |
| --- | --- | --- |
| Open / Save / Save as / Close | Ctrl+O / Ctrl+S / Ctrl+Shift+S / Ctrl+W | 目前文件或專案；Merge 分頁作用於 merge list |
| Undo / Redo | Ctrl+Z / Ctrl+Y 或 Ctrl+Shift+Z | 目前工作區；文字欄位優先使用自己的編輯歷史 |
| 下一個／上一個分頁 | Ctrl+Tab / Ctrl+Shift+Tab | PDF 文件或 Designer 專案分頁 |
| 命令面板 | Ctrl+K | 目前模式與專案 |
| 快捷鍵說明 | Ctrl+/ | Help → Keyboard Shortcuts |
| 複製／貼上／全選／Delete | Ctrl+C / Ctrl+V / Ctrl+A / Delete | 隨焦點作用於文字欄位或支援這些操作的畫布 |

## 修正及使用原則

- 還原 PDF 初始化時遺失的 Ctrl+Shift+Z Redo，並統一 Designer、Overlay、Workflow、Merge 的 Windows Redo 綁定。
- Designer 分頁切換保留內容與 Undo；隱藏模式和非目前專案不持有啟用的快捷鍵。
- PDF 輸入文字時，Save、Open、命令面板及應用程式命令可執行；頁面刪除、旋轉等工具快捷鍵不搶文字編輯操作。
- Organizer／Form／Compare 的自訂鍵只在相應工具範圍內作用，不會因此清除 PDF Workspace 的同名預設按鍵。
- 衝突檢查包含連續按鍵的前綴及 Redo 的第二個綁定；同一有效範圍不接受含糊綁定。
- 自訂全域鍵若與 Designer／Merge 預設鍵相撞，全域自訂鍵優先，衝突的工作區鍵停用；相應操作仍可由選單執行。快捷鍵說明顯示實際結果，恢復預設後工作區鍵可恢復。
- 快捷鍵說明是唯讀參考，可搜尋名稱、區段及其他綁定；Not assigned 表示沒有鍵盤綁定。
- 主工具列及側欄提示跟隨目前按鍵設定，不固定顯示 Ctrl+O／Ctrl+S 等旧文字。

## 自訂設定範圍

Preferences → Keyboard shortcuts 沿用目前 PDF Workspace、應用程式命令及 Organizer／Form／Compare 的自訂機制。此次未新增 Designer、Workflow 或 Merge 專案命令的獨立自訂介面；這些專案保留預設按鍵及模式隔離。

## 驗證

針對性測試涵蓋原生文字編輯、Save／命令面板、模式切換、專案分頁、Redo、客製設定保存／恢復、跨範圍重用、前綴衝突、全域鍵與 Designer／Merge 衝突及命令參考列表。未執行完整回歸或打包。
