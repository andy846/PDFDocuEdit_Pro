# PDFDocuEdit Pro v3.1.3 — Windows update

## 更新內容

- 選單、子選單、下拉框及標準 Tooltip 改用平滑的 14px 圓角，主體保持實色，減少白色文件背景上可見的鋸齒。
- 修正首次彈窗的透明邊緣設定、可編輯下拉框背景與 Tooltip 重用狀態，保留既有鍵盤操作及安全關閉。
- 修正彈窗事件監聽器的物件生命週期，避免隱藏視窗在程式退出時觸發原生錯誤。
- 加強主題切換穩定性，避免樣式更新期間舊視窗被過早回收。
- Extract Text Region 成功匯出後，進度更新至完整 N/N；取消、失敗或來源變動不會誤報完成。

## 範圍與更新

僅提供 Windows x64 Managed 升級包，保留帳戶版及舊 Launcher 相容更新入口。
已安裝使用者可在 Help → Check for Updates 更新。本輪沒有 Installer、Portable 或 macOS 包。
Windows-only latest 可能令舊版 Mac 更新檢查提示缺少附件；已安裝 Mac 程式仍可使用。

PyMuPDF 保持 1.26.6。實際跨螢幕、macOS、打印機、RIP 及插封機未作本候選驗收。
擁有人已批准直接公開，封裝候選的真實帳戶登入另於更新後自行測試，保持 Pending。

[開發驗證](POPUP_SMOOTH_EDGES_VALIDATION.md)；[本版發布驗收](RELEASE_VALIDATION_3.1.3.md)。
