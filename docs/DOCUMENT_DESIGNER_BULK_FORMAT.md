# Document Designer — 多選文字格式（2026-10-01）

## 技術範圍

基線：7cf1ab3 / document-designer-rules-dev-20261001。改動限於隔離 Designer：
新增 bulk_typography.py；properties.py 顯示多選文字及發送部分屬性，
workspace.py 接入選取／批量 Undo，font_controls.py 轉接批量字款請求，
chrome.py 工具列字號加入修改追蹤。使用既有 font_info/font_export 背景服務；
一個實體字款只準備一次，同一批用一個 Undo command。引擎、Qt 以外核心、
資料 snapshot、規則、公共版本及模板 schema 4 都不變，沒有新增相依。

## 使用方法

1. 在 **Design** 於目前模板頁框選文字物件；或到 **Layers** 用 Ctrl 點選多項、
   Shift 選連續範圍。Ctrl+A 可選取本頁全部物件。
2. **Properties** 會顯示選取及可格式化文字數量。不同字體／字號／排版／顏色
   會顯示 Mixed；控制項顯示第一個文字物件的值，不表示全部已相同。
3. 修改 **Family / Style / Choose font file**，可將同一實體字款套用到所選文字；
   每個物件的字號保持原值。粗體／斜體使用相應實體 Style。
4. 修改 **Size (pt)** 或工具列字號，只統一字號，保留各欄位原本字體及字款。
5. **Text layout** 可統一行距、水平／垂直對齊；**Appearance → Colour** 可統一文字色。
6. 輸入完成後按 Enter 或離開輸入框套用。只是移動焦點不會把 Mixed 值變成一致。
   如想統一為第一個物件現有的字號，可明確重輸該數值。
7. 每項批量修改都可一次 Undo / Redo。完成後切換不同 Record 預覽，再生成。

## 保留及限制

- 靜態／變數／混合文字都適用；Code 128 開啟 Show Code 128 text 時，其可讀文字亦適用。
  QR、圖片、線及框不會被文字設定修改。
- 範圍是目前頁已選取物件，沒有跨頁／全模板統一字體命令。
- 只改你編輯的格式項目。內容、欄位引用、位置、尺寸、規則、頁設定、未選物件及
  每物件的 glyph repair mapping 保留。
- 批量換字款保留各自字號；批量換字號保留各自字款。沒有自動補字或靜默替代。
  新字款是否足夠支援資料字形，仍須 Preview／整批 production preflight 驗證。
- 規則及指定字元補字仍逐一物件編輯，不會把某物件的特殊設定複製到整批。
- 字款準備完成只套用最初選取的物件。失敗／取消／字體設定在等待期間被 Undo 改變
  時，整批不套用；遲到的回調不會覆蓋新選取的物件。
- 沿用缺字、溢出、嵌入權限及生產核對檢查。使用者現有模板及穩定 checkout 不被改寫。

## 驗收及交付

21 個新增自動測試涵蓋 Mixed 字款／字號、只改指定屬性、工具列、
明確重輸相同字號、焦點移動、只修改合資格文字、一次 Undo、
一次 Windows Arial Bold 準備、保留補字／規則、非同步失敗／取消／舊回調。
原生及 Windows 打包驗收仍測試 100 筆／200 頁、Barcode／QR 解碼、
客戶實體字款、中文字形補字、規則、保存重開和原有 Editor。
最終完整回歸及交付紀錄在此文件後補及 validation/document_designer_bulk_format_20261001.json。

回退至上個里程碑：document-designer-rules-dev-20261001。
新測試版：dist-bulk-format/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。
本次公共版本仍為 2.5.15，屬於開發測試交付。
