# PDFDocuEdit Pro v2.5.6

Advanced Page Organizer 升級及穩定性修正，Windows x64 Managed Portable 發佈。

## 新功能與修正

- 智慧選頁：頁碼範圍、Odd／Even、Every N、Last N、反向選取。
- Reverse、Duplicate、Insert／Replace、空白頁、Rotate、Crop、Extract、Split 及兩份 PDF 逐頁 Interleave，支援 Reverse B、B 先開始與補白。
- 所有編輯先放入 Organizer 預覽；計劃 Undo／Redo、Cancel 放棄，以及 Apply 後主文件一次 Undo／Redo。
- 分組工具列、符合紙張比例的縮圖、正確旋轉方向與毫米尺寸。
- 修正 Blank pages 按鈕導致退出、自訂尺寸與方向不同步。
- 純旋轉／裁切保留原始頁面物件與內容串流，修正條碼、QR Code、細字及標記異常；匯入／複製保留隱藏圖層狀態。
- 修正部分動作錯誤處理、取消匯入暫存檔、未改動 Apply 的 Undo、Split 無效檔名及輸出同名檔案競爭。

## 從 v2.5.5 測試自動更新

1. 完全關閉其他 PDFDocuEdit Pro，從原有 **v2.5.5 Managed Portable 的 Launcher.exe** 啟動。
2. **Help → Check for Updates → Download Update → Update and Restart**。
3. 按提示處理未儲存文件；重新啟動後確認版本為 **2.5.6**。
4. 測試 Advanced Page Organizer 的 Blank pages、Rotate、Apply 及 Undo，再從同一個 Launcher.exe 重開。

已有 Managed Portable 的使用者毋須重新解壓部署包。直接部署 v2.5.6 不能驗證這次 v2.5.5 → v2.5.6 的更新流程。錯誤紀錄位於部署資料夾 logs/updater.log。

## 下載附件

- **Managed-Portable-Windows-x64.zip**：首次部署；完整解壓到允許寫入及執行的位置，使用 Launcher.exe。
- **Update-Windows-x64.zip**：供內建更新功能下載的完整版本，毋須手動解壓到舊安裝目錄。
- **update.json／update.sig**：Ed25519 簽署更新清單，沿用 v2.5.5 信任金鑰。
- **.sha256**：各 ZIP 的校驗檔。

本次沒有 Setup 安裝包。既有 Setup／普通 Portable 需一次過渡到 Managed Portable。Installer 未來可以安裝相同的 Launcher 架構；目前 Setup 的目錄與捷徑尚未整合該機制。

## 驗證與範圍

Organizer 修正已通過完整 512 項 pytest、Ruff、來源檢查及 Windows frozen Qt 自動操作驗證，包含預覽／Apply／Extract 的圖層逐像素比較及主文件一次 Undo／Redo。發佈流程再次完成 512 項測試（320.30 秒）、依賴驗證及打包檢查。隔離測試使用真正的 v2.5.5／v2.5.6 執行檔，通過簽章驗證、解壓、啟動握手與版本切換；最後狀態為 current=2.5.6、previous=2.5.5、stable，測試設定保留。該測試以腳本送出重啟請求，並非公司電腦上的按鈕實測。

更新清單有簽章不等同 Windows Authenticode 發行者簽章。公司端 GitHub 網絡、應用程式執行政策，以及此次真正跨版本更新仍需在目標電腦驗收。Crop 只調整可見範圍，不能代替 Redact。
