# Fixed multiple template pages — implementation note (2026-10-01)

Next accepted V3.1 milestone: one record produces an ordered, known set of template pages.
Scope: add/duplicate/delete/reorder pages, independent size/background/elements, record + page preview,
all-page font preflight, bounded production chunks and exact record/page reconciliation.
Dynamic overflow, rules, splitting and reprint remain later milestones.

## Repository mapping
- composition/template/model.py: PageSpec and schema 3 ordered pages; migrate v1/v2 single page, retain exact fonts/repairs.
  First-page Python accessors remain for existing callers; JSON has one canonical pages list.
- composition/template/serializer.py: copy/resolve all page assets.
- composition/engine/{renderer,subsets}.py: all-page rendering/preflight; selected-page preview.
- composition/production/{model,generator}.py: pages_per_record, expected_pages, fixed mapping in reports.
  Flush at chunk page limit between complete records; upper bound chunk_size + pages_per_record - 1.
- composition/designer/pages.py: isolated page UI/commands, stable page IDs across Undo/Redo.
- composition/designer/{workspace,canvas,chrome,font_controls}.py: active-page hooks and cross-page error targeting.
- composition/worker.py: selected-page preview request; existing QProcess isolation retained.
- tests/composition: migrations, multi-page order/sizes/backgrounds/font repairs, failure/cancellation/reconciliation, UI undo/navigation.
- scripts/composition_smoke.py: native/frozen/installed multi-page workflow.

No added dependency, public version change or editor rewrite.
Saved schema-3 projects require this development build; earlier projects open without source overwrite.
Acceptance: focused suite, full regression, native/frozen and installed smoke; synthetic 1,000-record / 2,000-page benchmark.

## 使用方法

1. 打開 Document Designer。舊 v1/v2 .pdcx 會自動作單頁讀取，原檔不會因開啟而改寫。
2. 用 Page → Add blank template page 新增頁面；Duplicate template page 會保留版面、主字體、補字設定及背景，並產生新的物件 ID。
3. 畫布上方 Template page 清單切換頁面；Alt+PgUp / Alt+PgDown 亦可。
4. Page → Current page size 改本頁尺寸；File → Use PDF background 只設定本頁背景。
5. ← / → 將目前頁提早／延後；− 刪除目前頁。最少保留一頁。所有頁面修改支援 Undo / Redo。
6. 可在不同頁之間複製／貼上物件。大於目標頁的物件會提示先縮小，不會悄悄改其尺寸或字體。
7. Preview 中，Record 控制資料筆數，Template page 控制該筆資料的模板頁。背景 worker 只渲染當前頁，不生成整份工作。
8. Production 先顯示每筆頁數與預期總頁數。輸出順序固定為第一筆的所有頁、第二筆的所有頁，以此類推。

例：398 筆 × 2 頁 = 796 頁。輸出第 691 頁是第 346 筆資料的第一模板頁。

## 相容及記憶體

JSON schema 升為 3，只有一個有序 pages 清單，沒有重複的頂層 page/elements。
仍可讀 v1/v2；主字體、實體字款、物件 ID、指定字元補字和資料設定完整保留。
建議首次保存使用 Save as 留下舊版本；舊測試版不能開 schema-3 專案。
正式應用版本仍是 2.5.15，這是功能旗標啟用的開發測試版。

每份模板支援 1–100 個固定頁；全模板最多 5,000 個物件。
各頁可用不同紙張尺寸及靜態背景。沒有動態 overflow、雙面補白或條件頁。
每個 chunk 在一筆資料完整生成後才寫出，最多 chunk_size + pages_per_record − 1 頁（預設 500）。
取消在記錄及模板頁之間檢查；不能中斷原生 PDF 呼叫。
失敗／取消只留下診斷紀錄，不發布半份 PDF。部分記錄不計成功。
qpdf 最終組裝仍有隨頁／物件數增加的記憶體開銷，不宣稱整條管線為固定記憶體。

## 對帳及報告

Production、control.csv 和 job.json 加入 pages_per_record、expected_pages。
成功要求：Input = Processed = Successful、Failed = 0，Generated Pages = Input × Pages Per Record，Files = 1。
job.json version 2 的 page_mapping 保存模板頁 ID、名稱、次序及一基頁碼公式；
仍以 source SHA-256 + 匯入記錄序號識別記錄。
glyph-repairs.csv 新增 Template page 欄，跨頁補字可追查；其他欄位及主字體原則不變。
失敗訊息指出 record、template page、object 和 field，Review failed object 會跳到所在頁。

## 驗收證據

- Composition suite：88 passed（build/qa-multipage-composition-88.xml）。
- 新增 15 個核心與 4 個 UI 案例：legacy 遷移、頁序／尺寸／背景、資源保存、補字、bounded chunks、失敗／取消、Undo／跨頁編輯／非同步背景定位。
- 既有測試只更新 canonical JSON 的 elements 路徑及 schema 版本預期，沒有刪除／停用測試。
- Native 200%、frozen 200%、installed 100%：100 筆／200 頁完整 smoke passed；中英文字、Arial exact Bold、條碼解碼、背景、補字、儲存、預覽、頁序與既有 Editor 開檔均通過。
- 使用者原 schema-2 模板 398 筆：逐頁與上次成功輸出比較，398 頁像素完全相同；1 個字元／1 筆補字；來源不變。客戶資料只存在 ignored build QA 目錄。
- Ruff / source verification 通過。
- 完整回歸及多頁基準結果見本文件最後的 Final validation。

## Final validation

Full Windows suite: 920 passed in 814.70 s (build/qa-multipage-regression.xml); an additional between-pages cancellation case then passed with all 88 Composition tests. No test skipped or disabled to satisfy the gate. The two final display-only changes (compact delete button and page-size formatting) also passed the focused suite and frozen/installed smoke.

Five non-overlapping synthetic plain-text trials per size; medians:

| Records | Pages | Generate s | Records/s | Composer MiB | Assembler MiB |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 2,000 | 2.71 | 368.9 | 77.0 | 27.8 |
| 10,000 | 20,000 | 25.95 | 385.3 | 99.2 | 191.5 |

Raw samples/selection/limits: docs/validation/document_designer_multipage_benchmark_20261001.json. Early overlapping trials were retained in ignored QA logs but excluded from these medians. Cold/warm cache was not separately controlled. This is not a comparative release performance claim or an image-heavy document guarantee.
