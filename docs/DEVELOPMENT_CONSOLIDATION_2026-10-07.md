# 2026-10-07 更新鞏固

覆核及修正日期：**2026-10-08**。基線為公開 v3.0.2，目前修改屬開發工作樹。

## 範圍與結果

本輪核對昨日新增的共用變數、Flatten／Repair、批次與 Workflow 整合、Generic Barcode、I25 紙序，以及間尺／參考線／磁吸。沿用現有服務與 worker；未新增依賴、公開版本或專案格式。

| 發現 | 修正 |
| --- | --- |
| 使用者輸出名可能與 `source-snapshot.pdf`、`candidate.pdf`、`preflight.pdf` 等內部檔案相撞，導致生成失敗或成品被後續清理 | `core/pdf_operations/service.py` 使用獨立、受管理的工作暫存目錄；發布資料夾只含成品 PDF、CSV 及 JSON。保留驗證後原子發布。 |
| 批次分析沒有顯示簽署／有限修復確認，使用者無法在介面確認後繼續 | 從各檔分析結果彙總並顯示確認項目。新選來源會重設這些確認。 |
| 確認警告會清空分析，造成不必要的大檔重掃 | 純確認只更新分析計劃的 permission flags；處理設定／密碼改動仍使分析失效。生成繼續比對全部選項並核對來源 hash。 |
| 批次的 Current page 沿用舊文件頁碼；Page range 在未知頁數時無法進行分析 | 批次禁用 Current page，原選項改為 All pages；頁碼範圍由每份來源分析驗證，超出範圍的檔案獨立報錯。 |
| Maximum Compatibility 仍可能被失效的頁碼草稿阻擋 | 全文件光柵化模式停用頁碼控制，忽略之前的 range 草稿；切回其他模式保留草稿。 |
| 全部來源分析失敗時直接呼叫 Generate 可能出現未捕捉的 StopIteration | 顯示沒有來源通過分析，保留錯誤供修正，不啟動生成。 |
| 批次完成後只有總狀態，缺少逐檔核對 | 顯示成功／需覆核／失敗／取消數量及前 100 檔摘要；完整結果留在報告，避免巨大清單進入 UI。 |
| Repair 長模式名稱的下拉內容及命名錯誤提示不足 | 重用 WideComboBox；命名預覽顯示 sanitisation 原因，清除過期 tooltip，更新 invalid 邊框；背景工作期间停用輸出資料夾選擇。 |
| 全頁分析逐頁在長 tuple 搜尋頁碼，造成不必要的平方級 membership 工作 | 全頁用 range，指定頁面用 set；不改選頁結果及既有 PDF 處理。 |

## 驗證

本輪 **287 個不同的相關測試通過**。各次重跑有重疊，下列按不同測試計算：

- PDF 操作／normalise／batch／UI／變數／Workflow cleanup／appearances：78 項。
- I25 profiles／production／UI／I25 encoder／Generic layout／production／builder：121 項；包含 1,000 封實際編碼解碼及循環紙序測試。
- Measurement／interaction／PDF rulers／guides／Mail Merge UI／Workflow inspection UI：88 項。
- 最後重跑 PDF 組及兩個 Workflow UI 檔案：100 passed，已包含在上列數字內。
- 今日累積修改及新增的所有 Python 檔案 Ruff 通過；`git diff --check` 通過。
- 離屏 Qt 截圖核對 Repair 三種模式及 Generic／Inserter 設定，在 960×640 邏輯畫面、深淺色、100%／200% 縮放下的主要操作及確認按鈕可見。

新增回歸案例涵蓋四個內部工作檔名分別用作 Flatten／Repair 輸出，含真實 Preflight；成品存在、可讀、頁數及搜尋文字正確，來源不變，發布資料夾沒有內部暫存 PDF。

## 使用及限制

- 分析後改處理選項或來源密碼，需要重新 Analyse；純粹勾選已顯示的簽署／光柵化／有限修復确认，不需要重掃。
- 批次頁碼範圍對每檔個別驗證；失敗檔案不影響其他成功來源。
- 既有 PDF 修復能力、XFA、數碼簽署、光柵化及待覆核輸出的限制不變，詳見 PDF production tools 文件。
- 原子性按單檔工作套件計算，整批不是單一交易。
- 本輪沒有重新打包或 GitHub 發布；完整回歸及 Windows 安裝包沿用統一验收。離屏顯示及成品解碼不代替實際 Windows／打印機／入信機驗收。
- 已開啟的程式需重新啟動才載入本輪修改；未停止使用者正在操作的程式。

## 後續修正 H5：Duplex without Media 的每頁流水號

`sequence_record()` 建立列印計畫的条件補上 `media.duplex`，與 Renderer 一致。仍共用既有 `build_print_plan()`，不新增計數器或格式遷移。

- 修正前的實際生成測試重現：單頁雙面第二筆 `002`（應 `003`），三頁雙面第二筆 `004`（應 `005`）。Simplex／兩頁 Duplex 對照案例原本通過。
- 修正後共 **128 項相關測試通過**：流水號、雙面選紙、I25 profile／生成、Generic layout／生成；與上面的鞏固測試有重疊，不相加計算。
- 新案例核對一／二／三頁、三筆跨 chunk 正式輸出、第二／第三筆隨機單頁預覽及像素一致、Job log 首末值、條件可見性、起始值／步幅／補零／前後綴。
- 快取案例核對 Simplex／Duplex 切換、增加模板頁面，以及啟用 Media 的 Stock 補白及停用／重新啟用；結果均按當前實際輸出頁面計算。
- 每頁流水號把補白背面計入偏移但不印在補白頁；每筆流水號及 I25 實體紙序語義不變。Ruff／diff check 通過，公開版本及保存格式不變。
- 受影響的已生成 PDF 需重新生成；此修正不修改舊成品。
