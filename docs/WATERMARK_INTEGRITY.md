# 水印完整性及透明度修補 — 2026-10-22

## 範圍及來源

- 工作區：`D:\Python_Project\PDFdocuEdit_Pro`，本機 `main`。
- 修改前完整 SHA：`7a1374e55a22a7e23d2f045f0e69df373f31efcd`。
- 修補由本報告所在提交保存；未提升公開版本、推送、移動 tag 或發布更新。
- Windows `.venv-dev`，PyMuPDF **1.26.6**。只使用合成 PDF、圖片及測試設定。
- 使用者的 `BOCHK.pdmp` 保持未追蹤，沒有讀取、修改或提交。

## 行為與檔案

| 檔案 | 修改 |
|---|---|
| `core/watermarks.py` | 逐字精確 glyph 檢查、固定字型 fallback、拒絕未支援的成形序列、序列化水印來源 PDF 的文字一致性檢查 |
| `dialogs/annotation_dialogs.py` | 0–100% 滑桿、未改動時保留原始浮點透明度、共用預檢及透明度取值 |
| `ui/watermark_preview.py` | 顯示安全的預檢錯誤，保持預覽副本及工作生命週期 |
| `core/viewer.py` | 交易失敗時保留具體 Unicode 原因及原有回滾狀態提示 |
| `tests/test_watermark_integrity.py` | 新增完整性、無部分寫入、fallback、過期對話框、透明度及 Qt 原生滑塊測試 |
| `scripts/ci_plan.py` | 新測試納入既有 Qt UI 測試設定 |
| `docs/UNIFIED_RELEASE.md` | 說明凍結 tag 文件、完成後證據及 main 同步規則 |

### 文字完整性

沿用舊字型選擇作第一候選：Latin-1 文字先用 Helvetica，其餘先用 `china-s`。
不足時依序嘗試另一個既有內建字型、隨程式附帶的 `NotoSans-Regular.ttf`、
`NotoSansCJKhk-Regular.otf`。每一候選必須以 `has_glyph(..., fallback=False)`
完整覆蓋文字；不隱式替換字元、不掃描系統字型或下載資源。

本輪不加入字形成形引擎。RTL、組合標記、控制／格式字元、ZWJ，以及需要成形的
Hangul conjoining Jamo 明確拒絕。預組合韓文仍可用；emoji 只有在現有候選字型及
輸出字碼檢查均可靠時才可能接受，不能據此聲稱一般 emoji 支援。

在獨立來源 PDF 寫入後，先序列化、重新開啟並核對提取文字與輸入**完全相同**，
才寫入目標頁面。此項檢查不把文字提取一致當成所有複雜文字外觀正確的證明。
失敗提示僅含原因及最多八個相關 Unicode 碼，不記錄完整輸入文字。
既有水印更新沿用交易及先建立成功再移除原件的機制。

預覽和 Apply 使用同一核心檢查；核心不信任曾成功的預覽或對話框資料。
批次沿用單一已驗證來源與資源重用，不逐頁解析字型。
字型物件快取有上限，附帶字型檔案身分改變會使快取失效。

### 透明度

文字及圖片均接受 0–100%。編輯既有物件但未調整透明度時，保留完整原值，
包括 0、0.004 及 0.123456789，不以整數百分比替代。
真正拖動、步進或 Home/End 選擇後才使用所選百分比。
原位按放手柄及原生樣式的無位移 `SliderMove` 不視為修改。
預覽、驗證和提交共用 `_selected_opacity()`。

## 驗證及證據

全部本機日誌、JUnit、合成文件、影像及隔離 QA 程式放於
`build/probes/watermark-integrity-20261022/`，不提交 Git。

主要指令（均使用 `.venv-dev\Scripts\python.exe`）：

```text
-m pytest tests/test_watermark_integrity.py tests/test_watermark_dialog.py -q --tb=short
-m ruff check .
```

完整相關模組使用既有 `scripts.regression_suite.run`，每模組獨立程序，
模組清單及結果保存於 `final-regression/result.json`：
水印完整性、位置、對話框、關閉重開、Session 暫存清理、Annotation 交易、
Mutation 交易、多文件視窗、私人版帳戶介面、渲染復原、旋轉邊界、來源契約、
CI 計劃、Windows 更新及製作授權／發布邊界。

- 最終水印測試：**49 passed**（45 項新測試及 4 項既有對話框測試）。
- 最終 15 模組回歸的精確結果見本報告下方「交付驗證結果」。
- 最初回歸保留 **295 passed / 1 failed / 1 skipped** 的證據。
  失敗為製作流程測試 `test_recovery_cannot_relabel_old_output_as_changed_template`，
  在長暫存路徑下準備階段被拒絕；以唯讀方式載入修改前模組，同樣失敗。
  基準與現版使用短暫存路徑均為 **8 passed / 1 skipped**。
  最終回歸採用短暫存根目錄，沒有修改或過濾測試。
- 跳過項目：主機沒有建立檔案 symlink 權限；不當作通過。
- 首輪 red、後續滑塊及 Jamo red/green 均保留，未刪除失敗證據。
- 獨立審查找到原位滑塊按放及 Jamo 成形兩項 P2，均已修正並確認沒有剩餘發現。

### Windows 隔離封裝 QA

以現有 PyInstaller、專案 hooks 及實際附帶字型建立 **QA 專用** console 封裝，
並非正式更新包或安裝程式。指令、spec、build log、QA 腳本與結果均保存於上述目錄。
執行 `frozen/WatermarkIntegrityQA/WatermarkIntegrityQA.exe <新測試目錄>`；
200% 測試另外設 `QT_SCALE_FACTOR=2`。

兩種縮放均通過：

- ASCII、中英混合及實際 Noto fallback 的四種頁面旋轉、字碼、可見渲染、Save/Reopen。
- 附帶 Noto 字型確實嵌入輸出；未用系統字型作封裝替代。
- 五類未支援序列在目標文件變更前拒絕。
- 每種縮放下 24 個深淺色、文字／圖片及精確透明度對話框檢查。
- 人工抽查合成 CJK 及 fallback 輸出影像的位置、方向及可見字元。

這是隔離 offscreen Qt QA，不能代替實際螢幕／硬件或正式帳戶全流程驗收。
macOS、Linux、本輪真實客戶檔案與實體打印機／RIP：**Not Tested**。
已發布 v3.0.11 的使用者驗收仍保留於
[該版驗收紀錄](RELEASE_VALIDATION_3.0.11.md)，不外推至本次尚未發布修補。

## 效能及限制

20 頁批次測試確認文字來源只準備一次；不新增背景工作或每頁字型掃描。
來源 PDF 的序列化與文字核對是每次準備的額外成本；含 CJK 字型時成本可能較高。
本輪沒有大型文件吞吐量或跨平台記憶體基準，不宣稱量化效能改善。
無法完整覆蓋單一文字的候選字型會拒絕，不做逐字分段 fallback。
不修改 PDF 處理引擎、既有水印 metadata、專案格式、依賴或生產規則。

### 建議實測

1. 用副本開啟 PDF，加入英文、中英混合及 `Fallback ẞ` 文字水印；
   比較預覽、Apply 及 Save/Reopen，旋轉頁面後確認位置、角度與比例。
2. 輸入阿拉伯文、希伯來文、emoji 或組合序列，確認預覽／Apply 明確拒絕，
   原文件及既有水印保持完整；多頁套用不可留下部分新增水印。
3. 將文字及圖片水印設為 0%，重新開啟屬性只調位置，Apply、Undo/Redo、Save/Reopen；
   確認仍為 0%。亦檢查 1%、5%、100%。小數透明度由合成自動化測試精確核對。
4. 預覽尚在處理時取消對話框，放棄文件修改並關閉／重開另一 PDF，確認沒有空白 Tab。

## 發布紀錄與主線同步

2026-10-22 只讀查核遠端 main：
`cfc19778e98a5ae86b967a864f6b6b0c8d34a5c8`。
它是修改前本機 main 的祖先，`rev-list --left-right --count` 為 **0 / 52**。
本次提交後同步範圍還會包括此修補；並非只有水印改動。
完整本次差異、主線提交清單及差異統計保留在本機 probe 目錄，供擁有人核對。

v3.0.11 tag 的來源 `a6d0b30c575ba0b6d1b9aa8e962d652f8fa9a783`、
公開附件、簽署及原始發布證據保持不變。
本機 main 已有完成證據及 2026-10-22 使用者驗收補錄；本輪未重新發布或改寫舊證據。
擁有人批准同步後仍須重新取得遠端 SHA 並核對祖先關係。
僅可普通 fast-forward 推送；遠端分叉時停止，不強推或自動合併。

## 交付驗證結果

- 最終 15 模組：**301 passed / 0 failed / 0 errors / 1 skipped**，共 302 個案例，
  各模組時間合計 200.13 秒。跳過原因為上述主機檔案 symlink 權限。
- 最終 45 項新完整性測試全部通過；另一次水印／對話框合併執行為 49 passed。
- Ruff 全專案檢查、`git diff --check`、修改文件的 4 個本機連結均通過。
- Windows PyInstaller 隔離 QA：100% 與 200% 各自成功；字型、渲染及透明度核對通過。
- 沒有執行本輪完整全專案回歸、跨平台原生封裝或正式發布驗收；本輪結果只涵蓋上述範圍。
- 獨立審查的兩項 P2 已以 red/green 及原生 Qt probe 確認修正。
