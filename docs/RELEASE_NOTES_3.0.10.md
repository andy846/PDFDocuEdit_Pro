# PDFDocuEdit Pro v3.0.10 — Windows Managed update

按擁有人要求，本輪只提供 **Windows x64 升級更新包**，保留帳戶版及舊 Managed Launcher 更新入口。沒有新版 Installer、Portable 或 macOS 附件。

## 更新內容

- **Smart Mailpiece Detection**：以既有偵測引擎及同一 SQLite Page Index 評估多個文件類型規則，保留邊界證據、TemplateID、衝突及未知分類。每份新 PDF 仍須掃描、覆核及明確接受。
- **Detection Profile Library**：Save profile 與 Library 整合，支援單一規則及多類型集合、匯入／匯出、改名、複製及修訂。名稱檢查涵蓋大小寫、頭尾空格及全形字；既有同名項目保留並加上識別標示，不能靜默覆寫另一 Profile。
- **Customer Production Profile**：可重用偵測規則與按 TemplateID 套用的 Overlay 版面。EnvelopePlan、序號、條碼 payload、雙面補白、來源核對及正式生產批准沿用既有流程。
- **分件輸出與檔名**：PDF／PS 以完整信封為單位處理容量與封數限制；可自訂有序檔名，加入紙數、封數及 Duplex `D`／Simplex `S`。成對 PDF／PS、清單與核對報告保持對應。預設 PDF 250 MB／PS 500 MB，系統每檔 2,000 MB 上限仍適用；單封超限會中止工作。
- **PostScript 速度與狀態**：轉換前的臨時 PDF 無損去重及取消檔檢查限頻，保留解析度、選紙及完整驗證。實際加速幅度依文件內容而定。
- **Editor 開啟 PS**：加入已驗證的轉換快取；來源或轉換設定改變時失效。顯示階段、已用時間及取消，分別記錄轉換與 PDF 開啟耗時。
- **Production 版面**：緊湊控制台及唯讀 Review dashboard，清楚分開預計／實際數量、覆核／批准／生成／發布、規劃條碼檢查與最終解碼覆蓋；缺失或部分結果不標作完整成功。
- **操作修補**：Command Palette 執行前重新驗證精確指令與當前可用狀態；修正旋轉後擦膠及同類編輯工具的選取範圍、Designer 頁面操作，以及 Windows 外部開啟 `.pdcx`／`.pdflow` 的 Designer 路由。

## 相容性及驗收限制

舊 `.pdmp` 及既有專案仍可讀取。新集合使用 `.pdmpx`，Customer Production Profile 使用 `.pdpp`；新增分類／類型 Overlay 功能使用 overlay v9，這類新專案不能用舊版程式開啟。Profile 儲存辨識規則，不儲存上一份 PDF 的已接受邊界；開啟 Profile 不代表授權生產。

條碼軟件解碼不等於實體插封機相容性。公司打印機／RIP／插封機、新設備容量限制及實際客戶工作仍須現場驗收。舊式單規則偵測行為維持相容；無警告並不保證每個信封都正確。

現有 Windows Managed 安裝使用 **Help → Check for Updates**。兩個 Windows 更新 ZIP 是相同程式內容，並非獨立 Portable。首次安裝可沿用 [v3.0.7 Managed 安裝版](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.7)，再更新。

macOS 本輪不製作附件。舊 Mac 更新器查詢 Windows-only latest 可能提示缺少 Mac 更新附件，已安裝程式可繼續使用。macOS、Apple 公證及實體設備未測項目不標作通過。

原生回歸、候選、簽署及實機驗收狀態見 [v3.0.10 驗收記錄](RELEASE_VALIDATION_3.0.10.md)。尚未執行項目維持 Pending；開發測試不代替本候選原生發布驗收。
