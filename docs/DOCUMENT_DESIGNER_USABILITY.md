# Document Designer — 操作便利性更新（2026-10-01）

這是目前功能的鞏固版本。正式版本仍為 2.5.15，Document Designer 開發入口保持啟用。
本輪集中在編輯、選頁、面板、預覽及輸入保護；引擎、主字體與指定字元補字規則沿用已驗證的版本。

## 操作改善

| 操作 | 目前方式 |
| --- | --- |
| 切換模板頁 | Template page 左右的 ◀ / ▶ 或 Alt+PgUp / Alt+PgDown |
| 新增頁面 | +；Page actions 亦提供新增、複製、刪除、改名、尺寸 |
| 調整頁序 | Page actions → Move page earlier / later；支援 Undo |
| 返回某頁 | 同一視窗中保留該頁縮放、中心位置及選取物件 |
| 查找欄位 | Data fields 的搜尋框，搜尋內部名稱及原始名稱；清除按鈕還原清單 |
| 編輯物件 | 雙擊畫布物件／Layers 項目，顯示屬性並聚焦內容 |
| 常用操作 | 畫布右鍵選單：剪下、複製、貼上、複製物件、刪除、排列、屬性、補字 |
| 窄視窗 | 寬度少於 1100 時 Properties 移到左側第三個分頁；拉闊後返回右側 |
| 預覽 | 顯示更新中、記錄／模板頁、錯誤狀態；Refresh 重試，Review object 返回錯誤物件 |

頁面上的 ◀ / ▶ 只負責切頁。頁序修改使用帶名稱的 Page actions，避免把翻頁誤作改序。

## 編輯文字及修正輸入

可以直接輸入 Account: {{Account_No}}。打到 {{Account 時，尚未完成的文字會保留在 Content，
不會因格式檢查被重設。完成 }} 後，內容會提交，Save／Generate 重新可用。

無效草稿會顯示原因及 **Revert unfinished edit** 按鈕：

- 可直接修正文字、位置、尺寸及其他屬性。
- 切頁、換物件、新增／排列物件、Undo、換字體、匯入及生成暫停，防止草稿被另一個操作覆蓋。
- Save／Generate 不能使用仍未完成的草稿，亦不能偷偷保存或輸出上一個有效值。
- Revert 回到最後有效的物件內容；不等於撤回整個專案。
- 關閉／New／Open 仍會詢問 Save／Discard／Cancel。無效草稿不能 Save；可以修正後保存，或明確選 Discard。

位置／尺寸輸入在離開欄位、切頁、修改頁面及生成前也會驗證。例如把 X 設得超出頁面，
會保留該值及說明讓使用者修正。

連續修改同一物件的文字會合併成一個 Undo 動作；停頓超過 0.8 秒、換物件／頁面、
改其他屬性或保存會形成新的編輯邊界。Undo 合併不跨越 Save 的乾淨檢查點。切到另一物件後再 Undo，會同步恢復原物件的選取、內容及字體屬性。

文字編輯不再逐字重建畫布物件、Layers 或匯入資料清單，因此游標、欄位搜尋及縮放能保持。
較早返回的預覽不能蓋過無效草稿的提示；手動改回有效內容會重新預覽。
預覽仍在背景生成當前頁，正在輸入的內容不會觸發整批 production。

## 快捷鍵及生產

Ctrl+D／Delete／剪貼簿的物件動作限定於畫布；在文字欄位按 Delete 只刪文字，
Ctrl+D 不會複製版面物件。畫布 Ctrl+D 複製選取物件。

匯入或生產期間，畫布不能用拖曳／方向鍵／Delete 修改版面；完成或取消後可繼續編輯。
字款或背景正在載入時，保存／生成會等待，避免使用尚未就緒的資源。

客戶標準字體仍須明確選擇。單字補字只處理已指定的缺字，不更換整個欄位的主字體。

## 建議試用

1. 開啟現有 .pdcx，試 Data fields 搜尋及 Layers 選取。
2. 雙擊文字，在 Content 輸入一個完整 {{Field_Name}}，中途停下觀察草稿提示。
3. 試 Revert、完成輸入後 Save、Undo／Redo。
4. 改縮放、切模板頁再返回；用 Page actions 改頁序後 Undo。
5. 拉窄至 960×640，從左側 Properties 編輯；拉闊確認右側屬性恢復。
6. 在文字欄與畫布分別試 Delete／Ctrl+D。
7. Preview 選不同記錄與模板頁；Generate 後核對 PDF、job.json 及 CSV。

使用新版前先保存並關閉舊程式。模板 schema 保持 3，可讀舊 v1/v2；
較舊的單頁版本仍不能讀 schema-3 專案，回退時需使用之前保留的模板。

## 驗收紀錄

- 程式碼檢查點：066d7bb。
- 新增 UI 操作測試：13 passed（1.68 秒），涵蓋真實文字輸入、無效草稿、數值提交、跨物件 Undo／字體、頁面縮放／選取、窄窗切換、快捷鍵、防修改狀態、欄位清單及過期預覽。
- Ruff 全專案、source verification 及 git diff --check 通過。
- 最終 frozen Windows exe：200% 縮放、深淺色、960×640／1240×820、保存重開、多頁／中文／Windows exact fonts／Code128／QR／補字 audit／100 筆 200 頁對帳／既有 Editor 開檔通過。
- 最終隔離 QA 安裝：100% 相同流程通過；QA 安裝已移除，沒有註冊 PDF handler 或捷徑。這不是正式安裝版的就地升級測試。
- 最終程式碼 066d7bb 完整回歸：**934 passed**（818.68 秒），0 failures / errors / skipped；其中 Composition 101 項，包含新增的 13 項 UI 測試。沒有停用或刪除舊測試。
- 可追蹤驗收：validation/document_designer_usability_20261001.json，包含執行檔及 ZIP SHA-256。
- 測試使用合成資料。本輪未改寫使用者原模板／資料，未宣稱重跑使用者 398 筆資料。

本機證據（build 目錄不提交 Git）：

- build/qa-designer-usability-focused.xml
- build/qa-designer-usability-regression.xml
- build/qa-designer-usability-build.log
- build/qa-designer-usability-frozen/result.json 與 UI 截圖
- build/composition-install-qa/result.json、acceptance/result.json、install.log、uninstall.log
- build/qa-designer-usability-installed.log

## 測試版與回退

- 執行檔：dist-designer-usability/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。
- 可攜 ZIP：release/PDFDocuEdit-Pro-v2.5.15-Document-Designer-Dev-Usability-Portable-Windows-x64.zip，附相鄰 .sha256。
- 回退至這輪之前的版本：document-designer-multipage-dev-20261001（25ca85d）。
- 目前交付標記：document-designer-usability-dev-20261001；原穩定 checkout 仍保留。
- 沒有公開發佈／推送，也沒有改正式產品版本。


## 範圍及限制

- 未新增規則、條件顯示、分檔或動態 overflow。
- 本輪沒有新增 dependency、改 public version 或修改 PDF Editor 行為。
- 頁面縮放／選取記憶只屬本次 Designer 視窗，不寫入模板。
- Properties 為可捲動面板；低於 1100 px 時與 Data fields／Layers 共用左側分頁。
- 縮放及主題截圖由實際 offscreen Qt 視窗生成；沒有宣稱已檢查使用者當前未保存的視窗。
- 生產效能沿用已有引擎基準，本輪沒有把 UI 改善稱為重新量測的大量產能。
