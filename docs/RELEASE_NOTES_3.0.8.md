# PDFDocuEdit Pro v3.0.8 — Windows Managed update

本輪按擁有人指定，只提供 **Windows x64 帳戶版更新**。沒有新 Installer、Portable 或 macOS 安裝／更新包。

## 更新內容

- Deep Search：背景搜尋的 UI 回應改善；加入 cooperative Pause / Resume，保留已完成結果。
- Template Designer：Design 集中 Paper / Tray、Simplex / Duplex；Barcode / QR 明確選擇 Direct Content 或 Barcode Logic，保留動態欄位。
- Production Review：Blocked 直接顯示原因；未完成的條碼檢查不再顯示成已核實零個。
- Visual Workflow：新 Media Assignment 預設沿用模板／Overlay，明確選 Workflow override 才覆寫；區分邏輯頁、實體頁及補白。
- Workflow 覆核：資料接受與正式生產批准分開；來源或未保存模板變動後要求重新檢查；Issues 返回有效設定來源。
- 旋轉物件：X / Y 對應可見外框，90° 條碼可移至頁邊；保留已有模板位置、保存重開及 Undo / Redo。
- PostScript：固定顯示轉換、選紙、回讀驗證階段和已用時間；只在有可靠頁碼時顯示數值進度。新增心跳、長時間沒有頁數回報的提示及轉換／驗證耗時報告。

## 升級

現有 Windows Managed 版使用 **Help → Check for Updates**。同時保留帳戶版及已知舊 Launcher 的簽章相容入口；兩份 ZIP 內容相同。更新公鑰、帳戶項目及專案格式保持不變。

此 Release 的 ZIP 是更新內容，不是可獨立啟動的 Portable。首次安裝仍下載 v3.0.7 Managed 安裝版，之後更新；未知 Launcher 仍可能需要先安裝已支援的 Managed 版。

## macOS / 其他產物

macOS、Installer 和 Managed Portable 本輪沒有重建，上一版 v3.0.7 附件保留。
舊 macOS 更新器只讀 GitHub latest Release；本 Windows-only Release 缺少 Mac 附件時，會提示沒有有效 Mac 更新包。現有 Mac 程式仍可使用；後續雙平台版本恢復相應更新附件。

## 驗證與限制

Windows 完整隔離回歸、原生打包、frozen login-ready、未登入 worker 拒絕、簽章與更新 smoke 結果記錄於 [驗收紀錄](RELEASE_VALIDATION_3.0.8.md)，未完成項目明確保留 Pending。

PS 進度修正不代表已解決原客戶文件轉換耗時：先前 Ghostscript 有 CPU / I/O 活動，但沒有頁數證據，不能保證持續前進或估計完成時間。沒有降低解析度、略過 PS 驗證或改動選紙指令。實際 printer / inserter、Mac 本版及尚未確認的真實帳戶測試不宣稱已驗收。
