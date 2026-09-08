## PDFDocuEdit Pro V2.5.4

V2.5.4 改善 PDF 修改、Undo／Redo、遮蓋儲存及背景列印的可靠性，並包含先前修復計劃中的架構改善。

### PDF 修改與 Undo／Redo

- 頁面旋轉、插入、刪除、重排及整理使用共同交易邊界；成功後只建立一筆 undo，失敗會回復文件。
- 註解新增、刪除、移動、文字及屬性修改、批次匯入，以及多頁浮水印和套用遮蓋均接入交易。
- Undo／Redo 先準備還原文件，成功後才移動歷史；快照寫入、開啟或顯示失敗時保留目前文件與歷史。
- 套用遮蓋後儲存會完整重寫並移除未引用的舊內容物件，涵蓋加密文件、重複儲存及 undo／redo 後再儲存。
- PDF 儲存、頁面擷取及註解輸出使用共用原子輸出流程，驗證完成後才替換目的檔。

### 列印及其他改善

- 單一及批次列印支援背景頁面準備／渲染、進度及合作式取消；失敗後回復 UI 狀態。
- 修正插入頁面的順序、重複頁選擇及部分失敗回復。
- 統一繁中／英文 OCR 語言設定與 veraPDF 偵測。
- 改善 Windows 檔案關聯查找／移除及設定預設值處理。
- 建置及測試統一使用 Python 3.12，逐步抽出修改／歷史協調層。

### 驗證

- Windows Python 3.12.14：389 個測試通過，涵蓋 35 個模組。
- Source verification、Ruff 及依賴一致性檢查：通過。
- Windows PyInstaller clean build、Inno Setup 編譯：通過。
- 封裝 Tesseract 及產品實際使用的 veraPDF／私人 JRE 啟動路徑：通過。
- EXE 啟動／單實例轉交：通過；Setup／Portable 版本及 SHA-256：核對一致。

### Windows x64 下載

- PDFDocuEdit-Pro-v2.5.4-Setup-Windows-x64.exe
- PDFDocuEdit-Pro-v2.5.4-Portable-Windows-x64.zip

下載後可使用同名 .sha256 檔核對完整性。

列印取消需等候進行中的渲染或驅動程式呼叫返回；已送到打印機的頁面未必能撤回。大型 PDF 的初始快照仍可能短暫阻塞介面。Undo 歷史只在目前工作階段有效。實體打印機及 macOS 安裝版未在本輪本機驗收中測試。
