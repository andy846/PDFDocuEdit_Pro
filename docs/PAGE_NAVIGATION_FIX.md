# 頁碼同步與 PDF 置中修正

## 行為

- 連續／雙頁模式按縮圖或指定頁碼時，保留指定的頁面；不讓稍後的捲動回呼改成畫面中央的另一頁。
- 實際捲動仍更新頁碼；双頁中左右兩頁與畫面中央距離相同時，保留目前選取的那一頁。
- 未啟用頁面同步的分割視窗有自己的頁碼，不改寫主視窗、縮圖或底部頁碼。啟用同步時透過主視窗統一通知。
- 刪頁／整理頁面後先重建所有主、分割及參照視窗的頁面清單，再發出同步通知，避免讀取已刪除的頁面。
- 文件版面小於閱覽區時，頁面與頁碼標籤作為一組水平、垂直置中。大型頁面保留捲動能力；單頁切頁從頁頂開始。
- 重新載入文件回到第一頁，版面模式切換保留目前頁碼。

## 驗證

新增 tests/test_page_navigation_sync.py 的 7 項測試。修正前已重現連續模式指定第 3 頁却變第 4 頁、雙頁指定右頁卻改成左頁，以及小頁面固定貼頂。整合測試同時核對 canvas、session、縮圖及底部頁碼／總頁數，包含分割同步、刪頁與 Undo／Redo，並捕捉 Qt 回呼例外。

完整 pytest 517 項通過（270.09 秒）；最後補充重新載入及大型頁面邊界修正後，32 項導航與主視窗回歸全部通過。Ruff、來源檢查及 git diff --check 通過。

本機修正版：build/page-navigation-fix/PDFDocuEdit Pro/PDFDocuEdit Pro.exe。請先關閉舊程式，保留整個資料夾。上述修正納入 v2.5.7 更新套件；現有 Managed Portable 可透過 Check for Updates 更新。

原生 Windows 來源版與 frozen 導航 QA 均通過，核對實際頁面渲染置中、連續／雙頁縮圖導航及狀態列同步。打包驗證紀錄：build/page-navigation-final-frozen-qa/result.json；畫面：同目錄 centered.png、navigation.png。另有 Organizer frozen QA 通過，包含 13 頁計劃、6 份輸出與主文件一次 Undo／Redo。
