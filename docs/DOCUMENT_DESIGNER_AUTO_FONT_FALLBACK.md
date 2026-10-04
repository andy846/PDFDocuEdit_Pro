# Document Designer 自動缺字字體替補（2026-10-02）

## 使用

Production 頁的 **Automatically substitute missing glyphs and report changes** 預設開啟。
Template / Preview 同樣使用這個選項；可取消勾選回到原本嚴格字體模式。
設定存應用程式偏好；本次工作的 auto_repair、掃描結果和替補紀錄保存於 job.json / glyph-repairs.csv。
模板 schema 仍為 6，既有模板及物件主要字體、手動 glyph_repairs 不被重寫。
GUI 預設自動；headless ProductionJob 預設嚴格，需明確 auto_repair=True 才啟用。

## 行為

1. 原字體已包含字形：保持原字體。
2. 使用者已配置逐字修補：優先使用指定修補。
3. 尚未配置的缺字：先找 bundled Noto CJK / Noto，必要時背景掃描 Windows 已安裝且可嵌入的字體，抽出實際 face。
4. 每個字元／主要 face 的替補結果快取；重複紀錄不重新掃描整個字體目錄。
5. 全檔檢查後將實際使用的主要及替補字體子集嵌入 PDF。
6. 原主要字體不被整欄替換，文字值及 Unicode code point 不改動。替補的字寬／metrics 可能改變換行和混合文字 baseline；預覽與輸出共用 Renderer。
7. 仍沒有可用字體：字體掃描繼續到全檔，集中輸出所有 Unresolved 字元及頁碼；不發布有缺字的正式 PDF。
8. 損壞的主要字體、欄位遺失、排版溢出等其他 critical error 仍會停止，不會因為自動替補而隱藏。

私用字不具有通用字義，Windows 有可用 glyph 時會替補，CSV 及摘要明確標示 Private-use / verify appearance；
在本機優先考慮 MingLiU_HKSCS。使用者須核對其外觀。不同電腦可用字體可能不同。
沒有字形內容重寫、Python eval、Excel 字體繼承或未授權字體下載。

## 報告

生產完成後可按 **Open font substitution report**。
UTF-8 BOM CSV 欄位：
Record / Object / Fields / Code point / Occurrences / Primary font / Repair font /
Template page / Output page / Character / Mode / Font file / Review note。

固定頁數下 Output page = (Record - 1) × Pages per record + Template page。
Mode 是 Automatic / Explicit / Unresolved。CSV 以紀錄、物件、字元聚合次數，逐列寫入磁碟。
取消或失敗後報告表示掃描得到的 proposed substitutions，沒有宣稱已發布 PDF。
job.json 的 font_scan.complete / checked_records 區分完整與部分檢查。

## 工程及測試

新增 composition/engine/fallback.py，不依賴 Qt；engine / preview / worker / production 共用 selector。
子集化收集動態替補字體；預覽及批次執行使用相同字形選擇。
ProductionJob 增加預設 False 的 auto_repair，JobResult 增加 font_scan / auto_repair。
Workspace 增加可保存偏好的選項及報告按鈕；沒有修改 viewer.py 或新增套件。
保留及更新原 stale-preview 測試，明確取消 auto_repair 後檢查嚴格模式；沒有停用測試。

自動測試覆蓋主要字體像素不變（無缺字時）、混合字體、逐頁對照、三筆全部未解決字一次回報、
一千筆重複字僅找一次、手動修補優先、Windows 私用字、損壞主要字體不被隱藏，以及 UI 模式切換／預覽／生產／報告。
本轮全 Composition 250 tests 通過。大型量測是 release QA，不增加普通 CI 的萬筆負擔。

## 使用者真實資料驗收

使用者保存的 AAAWER.pdcx + Excel 398 筆，在隔離 QA 資料夾生產，原模板及資料沒有改動。
原第 1 頁六欄 Noto Sans 及第 2 頁 Bookman Old Style 保留。
本次最新 Windows frozen build 完成：
398 成功，796 頁，0 失敗，2,398 次自動替補，166 個涉及紀錄，0 Unresolved，1 次私用字替補。
抽查第 3、691 頁：文字可顯示，渲染沒有警告。沒有假稱逐頁人工校對或印表機驗收。

## 萬筆量測

scripts/benchmark_composition.py --records 10000 --repeat 1 --fixture fallback --output build/bench-auto-font
一萬筆合成資料，每笔 Account + 中文田，完成 10,000 頁、30,000 次替補、0 Unresolved。
生成 59.04 秒，169.36 records/sec，composer peak 167.90 MiB，assembler peak 161.04 MiB。
單次樣本、與回歸及建置並行；不是中位數或舊版比較，不能代表不同機器、字體、長文字或影像版面。
字體快取及報告逐列寫入；PDF 仍沿用既有分塊／qpdf，未宣稱整個 job 記憶體固定不變。

最終驗收：Windows frozen 200% smoke 通過（含自動替補、私用字、報告頁碼）；報告按鈕橫向排列，增加生產摘要空間，最終 UI 3 個 targeted tests 通過。詳見 validation/document_designer_auto_font_20261002.json。
回退基線：b595766（字體診斷版），公共版本仍為 2.5.15 development build。
