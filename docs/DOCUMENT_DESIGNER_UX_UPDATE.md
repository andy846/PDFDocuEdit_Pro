# Document Designer — UX 更新與測試指引

日期：2026-10-01。這是 v3.0 功能的開發測試版；正式產品版本仍為 2.5.15。

## 本輪更新

### 名稱與入口

Welcome、Designer 視窗、File 對話框及說明統一使用 **Document Designer**。已開 PDF 時，也可從主程式 **Tools → Document Designer** 開啟。既有 .pdcx 模板仍可載入；內部 composition 套件／worker 名稱保留，避免破壞既有呼叫。

### Windows 字體

- 背景掃描 Windows 系統及目前使用者安裝的字體，包括 registry 所指的其他安裝位置。
- 可搜尋字體家族，選擇實際 Regular／Bold／Italic／其他字款。
- 支援 TTF、OTF、TTC／OTC 字體集及可變字體的具名字款。
- TTC 選中的 face 及可變字體 instance 匯出為確切的獨立字體檔，不模擬粗體／斜體。
- 系統字體在保存時隨模板 assets 保留，重開不會因系統換字體而默默替代。
- 保留 bundled Noto Sans／Noto Sans CJK HK，方便未設定系統字體的舊模板。
- 不允許嵌入／沒有可用 outline 的字體不能用於 PDF 文字；舊 .fon bitmap 字體不在可用 outline 清單。色彩字體若只輸出單色 outline，選取時會提示。

此電腦盤點出約 318 個 outline 字款／instance。實際清單取決於該部 Windows 已安裝字體，並非跟開發版捆綁全部 Microsoft 字體。

### 選單與工具列

File：New、Open、Save、Save as、Recent projects、PDF background、Rename、Close。

Edit：Undo／Redo、Cut／Copy／Paste、Duplicate、Delete、Select all。

Insert：Text、Variable field、Image、Line、Box、Code 128、QR。

Arrange：水平／垂直對齊、分佈、Bring to front／Send to back、選取文字套用 CJK 字體。

View：頁面尺寸、Fit page、縮放、5 mm grid／snap、面板顯示。

Data／Production／Help：匯入、Preview、Generate、Cancel、快捷鍵說明。

常用專案操作放第一列；插入、條碼選單、字號及縮放放第二列。工具列有溢出選單，窄窗仍可從完整選單操作。

### 畫布、圖層與屬性

- 左側新增 Layers，與畫布多選同步；可選取重疊物件。
- 對齊、分佈、前後排序均可 Undo／Redo。
- Design／Preview 切換保留原有選取。
- 顯示毫米游標位置與選取數量。
- 屬性分成位置／字體／內容／文字布局／外觀／圖片／條碼，只顯示適用區域。
- 字體家族、實際字款及工具列字號更容易取得；顏色可用色盤。
- Insert data field 可在文字游標位置插入變數。
- 視窗／面板尺寸與最近專案保存在 Designer 的獨立 settings group。

### 預覽與生產

新增首筆／末筆導航、頁面縮放比例。失敗後可按 **Review failed object / record** 回到物件，及 **Open reports folder** 查看 JSON／CSV。

生產仍使用獨立 engine／worker、整批缺字檢查、單頁固定模板、reconciliation 及完整輸出驗證。這一輪沒有改為動態分頁或加入自由腳本。

## 建議測試

1. 保存目前 .pdcx，再關閉舊版，開啟新的 Document Designer 開發版。
2. 在 Welcome 或 Tools 開啟 Document Designer。
3. 載入原有模板／資料，選中文字物件。
4. Family 搜尋 Arial、Calibri、Microsoft JhengHei、PMingLiU 或你常用的字體；Style 選實際字款。
5. 試文字修改、Insert data field、Layers、多選對齊及 Undo。
6. 試 100%／200% 顯示縮放、深淺主題、960×640 窄窗、工具列溢出與屬性捲動。
7. Preview 查看首筆、第二筆、長資料及最後一筆。
8. Save／重開／重新生成，核對字體、頁數、中文及控制報告。

Windows 字體更換為非同步工作；字款正在載入時暫不能保存／生成，避免意外使用舊字體。缺字仍需選擇具有該字形的字體。

## 證據與限制

Designer 測試包含實際 Windows Arial Bold 選擇、中文字體集、具名字款的靜態匯出、嵌入權限、保存後逐像素比較、字體選擇 Undo、圖層／對齊及不丟失未完成數值編輯。

50,000 頁效能數字沿用之前已記錄的固定頁引擎 benchmark；本輪未宣稱重新量測所有 Windows 字體的大批量產能。

## 本輪驗收結果

- 全部既有及新增測試：**891 passed**，800.70 秒。這是本輪完整回歸 checkpoint；之後的 Tools 入口、預設名稱及少量 UI 整理另以最終 Designer 專項及封裝流程覆核。
- 最後的 Composition 專項：**58 passed**，25.54 秒；深色條碼圖示修正後，Designer／Windows fonts 6 項再次通過。
- Ruff、source verification、git diff --check 通過。
- 最終 Windows frozen 測試：200% 縮放、960×640、深淺色、Windows Arial Bold、中文、PDF 背景、Code128／QR 解碼、100 筆生成、保存重開及既有 Editor 開檔。
- 封裝 worker 另驗證 Microsoft JhengHei TTC 的「田」及具名可變字體匯出／PDF 預覽。
- 獨立 QA 安裝測試：100% 縮放的相同 100 筆流程；完成後移除專用 QA 安裝，未註冊 PDF handlers 或 shortcuts。
- 上述都是合成測試資料；沒有代替使用者實際 398 筆資料的驗收。

可重跑：
```powershell
python -m pytest tests/composition -q
python scripts/composition_install_smoke.py --source "dist-designer-ux/PDFDocuEdit Pro"
```

本機證據（build 目錄不提交 Git）：

- build/qa-document-designer-regression.xml
- build/qa-document-designer-final-tests.xml
- build/qa-document-designer-final-polish-tests.log
- build/qa-document-designer-final-frozen/result.json
- build/qa-document-designer-final-frozen/gui/designer-light.png
- build/qa-document-designer-final-frozen/gui/designer-dark.png
- build/composition-install-qa/result.json
- build/qa-document-designer-build.log

測試版：

- dist-designer-ux/PDFDocuEdit Pro/PDFDocuEdit Pro.exe
- release/PDFDocuEdit-Pro-v2.5.15-Document-Designer-Dev-Portable-Windows-x64.zip
- 相鄰 .sha256 校驗碼。

原穩定 checkout 及 pre-v3.0-v2.5.15 回退標籤保留；未公開發佈／推送。
