# Mailpiece 智能分封實作與驗收 — 2026-10-04

## 操作入口

- Document Designer → PDF Overlay → **Auto Detect**。
- Visual Workflow → **Group Mailpieces** 節點 → **Auto Detect Mailpieces…**。
  Workflow 仍需要先設定至少一個資料抽取區域；只需分封、不抽取資料時可使用 PDF Overlay。

操作順序：**Analyze PDF → Suggested rule → Scan PDF → Review → Accept & apply boundaries**。
直接按 Scan PDF 也會先分析，再用第一個建議掃描。分析／掃描不會加入 barcode，也不會自動批准結果。

## 已實作

### 引擎

- 使用 PyMuPDF words 的座標重組文字行；不同 PDF blocks 的標籤／值可以按同一可見行讀取。
- 英文、中英文頁碼與分數格式；檢查重啟、缺頁、重複、總頁數衝突。有頁碼、首頁特徵及識別資料時，優先提出三訊號組合，並提示首頁／身份變更與頁碼未重啟的矛盾。
- 首頁固定文字特徵及附近觀察到的位置變化；稱呼文字可因地址行數而上下移動。
- Account／Member／Document 等標籤的識別值組合。保留前導零；同封後續頁的相同組合不重新開封。
- 每個訊號／識別欄位可有自己的區域；區域取詞中心點，避免只擦到相鄰文字就把另一欄一起讀入。
- 多訊號一致、單一訊號、重複身份、模糊識別值、無文字／空白頁等狀態與原因。
- 無法建立邊界時回傳空的候選集合及 `Unable to establish boundaries`，不能直接接受。
- 沒有完整 printed sequence 證據時，明示結尾由下一首頁或 PDF 尾頁推定；不宣稱文件完整性已獲證明。

引擎位於 `composition/pdf_source/smart_detection.py`，不依賴 Qt。
一次文字抽取保存至工作區自己的 SQLite 索引；各規則重用索引，逐頁讀取而非保留所有渲染頁面。
每次重新分析／掃描及接受前仍核對來源；取消清除未完成索引。

### 教一次與 profile

1. 選 **Teach a feature…**，設定一張首頁及一張後續頁。
2. 在左邊預覽框選靜態首頁特徵，按 **Use marker region**。
3. 可另框選識別資料的標籤＋值，逐個按 **Add ID region**。
4. 按 **Try taught rule**，比較範例、候選封與警告。
5. **Save profile…** 保存 `.pdmp`；以後 **Open profile… → Scan PDF**。

自動教學只保存已知靜態稱呼；其他標題需要操作者明確輸入固定文字。
profile 是具版本的 JSON，只保存靜態規則、標籤、座標及名稱，沒有 PDF 路徑、識別值、客戶姓名或掃描結果。
識別欄位教學目前需包含支援的靜態標籤；未帶標籤的任意文字區域不是這輪的識別欄位教學功能。

### 覆核與交接

- 結果表：封號、起止頁、頁數、狀態、證據／結尾來源；完整內容可由 tooltip／下方詳情查看。
- 首頁／尾頁、邊界前後頁及教學頁面可並排查看；Ctrl+wheel 放大，Fit page 恢復。
- Exceptions only、Next warning、Split、Merge previous、Undo／Redo；篩選後修改仍對應原始封號。
- 大清單使用 Qt model；證據查找使用索引，警告篩選使用二分搜尋，不建立逐封 QWidget。
- 接受前以背景 worker 核對 PDF bytes；來源改動則清除待接受結果並要求重新檢查／掃描。
- Designer 套用為一個可 Undo 的專案修改，保存／重開保留 v2 規則與接受紀錄。
- Workflow 保留既有抽取資料、來源快照及修正，僅重建 group／下游結果。
  分封接受後仍需完成既有的資料覆核，才可生成。
- 生成報告保留實際 v2 規則。`detection.csv` 原有六欄後新增 Boundary evidence／End basis；`job.json` 保留完整分封審核紀錄。

## 相容性

- `DetectionConfig v2` 包含逐訊號區域、身份欄位組合及 profile 名稱。
- v1 手動規則保持讀取及操作；現有專案不自動重新分封。
- 保留 `.pdcx`／`.pdflow` 格式、開發功能旗標與既有套印／流水號／barcode 處理。
- 沒有新增依賴、OCR、雲端分析、任意 Python／regex 執行、重啟自動续跑或公開版本變更。
- 沿用 PDF Overlay 的同頁面幾何限制；混合尺寸／旋轉、簽章及互動表單來源仍由既有檢查阻止。

## 真實樣本

`merged.pdf`，2,497 頁，使用 Dear 的窄水平區域與已觀察的三個相鄰垂直位置，
Employer Account No／Member Account No 兩個欄位交叉核對。

| 項目 | 結果 |
|---|---|
| 候選信封 | 398；全檔封數尚未由操作者獨立確認 |
| 已確認第 1 封 | 1–8 頁，符合 |
| 已確認第 2 封 | 9–16 頁，符合 |
| 第 5／13 頁 | 不重新開封 |
| 頁面覆蓋 | 2,497／2,497，連續、無重疊／漏頁／刪頁 |
| 規則警告 | 0；不等同已證明全檔準確或完整 |
| 最後一封結尾 | PDF 尾頁推定 |
| 最近一次已有索引的分析 | 4.71 秒 |
| 最近一次已有索引的規則掃描 | 3.20 秒 |

時間為本機單次觀察，不是性能保證或多次中位数。初次建立逐詞座標索引的觀察約 14.47 秒。
匿名規則與計數見 `validation/mailpiece_smart_sample_20261004.json`；不保存客戶身份值。

## 針對性驗證

相關範圍共 102 個案例已通過：

- 智能引擎／整合／既有分封：55 個（18 + 11 + 26）。
- 既有 Visual Workflow core／UI：47 個。
- Ruff 及 `git diff --check` 通過。
- Windows Qt 原生字體、200% DPI（devicePixelRatio=2）、960×640 的深淺色畫面已渲染並目視核對。
  兩張預覽、教學按鈕及底部操作均可見，左側不需水平捲動；長設定使用明確的垂直捲動。

測試含：有文字層的中文頁碼、可變頁數、雙識別欄位、地址區塊上下移動、正文 Dear、
重複收件人、缺少訊號、空白頁、printed sequence 衝突、教學／profile 重用、取消清理、
來源改動、篩選後邊界編輯、專案 Undo、保存／重開、Workflow 交接及 v2 規則的實際 PDF／報告生成。

原有 `test_background_scan_review_responsiveness_and_atomic_apply` 增加等待接受來源驗證完成，
原因是 v2 套用現在刻意在背景檢查來源；原有結果與 Undo 斷言保留，沒有停用或放寬測試。
完整應用回歸與 Windows 打包依照使用者安排留待整批更新統一驗收。

Git 里程碑：`f19496f`（引擎）、`5d8a53e`（教學／profile／覆核）；其後的交接與針對性穩定驗證另作一個提交。
