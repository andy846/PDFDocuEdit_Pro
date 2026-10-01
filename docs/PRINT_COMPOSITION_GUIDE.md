# Document Designer 操作與開發手冊

更新日期：2026-10-01。這是可試用的 v3.0 MVP 開發版本，正式產品版本資料仍為 2.5.15。

本輪 UX／Windows 字體更新及測試重點見 [更新說明](DOCUMENT_DESIGNER_UX_UPDATE.md)。

Current operation updates: [UI/UX consolidation](DOCUMENT_DESIGNER_USABILITY.md) and [fixed multiple pages](DOCUMENT_DESIGNER_MULTIPAGE.md).

## 1. 啟動與入口

Windows 可攜版：解壓整個 Composition-Dev ZIP，執行資料夾內的 **PDFDocuEdit Pro.exe**，在 Welcome 選 **Document Designer**。請保留 exe 旁的 _internal 資料夾。

Composition 使用獨立工作視窗，原有 PDF Editor 可繼續使用。視窗包含 Data、Design、Preview、Production 四個模式，以及資料欄位、版面、屬性三個區域。深淺主題沿用應用程式設定。

從原始碼啟動時，先使用 Python 3.12 安裝專案相依套件及準備素材：

```powershell
python -m pip install -r requirements-base.txt
python scripts/prepare_composition_assets.py
$env:PDFDOCUEDIT_ENABLE_COMPOSITION = '1'
python main.py
```

一般原始碼／穩定封裝預設不顯示入口；Composition 開發封裝內含啟用標記。

## 2. 建立版面

1. 按 **New** 建立空白 A4 模板。
2. **Page size** 可選 A4、A5、Letter、自訂毫米尺寸。
3. 如需要公司信紙，按 **PDF background**，選來源 PDF 及一個來源頁。
4. 系統複製該頁作背景，背景頁尺寸成為模板尺寸，原始 PDF 保持不變。
5. 使用 Text、Image、Line、Box、Barcode → Code 128／QR 加入物件。

背景是固定頁面，可透過 File → Remove background 移除。每個模板頁可選擇一個 PDF 來源頁作背景，並可新增多個固定模板頁；每筆資料依順序產生這些頁面。

## 3. 匯入 CSV／TXT

按 **Import CSV / TXT…**，確認編碼、分隔符號、有無標題、標題所在行及欄位映射。

- 支援 CSV、Tab、其他單字元分隔的 TXT。
- 編碼偵測是建議，請以 sample records 核對繁簡中文及符號。
- 原始欄名保留；右側映射的內部欄名用於模板。
- 空欄位保留為空字串；帳戶號碼等欄位保留前置零，不轉成數值。
- 正規化後撞名必須修改映射，不能將兩個來源欄位默默合併。
- 匯入在背景執行，資料保存在本次工作階段的磁碟 SQLite 快照。

雙擊或拖曳左側資料欄位，可在頁面建立變數文字。新拖入的欄位預設為 Noto Sans CJK HK，兼容中英文，右側屬性明確顯示所用字體；舊模板不會自動換字體。亦可直接編輯文字：

```text
Account Number: {{Account_No}}
{{Customer_Name}}
{{Address_1}}
Balance: {{Balance}}
```

本版不提供公式、Python、SQL 或可執行腳本。資料是文字；金額格式須在來源資料準備好。

資料匯入後是快照。來源改動需要重新匯入；執行前會檢查來源指紋，改動後會阻止使用舊快照生成。

## 4. 版面編輯與字體

選中物件後，在 PROPERTIES 設定毫米位置／大小、文字、字體、字號、對齊、行距、顏色及其他適用設定。

- 拖曳移動；拖曳大小控制點調整尺寸。
- 框選多個物件；方向鍵移動 0.5 mm，Shift + 方向鍵移動 5 mm。
- Delete、Copy/Paste、Duplicate，以及獨立 Undo/Redo。
- Ctrl + 滑鼠滾輪縮放，Space 拖曳平移，Fit page 返回完整頁面。
- 窄窗可使用工具列的溢出選單及可捲動屬性區。

英文文字可選 Noto Sans；繁體中文請明確選 **Noto Sans CJK HK**。框選一個或多個文字物件後，也可用 Arrange → Use CJK font for selected text 批量套用。此操作保留字號與粗體，清除自訂字體／斜體，可 Undo/Redo；不改動未選取物件。字體在最終 PDF 內嵌入。

Windows 系統字體可在 **Family** 搜尋，並在 **Style** 選確切字款。支援 TTF、OTF、TTC／OTC 及具名可變字體。另可使用 **Choose font file…** 選字體檔案。自訂粗體／斜體請選相應實體檔案，不使用模擬樣式。Noto CJK HK 提供 Regular／Bold；沒有斜體替代。

生成前的字體掃描會檢查整批資料，包含後面的記錄才出現的中文。缺字體、缺字、超出版面文字框、無效欄位或禁止嵌入的字體會阻止生產，避免靜默替代／截字。調整內容、字體或文字框後重新預覽。

補字及客戶主字體保留：選擇 **Repair missing glyph…**，設定單一 code point，詳見 [補字指引](DOCUMENT_DESIGNER_GLYPH_REPAIRS.md)。目前規則開發版讀取 v1／v2／v3，保存為 template_version 4；回退請保留舊模板。

## 5. 條碼

Code 128 用於可列印 ASCII 資料，例如帳戶號碼；QR 可包含 UTF-8 中文資料。

條碼使用向量圖形及白色 quiet zone。過小的 module size 會報錯；請放大條碼框。生產驗收包括解碼測試，但實際紙張／印表機／讀碼器仍需要現場核對。

## 6. 儲存與重開

按 Save，存為 **.pdcx**。檔案是含 template_version: 1 的 JSON。

系統將背景、圖片及自訂字體複製至相鄰的 **<模板名稱>.assets** 資料夾，並保留資料來源路徑、匯入設定及映射。搬移模板時，請一併搬移 assets 資料夾。

資料表內容不封存在模板中。重開後按 Import / remap data 匯入來源；來源遺失可 Locate File。模板檔案及資料來源仍須有可存取位置。

## 7. 預覽

切至 **Preview**，用上一筆／下一筆或記錄編號查看。

每次只生成所選記錄的 PDF 預覽，與生產共用版面 renderer。請檢查姓名、中文、地址、長文字、條碼及空欄位；最後一筆及異常資料也應核對。

## 8. 生產與報告

按 **Generate Production PDF**，選輸出父資料夾。系統建立獨立 Job ID：

```text
output/
  <job-id>/
    production.pdf
    control.csv
    job.json
```

執行流程：檢查模板／來源 → 掃描使用字元 → 嵌入字體子集 → 分批組版 → qpdf 合併 → 重新開啟及核對頁數 → reconciliation → 發佈工作目錄。

Production 顯示進度、數量、錯誤及報告路徑。完成後可 **Open production PDF**。

**成功條件**：input = processed = successful；failed = 0；generated pages = input records；generated files = 1。數量不符不能標示完成。

- control.csv：Job ID、來源、模板、時間、數量、頁數、輸出大小及狀態。
- job.json：機器可讀狀態、錯誤、來源指紋、模板身份、記錄序號／固定頁對照、資源量測。
- 日誌不寫出完整資料記錄文字。
- Job ID 以 UTC 時間加隨機身份建立；畫面時間與本地時間可能不同。

本版錯誤策略是 **Stop on critical error**。錯誤指出記錄／物件／欄位；修正後重新生產，沒有自動重印或續跑。

**Cancel job** 在安全檢查點停止。原生 PDF 操作需要先返回；合併程序可終止。取消／失敗留下 <job-id>-failed 診斷報告，不發佈半成品 production.pdf。已成功的其他工作保留。

## 9. 效能與本版限制

引擎每批預設最多 500 頁，資料從 SQLite 串流讀取。字體子集掃描只累積每種字體使用字元，不保留全部渲染頁面。

最後的 qpdf 合併仍需要 PDF 物件記憶體，並不是整條管線固定記憶體。50,000 頁中文＋條碼合成測試的組版峰值約 260 MiB，合併峰值約 1,657 MiB；詳見驗收報告。

開發版已支援固定多頁模板與條件規則；動態表格／溢出、分檔、重印、watch folder、AFP／IPDS 留待後續 v3.x。多頁操作見 DOCUMENT_DESIGNER_MULTIPAGE.md；條件顯示及替代文字／圖片见 DOCUMENT_DESIGNER_RULES.md。

## 10. 無 GUI 使用核心

Python 呼叫引擎不需要 QApplication 或 PDF Editor：

```python
from pathlib import Path
from composition.data.source import import_records
from composition.template.model import DataConfig, Element, Template
from composition.production.model import ProductionJob
from composition.production.generator import generate

store = import_records(DataConfig(path="input.csv"), Path("records.db"))
template = Template(elements=[Element(value="Account: {{Account_No}}")])
result = generate(ProductionJob(template.to_dict(), str(store.path), "output"))
if result.status != "completed":
    raise RuntimeError(result.error)
print(result.output_pdf)
```

worker 入口是 python main.py --composition-worker <request.json>；GUI 使用 QProcess、檔案 JSONL 事件與取消 token 呼叫它。公開 CLI、hot folder 及 server 產品入口未在本版加入。

## 11. 驗證與建置

```powershell
python -m pytest tests/composition -q
python -m pytest
python -m ruff check .
python scripts/verify_source.py
python scripts/prepare_composition_assets.py --verify-only
python scripts/benchmark_composition.py --records 100 1000 10000 50000 --fixture plain
python scripts/benchmark_composition.py --records 1000 10000 50000 --fixture mixed
python scripts/build.py --document-designer --portable-only --skip-tests
```

--skip-tests 僅在該來源已完成完整回歸時使用。建置需 Windows x64、Python 3.12、現有 Tesseract／veraPDF／Ghostscript 素材及 Composition 字體／qpdf 素材；新相依的版本與授權見 BUNDLE_INFO.json 與 THIRD_PARTY_NOTICES.md。

本次本機產物未簽署／未公開發佈；正式 v3.0 版本更新仍需原有 release 流程。

## 多選文字格式 — 2026-10-01

在目前模板頁框選文字，或在 Layers 用 Ctrl／Shift 多選，可於 Properties 一次更改
字款、字號、行距、對齊及文字色。工具列字號亦可批量套用。Mixed 提示表示原值不同；
只修改指定的項目，保留各欄位內容、位置、規則及補字設定。詳見
DOCUMENT_DESIGNER_BULK_FORMAT.md。此更新不改模板 schema 4 或公共版本。


## 流水號與免 CSV 生成 — 2026-10-01

Data → Running sequences 可設定多個起始值／增量／補零／前後綴欄位，並選擇每筆或每輸出頁遞增。Generate records without CSV / TXT 可直接指定 Quantity；文字、Code128、QR 及規則共用同一個值。保存為 schema 5；旧版模板可讀，回退須保留原模板。詳見 DOCUMENT_DESIGNER_SEQUENCES.md。
