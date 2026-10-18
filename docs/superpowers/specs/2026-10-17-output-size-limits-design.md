# 大量 Mail Merge：有大小上限的 PDF / PS 分件輸出設計

日期：2026-10-17。狀態：已獲 owner 批准實作；本輪不打包或發布。實作及驗收見 [操作／維護說明](../../BOUNDED_PRODUCTION_OUTPUT.md)。
基線：實際產品 worktree `print-composition-v3`，分支
`codex/deep-search-restore-layout`，HEAD `a5cd66db8d071c6db733c1f10e4f926751b83a76`，
包含目前未提交的 M0/M4、PS 效能及 Windows 專案開檔修補。其他 checkout 不修改。

## 1. 目標

讓數萬筆資料能安全產生多個有限大小的輸出包。用戶指定每個 PDF / PS 的
大小上限；系統另有不可在一般 UI 解除的安全上限。保持完整信封、品質、
全域編號、選紙、覆核、核對及原子發布。不是檔案位元組截斷或降低品質。

主要使用位置：Template Designer 的 Production、PDF Overlay、Batch 和 Visual
Workflow。共用一套 headless policy / packaging service，不建立另一個 PDF 引擎。

## 2. 現有架構與缺口（已讀碼）

| 現有元件 | 可重用部分 / 缺口 |
|---|---|
| `composition/production/generator.py:generate` / `_assemble` | 已按完整 record 寫約 500 頁的 chunk，之後仍組合成一個完整 PDF。chunk_size 是記憶體策略，不是成品大小限制。 |
| `workflow/pipeline.py:split_names` | 可按 count / field 建立 SQLite partition index；已有 10,000 件上限及檔名碰撞驗證。沒有 byte limit。 |
| `workflow/splitter.py:split_composed` / `qpdf_select` | 已有完整 record / envelope 分件、全域來源對照、媒體重編 file_page、逐件 PS、整組核對與原子發布。但必須先有整份已生成 PDF。 |
| `workflow/batch.py:_compose_item_claimed` | 先 generate，再 split_composed；即使選 Split Output，仍可能先形成巨型中間 PDF。 |
| `composition/media/postscript.py:export_postscript` / `_run` / `program_dsc` | 已有私有無損去重、保留解析度、進度、取消、選紙及完整 PS 解譯。沒有輸出大小監察及超限重分。 |
| `composition/media/planner.py:PrintPlan` | 單一實體紙張 / 正背面 / blank back / 全域 OutputPage 與 JobSheetNo 來源，必須沿用。 |
| `composition/media/ticket.py:export_rows` / `_ticket` | 已可逐件重建選紙包；JDF 有自己的 profile.max_ticket_bytes，不能誤當 PDF/PS 上限。 |
| `composition/production/journal.py:JobJournal` / `publish_package` | 已有獨占 claim、來源 binding、所有產物 checksum 及恢復檢查。 |
| `composition/review/service.py` / `authorization.py` | 已有 snapshot / fingerprint、明確批准及精確 outputs 檢查；動態再細分不能直接繞過原有 require_output_plan。 |
| `composition/production/model.py:JobResult`、Overlay reconcile | 現時單份生成要求 generated_files == 1；必須保留單件驗證，新增獨立整組彙總，不能單純移除核對條件。 |

結論：只替現有 Split Output 增加大小欄位不足。需要在生成期間分包，避免先建立
無上限的總 PDF / PS，再用現有服務逐件驗證及整組發布。

## 3. 建議上限（待設備資料確認）

容量顯示為十進位 MB：1 MB = 1,000,000 bytes；內部一律用整數 bytes 比較。

| 項目 | 建議預設 | 規則 |
|---|---:|---|
| 用戶每個 PDF 上限 | 250 MB | 可調 1–2,000 MB；不必填滿上限。 |
| 用戶每個 PS 上限 | 500 MB | PS 輸出時才適用；與 PDF 分開設定。 |
| 每件最多信封 | 1,000 封 | 額外、預設啟用的提早分件條件，可調整或關閉；byte / system 限制仍生效。 |
| 系統每個正式 PDF / PS 上限 | 2,000 MB | 一般設定不能提高或解除；不是聲稱所有 RIP 均支援 2 GB。 |
| 系統每件輸出頁數 | 20,000 頁 | 建議工程安全值，M0 性能驗證後凍結；只在完整信封邊界分件。 |
| 每個 Job 最大分件數 | 10,000 件 | 沿用現有 split_names 的安全數值；超出時阻止整組發布。 |

有效大小上限 = min(用戶值，系統值)。若之後取得可靠的設備上限，可再以設備值
作更低限制；今輪不假設 Printer Profile 已有可驗證的 RIP 檔案上限。

若用戶取消「自訂上限」，介面明示「使用系統安全上限」，不等於無限制。
JDF 保留既有 ticket 上限，亦是候選件須通過的條件；必要時再細分信封。

以上是建議產品政策，不是已完成的機器容量驗收。

## 4. 使用介面

放在 Production 的輸出檔名 / 路徑旁，標題為 **Output splitting**。
Design 頁只做版面、條碼及選紙；不在前後頁重複一套輸出設定。

```text
Output splitting
  Maximum PDF size:   [250] MB
  Maximum PS size:    [500] MB     (PDF + PS 才顯示)
  [✓] Maximum envelopes per part: [1000]
  Split only between complete envelopes
  System limit: 2,000 MB per file / 20,000 pages per part
```

- 修改後就地驗證，保留無效草稿，無效設定不能進入正式生成。
- Production Review 顯示有效上限、設定來源、完整信封策略、命名及預估件數。
- 件數估算明確標示「預估；大小可能令件數增加」，不假裝預先知道精確 PS bytes。
- 批准文字說明：允許按已覆核政策再細分，但不改內容、排序、數字或目的地。
- 執行時顯示目前件號、全域信封範圍、當前階段、實際 MB、已驗證待發布件數。
  最終件數未知時用「第 3 件」，不顯示虛構的「3 / 8」。
- Results 列出所有件的 PDF / PS、大小、信封範圍、頁 / 紙數、核對及報告；
  Open output 提供件清單，不能只開第一件而令人以為工作只有一份。
- 保留固定進度 / 取消及窄窗捲動；不加入新的 Task Center 或通知系統。

## 5. 生成與分件策略

### 5.1 一個工作、一套全域資料

先凍結來源 snapshot、排序、選擇、job identity、clock、媒體計劃及批准。
字體掃描 / 規則預檢沿用既有背景服務；不為每個小件重掃所有資料。

Render 使用原本 global record ordinal 和全工作 count。把有界 chunk、record /
envelope 的全域頁面區間、條碼 mark 及來源身分寫到 disk-backed 索引。
只組合當前候選件，禁止先建立全工作總 PDF。

### 5.2 邏輯分組與大小細分

1. 先沿用 Workflow 已設定的 count / field 分組；不能跨欄位群組合併。
2. 每個邏輯群組內，按原本次序及完整信封逐件收集。
3. 數量 / 頁數、已知資源量及先前實際轉換比例用作提早封件，預留例如 10%
   估算餘量。這是效能啟發式，並非合格證據。
4. 以現有 qpdf / chunk assembler 組合候選 PDF，讀取**實際大小**。
5. PS 模式沿用 export_postscript 的無損去重與原有輸出品質。
6. 任一實際 PDF、最終 PS 或 JDF 超限，候選群組按完整信封數二分，依次重試。
   每次群組嚴格縮小；不重新由第一筆生成全工作、不重置全域 ordinal。
7. 合格件才進行 / 完成條碼與完整 PS 回讀等既有 QC；保留所有要求的驗證。
8. 單一信封仍超限，停止該工作，指出 source record / envelope、實際大小及
   超出的限制。不得靜默拆信、漏頁、降低 DPI、壓低圖片品質或省略驗證。

同一候選 PDF + PS 共用完全相同的信封集合。一方超限時兩方一起再細分。
不把已生成 PS 按 bytes / %%Page 生硬裁切或拼接；每件重新用現有轉換器產生
有效 header/prolog/fonts/media setup/trailer。

### 5.3 超大暫存與磁碟安全

- 為 `_run` 增加指定候選輸出檔案的大小監察，達到候選安全預算就安全終止並
  reap 該 Ghostscript，回傳可再分件的 typed outcome，不當作正常完成。
- DSC 輸出採 counted writes；禁止超過有效成品上限後繼續複製整份。
- PDF native save 及外部 assembler 不能假設每次 write 都可被 Python 截住。
  以有界候選頁 / 封數、已知輸入 spool、檔案監察及磁碟餘量降低風險。
- **正式輸出大小是硬限制；暫存監察不是檔案系統 quota。** 監察間隔及 native
  I/O 可造成短暫 overshoot，不能承諾磁碟上任何暫存都永遠一 byte 不超。
- 生成前估計總輸出及 scratch 需求，逐件檢查剩餘磁碟容量；不足時安全停止。
  分件減少單檔及工作記憶體壓力，不會令全工作的總磁碟需求消失。
- 初輪按件順序轉換，不並行啟動多個 GS 搶 RAM；UI 保持既有隔離 worker。

## 6. 編號、選紙及結果安全

- Group Seq = 全工作信封序；Sheet Seq = 全工作紙張序，均保持現行 00 起及
  00–99 循環。跨分件不重置；一般 running sequence、QR payload 亦不重算。
- EOG 仍只取決於信封最後一張紙；分件邊界不能取代 EOG 邏輯。
- 雙面補白背面跟隨原信封，不能把 front/back 分到不同件。
- PrintPlan、全域 OutputPage / JobSheetNo 及 stock assignments 不變；僅每件
  File page 從 1 起，保留對照表。每件 PS 首面重新設定相同 Duplex/Tumble。
- 每件保留 PDF + PS / JDF 配對、獨立頁數 / 尺寸 / 條碼 / 選紙 / checksum。
- 集合核對：輸入信封 = 全件信封聯集；每封一次、不重複、不遺漏；頁 / 紙 /
  blank backs / marks 加總符合原計劃。生成結果不僅檢查第一個 output_pdf。
- 單件結果保留現有 reconcile；新增整組 reconcile，不放寬舊 generated_files==1。
- generated_files 繼續代表 PDF 件數；另報 artifact 數，避免 PDF+PS 當成兩倍信封。

## 7. 批准、發布與恢復

- 將有效大小政策、系統 policy revision、logical partitions、命名規則、來源 /
  範本 / prepared snapshot hash 及目的地納入既有 review fingerprint / receipt。
- 保留 `require_output_plan` 對舊明確分件清單的精確驗證。新增受控的
  partition-refinement 驗證：實際分件只能細分已批准群組，不能新增 / 遺漏 /
  重複信封、跨組合併、改路徑、降低檢查或擴大上限。不採通配授權。
- 調整任何上限需重新覆核。worker / engine 入口仍要求有效 session authorization。
- 在同一 job 私有 staging 完成所有件、manifest、reports 和核對，最後以既有
  publish_package 一次原子發布。後件失敗 / 取消，不能把前件呈現為成功整組。
- JobJournal 加入受綁定的逐件 checkpoint（範圍、policy、輸入 hash、輸出 hash /
  大小、驗證狀態）。先按現有 attempt / claim 管理，不掃描任意同名 PDF 當成果。
- 若支援中斷後續做，必須重新覆核來源與政策並驗證 checkpoint；只重用匹配的
  私有件。缺少證據則隔離，不自動續做或重複發布。此 gate 未完成前不得宣稱
  已支援續做；不能為加入續做而削弱既有拒絕重跑 / 重複發布規則。

命名與資料夾結構採下節的共用政策，不再硬編固定的分件 suffix。
control.csv 與每件 source-map 記錄全域來源及 local file page；總 manifest 保存
每件實際 bytes、hash、QC 狀態及分件原因。取消 / 失敗不留下可誤用的正式 PS。

## 7A. 用戶可自訂的檔名結構（2026-10-17 補充）

### 介面：只有一個命名入口

在 Production 的既有 output filename 元件上擴充 **File naming**，不另外增加
兩個互相競爭的 filename / split filename 設定。

```text
File naming
  Preset: [Print summary (recommended) / Original name + part number / Custom]
  Structure: [固定文字 + 插入變數…]
  [x] Apply this structure even when there is only one part

  PDF preview: Statement_20261017_part000001_2000SHT_1000ENV_D.pdf
  PS preview:  Statement_20261017_part000001_2000SHT_1000ENV_D.ps
  Next part:   Statement_20261017_part000002_2000SHT_1000ENV_D.pdf
  [Save naming preset…]
```

- 以現有 `ui/variable_name.py:VariableNameEdit`、預覽與變數選擇模式擴充；
  不建立另一套 parser / token syntax。簡單操作可選預設，進階才編輯 pattern。
- 固定文字、欄位次序、分隔符、日期格式可由用戶設定；常用格式可保存為
  本機命名預設，與大小政策一起保存到 production preferences。
- PDF / PS 的副檔名由輸出類型加上；pattern 只描述共用 basename，避免兩者
  名稱或件號不一致。UI 清楚展示最後完整檔名。
- 舊 output_name 是未自訂時的 fallback；採用 Custom 後只使用有效的 NamingSpec，
  不同時套用舊 suffix。模式與實際來源在 Review 清楚顯示。
- 新工作建議預設為 Print summary，包含件號、紙數、封數及 D/S，且預設單件亦
  套用（件號 000001）。明確選擇 Original name 的舊模式才保留原單件名稱；
  Custom 依單件套用選項，所有實際結果在 Preview / Review 展示，不能暗中改名。
- 主內容可捲動，預覽即時但不在主執行緒掃完整 dataset；錯誤草稿保留。

### 變數與順序

沿用現有 `core/variables` 的宣告式 resolver、frozen job clock、白名單 transforms
及 Windows-safe filename helpers。現有 parser 的 namespace 白名單尚無 `part`；
下列是**計劃新增**的受控 namespace，不是目前已支援功能：

| 變數 | 意義 |
|---|---|
| `{{job.name}}` / `{{job.id}}` | 已凍結的工作名稱 / 完整 Job ID。 |
| `{{system.date|date:"%Y%m%d"}}` | 已準備工作日期，不是每生成一件再讀現在時間。 |
| `{{part.number}}` | 全工作件序，由 000001 起；固定六位、不可循環或截短。 |
| `{{part.total_number}}` | 最終總件數，同樣六位；只有完成分件後才有可靠值。 |
| `{{part.first_envelope}}` / `{{part.last_envelope}}` | 連續群組的全工作完整信封 ordinal，並非會 00–99 循環的 Group Seq。可選既有 pad 格式。 |
| `{{part.envelope_count}}` / `{{part.page_count}}` | 本件實際信封 / 輸出頁數。 |
| `{{part.sheet_count}}` | 本件實際實體紙張總數，取自 PrintPlan；不是 PDF 頁數。 |
| `{{part.print_mode_code}}` | 本件實際列印模式：Duplex = D，Simplex = S。 |
| `{{group.value}}` | 僅在明確 field 分組且值已確認一致時提供的分組值；同一引擎新增受控 namespace。 |

件號是**輸出件序**，與信封 Group Seq、Sheet Seq 完全不同；它不會到 99 重置。
最多 10,000 件，六位足以讓 Explorer 按檔名排序。part 值只可由 packager 提供，
不能讓 imported record 覆寫。

多件格式必須包含且保留 canonical `part.number`，不允許用 filter 截短 / 重置 /
替換其數字。件號之前只可有本 Job 固定的文字或 job/input/system 常量；會隨件
變動的群組值、範圍及頁數放在件號之後，確保字典序不被分組名稱搶先改變。
UI 以具體預覽解釋，無效格式不能 Apply，而不是產生後才靜默補另一個件號。

### 生產摘要檔名：紙數 / 封數 / 單雙面

owner 補充要求：操作員由檔名即可讀出本件如何列印、要準備幾張紙，以及包含幾封。
新工作的建議預設結構為：

```text
{{job.name}}_{{system.date|date:"%Y%m%d"}}_part{{part.number}}_{{part.sheet_count}}SHT_{{part.envelope_count}}ENV_{{part.print_mode_code}}

Statement_20261017_part000001_2000SHT_1000ENV_D.pdf
Statement_20261017_part000001_2000SHT_1000ENV_D.ps
```

- `2000SHT` = 2,000 張實體紙；`1000ENV` = 1,000 封；`D` = 雙面。
  命名本身使用無千位逗號的 ASCII 整數，UI 可顯示千位分隔。
- Duplex = D、Simplex = S，來自本件實際套用的列印計劃，包含 Media 關閉但
  Duplex 開啟的情況。不能由 output pages 的奇偶或是否有 Media 推測。
- 紙數包含列印計劃所需的紙張，但空白背面不再當成另一張紙；同一張紙的
  front/back 只計一次。不把入信機額外插頁數混入打印機的用紙數。
- 封數取本件實際完整 mailpiece 數；不是頁數、Group Seq 或封號頭尾相減。
- 精確例子：1,000 封、每封 3 個內容頁，Duplex 每封補一個空白背面，應是
  2,000SHT / 1,000ENV / D、4,000 output pages；不能誤算為 1,500 或 4,000 張紙。
  相同內容改用 Simplex，則是 3,000SHT / 1,000ENV / S。
- 多種 Stock 的檔名顯示總紙數，準備各種紙 / 紙匣的明細仍由 media summary
  與每件報告提供，紙張明細加總必須等於 part.sheet_count。
- 若同件真的有不同單雙面設定，不能隨意標 D 或 S。現有不支援的混合情況
  維持阻止；將來若支援，須按模式再分成一致的件，不在本輪默默增加混合列印。
- 數字及模式在最終分件完成後，由受信任的 PrintPlan / partition membership
  推導，命名、Results、control.csv、manifest、PDF/PS 及媒體報告必須一致。
  未知值不填 0 或猜 S，正式命名須阻止並提示。
- 紙數 / 封數 / D/S 是 Print summary 預設的必要資訊。Custom 仍可調次序、
  字眼、分隔符、日期及其他允許欄位；保留單一命名入口及完整預覽。

其他可選格式範例（假設最後共有 12 件）：

```text
{{job.name}}_{{system.date|date:"%Y%m%d"}}_part{{part.number}}
Statement_20261017_part000001.pdf
Statement_20261017_part000001.ps
Statement_20261017_part000002.pdf

{{job.name}}_part{{part.number}}_of{{part.total_number}}
Statement_part000001_of000012.pdf

{{job.name}}_part{{part.number}}_ENV{{part.first_envelope|pad:8}}-{{part.last_envelope|pad:8}}
Statement_part000001_ENV00000001-00001000.pdf
```

所有範例為示例，不代表實際工作必定 1,000 封一件；大小上限可能提早分件。
封號 first/last 範圍僅在該件全域封號連續時提供。field 分組若包含 1、3、5 等
非連續封號，不提供會誤導為 1–5 全部已包含的範圍命名，提示改用 group.value、
件號及實際 envelope_count；完整 membership 仍在 source-map / manifest 中記錄。

若用資料欄位命名，必須是明確 group.value 或已證明的 Job 常量。多個不同值
不能默默拿第一個客戶的值代表整件；不存在 / 多值時阻止，提示先分組或改欄位。

### 資料夾、報告與配對

第一輪固定使用唯一 Job 資料夾及件號資料夾，basename 可自訂；不開放任意
含變數的完整路徑，避免與輸出根目錄或 Windows 路徑安全混淆。

```text
<Job ID>/
  control.csv
  outputs-manifest.json
  part000001/
    Statement_20261017_part000001_2000SHT_1000ENV_D.pdf
    Statement_20261017_part000001_2000SHT_1000ENV_D.ps
    postscript-pages.csv
    source-map.csv
  part000002/
    Statement_20261017_part000002_2000SHT_1000ENV_D.pdf
    Statement_20261017_part000002_2000SHT_1000ENV_D.ps
    ...
```

PDF-only / JDF 沿既有輸出格式產生所需附件，不生成假的 PS。
Results 依受信任的 numeric part index 排序，並顯示 envelope 範圍及實際 bytes；
manifest / control.csv 與最終檔案名稱、hash、local / global page map 相符。

### 大小自適應及最終命名

候選件用不對外的內部 ID，不在候選第一次輸出時承諾最終件號。大小再細分完成
後，按已批准的輸出群組順序及群組內信封次序，分配最終 part.number；件號全工作
連續，不因 field 群組改變而重置。這保留既有分組順序，不額外依群組文字排序。

總件數完成前，UI 用「待分件完成」或明示示例值預覽 total，不用 0 冒充結果。
所有 pattern 解算、改名、sidecar / JDF 引用更新及最終一致性核對，都在 staging
內完成；不可發布後才回頭改名。需要修改附件 bytes 時重新驗證相關附件，
計算最終 artifact hashes 後才寫 completion manifest 並原子發布。

命名 pattern、單件套用選項、變數來源及命名 policy revision 同樣納入 review /
authorization / checkpoint binding。修改格式就撤回舊 review；恢復時不重新取
日期、不擅改已確定件號，亦不以 (_2) 或時間戳默默改名避免碰撞。

### 檔名安全與驗收

- 沿用非法 Windows 字元 / reserved device names 處理、case-insensitive
  duplicate 檢查、已存在檔案拒絕及 containment / junction 防護。
- 現有 helpers 的 filename 160 UTF-16 units / full path 240 units 限制保留。
  若過長，提示縮短工作名 / 文字欄位或改輸出位置；不能使用對整體檔名的
  自動截短而切掉件號、總件數或副檔名。必要時在現有 helper 增加可選 strict
  length 模式，預設既有呼叫行為不變。
- `A/B` 與 `A:B` 等 sanitisation 後撞名、大小寫撞名、來源覆蓋、空值、
  缺少件號、件號截短、前綴變動破壞排序，必須驗證並定位問題。
- 生成前驗證 pattern 語法、允許欄位、scope、固定路徑及示例；精確件數未知時
  不能宣稱所有最終路徑已預先算妥。每件確定後檢查實際名稱，整組發布前再核對
  全部唯一性及路徑；失敗不發布半組。
- 測試 1/2/9/10/99/100/999/1000/9999/10000 件號排序，總件數後定、oversize
  候選二分、group 重排、CSV/PS/JDF 配對、CJK / 長路徑、單件模式、取消與恢復。

## 8. 保存與舊檔相容

首輪把大小政策當作**生產工作設定**：ProductionJob / OverlayJob 新增可選的
runtime 大小及命名 policy，UI 以現有 preferences 記住最近選擇，review / job report 留存
本次實際值。Workflow/Batch 在輸出階段套用同一政策；既有 count / field node
繼續生效，但不是另一份互相打架的大小設定。

不在舊 `.pdcx/.pdflow` 內偷塞會被舊版忽略的安全設定。Template.from_dict 的
constructor 對未知 top-level 欄位亦非可直接向下相容。今輪建議先不改專案格式，
UI 清楚說明大小政策未嵌入 recipe；不同電腦在 Production Review 檢查當次政策。

若 owner 要求「每份模板 / Workflow 必須永久攜帶上限並強制舊版遵守」，需另立
明確 schema / 最低 reader 版本遷移；舊版不能安全執行新限制時應拒讀，不能
保存重開後默默丟失安全上限。不得聲稱同時零格式變更且舊版強制理解新語義。

## 9. 預計檔案安排

| 新增 / 修改 | 職責 |
|---|---|
| 新 `composition/production/output_policy.py` | headless 大小政策、系統常數、effective limits、輸入驗證及 typed oversize outcome。 |
| 新 `composition/production/output_naming.py`，擴充 `core/variables/parser.py`, `paths.py` | 重用既有 resolver 的件級命名 adapter、受控 part/group namespace、順序與唯一性 / 長度驗證；不新增 parser。 |
| 新 `composition/production/packages.py` | 有界候選、共用 record/envelope ranges、件級輸出 / QC、整組核對與 checkpoint adapter。抽取可重用 splitter 邏輯，不能複製兩份。 |
| 修改 `composition/production/generator.py`, `model.py` | 保留 Renderer / 字體掃描，改為輸出有界候選；整組結果與向下相容的 primary output 欄位。 |
| 修改 `composition/overlay/generator.py`, `model.py` | 以 EnvelopePlan / PrintPlan 的可變頁數整封邊界接入共用 packager。 |
| 修改 `composition/media/postscript.py`, `ticket.py` | PS output monitor / counted output；每件重建現有媒體及 QC。 |
| 修改 `workflow/pipeline.py`, `splitter.py`, `batch.py` | count/field 為邏輯分組；呼叫共用 packager，移除安全新路徑對完整總 PDF 的依賴；保留舊 helper adapter。 |
| 修改 `composition/review/service.py`, `model.py`, `authorization.py`, `presentation.py`, `dashboard.py` | review policy、受控 refinement、實際件數 / 大小 / QC，missing 不顯示成功。 |
| 修改 `composition/production/journal.py` | 有效政策 / 範圍綁定、逐件驗證證據、恢復與整組原子發布。 |
| 新 `composition/designer/output_limits.py`，修改 `workspace.py`, `overlay_workspace.py`, `production_review.py`、`ui/variable_name.py` 及 Workflow 輸出設定 adapter | 共用可捲動設定元件與唯一命名入口、state invalidation、source / override 摘要與多件結果入口。 |
| 新 / 擴充 tests + README、Production Review / PS / Workflow 文件 | 下列驗收；不把 probe 或客戶資料提交為 fixture。 |

## 10. 實施次序與驗收

### M0 — 政策與基準（先定上限，再寫引擎整合）

- 凍結 MB bytes、建議值、system limit 及 legacy / runtime-only 保存行為。
- 命名先做測試：新增 `test_output_naming.py`，擴充 `tests/test_variables.py`；驗證完整
  順序、保護件號、延後總件數、變數 scope、配對及所有碰撞 / 長度情況。
- 命名摘要驗收固定值：1,000 封 × 3 頁，Duplex = 2,000SHT / 1,000ENV / D，
  Simplex = 3,000SHT / 1,000ENV / S；Media 關閉 + Duplex 亦須正確。
- 新 `tests/composition/test_output_policy.py`：邊界等於上限、上限+1、0 / 負數 /
  bool / 非數字、disabled custom 仍受 system cap、PDF-only 的 PS N/A。
- 以合成簡單 / CJK / 圖片 / 特殊大信封量測候選成本與暫存 overshoot；不以
  小 PDF 大小乘單一倍率當作可靠 PS 尺寸保證。凍結頁數安全值。

### M1 — 共用有界輸出（Template + Overlay）

- 測試先行，保留一次全域 render / identity 與全域編號，再改成逐件組合。
- `test_output_packages.py`：30,000 / 50,000 合成筆、不同頁數、PDF+PS 配對、
  一頁巨圖、最後一封、零筆資料、count / field 邏輯分組細分。
- 邊界測試用小 byte cap 的 deterministic fixture，不必每次建立 2 GB 檔。
  大資料整合另測記憶體 / disk / 實際大小；無上限總 PDF 不應出現。
- 每個 artifact 均 <= effective cap；單封超限有明確定位且沒有正式輸出。

### M2 — PS / 選紙 / 編號 / 全件 QC

- 擴充 `test_postscript.py`, `test_postscript_performance.py`, `test_media.py`,
  `test_media_duplex_sheets.py`, `test_inserter_production.py`。
- PS 膨脹、raw / programmed 超限、JDF limit、轉換/回讀失敗、取消、disk full /
  report failure、worker 強制中斷；owned child process 必須 reap。
- 跨第 99/100/101 封及紙張邊界驗證 Group/Sheet 循環；一般 Seq/QR 同一工作
  不重置；EOG/duplex/blank backs/stock 與不分件參考一致。
- DPI / 字體 / vector 設定不變，分件 PDF 依原順序抽樣重組作 pixel comparison；
  PS 完整解譯與頁數 / 尺寸核對照舊，條碼依既有支援範圍逐件核對。

### M3 — Workflow / 批准 / 發布與恢復

- 擴充 Workflow split、`test_production_authorization.py`,
  `test_production_output_safety.py`, `test_production_recovery.py`。
- 未批准、竄改上限或命名 pattern、擴大範圍、跨組搬信封、改輸出 root、重複件號、丟件、
  同時執行、舊 checkpoint、hash 不符、後件失敗，全數拒絕錯誤發布。
- 發布前全部完成才對外可見；中斷續做若納入交付，須通過獨立 checkpoint gate。

### M4 — UI / 端對端驗收

- UI 只展示可靠預估與實際狀態；多件 output 不只顯示第一份。
- 命名 preset / custom pattern、三件預覽、PDF/PS 成對、單件選項、重新開啟偏好
  及無效草稿保留；命名改動令 review stale，未知 total 不假裝已確定。
- 紙數 / 封數 / D/S 預覽、最後小件、奇數頁補背面、多 Stock、排除資料及件級
  最終計數與實際檔案 / 報告一致；不得使用全 Job 總數命名每一件。
- 設定變更令 review stale；全件成功才顯示 published；取消不呈現半件成功。
- 960×640、200% scaling、深淺色、鍵盤、長路徑 / CJK filename、任務中關閉。
- 舊模板 / Overlay / Workflow 保存及既有 count / field 結果保持可讀和一致。
- Windows / macOS 原生與公司實機 RIP 各自留證據；模擬不能當設備容量驗收。

各階段先相關測試，最終依既有統一安排做完整回歸、原生打包及 owner 審查。
本計劃不授權現在寫產品程式、提升公開版本號、合併 main 或發布。

## 11. 主要風險與清楚限制

1. 實際 PS 大小不可由 PDF 大小精確推算；少量候選重試是必要成本。
2. 拆件會重複部份資源 / prolog，總 bytes 可能稍增；不以降低畫質抵銷。
3. 要在 final bytes、完整信封及 system cap 同時成立；單封無法容納時只能報錯。
4. 分件政策影響批准內容及 output list；不得只修改 UI 或放寬 authorization。
5. 單檔有限不等於磁碟總用量有限；整組原子發布仍需容納所有待發布件及 scratch。
6. Native PDF/GS 輸出監察可能短暫超限；不能宣稱跨平台強制 filesystem quota。
7. 舊版不能自動理解新安全政策；首輪 runtime-only 保存及後續可能需要的
   schema migration 必須明確，不默默丟限制。

優先建議：以 **完整信封 + PDF/PS 實際大小硬驗證 + 生成中分件 + 原有整組
原子發布** 作第一個可交付整體；不要先做「整份生成後才切檔」的表面修補。
