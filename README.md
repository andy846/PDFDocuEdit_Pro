# PDFDocuEdit Pro V3.0.4 — Release Candidate

**PDF Editing & Print Production Suite** — PDF Workspace 與 Document Designer 共用一個主視窗，支援 PDF 編輯、Mail Merge、現有 PDF 套印及可覆核的生產工作流。文件及客戶資料在本機處理。

v3.0.4 候選版本準備同步提供 **Windows x64 登入版**及 **macOS Apple Silicon 登入測試版**。
現有 GitHub 正式版 v3.0.3 保留；只有兩平台原生打包、簽章及發布驗收完成後才公開新 Release。
Mac 測試版尚未完成 Apple Developer ID／公證，OCR 及 Intel 不在此輪支援範圍。

## v3.0.4 登入與雙平台更新

- 首次登入需連線核對已批准帳戶；離線批准分別保存於 Windows Credential Manager／macOS Keychain。帳戶入口位於 Settings／More commands，不佔用主工具列；啟動 Splash 自動顯示版本。
- 現有 v3.0.3 Windows Managed 版可透過原有更新入口升級到登入版。舊 Launcher 保留 schema-1 格式，新版程式額外驗證已簽署的登入版／帳戶項目；後續更新亦保留相容附件。
- 新 Windows 登入版及 Mac Managed 登入版使用各平台專用簽章更新。Mac 第一次使用請安裝 Managed DMG；舊 standalone 版本須先手動更換為 Managed 版。
- 更新仍由使用者確認：檢查、下載驗證、保存，再更新並重啟。取消保存不重啟；等待登入不觸發回退；真正啟動失敗可恢復上個版本及設定。
- 兩平台由同一 commit 打包。先補齊同一 Draft Release 的安裝包、更新包、manifest、簽章及校驗碼，核對完成再公開；CI 不持有更新私鑰。

操作及發布門檻見 [雙平台發布流程](docs/UNIFIED_RELEASE.md)。
已有 Mac v3.0.3 登入测试版的升級步骤及验收清单见 [Mac 候選版實測](docs/MAC_UPDATE_ACCEPTANCE.zh-HK.md)。

## macOS 對齊開發

Apple Silicon 對齊及登入工作已整合至 v3.0.4 候選來源；目前 Windows 正式發布仍保留 v3.0.3。
專用 Mac CI 建置原生 qpdf、libzbar、Ghostscript 及離線 veraPDF／JRE，再檢查
Designer、Workflow、Production Review、Barcode 與 PDF／PS 生產功能。
Mac 分支新增 Managed DMG、自動更新及私人帳戶登入：與 Windows 共用登入批准、離線使用、撤銷覆核及簽章更新／回退核心。
私人版使用 macOS Keychain，更新按平台及私人／公開渠道隔離。原生 Mac 安裝包驗收仍需通過 CI；OCR、Intel 及正式 Developer ID 簽署／公證另待後續。
下載 Mac CI artifact 不代表已完成實機或打印機驗收。詳見 [macOS 開發與部署紀錄](docs/MACOS_PARITY.md)。

## 最新開發更新：生產覆核

另有独立的 **Windows／macOS private account 測試分支**：首次登入須在線取得帳戶批准，
其後使用 Windows Credential Manager 保存的批准可離線啟動；背景核對不傳送 PDF 或客戶資料。
v3.0.4 新安裝及 Windows Managed 更新目標均為登入版；v3.0.3 舊安裝保持原有行為直到使用者選擇升級。
帳戶配置、停權／登出行為及驗收限制見 [Private account 開發及驗收](docs/PRIVATE_AUTH.md)。
私人測試版登入畫面沿用程式圖示及深淺色主題；帳戶入口位於 More commands／Settings
選單，顯示登入帳戶，提供核對及登出操作，不佔用主工具列。

此節描述已整合的候選功能；GitHub 最新公開版本仍為 **3.0.3**，發布狀態以 Release 及验收紀錄為準。

- **Template Designer／PDF Overlay**：按 Generate PDF 或 **Review Production…**，先選輸出資料夾並進入 **Production Review**。背景檢查完整資料後，才可 **Confirm production**；覆核及預覽不生成正式 PDF／PS／JDF。
- **Visual Workflow**：保留原有資料／分封及逐工作批准；Run Ready Jobs／Run approved branches 會再進入共用生產覆核，逐一選擇工作核對。
- **Summary**：輸入、保留及排除數量、輸出頁數、實體紙張、補白背面、Simplex／Duplex、紙種需求、PDF／PS／JDF backend、輸出名稱及分檔計畫。
- **Mailpieces／Paper sheets**：每頁 50 筆，可搜尋、跳至封號或輸出頁；選一張紙即可查看正反面。Workflow 篩選／排序後仍保留來源記錄及 PDF 頁面定位。
- **Barcode values／Issues**：顯示實際 payload、I25 各段及 Generic segments、位置與尺寸。錯誤定位到封／記錄、頁面、欄位或物件，可返回既有設定；字體自動替代提供檢查 CSV。
- **安全確認**：錯誤、取消、未完成或已過期的覆核不能確認；警告須勾選已覆核。修改設定或來源後須 Check again，生成前再核對來源雜湊及工作設定。預覽與正式生產沿用同一 Job ID、時間及輸出命名。
- **版面**：窄視窗切換 Mailpieces／Details；Barcode values 獨立成頁，保留紙面預覽空間。切回設計後仍可返回 Production Review。

詳見 [生產覆核操作、架構及驗收](docs/PRODUCTION_REVIEW.md)。畫面及預覽不代表打印機／入信機已通過實機驗證；成品條碼解碼及 reconciliation 仍由正式生成流程執行。本輪只做相關測試，完整回歸與 Windows 打包留待統一驗收。

## V3.0.2 功能基礎

- **Conditional Mail Merge**：按清單處理多個資料檔，條件分流到不同模板；整批流水號、例外覆核、逐分支批准及來源記錄對照。
- **Template Designer**：跨頁同位置／同頁底距離複製欄位及 Paste in place；修正文字框太小時畫布空白問題。
- **PDF 間尺**：精準端點、上方／左側紙面尺、可拖拉參考線、精確位置設定及磁吸。
- **雙面選紙**：允許多頁模板重用紙種，按實體正反面檢查選紙設定。
- **Inserter I25 — 18 digits**：Group／Sheet 預設由 `00` 起、實體紙序、EOG／校驗碼自動計算、六個插頁條件及成品解碼 CSV。

詳見 [v3.0.2 發佈說明](docs/RELEASE_NOTES_3.0.2.md) 及 [驗收記錄](docs/RELEASE_VALIDATION_3.0.2.md)。

## V3.0.3 更新：PDF 生產整理與共用變數

本版新增 PDF 生產整理工具、共用變數及以下修正。詳見 [v3.0.3 發佈說明](docs/RELEASE_NOTES_3.0.3.md) 與 [驗收記錄](docs/RELEASE_VALIDATION_3.0.3.md)。

- **Splash 自動版本號**：啟動畫面由 `core.resources.APP_VERSION` 繪製版本文字；日後更新程式版本毋須再修改 `Splash.png`。支援 Windows 顯示縮放及圖片載入失敗時的備用畫面。
- **Generic Barcode 表格編輯**：雙擊 Name、Length 或 Source 可直接修改；位置及預覽自動更新。選取一段後按 **Edit selected segment…** 可跳至詳細設定，指定資料欄位、固定值及流水號。
- **每頁流水號雙面修正（H5）**：Duplex 開啟而 Print Media 關閉時，仍按實際輸出 PDF 頁數計算，包含補白背面；補白頁佔號但不印流水號。三頁模板從 1 開始時，前兩筆為 `1、2、3、空白` 及 `5、6、7、空白`。預覽、正式生成及 Job log 使用相同計算；每筆流水號及 I25 實體紙序語義不變。受此問題影響的舊成品需重新生成，既有輸出檔不會自動修正。
- **Add Image／Signature Image 位置與尺寸**：新加入的圖片會自動選取並轉回 Browse，可拖動位置、拖四角縮放，右側 Manage 可輸入 X／Y／Width／Height（mm）。預設保留比例，Shift 可自由縮放；支援刪除及 Undo／Redo，保存 PDF 後重開仍可編輯。Apply 固定於設定面板底部，鍵盤移到設定欄會自動捲動至完整顯示；點頁面空白處取消選取。未修改的尺寸保留原始精度，避免顯示四捨五入造成超出頁面。圖片保持一般 PDF 頁面內容；Signature Image 是簽名圖片，不是數碼簽署。舊版插入或外部 PDF 的未標記圖片不會自動變成可編輯物件。
- **Keyboard Shortcuts Review**：Windows 各工作區 Redo 支援 `Ctrl+Y`／`Ctrl+Shift+Z`；Designer 專案分頁可用 `Ctrl+Tab`／`Ctrl+Shift+Tab` 切換。文字欄位保留編輯快捷鍵，Save 及命令面板仍可使用；修正自訂全域鍵、連續按鍵前綴及跨模式衝突，主工具列提示與 Help → Keyboard Shortcuts 同步顯示實際綁定。詳見 [快捷鍵檢查及使用說明](docs/KEYBOARD_SHORTCUT_REVIEW.md)。

- **Tools → Flatten PDF**：亦可從 PDF Workspace 左側 **Utilities → Flatten PDF** 開啟。先 Analyse，再按選定頁面把可見標註／AcroForm 外觀轉為頁面內容；保留搜尋文字、頁面尺寸與方向。只能產生新副本，現有編輯內容與 Undo 不會被取代。
- **Tools → PDF Repair / Production Normalise**：亦可從左側 **Utilities → PDF Repair / Normalise** 開啟；未開文件時可選擇來源 PDF。Safe Repair 重寫結構；Normalise 可明確選擇移除 JavaScript、附件、metadata、平面化及裁切異常 CropBox。Maximum Compatibility／Rasterise 是獨立、需確認的影像重建選項。
- 兩工具共用背景處理、取消、驗證、新工作資料夾及 CSV／JSON 紀錄；可選現有 Production Preflight 前後比較。**Choose PDFs for batch processing…** 逐檔處理，保留成功結果及失敗紀錄。
- **Visual Workflow** 新增 Flatten PDF、Repair / Normalise PDF 節點，放在 Input／Merge 之後、Extract 之前。Check to this step 的 PDF 只留在暫存工作區；正式輸出仍須 Review。需覆核的修復結果請先在 PDF Workspace 檢查。
- **共用輸出命名**：Template Designer、Mail Merge batch、PDF Workflow 及新工具可用 `{{input.stem}}_{{job.id}}.pdf`、`{{system.date}}`、`{{workflow.sequence|pad:6}}` 等。預覽會指出無效／缺失值；Windows 檔名清理只影響輸出名，不改來源資料。
- 新 PDF Workflow 使用格式 **v6**，因舊版不認識 PDF 整理節點；v1–v5 繼續讀取，v5 條件分支流程不變。舊流程升級會保存新副本；含新節點的 v6 檔案不能由 v3.0.2 舊安裝版開啟。模板／Overlay／Barcode 格式不變。

**範圍**：不保證修復所有 PDF；XFA、缺失或不支援的外觀會阻止相應操作。Hidden／Invisible／NoView 物件會保留並在分析及報告列明，可能仍具互動性。非光柵化透明度平面化未提供；透明度／Actions 未能全面檢查時會標示 Not checked。數碼簽署副本須確認失去原簽署有效性；加密來源不得靜默解密輸出。Rasterise 不會自動 OCR，會失去原有搜尋文字、向量及互動內容。

Designer 文字仍沿用 `{{Field_Name}}` 保存語法，已共用解析／取值服務；新增 namespace／transform 首先用於輸出命名，尚未擴展至模板文字、Barcode、資料夾或自訂報告欄位。
詳見 [開發實作與驗收範圍](docs/PDF_PRODUCTION_TOOLS_DEVELOPMENT.md)。

今日功能、程式完整性及版面鞏固的修正與針對性測試，見 [2026-10-08 開發鞏固紀錄](docs/DEVELOPMENT_CONSOLIDATION_2026-10-08.md)。

搜尋連續提交時會先取消並等待舊任務完成，只執行最後一次要求；舊進度與結果不再更新介面。PDF 套印載入較小專案、切換分封及 Undo／Redo 時，先調整封號及頁碼範圍；無效計劃顯示錯誤並停止預覽及生成。

昨日 PDF 生產工具、變數、條碼及間尺更新的進一步覆核，見 [2026-10-07 更新鞏固紀錄](docs/DEVELOPMENT_CONSOLIDATION_2026-10-07.md)。Flatten／Repair 批次支援共同頁碼範圍、逐檔錯誤及完成數量摘要；純警告確認保留分析，修改處理設定或密碼仍需重新分析。輸出命名預覽會說明非法字元清理，內部工作 PDF 與成品分開存放。

## V3.0.0 功能基礎及目前操作指南

| 工作區 | 能力 |
| --- | --- |
| PDF Workspace | 保留閱覽、編輯、標註、Organizer、Preflight、OCR、搜尋、列印及間尺；Merge PDFs 使用獨立分頁，可調整來源、選頁與預覽。 |
| Template Designer（Document Designer 模式內） | 多頁 PDF 背景或空白模板、CSV/TXT/Excel 資料、Merge Fields、流水號、Code 128／QR／I25、條件規則、批次文字與幾何設定、間尺與磁吸對齊。 |
| PDF 套印 | 固定或覆核後的可變頁數分封；加入序號、文字及入信 Barcode，保留來源頁對照及 QC 紀錄。 |
| Visual Workflow | 可視節點設定 Visual Extraction Region、資料映射／處理、不同信件模板、預覽覆核、生成、選紙及分檔；批次工作各自記錄狀態與結果。 |
| 生產輸出 | PDF、PDF + Canon offline JDF 或 **PDF + PostScript**；以 Stock 指定各頁用紙，Printer Profile 保存各環境的 MediaType／MediaPosition 對應。 |

### 快速開始

1. 在主工具列切換 **PDF Workspace｜Document Designer**。切換保留當次工作、未保存修改與背景任務。
   **Document Designer** 是模式名稱；內含 **Template Designer**（模板設計）、**PDF Overlay**（現有 PDF 套印）及 **Visual Workflow**（生產流程）。
2. 已加工的 PDF 可用 **Send to Designer** 建立一般多頁 Mail Merge 專案或 PDF Overlay 專案。
   多頁 Mail Merge 的共用頁腳：選取一組欄位，用 **Edit／右鍵 → Repeat on template pages…** 一次複製到指定頁，保留座標、尺寸及設定；可選相同頁底距離。**Ctrl+Shift+V（Paste in place）** 跨頁貼上保留原位。副本獨立，整次複製可一次 Undo；放不落目標頁時會提示並阻止。
3. 一般模板：匯入資料 → 放置 Fields／Sequences／Barcode → 逐筆預覽 → 保存 `.pdcx` → Generate Production PDF。
4. 已完成 PDF：Auto Detect Mailpieces → 查看規律與例外 → 接受邊界 → 加入套印物件 → 生成及核對。
5. 選紙輸出：一般 Designer 的 **Page → Print Media / Stocks…**；Overlay 的 **Production → Print Media / Stocks…**；Workflow 則配置 **Media Assignment** 節點。

### 入信機 I25：18 位 preset

在 Template Designer／PDF Overlay 選取條碼物件，於右側 **Barcode → Preset** 選
**Inserter I25 — 18 digits**，再按 **Configure…**。Visual Workflow 重用所選模板或套印專案嘅 preset。

- **Sequence**：Group＝信封流水號，第一封 `00`、第二封 `01`，同封所有紙張一致，`99 → 00`。Sheet＝整個生產 job 的實體紙張流水號，第一張 `00`、逐張遞增，跨封不重設，`99 → 00`；雙面正反面共用紙序。完整封號及整批紙號另存於報告。
- **Inserts**：六個插頁各可選不插入、固定插入或宣告式條件；兩組編碼各以 1／2／4 相加。VS1／VS2 出信 BIN 分流保持 Off。
- **Customer info**：預設九個零，或選擇恰好九位 ASCII 數字欄位；保留前導零，不截短或補數字。
- **Printing / Placement**：Production 頁及生成前覆核畫面可直接選 Simplex／Duplex，並顯示輸出頁數、實體紙張及所需條碼數；已有 Media 時沿用其設定。兩頁 Duplex 模板只需第一頁正面條碼；Simplex 的每頁均為獨立紙張，需要各自正面條碼。每張紙正面一個控制條碼，雙面奇數頁補空白背面且不印條碼。模板可一次套用至所需正面頁、同一座標，列出目標與更新數量並支援一次 Undo。
- **Preview**：分段顯示 18 位數字與條碼圖。第 7 位自動 EOG、第 8 位固定零、第 18 位按前 17 位乘 `31313131313131313` 的 modulo-10 補數自動計算；不額外加校驗碼。
- 生產前逐封檢查資料、尺寸與正面條碼數量，超過 99 張紙或資料錯誤會阻止生成。生產後解碼成品並輸出 `barcodes.csv`，包含完整封號、封內紙號（Sheet）、整批實體紙號（Job sheet）、輸出頁、由 00 起嘅整批循環條碼紙序（Sheet sequence）、插頁碼、EOG、校驗碼及核對結果。

依校驗公式，首封第一張非結尾、無插頁、客戶資訊全零為 `000000000000000000`；第二張結尾為 `000100100000000006`。
每個獨立 Production Job 重新由 `00` 開始，包含 Workflow 各獨立 job。舊 I25 專案生成前會提示 **Update I25 sequences**；確認才將 Group start 改為 `00`、Sheet 改成跨封計數，並重設機器驗證為 pending。可用一次 Undo 還原，Generic profile 不受影響。Production 的 **Apply barcode to required fronts…** 可預覽後同位置套用至所需正面。設定仍需配合實際入信機尺寸、方向與讀取位置驗證。

### Generic Barcode：自訂長度及資料來源（開發更新）

Template Designer／PDF Overlay 選取 Barcode → **Configure… → Generic — custom barcode layout**。
Visual Workflow 使用同一模板／套印設定，並在檢查及正式生成時核對。

1. 設定 **Total length**，加入及排序各個 Segment。每段自行定義長度；表格顯示起止位置、來源及編碼預覽，長度總和必須等於 Total。
2. **Source** 可選固定文字、匯入／映射資料欄（CSV/TXT/Excel）、系統值，或 Running sequence。系統的 EnvelopeSeq 與資料中同名欄位分開；PDF 擷取值由 Workflow 的資料欄傳入。
3. **Numeric** 只接受非負 ASCII 數字，按設定長度補零；已有零 padding 會先正規化，例如 `000001` 配兩位輸出 `01`。**Text** 完整保留內容及前導零，必須恰好符合長度，不裁切、不補字、不移除空白。I25 最終仍要求偶數位 ASCII 數字；Code 128 要求可列印 ASCII，Unicode 可用 QR。
4. **Running sequence** 可選模板已有的流水號，或建立僅用於條碼的流水號，設定 Start（預設 0）、Increment（預設 1）及每筆／封、整份輸出頁或每封實體紙序範圍。双面正反面共用紙序。
5. 長度溢位預設停止；只有 Numeric 流水號可明確選 **Cycle**，例如兩位 `98 → 99 → 00`。資料欄永不循環或截短。`barcode-cycles.csv` 記錄每次循環的完整原值、編碼值、封號、輸出頁、物件與來源列；以工作紀錄／Workflow 來源對照追查原始資料。

預覽只核對目前與可用樣本；未載入資料時可先保存結構有效的設定，但不能代替生產驗證。生成前在背景檢查全量可見條碼的值、格式和尺寸；完成後解碼最終 PDF，`barcodes.csv` 記錄 payload、頁面及核對結果，數量或內容不符不發布 PDF。可取消，失敗保留診斷報告。

舊 Generic profile 保留原有 payload；按 **Convert to fixed-length layout…** 才轉換。不明長度及 Total 必須自行確認，不會猜測或自動變更舊結果。新固定 layout 使用 profile v3；模板保存為 v12、套印 v8，保留舊檔讀取；18 位 Inserter preset 的編碼不變。此開發更新未變更公開版本號或發布安裝包。

詳細架構與針對性驗收見 [Generic Barcode Layout 說明](docs/GENERIC_BARCODE_LAYOUT.md)。

### V3.0.1 更新：Visual Workflow 節點核對

選取節點後，用右側 **Settings｜Input｜Output｜Issues** 核對設定與資料。
**Check to this step** 處理完整輸入並保存暫存結果；Mail Merge 須明確選擇一個 batch job。
Input／Output 每頁 50 筆，Enter 搜尋、來源身分及修改前後對照；**Inspect field…** 可查看其他欄位與長內容。
Compose／Output 的試跑只檢查及提供單筆預覽，不發布生產檔案或批准工作。

任務進行中可選取節點、平移、縮放及查看已完成結果。窄窗可用底部 **Split view／Steps／Canvas／Details** 切換面板。
來源或上游設定改變後須重新檢查。正式生產仍由既有 Review／Run 流程執行。
詳見 [實作說明](docs/VISUAL_WORKFLOW_INSPECTION.md) 及 [v3.0.1 發佈說明](docs/RELEASE_NOTES_3.0.1.md)。本次亦更新程式內 **Help → README**，補齊 Designer、Workflow、分封及選紙操作入口。

### V3.0.2：Conditional Mail Merge

在 Document Designer 的 **Create Visual Workflow → Conditional Mail Merge**，或首頁 **For each file → Route by template** 開啟。

- **For each Data File**：加入多個 CSV/TXT/Excel 檔案，或擷取資料夾的一次性清單；按清單次序使用相同資料整理流程。
- **Batch Sequence**：跨整批資料編號。排序／篩選先於編號；例外記錄保留號碼，正常記錄不重新補號。模板用 `{{WorkflowSeq}}` 引用預設序號欄位。
- **Route by Condition**：以 All／Any 條件分到不同信件模板；只接受唯一匹配。無匹配且沒有明確 fallback、重複匹配或無效資料，進入 Exceptions。
- 每個資料檔 × 模板分支有獨立核對、批准、PDF／選紙輸出及結果。Collect Results 整合紀錄與報告，不合併 PDF。
- **Check to step** 與 **Check & Preview** 不發布生產檔案；Input／Output／Issues 每頁 50 筆，保留來源記錄及序號。先覆核並批准，再 **Run approved**。
- 部分生產須確認已覆核例外／被阻擋項目。生成記錄對照 CSV、例外 CSV、批次摘要及 JSON；已完成且未改動的有效輸出在重新檢查時保留。

這是有界的資料檔迭代及單層條件分支，不支援自由回接、巢狀迴圈或 PDF 分封分支。原有 v1–v4 工作流保持可讀；新功能使用 v5 `.pdflow`。詳細操作及驗證見 [分支工作流說明](docs/VISUAL_WORKFLOW_BRANCHING.md)。

### PostScript 與 Printer Profile

在 **Printer profile** 選擇 `PDF + PostScript (no separate job ticket)`，配置每個 Stock 的 **MediaType／Colour** 或 **MediaPosition**，保存環境 profile。先用 **Export paper-selection test PS…** 列印少量測試紙，再正式生成。

**Profile library…** 可按設備篩選本機設定、預覽完整選紙規則或單獨 printer 對應表，並在背景匯入 JSON／資料夾。取消載入保留目前草稿；設備 profile 仍需實機選紙驗證。詳見 [使用指引](docs/POSTSCRIPT_USER_GUIDE.md#profile-library)。

PS 模式保留核對 PDF，另產生 PS、逐頁選紙 CSV、機器可讀報告及 Job log；分檔後每個套件有自己的 PS。程式會解譯 PS 核對頁數及尺寸，失敗／取消不發布半成品。

實際紙匣編號、紙張屬性及 DFE 佇列覆蓋行為需要實機確認；通用 profile 不包含未驗證的機型 preset。PS 透明效果可能平面化，提供 300／600／1200 dpi 設定。詳見 [PS / Profile 操作指南](docs/POSTSCRIPT_USER_GUIDE.md)。

### 生產核對與邊界

- 生成在背景執行，提供取消、輸入／處理／成功／失敗筆數、頁數、輸出檔案及 reconciliation。
- Windows 字體供模板選用；缺字可逐字修復或自動使用可用字體，保留主要字體並記錄替代頁數／字元。
- 自動分封依文字層、位置、頁碼及識別資料；證據不足時要求覆核，不宣稱能替任何 PDF 自動證明信件完整。
- 入信機的 barcode value／讀取位置，以及打印機選紙仍須按實際設備規格配置。軟件驗證不代表實機已驗收。

詳見 [v3.0.0 發佈說明](docs/RELEASE_NOTES_3.0.0.md) 及 [正式驗收記錄](docs/RELEASE_VALIDATION_3.0.0.md)。以下 V2 章節保留作歷史更新記錄。

## V2.5.16 Deep Search 與間尺增強

- Deep Search 逐次記錄關鍵字命中，可依檔案、關鍵字及來源篩選，並開啟 PDF 對應頁面。
- 重新設計可列印的 HTML 搜尋報告；CSV 每次命中各佔一列，匯出可選全部或目前篩選結果。
- 間尺支援逐頁比例校準、編輯已儲存量度線端點，並在重新校準後更新相關標籤。

詳見 [v2.5.16 版本說明](docs/RELEASE_NOTES_2.5.16.md)。

## V2.5.15 PDF 間尺

- 在已開啟的 PDF 頁面點選兩點，量度文件定義的紙面直線距離。預設以 mm 顯示，也可切換 cm；縮放和旋轉不改變結果。
- 同頁可保留多條暫時量度線，逐條刪除或清除；可把選中的線與數值儲存為 PDF 標註。
- 量度線端點使用垂直於量度線的短刻線，保留較大的拖動範圍；可按住拖拉、放手完成，或點選兩點。端點拖動保留捉取偏移，按住 Shift 保持畫面上的水平／垂直。開啟量度工具時自動顯示上方及左側紙面輔助尺，跟隨縮放、捲動及 mm／cm 單位，並標示游標位置與參照頁。退出工具後隱藏，輔助尺不會寫入 PDF。
- 輔助尺以目前顯示方向的頁面左上角為零，顯示紙面尺寸；校準後的實際距離另在量度線上顯示。
- 可由上方尺拖出水平參考線、左側尺拖出垂直參考線；Alt＋拖拉移動已有參考線，拉到頁面外刪除，Esc 取消。右擊參考線可設定精確位置或刪除；點左上角頁碼／單位區，或右擊輔助尺，可顯示／隱藏參考線、清除本頁及開關磁吸。
- 量度起點、終點及端點拖動可磁吸至參考線與頁邊，吸附距離固定為 8 個畫面像素；Alt 暫停磁吸，Shift 保持水平／垂直。參考線跟隨縮放及旋轉，只保留於本次文件工作區；重新載入文件會清除，不會寫入 PDF，亦不影響 PDF 的 Undo／Redo。
- 量度採用 PDF 紙面尺寸，不推算圖則或地圖的比例尺長度。

詳見 [v2.5.15 版本說明](docs/RELEASE_NOTES_2.5.15.md)。

## V2.5.14 Viewer and form improvements

- Fill AcroForm fields directly on the PDF page with a right-side field list, staged preview, Apply and one-step Undo.
- Keep form drafts when changing tools or tabs, with prompts on save and close.
- Improve viewer layout, search result page actions, and page extraction/deletion workflows.
- Provide a managed Inno Setup installer for first deployment alongside signed update and Managed Portable packages.

See [release notes](docs/RELEASE_NOTES_2.5.14.md).

## V2.5.10 啟動與大型文件效能

- Welcome 重新設計；最近檔案使用快取，網路路徑在背景檢查。
- 開檔背景處理、虛擬化頁面與縮圖、按需載入全文分析。
- 修正長文件拖動縮圖捲軸後的頁碼位置偏差與空白預覽。
- 超過 1,000 頁的 Advanced Page Organizer 使用虛擬列表、背景準備、進度與安全取消。
- 加入 PERF 效能紀錄及大型文件回歸測試。

詳見 [版本說明](docs/RELEASE_NOTES_2.5.10.md) 與 [效能報告](docs/STARTUP_AND_OPEN_PERFORMANCE.md)。

## V2.5.9 閱覽與縮圖修正

- 移除文件分頁列上方額外白線。
- 大量頁面的縮圖介面按需建立，快速捲動優先載入可見頁並自動補齊。
- Continuous / Facing 持續捲動時定時刷新，不再等停止捲動。
- Facing 從第 1、2 頁開始並排；單數末頁獨立顯示。

## V2.5.8 表單、比較與快捷鍵

- **Utilities → Fill PDF form**：填寫既有 AcroForm、預覽常見公式計算、套用後一次 Undo；支援圖片及手寫簽名外觀。
- **Utilities → Compare PDFs**：並排查看文字／視覺差異、插刪頁、手動配對，以及背景運算與取消。
- **Preferences → Keyboard shortcuts**：自訂命令按鍵及作用範圍，檢查重複與多段快捷鍵前綴衝突。

簽名外觀不構成數位簽章；XFA 及未支援的腳本不會執行。詳見 [操作與實作說明](docs/IMPLEMENTATION_STAGES.md)。

## V2.5.7 navigation fixes

Page thumbnails, viewer navigation and page counts stay synchronized; fitting PDF pages are centered. See [fix details](docs/PAGE_NAVIGATION_FIX.md).

## V2.5.6 Advanced Page Organizer

智慧選頁、Reverse、Interleave、空白頁、批次裁切及 Extract／Split，整合暫存預覽與 Undo／Redo。修正旋轉內容、縮圖比例、空白頁崩潰及匯入圖層顯示問題。

詳見 [版本說明](docs/RELEASE_NOTES_2.5.6.md) 及 [Organizer 操作指南](docs/ADVANCED_ORGANIZER.md)。

## Portable updates

Windows managed portable builds now support **Help → Check for Updates**:
signed GitHub ZIP downloads, a fixed launcher, isolated versions, and automatic
startup rollback. First deployment can use the Inno Setup installer or extract
the Managed Portable ZIP; both launch through Launcher.exe.
See [更新與發佈指南](docs/PORTABLE_UPDATES.md).

Download the [V3.0.3 release](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.3). New users can install the Setup EXE or extract the Managed Portable ZIP. Both use Launcher.exe for managed updates.
Existing legacy Setup installations need a one-time transition to the managed installer or portable package.

## V2.5.4 stability update

- Atomic rollback for page plans and page insertion; insertion preserves caller order and duplicates.
- Shared OCR language normalization and veraPDF discovery, including `VeraPDF/` and `verapdf/`.
- Runtime/build contract: Python 3.12.x. OCR is not bundled in the macOS build.
- Single and batch printing now prepare/rasterize pages in cancellable workers, with live progress. One page image is in flight at a time; printer interaction stays on the GUI thread. Cancel stops at the next safe checkpoint.
- Safe association unregister, settings null fallback, and public `PDFViewer.apply_theme()`.
- CI runs affected tests and basic smoke checks on ordinary branch pushes. PRs and merges run the Windows automated suite; UI interaction and Linux/macOS core jobs run when relevant files change, and version tags run every test group. Pillow is pinned to 11.3.0.

The Windows x64 release target is V3.0.3. Setup and Managed Portable downloads include SHA-256 files.

See [repair report](PROJECT_REVIEW_REPORT.md) and [release notes](docs/RELEASE_NOTES_2.5.4.md) for coverage and remaining limitations.

## Background printing follow-up (2026-09-07)

The next development step is complete on this source tree: background preparation/rendering, cooperative Cancel, one job per batch file, and automatic UI/resource restoration. Application editing controls are suspended while printing. Closing the batch dialog requests cancellation and hides it safely. The initial snapshot of an unsaved live document and native printer calls can still briefly block; pages already accepted by the driver may not be retractable.

See [background printing report](docs/BACKGROUND_PRINTING_REPORT.md). The background-printing report records its development checkpoint; the current release also includes the subsequent transaction and history improvements.

## 主要功能

### PDF 閱覽與導覽

- 單頁、連續頁、雙頁與封面雙頁版面
- 可延遲載入的頁面縮圖、快速跳頁、縮放及頁面尺寸（mm）顯示
- 水平或垂直 Split View，可同步頁碼與縮放比例
- Browse、Hand、Select Text 及 Magnifier 四種 Canvas 模式，可直接從主工具列切換
- 書籤、目錄、文件資訊及快捷鍵指南

### Document Inspector、Preflight 與 Smart Detection

- 每個文件 session 提供非模態 Analysis Panel，結果可跳頁、複製頁碼、匯出 CSV/XLSX、擷取或送往 Organizer
- Inspector 檢查 metadata、page boxes、字型、圖片 occurrence/effective DPI 及 colorspace
- General Office、Digital Print、Production Print 三組可編輯 preflight profile
- Exact/Near Blank、文字、圖片、vector、annotation、form、barcode 及 QR code detection
- 分析以 revision 標記；文件修改後舊結果會變成 stale，不能直接套用頁面操作
- PDF/A-1～4 與 PDF/UA-1/2 由離線 veraPDF Greenfield 驗證；PDF/UA 結果只代表 machine-verifiable checks
- PDF/X 僅提供 readiness checks，不宣稱正式 compliance

### 頁面整理

- 清晰的多頁 selection、鍵盤操作、插入線及 `N pages selected` 狀態
- Insert、Replace、Duplicate、Extract、Delete、Rotate、Restore 及重新排序
- 外部 PDF 插入／取代支援頁碼範圍與記憶體內密碼；Apply 為單一 Undo transaction
- 規則式頁碼範圍處理及縮圖式頁面管理
- 合併 PDF、疊加文件、壓縮與批次處理

### 標註與內容工具

- Typewriter、Text Box、Callout 可編輯 FreeText annotation
- Line、Arrow、Ellipse、Polygon、螢光、Underline、Strikeout、Squiggly、Ink、Rectangle、Note、Stamp
- Rubber Stamp 支援 14 款內建印章，以及可命名、重複使用及移除的自訂 PNG/JPG 或文字印章
- 每個工具可保存 stroke/fill/opacity/width/font defaults、Recent Colors 及命名 palette
- 區域文字擷取、條碼掃描、文件分析及診斷
- 深度搜尋及 Find/Open 文件搜尋

### 列印

- 單一及批次列印
- 頁面範圍、紙張、方向、彩色、雙面、份數、縮放、置中及偏移設定
- Draft 150、Standard 300、High 600 DPI 及 72–600 DPI 自訂列印質素
- 自動記住上一次列印設定
- **開發版列印改善**：PDF 在獨立渲染程序每份開啟一次；逐頁傳回影像，不再每頁重新解析整份 PDF。列印期間可捲動、縮放及切換 PDF 分頁，修改與重複送印暫時鎖定。
- **Batch Print → Printer Preferences…**：確認後同步通用設定，並沿用同一個 QPrinter 執行整批獨立送印工作。Paper 的 **Printer settings** 使用本次確認的紙張尺寸及邊界；之後修改介面設定會優先套用，取消 Preferences 不改動原設定。
- 自訂 printer layout 及驅動專用設定只保留於本次對話框／批次；更換打印機或重開程式需重新確認。選紙、Tray 及 finishing 仍以實際 Windows 驅動支援和實機驗收為準。
- 取消停止後續頁面；已交给 spooler 的頁面未必能撤回。詳見 [列印改善驗證紀錄](docs/PRINTING_M5_M6.md)。

### 轉換與資料工具

- PDF、Office、文字、圖片及 PostScript 工作流程（視系統可用元件而定）
- Merge CSV / Excel 支援 `.csv`、`.xlsx` 及 Legacy Excel `.xls`
- 合併工作表固定命名為 `sheet1`，並保留數字型別、移除空白資料列

### 安全與私隱

- PDF 密碼及權限設定
- 本機桌面處理；文件不會因一般編輯流程自動上傳至雲端

## 支援格式

- 文件：PDF、PS、EPS、TXT
- 試算表：CSV、XLS、XLSX
- Office 轉換能力取決於 Microsoft Office 或 LibreOffice
- PostScript 轉換使用隨程式提供或系統安裝的 Ghostscript

## 下載

Windows 版本可於 [Releases](https://github.com/andy846/PDFDocuEdit_Pro/releases) 下載：

- 安裝版：[Inno Setup V3.0.3](https://github.com/andy846/PDFDocuEdit_Pro/releases/download/v3.0.3/PDFDocuEdit-Pro-v3.0.3-Setup-Windows-x64.exe)，新安裝會使用 Launcher.exe，支援日後程式內更新。
- 免安裝版：[Managed Portable V3.0.3](https://github.com/andy846/PDFDocuEdit_Pro/releases/download/v3.0.3/PDFDocuEdit-Pro-v3.0.3-Managed-Portable-Windows-x64.zip)，解壓後執行 Launcher.exe。
- 後續更新：在程式內按 Help → Check for Updates；Update ZIP 是更新附件，不是首次部署包。各下載均有同名 .sha256 校驗檔。

### Windows release build

在 Windows x64 安裝 Python 3.12、Inno Setup 6 並設定更新簽署私鑰後，可執行
`scripts\build_windows.bat`。確認同一提交的 GitHub CI 已通過後執行；流程會驗證 source，並建立 PyInstaller
程式、簽署更新 ZIP、Managed Portable ZIP、Inno Setup 安裝檔及各自的 SHA-256 checksum。

V3 預設包含 Document Designer；先以 Python 3.12 執行 `scripts/prepare_composition_assets.py`，準備 manifest 驗證的字體及 qpdf。開發時可用 `PDFDOCUEDIT_ENABLE_COMPOSITION=0` 暫時關閉；正式發佈不可關閉此功能。

正式簽署 build 可設定以下環境變數：

- `PDFDOCUEDIT_SIGNTOOL`：Windows SDK `signtool.exe` 完整路徑
- `PDFDOCUEDIT_CERT_SHA1`：Authenticode certificate thumbprint
- `PDFDOCUEDIT_TIMESTAMP_URL`：RFC 3161 timestamp URL（可省略）

設定後會簽署主程式、Launcher、Setup 及 Uninstaller。Installer 會將 PDFDocuEdit Pro
註冊為 PDF、PS、EPS 的可選開啟程式，但不會未經使用者同意改寫 Windows
現有預設程式。


### PDF/A 與 PDF/UA 驗證（Windows / macOS）

Release build 固定 veraPDF Greenfield 1.30.2，並按平台封裝私人 Eclipse
Temurin JRE 21。驗證全程離線，clean machine 不需要 system Java。
`build_assets/verapdf/BUNDLE_INFO.json` 記錄來源 URL、版本、SHA-256、大小及
授權。正式建置可先執行 `python scripts/prepare_verapdf.py`，下載、驗證並
建立平台對應的 `VeraPDF/` bundle；script 會拒絕覆蓋既有 bundle。
`scripts/build.py` 會再檢查 launcher、JRE、manifest，並執行離線
`--version` smoke test；缺少或版本不符會中止 release build。

PDF/UA 報告只包含機器可驗證規則；沒有 XMP conformance claim 顯示
`Not declared`，不會自動當作 PDF/A-1b。PDF/X readiness 不等於 certification。

### OCR (Windows x64)

Conversion 面板提供 bundled Tesseract 5.5.3 英文／繁中 OCR，可抽取 UTF-8
文字或建立 searchable PDF，且不會取代原始檔。Release build 必須包含完整
`Tesseract/` runtime、`eng`、`chi_tra` 語言資料及 PDF config；缺少任一
必要資產時建置會直接失敗。

開發、測試及封裝可使用專案內的 `scripts/build.py` 建置腳本。

### Redaction save follow-up

Applied redactions now require a full garbage-collected save, including encrypted outputs and repeated saves. See the [redaction save report](docs/REDACTION_SAVE_REPORT.md) for reproduction and validation.

### V2.6 architecture preparation

Page, annotation, watermark and applied-redaction actions now use a shared transaction boundary. Undo/redo preserves the live document and history when preparation or restoration fails. Mutation/history coordination lives in `ui/mutation_controller.py`; migrated PDF and annotation outputs share `core/io_atomic.py`.

Windows Python 3.12.14 validation: **389 passed across 35 modules**, plus Ruff and source verification. See the [architecture report](docs/V2.6_ARCHITECTURE_REPORT.md) for detailed scope and remaining packaging/platform checks. These are historical V2.5.4 validation results.

## 版權

Copyright © 2026 Andy Leung. All rights reserved. PDFDocuEdit Pro is proprietary software. Unauthorized copying, modification, distribution, or commercial use of this software or its source code is prohibited.
