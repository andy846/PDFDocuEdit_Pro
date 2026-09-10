# Advanced Page Organizer

開啟 PDF 後進入 **Advanced Page Organizer**。所有頁碼都依目前預覽順序計算；只有 **Apply Page Plan** 會修改主文件，並建立一次主文件 Undo。

## 選頁與操作

- 選頁欄支援 `1-10,15,20-30`、`odd`、`even`、`every 4th page`、`last 10 pages`、`all`，亦可用逗號組合。大小寫不敏感、重複去除、按預覽順序選取。空字串清除選取；語法錯誤或明確越界保留原選取。
- All／Odd／Even／Every N／Last N／Invert／Clear 是相同選頁功能的快捷按鈕。Every N 與 Last N 使用旁邊的數值。
- Reverse 只反轉選取頁所佔的位置；未選取頁不動。Duplicate 建立獨立頁面實例，之後旋轉及裁切互不影響。
- Replace 要求連續選取，可用不同頁數取代。Insert 可選擇選取之前／之後、文件開頭／結尾。
- Blank pages 可設定數量及位置，使用參考頁尺寸、A4、Letter 或自訂毫米尺寸；提供直向／橫向。預設跟隨最後選取頁，沒有選取時參考末頁。
- Undo plan／Redo plan 還原暫存操作。在頁面網格內可用 Ctrl+Z、Ctrl+Shift+Z 或 Ctrl+Y。Restore 重設至原文件的頁面計劃，仍可用 Undo plan 還原。

## Interleave

A 是目前完整預覽，B 是另外選取的 PDF。匯入 B 時可輸入密碼及選頁表達式。確認匯入後使用受管理的快照，原來源之後被移動或改寫不會改變計劃。

設定 A／B 先開始、Reverse B，以及剩餘頁直接接續或補空白頁。補白尺寸依同一對的實際頁面可見尺寸。確認表格會顯示來源、原頁碼、結果頁碼及總頁數；**Use This Page Plan** 只改變 Organizer 預覽。

## Crop

選取頁面後按 Crop，在第一個選取頁上拖拉裁切框，或輸入左／上／右／下毫米數值。兩者同步；批次裁切以各頁目前顯示方向計算相同邊距，包含既有旋轉與 CropBox 偏移。

任一頁沒有剩餘有效面積時整次拒絕，並列出問題頁。Crop 只改變可見範圍，**不刪除底層內容，不能代替 Redact**。重複 Crop 會從目前可見範圍繼續裁切；Undo plan 可撤銷。

## Extract 與 Split

Extract 輸出目前選取頁；Split 輸出整個預覽，可每頁、每 N 頁或指定頁後分割。Split 先列出檔名、頁碼及頁數，確認後選擇輸出資料夾。

預覽、Apply、Extract、Split 共用組裝與變換程式，因此待套用的旋轉、裁切、複製、交錯及空白頁都會反映在輸出。

輸出不修改主文件，亦不覆蓋開啟中的來源 PDF；其他同名檔預設拒絕覆蓋。每份檔案獨立暫存、驗證後才原子提交。取消或失敗會保留先前已完成的檔案，完成視窗列出清單；整批輸出不是一個原子交易。之後 Cancel Organizer 不會撤回已輸出的檔案。

## 開發與驗證

本功能沒有發佈 GitHub Release，也沒有變更已發佈版本。`build/advanced-organizer-preview/PDFDocuEdit Pro/` 是本機功能預覽；保留整個目錄，執行其中的 `PDFDocuEdit Pro.exe`。其版本資訊仍沿用 2.5.5，不能當作正式更新套件分發。

新增 `core/page_plan.py`，保留原 `parse_page_range()` 相容行為。`PagePlanEntry` 仍可從 `core.pdf_engine` 匯入，新增欄位均有預設值。外部快照的生命週期延續至主文件 Apply 完成；輸出工作只持有私有 PDF 物件。縮圖按可見區域產生、以實例及變換快取，最多保留 128 張。

測試入口：

```powershell
& .venv-312/Scripts/python.exe -m pytest -q
& .venv-312/Scripts/python.exe -m ruff check .
& .venv-312/Scripts/python.exe scripts/verify_source.py
& .venv-312/Scripts/python.exe scripts/organizer_smoke.py build/organizer-source-qa
```

`scripts/organizer_smoke.py` 是獨立 QA 入口，只建立測試 PDF、使用隔離設定；可用應用程式相同 PyInstaller spec 改用此入口打包。它以 Windows 原生 Qt 執行鍵盤選頁、拖拉裁切、暫存歷史、快照與輸出工作，再透過主視窗驗證 Apply 的單次 Undo／Redo，產生 `result.json` 及截圖。QA 執行檔不是提供使用者的主程式。

初版驗證：完整 pytest 479 項通過，另兩項書籤／註解回復及部分取消補充測試通過；Ruff、source verification 通過。原生 Windows 的來源版及 frozen QA 均通過，產生 13 頁計劃與 6 份輸出。Windows Computer Use helper 啟動失敗，因此未聲稱完成人手式桌面點選巡檢；打包驗收採上述 Qt 自動操作。

極大型文件仍會建立每頁的頁卡元件；本次縮圖採按需載入，並非完整頁卡虛擬化。單一複雜頁面的渲染與單次 PDF 儲存完成前不能中斷，取消在安全檢查點生效。

## 旋轉與介面修正（2026-09-10）

- 工具入口、視窗及 Undo 名稱統一為 **Advanced Page Organizer**。
- 上方集中智慧選頁；左側依 Arrange pages、Rotate / crop、Add / replace、Export copies 分組。底部固定暫存歷史及 Apply／Cancel；較短視窗可捲動左側工具。
- 縮圖白色紙張框依實際比例顯示，旋轉 90° 的 A4 顯示 **297 × 210 mm · 90°**，不是固定直向紙框。待更新的舊縮圖會清除，Undo 後紙框及尺寸同步還原。
- 預覽不再把原頁匯入空白的單頁 PDF，而是保留完整來源的私有副本；這可保留圖層顯示設定及原始表單外觀。已重現舊預覽在隱藏圖層測例中與原頁不一致，新預覽與原頁相同。
- 若頁數與順序不變，Apply 直接修改原頁的旋轉／裁切屬性，不呼叫 select 或 insert_pdf。交易與 Undo 快照不進行物件合併、xref 重編號、內容清理或重新壓縮；輸出只清除不可達物件。
- 新增 EAN-13、QR Code、4pt 細字、細線、圖層、註解及表單測例。驗證四種旋轉角度及 CropBox 偏移，檢查原始串流逐位元組保持不變、條碼仍能解碼、Apply／Save／Export 畫面與僅修改原頁旋轉屬性的參考結果一致。
- 尚未取得使用者出現異常的原 PDF；上述測例不能證明該特定文件已完全修復，仍需以原檔重測。

重新打包的測試版使用新的 build/advanced-organizer-preview 目錄。請先完全關閉舊版再開新執行檔，避免單一執行個體機制把操作轉交舊版。沒有發佈 GitHub Release。

本輪修正驗證：完整 pytest **491 項通過**（420.67 秒），版面修正後另重跑 21 項相關測試通過；Ruff、source verification、git diff --check 通過。最終 frozen Windows QA 通過，結果見 build/advanced-organizer-final-qa/result.json；包含 13 頁計劃、6 份輸出，以及主文件一次 Undo／Redo。最終主程式位於 build/advanced-organizer-preview/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。

## Blank pages 崩潰修正（2026-09-10）

空白頁對話框原本把寬高輸入元件命名為 self.width／self.height，覆蓋 QWidget.width()／height()。ToolDialog 顯示時調整視窗大小因而發生 TypeError，Qt 事件回呼未處理的例外導致程式退出。已改為 width_mm／height_mm，保留原生視窗方法。

新增 8 項測试，實際顯示對話框、點擊 Blank pages 按鈕，涵蓋參考尺寸、A4、Letter、自訂尺寸、方向、取消、插入以及計劃 Undo／Redo。相關回歸共 68 項通過；Ruff、source verification 通過。打包 QA 入口也改成實際點擊 Blank pages 並確認對話框，不再直接呼叫插入方法代替。

本次修正版主程式位於 build/advanced-organizer-blank-fix/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。請先完全關閉舊版，保留整個程式目錄；沒有發佈 GitHub。

## Organizer bugs 巡檢修正（2026-09-10）

- 修正複製／匯入頁面遺失來源隱藏圖層狀態：匯入時保留每個 OCG 的可見狀態，並為複製的圖層實例保留獨立識別，避免名稱與字典內容相同的圖層互相影響。預覽、Apply 與重新開啟的輸出逐像素比較；來源 PDF 不被標記或修改。MuPDF 的 OCG 快取需在修改目錄後重建，此路徑亦納入 frozen Windows QA。
- 自訂空白頁的寬高數值與方向雙向同步，輸出尺寸與畫面輸入一致。
- Organizer 動作按鈕捕捉失敗並顯示錯誤，避免 PDF 讀取／渲染例外從 Qt clicked 回呼逸出。Interleave 無效預覽停用確認，Crop 套用錯誤保留計劃。
- 取消或輸入無效匯入範圍時立即釋放該快照；選頁後更新 Shift 選取起點。
- 未改動的計劃 Apply 不再標記文件已修改或增加 Undo；修改仍維持一次 Undo。
- Split 拒絕控制字元檔名，無效設定清除舊輸出清單，設定恢復有效後移除錯誤提示。
- 匯入進度支援超過 2 GB 的數值；輸出提交階段也禁止覆蓋期間被其他程式建立的同名檔案。

新增 tests/test_organizer_audit.py，涵蓋隱藏／同名圖層、原來源不變、無修改 Apply、輸出提交競爭、自訂尺寸、64 位進度、無效 Split、加密來源及 Insert／Replace／Interleave／Extract／Split 實際按鈕流程、取消匯入與錯誤回呼。原生 QA 額外逐像素比對含圖層的混合頁面預覽、Apply、Extract。

修正版位於 build/advanced-organizer-audit/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。使用時先完全關閉舊版，保留整個目錄。本輪沒有發佈 GitHub。

本輪最終驗證：完整 pytest **512 項通過**（278.63 秒）；Ruff、source verification、git diff --check 通過。來源版與 frozen Windows QA 均通過，13 頁計劃、6 份輸出及主文件一次 Undo／Redo。測試紀錄：build/organizer-audit-pytest.log；打包驗證：build/organizer-audit-frozen-qa/result.json。
