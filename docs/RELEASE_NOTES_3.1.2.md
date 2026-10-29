# PDFDocuEdit Pro v3.1.2 — Windows update

本版只提供 **Windows x64 Managed 升級包**，保留帳戶版及舊 Windows Launcher
更新入口。現有 Managed 安裝使用 **Help → Check for Updates**。本輪不製作
Installer、Portable 或 macOS；首次安裝沿用既有完整安裝版。

## 本版更新

- **Extract Text Region 2.0**：每個命名選區對應一欄，多行文字維持同一儲存格。
  Raw／Clean 預覽、合併多行、欄位格式及空值／缺少文字層等問題均可檢查。
- **直向 A4 工作台**：PDF 使用左側全高度預覽；右側集中欄位屬性、分頁結果
  及操作。記住視窗、最大化、面板比例及側欄狀態，保留縮放／平移及橫向表格捲動。
- **選區辨識及編輯**：明確按 New region 後拖畫，Esc 取消；選框有編號名稱、
  目前欄位強調、重疊選單、邊界內複製偏移，保留 Undo／Redo 及毫米座標。
- **一步 Excel 匯出**：Extract & Export Excel 完整處理所選頁面，再選儲存位置；
  有效完整結果可重用。Try 10 pages 為可選試抽，即使試抽涵蓋全部頁面，也不會
  當作完整結果直接匯出。More 保留只抽取、CSV／TXT 及 Visual Workflow 交接。
- **資料及生命週期保護**：磁碟 SQLite 結果分頁；XLSX 保留文字型別、前導零及
  多行；匯出沿用來源保護、覆寫確認與原子發布。取消、關閉、失敗、來源或規則改變
  不會繼續過期的一步匯出；工作釋放後才清理本次暫存資源。

## 驗收及限制

- 擁有人已完成來源 `3b710c5` 的功能實測驗收；封裝後完整 Windows 回歸、
  frozen 啟動、連續升級及公開簽章／附件核對另按實際證據記錄。
- PyMuPDF 保持 **1.26.6**；不改 PDF 引擎、專案格式或生產批准規則；不新增
  Extract Text Profile、OCR 或雲端處理。圖片型 PDF 須先另行 OCR。
- 沒有新版 macOS 附件；舊 Mac updater 如只讀 latest，可能提示缺少更新。
  已安裝 Mac 程式仍可使用，本輪不聲稱 Mac 或實體打印設備已驗收。
- 新 frozen 候選真實帳戶登入未獨立測試時保留 Pending / Not Tested，不以來源
  功能驗收或先前版本結果代填。
- [操作說明](EXTRACT_TEXT_REGION.md)、[開發驗證](EXTRACT_TEXT_REGION_VALIDATION.md)、
  [本版發布驗收](RELEASE_VALIDATION_3.1.2.md)。
