# Document Designer — 指定字元補字

日期：2026-10-01（香港）。開發測試版，正式產品版本仍為 2.5.15。

## 客戶字體原則

主字體是排版標準，不能因為一筆資料缺字就更換整個 Field 的字體。

本輪加入 `glyph_repairs`：每個文字物件可為明確的 Unicode code point 指定補字字體。只有主字體沒有該字形時，該字元才會使用指定字體。未設定的缺字仍阻止生成；沒有系統字體自動替代。

例如：

- Primary：Microsoft YaHei
- Field：Field_4
- Code point：U+E473
- Repair：MingLiU_HKSCS
- 其他字元及其他物件繼續使用各自的主字體。

即使配置了 U+0041 補字，原字體有 A 字形時仍使用原字體。補字不更改主字體的 family、實體檔案、字款、字號、顏色或物件位置。

## 在 Designer 內設定

1. Production 失敗後，按 **Repair missing glyph — keep primary font**。會定位物件、記錄及預填缺失 code point。
2. 或選中文字物件，在 Typography 按 **Repair missing glyph…**；Arrange 選單亦有相同入口。
3. 輸入例如 `U+E473`，或直接輸入單一字元。
4. 選 Repair family／Exact style，或 Choose repair font file。
5. Apply 後，背景 worker 檢查該實體字款確實包含所需字形；不相容字體不會寫入模板。
6. Preview 檢查失敗記錄。狀態列顯示本次預覽的補字數量。
7. 保存及生成；Production 顯示補字數量、涉及記錄及審閱提示。

補字設定、移除均可 Undo／Redo。已配置清單可選取並按 Remove selected repair。更換主字體後，若主字體已支援該字元，補字設定仍保存但不生效。

## 排版及字形核對

引擎把文字拆成連續字體 runs，只有必要的缺字 run 使用補字字體，使用原字號、顏色及主字體基線。

換行及後續字元位置使用實際補字寬度，因此需要查看受影響記錄的實際排版。超出文字框、補字字體高於／低於容許區域會報錯，不會隱藏截字或自動縮小。

私用字沒有通用字形含義；有字形不代表語義正確。需按客戶原 PDF／原字體核對。本次使用者資料的來源 PDF 字體為 Ming-Lt-HKSCS-UNI-H，所選補字字形亦已對照確認。

## 生產報告

成功且有實際補字時，輸出 **glyph-repairs.csv**：

Record / Object / Fields / Code point / Occurrences / Primary font / Repair font

CSV 不寫姓名、地址或完整資料值。job.json／control.csv 加入補字數量、涉及記錄數及報告位置。成功狀態仍有明確警告提示審閱補字報告。

若生成失敗，暫存 PDF 仍不發佈；可能保留 glyph-repairs-preflight.csv 作診斷，屬預檢資料，並非已發佈補字結果。未使用補字的成功工作不產生空白補字報告。

報告逐行串流寫入，沒有在記憶體累積全批逐筆清單。

## 模板遷移

- 新格式為 **template_version: 2**，新增各 element 的 glyph_repairs。
- 新版讀取 v1／v2；v1 自動在記憶體遷移，未設定補字，不會默默更換字體。
- 保存時，主字體與補字實體檔案一併複製至相鄰 .assets，並檢查嵌入權限。
- 舊開發版不能讀 v2 模板。原始 v1 模板／assets 保留作回退，不要用舊版開新副本。
- 未改動穩定 PDF Editor、公開版本或既有檔案。

## 已驗證

- 最終 Composition 專項：69 passed。
- Windows frozen，200% 縮放，100 筆 GUI 流程：補字對話框、原字體不變、保存重開、逐筆報告、中文、條碼解碼、預覽、背景生成、既有 Editor 開檔。
- 隔離 QA 安裝，100% 縮放，同一流程通過；之後移除，未註冊 PDF handlers／shortcuts。
- 真實 398 筆及原用戶版面：398 頁，0 失敗，1 次補字、1 筆記錄。
- 逐字檢查整份輸出：只有第 346 頁的 U+E473 使用 MingLiU_HKSCS，其他文字均保留 Microsoft YaHei。
- 第 1／345／347／398 筆預覽與上一版原字體輸出逐像素一致。
- 原模板檔案 hash、所有主字體實體檔案 hash 保持一致。

完整回歸重跑：**902 passed**，804.88 秒；最終代碼的專項為 **69 passed**。首輪在既有 VisualOrganizerDialog 的 Qt 原生 findChildren 呼叫出現 access violation；該模組未修改，單獨 11 項及完整重跑均通過。首輪原生崩潰原因未確認，原始記錄保留；沒有停用或略過測試。

證據（build 內不提交用戶資料）：

- build/qa-glyph-repair-final-tests.xml
- build/qa-glyph-repair-regression.log
- build/qa-glyph-repair-regression-retry.xml
- build/qa-glyph-repair-dialog-regression.log
- build/qa-glyph-repair-frozen/result.json
- build/qa-customer-glyph-repair/result.json
- build/composition-install-qa/result.json

新測試版：dist-glyph-repair/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。
Portable：release/PDFDocuEdit-Pro-v2.5.15-Document-Designer-Dev-GlyphRepair-Portable-Windows-x64.zip。
