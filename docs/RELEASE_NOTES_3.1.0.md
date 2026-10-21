# PDFDocuEdit Pro v3.1.0 — Windows update

本版依擁有人要求只發布 **Windows x64 Managed 升級包**，保留帳戶版及舊 Launcher
更新入口。Installer、Portable 和 macOS 本輪沒有重新製作。現有 Managed 安裝請用
**Help → Check for Updates**；首次安裝使用 GitHub 已有完整安裝版。

## 本版修補

- **關閉後重開 PDF**：Apply／Discard 及未保存提示以實際關閉階段協調，
  外部開檔請求等安全退休後交給有效的新 Viewer，避免隱藏的舊視窗接收文件。
  這修補已重現的生命週期缺陷，不代表所有歷史空白 Tab 都只有同一原因。
- **暫存 PDF 清理**：文件安全退休時清除它擁有的 Undo／Redo 暫存副本；
  使用中讀取器及取消關閉保持受保護。不清掃其他程式或過往無法歸屬的暫存檔。
- **文字水印完整性**：逐字檢查實際 glyph coverage、依序嘗試既有及附帶字型，
  在修改頁面前核對獨立水印 PDF 的輸出文字。缺字、錯誤字碼及不支援成形會明確拒絕。
- **精確透明度**：文字／圖片支援 0–100%；編輯其他屬性、原位按放滑塊時，
  保留原有小數透明度。真正調整後才採用所選百分比。
- **主線及驗收文件**：同步現有開發歷史到 main，版本統一為 3.1.0；
  已凍結 tag 保留當時文件，完成證據及後續使用者驗收由 main 上版本驗收文件承載。

既有 Smart Mailpiece Detection／Profile、分件與命名、Production Review、
PostScript 快取及輸出、旋轉編輯和圖片／印章功能隨最新開發線保留。

## 相容性及限制

- 不加入新 PDF 引擎、字形成形引擎或第三方依賴，不改更新信任金鑰或生產批准規則。
- 文字水印本輪不支援 RTL、組合標記、ZWJ、控制字元及需要成形的 Hangul Jamo；
  部分 emoji 亦無可靠字型。會顯示相關 Unicode 碼，不能靜默刪字或替換。
- 既有 overlay v9 等專案相容性要求維持不變；新版專案不可假設舊版均可讀取。
- 本版沒有 Mac 附件；舊 Mac updater 若只查 latest，可能提示缺少 Mac 更新，
  已安裝程式仍可使用。macOS 本輪不聲稱驗收通過。
- 正式候選及實際驗收見 [v3.1.0 驗收紀錄](RELEASE_VALIDATION_3.1.0.md)。
  v3.0.11 的登入、客戶工作及設備驗收不自動代填為本候選通過。
