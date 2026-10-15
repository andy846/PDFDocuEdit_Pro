# PDFDocuEdit Pro v3.0.9 — Windows Managed update

本輪按擁有人指定，只發布 **Windows x64 帳戶版自動更新包**。不建立或上傳 Installer、Portable 或 macOS 產物。

## 更新內容

- **列印紙張與 Fit**：單次及批次共用紙張能力檢查；不支援、未知或回報不一致時要求確認輸出紙張，不靜默改為 A4。Fit 按列印開始後的有效可列印範圍計算，重用已渲染頁面，修正重複邊距。
- **批次列印**：保留原生設定視窗選定的橫直向；相同情況可在本批次共用確認，略過文件不再標作 Error。Actual Size、Custom Scale 及位移保持原意。
- **Deep Search**：首次開啟恢復緊湊版面，沿用 Pause / Resume。
- **安全關閉**：兩個模式共用狀態條，平常隱藏，等待超過三秒或失敗才顯示；Designer 冇分頁亦可看到原因、已用時間及待處理工作。清理前可返回工作，清理開始後只允許安全重試。
- **多視窗**：全部視窗先完成退出準備；子視窗重試會繼續整體退出，已關閉視窗的清理邊界仍保留。新增不含文件值或憑證的狀態診斷。

## 更新方式及限制

現有 Windows Managed 安裝使用 **Help → Check for Updates**。帳戶版及已知舊 Launcher 相容入口均保留，兩個更新 ZIP 具有相同程式內容。ZIP 不是可獨立啟動的 Portable；首次安裝沿用 [v3.0.7 Managed 安裝版](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.7)，再更新。

公司實體打印機／DFE 驗收仍待進行；模擬／PDF Output 通過不代表驅動程式一定如實回報紙張或實際紙匣。原始 Designer 鎖定事故的唯一觸發原因未確認，本版修補已重現的關閉路徑。

macOS 本輪沒有更新附件。舊 Mac 更新器查看 Windows-only latest 會提示缺少 Mac 更新包，已安裝程式仍可使用。不把舊 Mac 包標成新版本。

Windows 原生完整回歸、打包、frozen 啟動、簽章及更新結果見 [驗收紀錄](RELEASE_VALIDATION_3.0.9.md)。未執行的真實帳戶登入或硬件驗收保持 Pending，不以發布指示代填為通過。
