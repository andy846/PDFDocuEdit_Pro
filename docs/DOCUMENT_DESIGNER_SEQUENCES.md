# Document Designer — 流水號生成器

## 使用方式

1. 開啟新版 **Document Designer → Data → Running sequences…**，或左側 Data 面板同名按鈕。
2. 每列是一個可重用欄位，例如 `Ticket`、`PageSeq`。設定 Start（起始值）、Increment（增量）、Digits（最少數字位數）、Prefix、Suffix 和 Scope。
3. 要免匯入資料，選 **Generate records without CSV / TXT**，設定 Quantity，按 OK。
4. 在左側拖曳欄位到版面，或在文字 / Code 128 / QR 內容輸入 `{{Ticket}}`。
5. 切換 Preview，檢查不同 Record 及模板頁；Generate PDF 會輸出新工作資料夾，連同 control.csv / job.json。
6. 儲存 .pdcx 可保留全部流水號設定與生成數量。生成模式重開時不用尋找 CSV。

可同時使用 CSV 與流水號：選 **Use imported CSV / TXT records**。紀錄數採用已匯入 snapshot；Quantity 在此模式停用。匯入新資料會切回 imported 模式，保留流水號設定。切回 generated 模式會保留資料配置，但該批次不使用 CSV 欄位。

例如 `Ticket` Start=1、Increment=1、Digits=5、Prefix=`T-`：
`T-00001`、`T-00002`、`T-00003`。

Digits 是最少位數，超過位數的數字不截斷。可用負起始值及負增量；例如 Start=-2、Increment=-2、Digits=3 → `-002`、`-004`。零增量、重名、無效欄位名稱會阻止套用。

## 每筆／每頁

若每筆紀錄有兩頁：

| Scope | Record 1 / page 1 | Record 1 / page 2 | Record 2 / page 1 | Record 2 / page 2 |
|---|---|---|---|---|
| Per record | 000001 | 000001 | 000002 | 000002 |
| Per output page | 000001 | 000002 | 000003 | 000004 |

每頁號碼按完整輸出的「紀錄順序 × 模板頁順序」計算。改模板頁數、順序、起始值或增量會改變相應號碼。Data 範例表顯示模板第一頁；其他頁以 Preview 核對。隱藏所有物件的固定頁仍然存在，頁號仍遞增。

同一設定、來源順序、紀錄及頁次必定得到相同值。預覽不消耗號碼，取消後重新生成從相同起點開始。**不會自動保留下一批號碼**；新批次要連號，須自行更改 Start。本功能不保證不同工作／不同電腦之間的號碼唯一性。

流水號欄位可用在文字、混合文字、Barcode / QR 或規則中。帶前後綴的值是文字，數值比較規則要使用不帶前後綴的序號。字款、補字、條碼尺寸、長文字等沿用既有驗證。

## 資料與編輯保護

- 流水號不得與實際匯入／映射後的欄位同名；不覆寫原資料。
- 移除／改名仍被物件或規則引用的序號時，設定面板會指出問題；先修改引用。
- 一次設定是一個 Undo；支持多個序號欄位。
- 模板最多 100 個序號欄位。Generated quantity 可設定 1–1,000,000，但大數量的實際可用性仍視背景、圖片、字型及可用磁碟／記憶體而定；本輪較大實測是 50,000 筆的合成單頁範例。
- 不提供按群組重設、跨工作累計、亂數序號、跳過失敗繼續生成或選取紀錄重印。

## 模板相容及回退

新版讀取 schema 1–4，保存為 **schema 5**。舊版 Designer 不能開 schema 5。
第一次升級請用 **Save as…** 保留原 .pdcx 及其 assets 資料夾；Git 程式回退不會倒轉使用者模板。
公共版本維持 2.5.15，本次為開發測試版。
上一個程式回退標籤：`document-designer-bulk-format-dev-20261001`。

## 技術實作

新增模組：
- `composition/data/sequences.py`：純整數運算、schema 驗證、來源欄位衝突檢查、CompositionRecords。
- `composition/designer/sequence_dialog.py`：設定表格、輸入錯誤及即時首尾範例。
- `composition/designer/sequence_controls.py`：UI / Undo / 小型樣本 cache。

模板新增 SequenceSpec[]、record_mode、generated_count。原 CSV SQLite snapshot 與映射保持原有接口；generated 模式只逐筆 yield 空資料，沒有建立大量記錄或 PDF 頁清單。序號在渲染的逐頁 context 中加入；rules、字型預檢、預覽及 PDF 共用 sequence_record()，不修改來源字典，不使用可變累加器或 eval。

既有 500 頁 chunk／獨立 qpdf assembly／验证及 reconciliation 沿用。job.json 記下完整序號規格、首尾值、資料模式及 generated ordinal identity；control.csv 記下 Record Mode / Sequence Fields。既有 job_version 2 的欄位保留，增加 metadata。模板保存序號規格，沒有新增依賴或改動 viewer.py。

## 驗證

自動測試涵蓋格式與邊界、版本遷移、來源不被改寫、欄位衝突、逐頁規則、font subset、chunk 邊界、隨機預覽、重跑、取消、真實 GUI 配置／Undo／生產／重開。
Windows 開發 exe 另做現有 CSV/CJK/背景/規則/補字/多選字型流程，及 generated 模式的 100 筆 × 2 頁、QR／Code128 解碼、儲存重開和 200% 縮放檢查。
完整結果以 `validation/document_designer_sequences_20261001.json` 為準；benchmark 合成量測不能當作客戶文件／實際印表機的保證。

## 本輪量測結果

合成單頁文字流水號、每個規模 3 個獨立生產程序，中位數：

| 紀錄／頁數 | 生成秒數 | 紀錄／秒 | Composer 峰值 MiB | qpdf 峰值 MiB |
|---:|---:|---:|---:|---:|
| 1,000 | 2.40 | 415.8 | 76.4 | 18.5 |
| 10,000 | 22.05 | 453.6 | 87.8 | 100.7 |
| 50,000 | 157.41 | 317.7 | 137.7 | 465.7 |

全部 9 個工作完成 record/page/file 對帳。這批量測部分時間與完整回歸、建置／ZIP／GUI 測試並行，系統負載及缓存未控制，不能用來比較前後版速度。Composer 沒有累積整批已渲染頁，整個程序峰值仍有上升；qpdf 合併的物件記憶體隨輸出頁數增加，並非定量記憶體保證。不能由 50,000 筆單頁文字結果推斷 1,000,000 筆或影像／背景密集範例。原始試次見 validation/document_designer_sequences_benchmark_20261001.json。
