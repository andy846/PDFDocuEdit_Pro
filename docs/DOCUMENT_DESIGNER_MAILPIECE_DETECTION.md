# Document Designer — Mailpiece Detection

Development checkpoint: 2026-10-03. No public version change or release packaging.

## 操作流程

1. 在 Document Designer 建立 PDF envelope overlay。開檔的 Grouping 視窗可勾選「Auto-detect variable page counts」。已有套印專案可直接按工具列 **Detect mailpieces**。
2. 選偵測方法、文字條件及搜尋範圍，按 **Scan PDF**。掃描使用背景 QProcess；主介面保持可操作，切換模式不取消掃描。
3. 結果表顯示每封來源頁範圍、頁數及 Needs review。選一行可查看起始證據、逐頁來源預覽及 QC 警告；Source page 控制可查看該封其他頁面。
4. 必要時 **Split here** 或 **Merge with previous**。不得合併跨越已排除分隔頁的兩組。原始警告保留在報告，人工調整另記 edits。
5. 勾選已覆核邊界／排除頁面的確認，再按 **Accept & apply boundaries**。套用是一個 Undo 操作，保留現有文字、字型、barcode profile、流水號及列印設定。
6. 設定流水號／barcode，預覽及產生 PDF。LetterPage / LetterPageCount 等欄位、雙面補白、首／尾頁 scope 和 barcode QC 都使用已接受的動態分組。

## 偵測方法

| 方法 | 設定與行為 |
| --- | --- |
| Page number pattern | 例如 `Page {CURRENT} of {TOTAL}` 或 `{CURRENT}/{TOTAL}`；首個頁碼重啟為 1 開新封；缺頁、跳號、重複／歧義匹配、total 改變及未完成序列均產生警告。 |
| Document / Account ID changes | 例如 `Member Account No. : {ID}`；相鄰頁的 ID 改變開新封。預設 missing ID 需要覆核；若 ID 只在每份文件首頁出現，明確勾選 **ID only on first pages (carry forward)**。相同 ID 可接續中英文文件；ID 在其他客戶之後重新出現會提示疑似重複／亂序。 |
| First-page text | 每行一個 literal marker，全部命中才開新封；例如 Statement Date + Account Number。 |
| Separator page | 命中文字後結束前一封，可移除或保留分隔頁。移除頁碼明確記錄；保留時分隔頁附於前一封。開頭的保留分隔頁另列一封並警告。 |
| Text region present | 指定區域有文字就視為起始頁；這是文字存在檢查，不會自動判斷是否為地址。 |
| Combined | 可選 ID、頁碼重啟、首頁文字及區域存在，以 OR／AND 組合。條件分歧會列警告。沒有任意 Python、shell 或任意 regex。 |

搜尋範圍可選 Whole page 或毫米 X/Y/W/H；在來源預覽拖拉矩形亦可設定。**Ctrl + 滾輪**縮放來源預覽，**Fit page**恢復全頁。修改任何偵測條件會使舊結果不可套用，必須重新 Scan。

## 實際樣本核對

使用提供的 `merged.pdf`：2,497 頁，有文字層。

| 設定 | 候選分組 | 每封頁數 | 首兩組 |
| --- | ---: | --- | --- |
| 首頁文字 Member Account No. | 796 | 2–5 | 1–4、5–8 |
| Member Account No. : {ID}，首頁 ID carry forward | 398 | 5–8 | 1–8、9–16 |

兩種規則均沒有偵測到規則內的異常。這不代表客戶分封規格已由 operator 認可；中英文應同封或分封仍須確認。沒有對樣本加 barcode、產生正式 PDF 或寫入來源檔案。各方法完整掃描約 17 秒（本機單次觀測，不是正式效能保證）。可重現的規則及統計記錄於 `docs/validation/mailpiece_sample_20261003.json`；不保存會員 ID 或來源文字。

## 工程安排

- `composition/pdf_source/detection.py`：宣告式條件、串流文字掃描、邊界與 QC；不依賴 Qt。
- `composition/pdf_source/planner.py`：固定／動態共用 lazy PagePlan、局部每封頁數、累計 output offset、binary-search output-page 回查；不保留整批渲染頁。
- `composition/designer/mailpiece_dialog.py`：只顯示目前方法的欄位、按需 QAbstractTableModel、單頁背景預覽、手動修訂及明確接受。
- `composition/worker.py`：新增 mailpiece_scan / mailpiece_preview 協定；沿用既有合作式取消及安全清理。
- 只修改套印模組的來源、預覽、產生與報告整合；沒有把偵測邏輯放入 viewer.py。

## 保護與相容

- 自動偵測待覆核的專案不可 Generate。來源改動後重新 Inspect 會清除旧邊界的效力、保留物件，要求重新 Scan／Review。
- accepted review 綁定來源 SHA-256、確切 groups 及 excluded_pages。正式工作沿用 hash-checked source snapshot，再核對幾何；不默默沿用過期頁碼。
- 每個來源頁必須屬於且僅屬於一封，或明確列為排除 separator。Reconciliation 比對 copied + excluded = source，generated = source - excluded + inserted blank。
- 產生 envelopes.csv、pages.csv、barcodes.csv、control.csv、job.json，並新增 detection.csv。job.json 保存規則、警告、人工修訂與接受時間；不保存抽取出的會員 ID 或全文。
- 套印專案 schema **3**；schema 1／2 可遷移讀取。新 schema 向舊程式不相容，勿手動降版號。模板 schema 仍為 7。
- 首版動態來源要求全檔頁面幾何／旋轉一致；不一致會阻止掃描並要求檢查。沒有 OCR、AI 地址辨識、影像內容判斷、任意巢狀邏輯樹或自動認證入信機規格。

## 針對性驗收

- 47 個相關案例：新增 26 個偵測／QC／來源區域與旋轉／手動覆核／真實背景工作／來源改動／動態正式輸出案例，並驗證受影響的固定頁數、來源保護、scope、保存、旋轉版本相容及 optional barcode 行為。
- 額外 2 個 200% 縮放驗收：960×640 覆核視窗無橫向裁切、來源區域拖選、背景掃描可回應及確認前不修改專案。
- Windows Segoe UI 的 light／dark 視覺檢查已完成。Ruff 及 git diff --check 通過。
- 本輪沒有執行完整回歸、Windows 打包、大型生產 benchmark 或樣本的正式列印生產。

保存目前專案並重開開發版程式以載入新 UI。偵測不會自行新增或更改 barcode。
