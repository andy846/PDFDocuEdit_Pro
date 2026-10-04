# Document Designer — 現有 PDF 分封、流水號及 Barcode 套印升級計劃

日期：2026-10-02。基線：91cd0e3（版面升級 11e2fc6、v3.0 Splash）。
目前 Template schema 6；上次驗收 1,088 個專案測試通過。

**本文件是下一階段實作及驗收規格，不代表功能已完成或已有發布日期。**
新功能名稱：Existing PDF / Production Overlay。產品入口沿用 Document Designer。
本次目標是處理已完成內容的整份 PDF，按固定頁數分封，加入可核對的識別碼。
原有 CSV／Excel／虛擬紀錄生成模式繼續使用。

## 1. 交付情境與完成定義

使用者提供一份 3,000 頁 PDF，每封信固定包含 3 個來源 PDF 頁面。
單面模式下，輸出 1,000 封、3,000 頁；每封共用一個 Envelope sequence。
每頁再依指定位置加入文字及 Barcode，原信件的內容與次序保持一致。
不要求另外建立 1,000 筆 CSV，不需要逐頁設定背景或手動貼 Barcode。

| 來源頁碼 | 信封序號 | 封內來源頁次 | 單面輸出頁碼 |
| --- | --- | --- | --- |
| 1–3 | 000001 | 1、2、3 | 1–3 |
| 4–6 | 000002 | 1、2、3 | 4–6 |
| 2998–3000 | 001000 | 1、2、3 | 2998–3000 |

軟件完成：來源可匯入、分封、視覺套印、預覽、保存重開、背景執行、取消、
輸出可開啟、Barcode 可解碼、逐封／逐頁對照與 reconciliation 全部通過。
入信機完成：另須指定機型／設定的實際紙本讀碼及入封驗收；不以軟件解碼冒充機器驗收。

## 2. 已有能力與需要補上的能力

| 現有元件 | 本次用途／需要新增 |
| --- | --- |
| SequenceSpec、composition/data/sequences.py | 重用起始值、增量、補零、前後綴；新增由 PDF 分組驅動的 Envelope 序號 |
| Element、Renderer._barcode() | 重用文字、Code 128、QR、向量條碼、quiet zone 與現有字體處理 |
| 三頁以上固定模板 | 重用封內版面概念；來源 PDF 頁面由分組映射切換 |
| Canvas／Properties／Undo | 重用套印物件編輯，不另建大型編輯器 |
| QProcess worker、JSONL events、cancel file | 新增來源檢查／套印預覽／套印生產任務 |
| 分塊 PDF、qpdf、validate_pdf_file、唯一 job directory | 重用輸出和提交策略；避免整份輸出留在記憶體 |
| JobResult、CSV／JSON 報告 | 新增來源頁、信封、紙張、Barcode 及逐頁映射統計 |

現有背景只接受單頁 snapshot，production 會重複模板背景。
本功能需新增真正的 PDF 頁面來源；不能把 3,000 頁變成 3,000 個模板頁／QWidget。

## 3. UI 與完整操作流程

Document Designer → File → New → Existing PDF Overlay。
新建選擇只在開始工作時出現，保留現有精簡工具列與底部單行狀態。

1. **Source**：選擇整份 PDF。立即顯示待檢查列，背景讀取頁數／加密／簽署／頁面幾何。
2. **Envelopes**：Pages per envelope = 3；顯示 3,000 source pages → 1,000 envelopes。
3. **Print mode**：明確選擇 Simplex 或 Duplex；確認 PDF page 與 sheet 的意思。
4. **Sequence**：EnvelopeSeq、Start 1、Increment 1、Digits 6；預覽第一及最後序號。
5. **Design**：在來源頁面上拖放文字／Barcode，選擇套用範圍及格式。
6. **Preview**：Envelope 18 / 1,000；Source page 52；Letter page 1 / 3。
   切換封、封內頁與插入空白頁，顯示實際 Barcode payload。
7. **Production**：先顯示來源頁數、封數、紙張數、輸出頁數、預計條碼數、輸出位置與阻止項。
8. **Generate stamped PDF**：背景執行；提供封數／頁數進度與 Cancel。
9. **Results**：Open PDF、Open envelope report、Open page/barcode report、Open report folder。

左側改為 Source / System fields / Layers；中間是目前来源頁＋套印物件；右側沿用 Properties。
目前不需要的 CSV 匯入、增加／刪除模板頁操作不在 Overlay 模式啟用，提供原因提示。
來源頁序由原 PDF 決定；編輯來源內容可使用既有 Organizer／Editor，再重新綁定來源。
預覽只處理請求的一頁，快速連續切頁採用既有 generation ID，拒收舊結果。

## 4. 分封規則與來源一致性

對來源頁 p（對使用者一基）、每封來源頁數 k：

- envelope_index = floor((p - 1) / k) + 1
- letter_page = ((p - 1) mod k) + 1
- envelope_count = source_page_count / k
- envelope_sequence = start + (envelope_index - 1) × increment

k 必須為正整數。來源為 0 頁、頁數不可被 k 整除或序號超出 profile 固定位數時阻止生產。
例如 3,001 頁／3：指出最後一封不足三頁，不能自動忽略或默默補完。
初版使用整份 PDF、順序遞增、固定分封，不加入任意分支／內容識別／可變頁数。

檢查來源的大小、修改時間、頁數和雜湊。生產時背景串流複製為 job 專用只讀 snapshot，
複製前後核對來源，預覽驗收的雜湊與生產 snapshot 一致才執行。
已變更、缺檔或轉向另一份 PDF → Needs review，重新分析後由使用者核對。
GUI 不同步 stat／open 網路路徑；各 worker 擁有自己的 PDF document。
來源檔絕不被輸出覆蓋；原始資料不寫入人類可讀 job log。

## 5. 單面、雙面與紙張計數

首輪 core smoke：**單面、每封三個來源 PDF 頁面 = 三張紙**。
雙面也是本升級的明確交付門檻，但不可在未確認使用者實際印法前假定其規格。

| 列印模式 | 每封來源頁 | 每封輸出頁 | 每封紙張 | 1,000 封總輸出頁 |
| --- | ---: | ---: | ---: | ---: |
| 單面 | 3 | 3 | 3 | 3,000 |
| 雙面、每封從新紙正面開始 | 3 | 4（含末尾空白背頁） | 2 | 4,000 |
| 雙面、使用者實際指三張紙 | 需確認是否 6 个來源頁 | 依確認結果計算 | 3 | 依來源頁數計算 |

雙面採明確「Each envelope starts on a new sheet」設定；來源頁為奇數時，
逐封末尾加入空白背頁，預覽、page map 及統計都標明，不能默默插入。
來源頁次、輸出頁次與紙張次分開命名；不把 3,000 頁當成 3,000 張紙。
Barcode 可選每個來源頁、所有輸出頁（含插入空白頁）、每張紙的正面、首張或末張。
插入空白頁可以只印控制標記；IsInsertedBlank 表示沒有原始信件內容，不表示必定完全無墨。
若機器只讀紙張正面，控制欄位應使用 SheetNo／SheetCount，實際 profile 按機器文件設定。
列印驅動的反序／縮放／翻面方式與實際入紙方向都列入紙本驗收。

## 6. 系統欄位與套用範圍

| 欄位 | 例子 | 意義 |
| --- | --- | --- |
| JobId | job 的唯一 ID | 此次執行身份；不直接推定機器接受此字串 |
| EnvelopeSeq | 000018 | 每封共用、可設定起始值／增量／補零 |
| EnvelopeIndex / EnvelopeCount | 18 / 1000 | 此次分組次序／總封數 |
| SourcePage | 52 | 原 PDF 頁碼；插入空白頁時為空 |
| LetterPage / LetterPageCount | 1 / 3 | 封內來源頁次及來源總頁數 |
| OutputPage | 69（雙面例） | 最終輸出 PDF 頁碼 |
| PrintPage / PrintPageCount | 1 / 4 | 封內輸出頁次，含插入的空白頁 |
| SheetNo / SheetCount | 1 / 2 | 雙面實際紙張次序／總紙張數 |
| Side | Front / Back | 實際紙面 |
| IsFirstSheet / IsLastSheet / IsInsertedBlank | 布林值 | typed rules／機器 profile 使用 |

文字例：{{EnvelopeSeq}}；Barcode 使用相同結構化欄位來源。
系統欄位不能被 CSV 或自訂序號覆寫；衝突在驗證階段列明。
套印物件可選：所有來源頁、所有輸出頁（含插入空白頁）、首頁、末頁、指定 LetterPage、每張紙正面。
規則與固定範圍交集決定實際出現位置；預覽和 production 共用同一計算。

## 7. Barcode builder 與機器 profile

初版重用 Code 128／QR；沒有證據時不宣稱任何一種一定適用某機器。
使用可編輯 token 清單：literal、field、指定寬度的數字、分隔符。
不加入 eval()、Python、任意外部程式或自製完整腳本語言。

**僅示意、不代表已符合入信機協議：**
[EnvelopeSeq:6][LetterPage:2][LetterPageCount:2]
→ 第 18 封第 1 頁：0000180103。
雙面／紙張控制應按已確認協議選擇 SheetNo／SheetCount 等欄位。

Properties 顯示：類型、X/Y/W/H（mm）、旋轉、module size、quiet zone、可讀文字、
套用範圍、目前 payload、第一／最後封樣本及容納檢查結果。
預檢全部預期 payload：字元集、固定長度、欄位寬度、序號範圍、Barcode 尺寸。
沿用向量條碼與白色 quiet-zone backing；用戶在預覽確認不遮蓋原信件內容。
Barcode symbol 本身的校驗與機器協議的 payload check digit 分開處理，不能混用。
需要協議 check digit 時，只實作規格明確且有測試樣本的算法。

profile JSON 含 schema、名稱、機型／讀碼設定、symbology、token 格式、位置、
單／雙面、讀取面、送紙／PDF 順序假設及驗收紀錄。
Generic profile 可用於軟件測試，明確標為「Machine validation pending」。
取得機型、文件及實際樣本後才建立該機器 profile；不得預填看似通用的入信控制協議。
初版不宣稱跨 job 自動保留流水號區間；新的 job 由使用者檢查起始及末尾序號。

## 8. PDF 內容與版面保存

採來源頁面複製＋套印層，保留文字層、已嵌入字體、向量及影像。
不能先把整頁 rasterize 再輸出；不能套用目前固定背景 show_pdf_page 路徑來冒充全頁保留。
新 Overlay painter 使用既有 Element/文字/Barcode 邏輯，不重做整個 Viewer。
來源字體資源不得被套印 font subsetting 改寫；新嵌入字體與原 PDF 資源分開處理。

在旋轉後可見 CropBox 的左上角以 mm 定位；工作器統一轉換到 PDF 座標。
保留 MediaBox／CropBox／旋轉。每封同一 LetterPage 的頁面幾何須一致；
若不同，列出來源頁碼並 Needs review，初版不默默縮放原頁。
不同封內頁角色可以有不同大小，使用相應 role 的套印版面。
以旋轉 0/90/180/270 度、非零 CropBox 原點、不同封內頁尺寸測試實際對位。

MVP 預檢阻止仍有密碼、數碼簽署或未支援互動表單的來源，顯示原因及可處理入口。
註解的可見性／列印旗標須有明確複製政策與測試；不宣稱完整保留所有文件級互動功能。
套印本身是可見內容變更，來源只有在獨立輸出 PDF 中增加指定標記。

## 9. 資料模型、檔案及實際 repo 對應

新增（名稱可在 P0 按現有命名慣例微調）：

| 檔案 | 職責 |
| --- | --- |
| composition/pdf_source/model.py | PdfSourceSpec、分封／列印參數、來源身份 |
| composition/pdf_source/source.py | metadata、snapshot、來源一致性、頁面幾何檢查 |
| composition/pdf_source/planner.py | 惰性 EnvelopeRecord／PagePlan、單／雙面、空白頁映射 |
| composition/overlay/model.py | OverlayLayout、位置套用範圍、OverlayJob |
| composition/overlay/barcode_profile.py | token 格式、payload 驗證、機器 profile 版本 |
| composition/overlay/renderer.py | 來源頁複製及共用 painter；無 Qt |
| composition/overlay/generator.py | snapshot→分塊套印→驗證→reconciliation→提交 |
| composition/overlay/reports.py | envelope/page/barcode map、control.csv、job.json |
| composition/designer/pdf_source_dialog.py | Source／Envelopes／Print mode 設定與預檢 |
| composition/designer/overlay_controls.py | 模式切換、封／頁導航、內建欄位、結果 |
| composition/designer/barcode_profile_dialog.py | token builder、機器 profile 與樣本預覽 |
| tests/composition/test_pdf_overlay_*.py | 模型、來源、幾何、條碼、取消與 UI 測試 |
| scripts/benchmark_pdf_overlay.py | 來源規模、各階段時間與兩程序峰值記憶體 |

套件重用：PyMuPDF、fontTools、PyQt6、Pillow、python-barcode、segno、qpdf 及已打包的
pyzbar 解碼器。此方案不要求新增依賴；P0 若發現必要新套件，先核對授權、Windows及PyInstaller。

小幅修改：template/model.py、serializer.py；data/sequences.py；engine/renderer.py 抽出共用
paint_elements 服務；production/model.py 共用摘要欄位；worker.py 增加
inspect_pdf_source / preview_overlay / generate_overlay tasks；designer 的 chrome/workspace 接入。
既有 generate() 保持模板模式；不令其認為 3,000 個來源頁等於 3,000 個模板頁。
core/viewer.py 和 main.py 沿用現有 Designer／worker 入口，不加入分封或 Barcode 業務邏輯。

資料契約：EnvelopeRecord 是一封的身份和來源連續範圍；PagePlan 是來源頁→輸出頁／紙面的映射；
OverlayJob 固化來源 snapshot、設定、profile 和 job identity；UI 不把 fitz document 傳入引擎。
初版所有 group 由公式惰性計算，CSV 逐列寫出，不建立每頁 QWidget 或所有渲染頁 list。

建議 .pdcx schema 7：source_mode = template / existing_pdf；pdf_source 為來源參照與分封設定；
overlay 設定存布局／適用範圍／profile。舊 1–6 模板載入預設 template mode。
舊讀取路徑／保存後字體及規則需回歸；舊 build 不能讀新 schema，保存新格式前有備份。
3,000 頁來源不複製入 JSON；保存相對參照及 fingerprint。缺檔提供 Locate PDF，重定位後核對身份。
覆寫 schema 的最終字段名稱在 P0 定稿，不在本計劃階段提前修改版本常數。

## 10. 生產、QC、報告及取消

Source check → Snapshot → Group/Page plan → All payload preflight → Compose chunks →
qpdf assembly → Output open/page-count check → Barcode QC → Reconcile → Reports → Publish。

- 以整封邊界落盤；記憶體 chunk 上界是 configured chunk + 最大每封輸出頁數 - 1。
- 共用 worker 進度／cancel file；安全點停止。原生 PDF 呼叫不能假稱即時可中斷。
- 取消／失敗保留診斷，不發布半成品 PDF；整 job 驗证后同父資料夾提交。
- 生產 Barcode QC 按預期 mark 逐個渲染小區域並解碼，比對**確切 payload**；
  不只檢查 encoder 成功。剪裁解碼解析度及失敗策略在 P0 feasibility 確定並 benchmark。
- mark 的數量依套用範圍计算：每來源頁 = 3,000；首頁 = 1,000；雙面每張紙正面 = 2,000。
- Machine profile 指定 required read positions，每封需覆蓋所有必須讀取的紙面／頁面。
  條碼被 rules 隱藏或位置缺漏時阻止輸出；不能因 expected marks 被算成 0 就宣稱通過。
- 機器接受的唯一性規則由 profile 定義；只有信封 ID 可以合法在同封多頁重複。
- 每封映射须連續、沒有缺頁／重複／跨封混入；所有來源頁正好使用一次。
- source pages + inserted blanks = output pages；successful envelopes = input envelopes；
  expected marks = rendered marks = QC decoded matching marks，全部相等才 Complete。

報告：

| 檔案 | 最低欄位 |
| --- | --- |
| envelopes.csv | JobId、EnvelopeIndex/Seq、來源起末頁、輸出起末頁、來源頁數、輸出頁數、紙張數、Status |
| pages.csv | SourcePage、OutputPage、EnvelopeSeq、LetterPage、PrintPage、SheetNo、Side、IsInsertedBlank |
| barcodes.csv | OutputPage、ObjectId、ProfileId/version、Payload、Placement、Decode status、Error |
| control.csv | Source/snapshot hash、來源／輸出頁數、封數、空白頁數、預計／實際／QC 條碼數、開始／完結時間、狀態 |
| job.json | 版本、身份、固定參數、來源身份、profile snapshot、各計數及結構化錯誤；不含信件文字 |

錯誤須指出封、來源頁、輸出頁、物件或欄位；無生成頁時相應值保持空。
CSV 逐行寫入，沿用對 Excel 公式字串的處理；機器 payload 的準確原值保存在結構化資料。
範例正常結果：Input envelopes 1000、Successful 1000、Source pages 3000、Output pages 3000、
Expected/Decoded barcodes 3000（單面每頁）、Failed 0。

## 11. 里程碑及開工次序

| 階段 | 交付 | 完成門檻 |
| --- | --- | --- |
| P0 — 盤點／規格／probe | schema、UI 線框、來源複製／旋轉／字體資源 probe、機器待確認事項、benchmark 方法 | 審查風險清單；沒有 Viewer 大改；不同 geometry及原字體可保留 |
| P1 — 分封與欄位 core | PdfSourceSpec、snapshot、EnvelopeRecord、PagePlan、序號與payload builder | 無 GUI：3000頁→1000封映射正確；3001頁明確阻止；保存／重定位測試 |
| P2 — Headless套印 | 單面來源複製、文字／條碼、chunk、QC及報告；再加入雙面空白映射 | 3000頁實際PDF E2E、全部條碼解碼、原頁對位；雙面4000頁／2000紙張映射正確 |
| P3 — Designer操作 | Source入口、分封設定、視覺定位、scope、封／頁預覽、save/reopen | UI可完成兩種印法；預覽与生产相同；沿用960×640及760×580精簡布局 |
| P4 — 生產健全化 | 預檢、進度／取消、來源變更、失敗診斷、結果操作、profile管理 | 強制失敗／取消不提交PDF；reconciliation mismatch不Complete；正式輸出與逐頁map一致 |
| P5 — 機器實測／發布QA | 使用者提供的機型profile、列印與入封樣本、性能、全部回歸、Windows frozen驗收 | 紙本讀碼／分封按實際規格通過，完整pytest／Ruff／frozen smoke通過才標機器可用 |

每個階段有可測試的獨立 commit／checkpoint，先無 UI 跑通再接 Designer。
P1/P2 先用合成來源；通用功能與確認機型的工作可並行推進，不猜測設備協議。
若實際工作需要雙面，雙面 gate 未過時不能宣稱已完成使用者目標。
計劃階段只增加文檔，不開始大型 monolithic patch。

## 12. 驗收矩陣與性能

必要案例：

1. 6頁／3頁一封：两封同封相同EnvSeq、跨封增加；原內容次序與新增碼逐頁吻合。
2. 3000頁／3：1000封，完整來源頁map、末封序號001000；逐个Barcode payload解碼。
3. 非1起始、非1增量、prefix／suffix、位數不足、0頁／餘頁、payload不合法／太寬。
4. 雙面奇數來源頁：每封隔開新紙、插入空白頁；來源／輸出／紙張／讀取面映射一致。
5. 首／末／所有頁及每張紙正面 scope；避免把信封序號重複判成非法。
6. 所有旋轉、非零CropBox、不同封內角色尺寸；原字体／文字層／影像／向量及註解政策。
7. 来源改动、删檔、替換、缺檔重開、加密／簽署／表單、來源輸出同路徑。
8. 取消发生在copy／compose／assemble／QC，失敗無正式PDF；報告能指出最後有效狀態。
9. 既有 CSV／TXT／Excel／虛擬紀錄、多頁模板、rules、font fallback、bulk typography 全部回歸。
10. Windows frozen build以真正子程序完成來源檢查、預覽、條碼解碼、生產及取消。

benchmark fixture：300、3000、10000、30000 個来源PDF頁；3頁分封時依序100／1000／
3333+餘1（拒絕測試）／10000封；另用9999頁做3333封正常性能測試。
分離文本／影像來源，記錄page size、檔案大小與可重跑的fixture hash。
量測snapshot／compose／assemble／QC時間、pages/sec、envelopes/sec、composer與assembler峰值、
輸出大小、temporary disk peak；不得只報compose时间而隱藏逐頁QC成本。
同機同fixture冷／暖各5次，報中位數及變異；M0量測後才定吞吐門檻，不先承諾幾秒跑完。

UI門檻：選來源操作不因檔案數量同步讀檔；GUI派送100ms內返回；處理時可切換／拖曳主窗。
預覽首張／跳到最後一封只處理請求頁；記錄首次和暖快取延遲，不生成完整3000頁才顯示。
用同環境重測既有Designer操作，計畫門檻為中位數不劣化超過10%；目前數值不是新功能實測結果。
不把「分塊500頁」等同整 job 固定記憶體：来源document cache與qpdf object memory另外量測。
普通CI用小fixture，release QA才跑大批量和紙本機器測試。

## 13. 範圍邊界及仍需提供的資料

本次包括：一份現有PDF、固定分封、單／雙面明確計數、序號、Code128／QR、範圍套印、
preview、保存重開、背景輸出、全部預期Barcode QC、來源／封／頁報告及指定機器profile。

後續：可變頁數／內容判斷分封、外部CSV逐封配對、多PDF合併來源、選封重印、
跨job號碼區間管理、特定OMR／控制marks、hot folders與production queue。
本次不加入AFP／IPDS、讀碼機控制驅動、完整印表機tray／finishing控制或自由腳本。

待用戶確認：入信機品牌／型號、可用Barcode格式樣本／文件、單／雙面及3頁的實際意義、
讀碼面／送紙方向、是否有payload check digit、條碼位置限制與預設起始序號。
這些決定機器profile與紙本驗收；通用分封／頁面來源／套印架構可先定稿。


## Implementation progress — 2026-10-02

- P0/P1: implemented; architecture note and tagged headless grouping/source/project models.
- P2: implemented; bounded vector overlays, exact barcode QC and reconciled reports. See [P2 validation](PDF_OVERLAY_P2_VALIDATION.md).
- P3: test workspace implemented; see [Designer test-build acceptance](PDF_OVERLAY_P3_ACCEPTANCE.md).
- Physical machine-profile acceptance remains pending hardware specifications and samples. This progress entry does not declare production readiness.
