# PostScript 選紙輸出與 Printer Profile

## 開啟

- 一般 Document Designer：`Page → Print Media / Stocks…`。
- PDF Overlay：`Production → Print Media / Stocks…`。
- Visual Workflow：選取 `Media Assignment` 節點，再開啟 `Configure step`。

勾選 `Enable Media Assignment and selected production output`。在 **Printer profile** 選擇 `PDF + PostScript (no separate job ticket)`。

## 設定三頁信件

1. **Stocks**：定義 LH_A、LH_B、LH_C 的紙張尺寸及名稱。
2. **Page rules**：按模板頁面或 Logical page 指定第 1 頁 → LH_A、第 2 頁 → LH_B、第 3 頁 → LH_C。規則會在每封信重複，不用逐張輸出頁設定。
3. **Printer profile**：輸入 profile 名稱及控制器備註；選擇紙張選取方式。
   - **Paper attributes**：每個 Stock 設定實際 `MediaType`，可加 `MediaColor`。需要按重量配對時才勾選重量選項。這些是 PostScript 屬性，不會自動將 DFE 的 Paper Catalog 名稱轉成可用指令。
   - **Paper source position**：每個 Stock 指定控制器使用的 `MediaPosition`。0 是有效數值；此數值可能與機身顯示的 Tray 1／2 不同。
4. **Save printer profile…**：保存設備對應表；另一個環境可載入或另存自己的對應表。**Save media profile…** 同時保存 Stock、頁面規則及設備設定。
5. **Media preview → Export paper-selection test PS…**：每種 Stock 產生一張測試紙，不含客戶資料。先列印此小檔，確認紙種／纸匣與雙面方向。
6. **Check & Preview**：檢查實際頁數、正背面、空白背頁及各 Stock 所需張數，再按 OK。
7. 正常執行 **Generate Production PDF**；所選 profile 會額外產生同名 `.ps`。

首次使用 PS 時預設設備類別為 Generic PostScript 3。Canon、Xerox 等類別是 profile 的識別資料，沒有內置未驗證的機型紙匣編號。換設備時需更新對應表。

## Profile library

Print Media 對話框頂部的 **Profile library…** 可集中查看本機保存的設定，按設備（6300 / 6000、i300、iX 等）及 profile 類型篩選。

- **Import profiles…**：匯入一個或多個 profile JSON。
- **Import folder…**：連同子資料夾匯入，最多一次 100 份；解壓 profile 套件後可直接選其資料夾。
- **Complete media setup**：包含紙種、頁面規則、雙面及 printer 對應表。
- **Printer mappings only**：只換設備對應表，保留目前紙種及頁面規則；Stock ID 須吻合。

選取後先查看右側設定摘要，再按 **Use selected profile**。設定載入為草稿；檢查 Page rules，輸出小量選紙測試，最後執行 Check & Preview。取消選擇保留現有草稿。模板頁面 ID 不吻合的設定會阻止載入；跨模板重用宜採用 Logical page 或 Page role 規則。

Logical page 規則在每封信／每筆 record 內重複，並不是整個 PDF 的絕對頁碼。原本按全檔頁碼指定的選紙樣本，必須按實際信件結構覆核後才能生產。

Profile 匯入與清單讀取在背景執行，重複設定不重複建立。無效檔案會列出錯誤；取消匯入保留已完成項目。設定保存在本機應用程式設定目錄的 `composition/media_profiles`，不包含來源 PDF 或客戶資料，也不隨軟件發布。內置程式只提供通用設定能力，不宣稱某設備已通過實機驗收。

## 雙面

在 **Page rules** 勾選 Duplex。正背面使用同一張實體紙，不能要求不同 Stock。可選擇阻止衝突，或在 Stock 改變時插入空白背頁；空白背頁會改變輸出頁數及相關頁碼／barcode，套用前會要求確認。

選纸指令寫在每張實體紙的正面，背面繼承同一 Stock。**Printer profile** 的 Tumble 控制短邊翻轉，長邊翻轉時不要勾選。

## 產物

成功工作目錄包含：

- 生產 `.ps` 與可供核對的 `.pdf`；PS 模式不產生獨立 JDF。
- `postscript-pages.csv`：逐頁 Stock、正背面及實際選紙指令參數。
- `postscript-report.json`：PS 大小、SHA256、軟件驗證結果。
- 原有 `media-plan.csv`、Stock 張數報告、`job.json` 與 Control report。
- `SUBMISSION.txt`：列印與核對說明。

Workflow 分檔後，每個套件各自產生 PS、PDF 及選紙對照；File page 由 1 開始，保留全局頁碼及流水號。

程式會將 PS 重新解譯，確認頁數及頁面尺寸後才發布。取消或失敗不會發布半成品。生產摘要列出 PS 路徑；使用 Open reports 可查看工作目錄。

## 實機驗收範圍

通用 PS 3 指令可由 profile 配置；最終取紙仍由打印機／DFE 的支援及佇列設定決定。DFE 的強制紙種、雙面、拼版設定可能覆蓋檔案指令。所有 profile 保持 **Device validation: Pending**，不因軟件驗證通過就聲稱實機已通過。

PS 不支援 PDF 的原生透明效果，轉換可能平面化；設定提供 300／600／1200 dpi，預設 600。保留 PDF 用作核對。收到實際 printer 樣本後，先確認 MediaType／MediaPosition 的值，再做小量紙張測試。
