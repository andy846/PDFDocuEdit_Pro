# Document Designer — Excel 匯入

## 操作

**Data → Import data…** 或左侧 **Import CSV / TXT / Excel…** 可選 .xlsx / .xls。
選擇 Worksheet，指定 Header / start row，確認 Header 是否有欄位名稱，再修改 Variable name 映射。
Sample records 顯示實際轉換後值；重名／無效變數名稱會停用 Import data，修正後才能繼續。

一次匯入一個工作表，匯入後建立 SQLite snapshot。可將欄位拖到版面，照常使用文字、Barcode / QR、規則、流水號、Preview 及 Generate PDF。
修改 Excel 來源後須重新匯入；儲存專案會保留檔案引用、工作表、標題列、映射、公式及補零設定。
原 Excel 檔案只讀，不會寫回，也不會改变模板物件原有字型／補字。

## 值的處理

| Excel 值 | 匯入文字 |
|---|---|
| 文字 `000123` | `000123`，不去除前置零 |
| 數字 123，格式 `000000` | 預設 `000123`；可取消 Preserve simple leading-zero number formats |
| 數值／金額 10000.25 | `10000.25`，不加入千分位／貨幣符號 |
| 日期 | ISO `2026-10-02` |
| 時間／帶時間日期 | ISO `09:30:00`／`2026-10-02 09:30:00` |
| Boolean | `TRUE` / `FALSE` |
| 空欄位 | 空字串 |
| 完全空白列 | 略過，完成訊息及 metadata 列出數量 |

數字位數／自訂格式不是完整 Excel 顯示格式引擎。只支持單一 `0` 掩碼（1–32 位）補零；貨幣、百分比、分組、自訂分段、特殊帳號遮罩不会被复制。
帳號等識別碼若需要固定文字，建議原 Excel 儲存為 Text；已被 Excel 捨棄的前置零或精度不能復原。
文字樣式、顏色、字型、合併儲存格的排版不會轉成模板版面。合併資料列若造成欄位缺失，須先整理成表格式資料。

完整 Excel 表頭需非空且唯一。中文原欄位名稱保留，Variable name 使用字母、數字及底線；不同中文名稱可能正規化成相同名稱，請於映射表修正。資料若超出表頭所定義的欄數，会明确報錯，沒有截掉資料。

## 公式

.xlsx 預設拒絕公式。可勾選 **Use saved formula results (no recalculation)** 使用工作簿已儲存的結果。
**程式不計算公式、不啟動 Excel、不執行巨集或外部程式。**

沒有 saved result 或包含 Excel error（例如 #DIV/0!）會指出工作表／儲存格，匯入失敗並清理不完整 snapshot。
請在 Excel 計算並保存後重新匯入，或把公式轉成值；也可另存 CSV。
快取結果是否仍正確無法由匯入器確認，UI 及 production job warnings 會記錄這個限制；即使有快取也不会宣稱已重算。
空白公式結果無法可靠區分缺少快取時會拒絕，請轉為明確值。

舊式 .xls 使用 saved cell values。讀取套件不能完整辨別公式身份／缺失快取／新鮮度，所以首次建議設定是使用 saved values，並顯示較強的限制訊息。若要嚴格辨認公式，請另存 .xlsx。
不支援 .xlsm / .xlsb、密碼加密工作簿、跨工作表合併、Excel Table / named-range 選取或多來源 join。

## 來源及報告

Snapshot metadata 保存來源 SHA256、工作表、完整匯入配置、空白列數及實體列號（records.source_row）。
Job log 加入 import_configuration，Excel record identity 包含工作表及匯入配置；control.csv 增加 Source Worksheet。
固定頁數、PDF 驗證、對帳、取消及不發布半成品的流程不變；Excel 公式警告也會傳入生產摘要。

## 模板相容及回退

本次使用 **schema 6**，可讀 schema 1–5（含上一版流水號設定）。新增 DataConfig.sheet / excel_formulas / preserve_zeros。
舊版不能讀 schema 6。首次升级請 **Save as…** 保留原模板及 assets 資料夾。
公共版本仍為 2.5.15，本次为測試版；原穩定 checkout 未修改。
程式回退標籤：`document-designer-sequences-dev-20261001`。

## 工程設計

新增 `composition/data/excel_source.py` 適配器；.xlsx 使用現有 openpyxl read_only，.xls 使用現有 xlrd on_demand。
CSV / TXT / Excel 共用 source_rows / field_names / sample_records / SQLite snapshot；Designer 只透過既有 subprocess worker 查工作表、讀樣本及匯入。
沒有新增套件、沒有 Excel COM、自訂 eval 或 viewer.py 改動。既有 PyInstaller hiddenimports 已包含 openpyxl / xlrd。

read_only 支持逐列解析，但 shared strings／styles 仍可能佔用與檔案內容相關的記憶體；.xls 選定工作表由 xlrd 載入記憶體。**不是所有 Excel 檔案都保證定量記憶體**。
上限仍為 1,000 欄、每筆文字 1,000,000 字元；多餘欄位及不完整 snapshot 不会默默忽略。
讀完後會再次確認來源 size / mtime / SHA256 時的一致性，取消／失敗／換工作表會釋放 reader。

## 測試與交付

新增 32 個案例涵蓋 XLSX、實際 OLE/BIFF8 XLS、中文、日期（含午夜）、補零、Boolean、空白列、無標題、欄位映射、公式拒絕／快取／錯誤、來源列號、取消清理、schema 5 遷移、CSV 控制字元、1,000 筆 snapshot 及真實 UI → Preview → PDF → 保存重開。

Windows native/frozen/installed smoke 覆蓋原有 CSV/字型/背景/規則/流水號流程，另驗證 Excel 工作表／標題列／映射、100 筆 XLSX＋流水號＋QR/Code128 解碼、100 筆 XLS 生成及工作表設定重開。
完整結果见 validation/document_designer_excel_20261002.json；匯入原始量測見 validation/document_designer_excel_benchmark_20261002.json。
合成／offscreen 驗收没有代替客戶實際工作簿或印表機驗收。
