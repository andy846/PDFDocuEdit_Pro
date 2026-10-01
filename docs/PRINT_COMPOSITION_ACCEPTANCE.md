# Print Composition MVP 開發驗收報告

日期：2026-10-01（香港）。狀態：**MVP 已實作並完成本機驗證；可攜開發版可試用。**
正式版本 metadata 仍為 2.5.15；本報告不宣稱 v3.0 已公開發佈。

## 開發隔離與回退

- 穩定基線：main 的 a4a7ed0，v2.5.15。
- 回退 tag：pre-v3.0-v2.5.15。
- 實作分支：feature/print-composition-v3，附於 print-composition-v3 worktree。
- 原始 measurement-calibration checkout／功能分支保持原狀。
- 所有里程碑儲存在本機 Git；沒有推送 remote。
- 舊 V3 搜尋／工具工作流方案由新 Print Composition 方案取代；歷史由 Git 保留。

## 里程碑與實際交付

| 里程碑 | 實際檔案／設計 | 狀態 |
| --- | --- | --- |
| M0 架構盤點 | PRINT_COMPOSITION_ARCHITECTURE.md；選定獨立視窗、worker、qpdf 分批管線 | 完成 |
| M1 Template / Data | composition/template；composition/data；嚴格 JSON v1、來源映射、SQLite 快照 | 完成 |
| M2 Headless Engine | composition/engine；精確字體、字體子集、背景、文字、圖形、圖片及條碼 | 完成 |
| M3 Workspace | composition/designer；選取、拖動／縮放、屬性、獨立 Undo/Redo、save/load | 完成 |
| M4 Import / Preview | 編碼／分隔符／標題設定、原始欄名、拖欄位、單筆預覽 | 完成 |
| M5 Production | composition/production；QProcess worker、進度、取消、單一正式輸出提交 | 完成 |
| M6 Reconciliation / Reports | 計數核對、control.csv、job.json、記錄錯誤及失敗診斷 | 完成 |
| M7 Performance / Regression | 串流基準、完整回歸、最終 Composition 測試、frozen／installed smoke、CI | 完成本機驗證 |

### 最小整合與相容影響

- ui/workspace.py：Welcome 入口。
- core/viewer.py：開啟／關閉擁有的 Composition 視窗。
- main.py：在載入 Qt 前 dispatch headless worker；開發封裝包含受環境旗標保護的 QA 入口。
- core/__init__.py：改為 lazy public exports，以移除 headless 匯入時意外載入 Qt；保留既有公開 import identity，回歸測試覆蓋。
- PyInstaller、build、package discovery、來源檢查及 CI：加入 opt-in 素材與測試；正常封裝預設不啟用 Composition。
- 原有 editor 文檔模型、Undo/Redo、偏好版本及公開版本號未遷移。Composition .pdcx 是新格式；未知版本拒絕載入。

### 驗證重點

來源 fingerprint 與引用欄位、禁止任意執行程式、固定頁數核對、不覆蓋來源、字體缺失／缺字／超出框阻止生產、失敗／取消不發佈部分 PDF、報告 CSV formula escaping、背景逐像素保真、條碼實際解碼。

CJK CID 字體子集保留 glyph IDs，並以 production／preview 逐像素比較驗證。只檢查文字抽取不足以證明印刷外觀。

## 測試結果與證據邊界

| 驗證 | 結果 | 本機證據 |
| --- | --- | --- |
| 完整既有＋Composition pytest | 877 passed，0 failures/errors/skips；1048 秒 | build/qa-composition/regression.xml |
| 最終 Composition pytest | 47 passed，0 failures/errors/skips；20 秒 | build/qa-composition/composition-final.xml |
| Ruff／source／素材 hash | 通過 | 本機命令結果、BUNDLE_INFO.json |
| Windows frozen，100% 縮放 | 100 筆生成、中文、背景、Code128/QR 解碼、save/reopen、editor 開檔通過 | build/qa-composition-final-frozen-1/result.json |
| Windows frozen，200% 縮放 | 相同完整工作流通過；GUI event loop 保持運作 | build/qa-composition-final-frozen-2/result.json |
| 安裝後 smoke | 隔離 QA AppId 安裝後實際 exe 通過；已完成 uninstall | build/composition-install-qa/result.json、安裝／移除 logs |
| 視覺檢查 | light／dark、960×640／200% 畫面已檢查 | frozen smoke screenshots |

完整 877 項回歸是在 ef0d335 檢查點執行。之後的修改集中在 Composition 字體／barcode 效能、背景異常清理、開發封裝名稱與文件；使用最終 47 項 Composition 測試及重新封裝 smoke 驗證。**不能將這兩次結果稱為在最終 HEAD 重跑了全部測試。**

完整套件未刪除／停用測試，也沒有降低覆蓋要求。QA installer 使用獨立 AppId／工作目錄，不註冊 PDF 檔案處理器；這不是既有正式安裝版就地升級驗收。

## 可重複效能基準

環境：Windows 11 x64，Python 3.12.14，Intel i7-1185G7（4 核／8 threads），PyMuPDF 1.26.6、qpdf 12.4.2。每筆固定一頁，chunk size 500，本機資料；**每格單次樣本，沒有宣稱五次中位數或冷／暖快取統計。**

Plain：一個英文變數文字物件。
Mixed：帳號、姓名地址、Box、Code 128、QR、Noto Sans CJK HK 中文文字。

時間包含字體掃描／子集、組版、合併、驗證及報告，不包含表內另外量測的匯入。MiB = bytes / 1,048,576。

| Fixture | 記錄／頁數 | 生成秒 | 頁／秒 | 組版峰值 MiB | 合併峰值 MiB | PDF MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Plain | 100 | 0.69 | 145.15 | 75.3 | 10.5 | 0.05 |
| Plain | 1,000 | 2.38 | 419.48 | 75.9 | 18.4 | 0.46 |
| Plain | 10,000 | 18.31 | 546.26 | 87.4 | 101.6 | 4.72 |
| Plain | 50,000 | 81.97 | 609.99 | 137.0 | 469.0 | 23.93 |
| Mixed | 1,000 | 14.39 | 69.48 | 190.6 | 42.1 | 2.89 |
| Mixed | 10,000 | 130.61 | 76.56 | 190.6 | 339.0 | 29.16 |
| Mixed | 50,000 | 561.44 | 89.06 | 260.3 | 1657.2 | 146.44 |

所有樣本均完成實際 PDF 重新開啟、頁數及記錄 reconciliation。峰值為不同 process 的各自 peak working set，不能將表內兩欄當作同一時刻相加。

可追蹤數據存於 docs/validation/composition_benchmark_20261001.json；完整本機 PDF／job.json 在 .benchmarks/composition-final/20261001-030447 與 .benchmarks/composition-mixed-final-verified/20261001-030855。

### 效能限制

1. 已驗證 50,000 記錄；100,000 的 extended benchmark 尚未執行。
2. 組版保留有界 chunk／字元集合，而 qpdf 物件表記憶體會隨頁數增加。不是整條管線的常數記憶體保證。
3. Mixed 50,000 頁約需 1.62 GiB assembler peak；低記憶體環境、大型背景／圖片／不同字體可能需要更多資源。
4. 測試資料是合成固定頁資料。沒有真實客戶業務 fixture；沒有保證所有網絡路徑、影像密集 PDF 或印刷機的產能。
5. 此版本未在每筆執行完整 veraPDF／印刷規範 preflight。已共用既有 PDF 開啟／頁數驗證服務；使用者可對最終 PDF 再執行原有 Preflight。
6. GUI smoke event-loop ticks 與畫面檢查證明工作不跑 GUI thread，但不是完整延遲分佈量測；沒有宣稱所有 GUI 操作小於特定毫秒。

## Definition of Done

使用者可從 Welcome 建立空白／PDF 背景、匯入 CSV/TXT、查看／拖入欄位、加入靜態／變數文字、編輯位置與字體、保存／重開、預覽多筆、在背景生成數千至 50,000 頁、收到 summary／reconciliation／CSV／JSON，以及清楚記錄錯誤。

既有完整回歸已通過；Windows 打包與隔離安裝 smoke 通過。可試用 MVP 已完成。正式發布仍需實際業務資料／實際列印驗收與既有版本／簽署／release 流程。

## 交付與下一版本

- 可執行目錄：dist/PDFDocuEdit Pro。
- 可攜 ZIP：release/PDFDocuEdit-Pro-v2.5.15-Composition-Dev-Portable-Windows-x64.zip；附 .sha256。
- 操作說明：PRINT_COMPOSITION_GUIDE.md。
- qpdf／字體／barcode 授權：THIRD_PARTY_NOTICES.md，素材版本／hash：build_assets/composition/BUNDLE_INFO.json。
- v3.0.1：真實資料驗收後的 bug fixes／效能／mapping 改善。
- v3.1：多模板頁、規則、條件 visibility、分檔。
- v3.2：重印、history、OMR／inserter marks、watch-folder prototype。

目前沒有正式 v3.0 發布日期，也沒有開啟排程、hot folder、自動背景續跑或遠端處理服務。

## 使用者測試修正：後續記錄的中文字形

失敗案例 Job 20261001-060341-350711a4：398 筆輸入，Record 2 / Field_2 在 Noto Sans 下缺少 U+7530（田）。當時未發佈 PDF；未保存的模板仍保留在原有視窗。

修正：

- 新拖入的變數欄位明確使用 Noto Sans CJK HK 作預設，已有模板不自動換字體。
- Objects 提供選取文字批量套用 CJK 字體，保留大小／粗體，可 Undo。
- 既有串流字元掃描同步檢查整批資料的字形，包括不許 subsetting 的字體。字元只需首次出現時檢查。
- 缺字在任何頁開始組版前阻止生成，保留記錄／物件／欄位錯誤及診斷報告。失敗的 preflight 記錄計入 failed/processed；successful 為已組版記錄，故此時為 0。
- 沒有靜默字體替代。

52 項 Composition 測試通過。新增案例以合成資料驗證第二筆才出現「田」、不許 subsetting 仍會檢查、398 筆選擇 CJK 字體後成功生成、預設字段字體顯示，以及選取字體操作／Undo。這不是宣稱已對該使用者的 398 筆真實資料完成重跑。

修正版另放 dist-font-fix，避免覆寫目前使用者開住的 executable。切換前先保存 .pdcx 並關閉原程式；可攜修正版名稱含 FontFix。

打包後再次驗證：完整 100 筆 Welcome／預覽／中文字體／條碼／保存及生產 workflow 通過（build/qa-font-fix-frozen/result.json）；獨立 frozen worker 匯入及生成 398 筆合成資料通過（build/qa-font-fix-398/acceptance.json）。

## Document Designer fixed multiple pages — 2026-10-01

The next accepted V3.1 milestone is delivered locally: fixed ordered pages per record, independent page size/backgrounds, page add/duplicate/delete/reorder/rename with Undo/Redo, selected-record/page preview, all-page font validation, explicit repairs and exact multi-page reconciliation.

Evidence: full existing Windows regression 920 passed (814.70 s); final Composition suite 88 passed, including the subsequently added between-pages cancellation case. Ruff/source checks passed. Native 200%, frozen 200% and installed 100% smoke generated 100 records / 200 pages; QA installation was removed. Original schema-2 customer template migrated to schema 3 with all 398 output pages pixel-identical to its previous successful PDF and the same single glyph repair.

Five non-overlapping plain-text trials: 1,000 records / 2,000 pages median 2.71 s, composer 77.0 MiB, assembler 27.8 MiB; 10,000 records / 20,000 pages median 25.95 s, composer 99.2 MiB, assembler 191.5 MiB. Synthetic fixed-page/local fixtures, without separately controlled cold/warm cache; no comparison to older one-page measurements or guarantee for image-heavy documents. Raw samples/selection: validation/document_designer_multipage_benchmark_20261001.json.

This is a development delivery; public version remains 2.5.15. Schema 3 reads v1/v2; older builds cannot open newly saved schema-3 projects. Use Save as to retain an older project for rollback. Conditional visibility/basic rules and output splitting remain next milestones. See DOCUMENT_DESIGNER_MULTIPAGE.md for operation and limits.


## Document Designer usability consolidation - 2026-10-01

Code checkpoint 066d7bb: retained incomplete property drafts, validation before page actions,
per-page zoom/selection, compact Properties tab below 1100 px, searchable fields, double-click
properties, canvas context menu/scoped shortcuts, grouped text Undo and async preview protection.
Cross-object Undo restores the selected object's exact font controls. Engine/schema unchanged.

Final full regression: 934 passed, 0 failures/errors/skips (818.68 s); Composition 101 tests,
including 13 new interaction cases. Ruff/source/diff checks passed. Final Windows frozen 200%
and QA-installed 100% workflows passed: 100 records / 200 pages, exact Windows faces, CJK,
explicit glyph repair/audit, barcodes, save/reopen, reconciliation and existing editor open.
QA installation removed. Synthetic data/offscreen Qt; customer source data was not changed.

See DOCUMENT_DESIGNER_USABILITY.md and validation/document_designer_usability_20261001.json.
Portable development delivery: dist-designer-usability; public version remains 2.5.15.
Rollback to the preceding milestone: document-designer-multipage-dev-20261001.

## Document Designer conditional rules - 2026-10-01

Checkpoint 889b4e6: declarative All/Any text/Decimal conditions, per-object visibility and
one alternative text/barcode/static image branch; shared headless preview/glyph preflight/
production selection. Object properties/Rules menu, row limits, sample check, Undo/Redo,
copy/page duplication, explicit font repairs and static asset save/load are retained.
Schema 4 reads v1-v3; old builds cannot open newly saved projects.

Full regression: 989 passed, 0 failures/errors/skips (797.17 s), including 156 Composition
cases / 55 new rule cases. Ruff/source/assets/diff checks passed. Native 200%, final frozen
200% and installed 100% passed 100 records / 200 pages; QA installation removed.
Four-record synthetic demo exercised GS/IS and high/low balance branches; its four output
pages rendered without warnings, and qpdf --check returned 0.

Five-trial 10,000-record / 20,000-page conditional fixture median: 41.11 s, composer 101.7 MiB,
assembler 223.0 MiB. No-rule median 27.00 s (+4.04% vs prior same-fixture baseline).
Synthetic local measurements with uncontrolled cache/host activity; see raw samples and
limitations in validation/document_designer_rules_benchmark_20261001.json.

Operation, limits and delivery: DOCUMENT_DESIGNER_RULES.md. Full validation manifest:
validation/document_designer_rules_20261001.json. Independent executable folder dist-rules;
portable ZIP name includes Dev-Rules. Previous Git rollback: document-designer-usability-dev-20261001.
Public version 2.5.15 unchanged; output splitting remains a later milestone.

## Document Designer selected-text typography - 2026-10-01

Current-page multi-selection now supports partial typography changes, shared exact Windows
face preparation, retained per-object fonts/sizes/repairs/rules and one Undo per batch setting.
Full regression passed: 1010 tests, zero failures/errors/skips (848.93 s) on 5196c18.
The subsequent toolbar-only draft-context protection passed all 179 Composition tests on
4871ead, including 23 new bulk-format cases. Final frozen 200% and installed 100% workflows
passed 100 records / 200 pages; QA install removed; portable CRC and SHA256 verified.
The first regression attempt had a Qt native style failure; the new test application fixture
was changed to session scope and the full suite rerun. No product/theme code or test disabling.

Full scope/evidence: validation/document_designer_bulk_format_20261001.json.
Operation/limits: DOCUMENT_DESIGNER_BULK_FORMAT.md. Executable folder: dist-bulk-format.
Git rollback: document-designer-rules-dev-20261001; current tag:
document-designer-bulk-format-dev-20261001. Engine/schema/public version unchanged.


## Document Designer running sequences — 2026-10-01

Named stateless sequences and generated quantity mode are implemented on 266b437.
Schema 5 reads v1–4; source field collisions are blocked. Shared values serve record/page
preview, exact-font/rule preflight, PDF text/barcodes and production logs. No viewer rewrite,
new dependencies or public version change. Old project originals must be retained for rollback.

Full Windows regression: 1041 passed, zero failures/errors/skips in 1234.32 s.
Composition-focused run: 208 passed, including 29 sequence cases.
Frozen 200% and installed 100% acceptance passed existing CSV/CJK/background/rules/fonts
and generated 100 records × two pages with QR/Code128 decoding; QA installation removed.
Portable ZIP CRC/SHA256 verified. No tests disabled; one legacy-schema fixture was updated
to contain only actual schema3 keys, retaining the original font/glyph-repair pixel assertion.

Three-trial synthetic one-page sequence medians: 1,000 records 2.40 s; 10,000 22.05 s;
50,000 157.41 s. Composer 50,000-record peak median 137.7 MiB; assembler 465.7 MiB.
Host load/cache uncontrolled and other QA/build tasks overlapped parts of the trials.
Do not treat these as real-printer/customer-PDF or constant-process-memory guarantees.

Evidence: validation/document_designer_sequences_20261001.json and
validation/document_designer_sequences_benchmark_20261001.json.
Operation/limits: DOCUMENT_DESIGNER_SEQUENCES.md. Delivery folder: dist-sequences.
Current tag: document-designer-sequences-dev-20261001; rollback:
document-designer-bulk-format-dev-20261001.


## Document Designer Excel input — 2026-10-02

Excel adapter on abc1110 supports .xlsx / .xls, sheet/header selection, aliases, ISO dates,
text/simple-format leading zeros, explicit saved-result formula policies and SQLite snapshots.
Schema 6 reads 1–5. Workbook sheet/import configuration distinguish report record identity.
Existing sequence/render/font/validation/reconciliation machinery is reused; no viewer
rewrite, new dependencies or public version change.

Full Windows regression: 1073 passed; zero failures/errors/skips; 1004.65 s.
Composition: 240 passed, including 32 new Excel/CSV regression cases.
Native/frozen 200% and installed 100% acceptance passed the existing editor/Designer flows,
plus XLSX sheet/header/mapping, CJK/zero-padding/date/sequence/Code128/QR generation,
save/reimport, and actual OLE/BIFF8 XLS generation. XLSX and XLS each reconciled 100 pages.
QA installation removed; portable ZIP CRC/SHA256 verified. No tests disabled.

Three-trial synthetic inline-string XLSX import medians: 1,000 rows 0.40 s / 44.6 MiB;
10,000 1.20 s / 47.0 MiB; 50,000 5.25 s / 52.5 MiB. This measures import only, with
uncontrolled host load/cache and overlapping regression; not a guarantee for shared-string
or style-heavy workbooks, XLS memory, actual customers or printers.

Evidence: validation/document_designer_excel_20261002.json and
validation/document_designer_excel_benchmark_20261002.json.
Guide: DOCUMENT_DESIGNER_EXCEL_IMPORT.md. Delivery: dist-excel.
Tag: document-designer-excel-dev-20261002; rollback: document-designer-sequences-dev-20261001.
