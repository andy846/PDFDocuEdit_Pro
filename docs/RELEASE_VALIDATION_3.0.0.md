# v3.0.0 正式驗收記錄

2026-10-05，Windows x64 / Python 3.12。正式測試及打包正在進行；發佈前填入實際結果。

## 驗收項目

- 完整 pytest（PDF Workspace、Designer、Workflow 與 PS）。
- Ruff、來源契約、相依套件及 bundled runtime／字體完整性。
- GitHub PR 與版本 tag CI。
- Windows PyInstaller / managed Launcher / Inno Setup。
- 隔離部署與安裝測試，不改動使用者正在操作的程式或 PDF。
- 更新簽章、部署狀態及各下載 SHA256。

實機打印機選紙與入信機驗收待使用者提供規格及樣本；不列作已通過項目。

## 有意更新的測試契約

`test_release_metadata_is_v3_0_0` 由歷史 v2.5.16 更新為 v3.0.0，檢查版本 metadata 一致；新增測試不取代既有回歸測試。

- Media schema 已將模板升至 10、Overlay 升至 6；舊版輸入 fixture 保留，遷移輸出斷言改為目前版本。
- 批次修改失敗保留草稿供修正，測試驗證 Revert 能恢復；主預覽 queue 測試與新增並排預覽 queue 分開驗證。
- 修正三個共用 Qt fixture 的參數傳遞，保留所有交接與 Merge UI 案例。
- Windows 完整測試按模組隔離 QApplication、樣式及原生資源；每個案例均執行並保留 JUnit，崩潰／逾時均失敗。
- Workflow 的三組 production integration tests 需要已驗證的 Windows qpdf bundle，仍全部列入 Windows 完整測試；macOS／Linux 僅執行平台中立組，避免將 Windows binary 需求誤分類為跨平台驗收。
- Qt fixture 沿用正式入口的先安裝主題、再建立控制項次序；測試間派送 DeferredDelete，避免未執行的銷毀累積。新增關閉後初始化計時器及 QSS proxy ownership 回歸。
- 通知列現在屬於 PDF mode 容器，保留不改變 viewport 的全部斷言；導航快捷鍵測試明確啟用視窗及 PDF 焦點。
- Native/frozen smoke 更新為 Designer host 的目前專案、主視窗 resize、批次草稿 Apply，以及明確新增 control barcode；不再假設新來源自動加入 barcode。

## 本機完整回歸與修正重驗

116 個模組均已執行；首輪揭露的失敗保留在 log，修正後重驗受影響模組。最終覆蓋 1,638 個案例，全部通過，無移除／跳過既有 Windows 案例。Ruff、來源驗證及 pip check 通過。

來源版端到端 smoke 通過：含 Windows font、CJK、Excel/XLS、多頁、序號、規則、barcode decode、200 頁 reconciliation、simplex/duplex overlay 及 6 頁含 CJK/I25 的 PS。發布包與更新測試結果待打包後記錄。

## 合成性能樣本

同機 Windows 11 x64 / Python 3.12.14；plain 固定一頁模板，每組一次，非客戶樣本或多次中位数。

| Records / pages | 總秒數（含 import） | Records/s（generation） | Composer peak MiB | Assembler peak MiB |
|---:|---:|---:|---:|---:|
| 1,000 | 2.68 | 377 | 87.8 | 18.1 |
| 10,000 | 24.54 | 410 | 98.8 | 99.8 |
| 50,000 | 133.84 | 376 | 148.8 | 461.3 |

所有組別 record/page reconciliation 通過。Renderer 分塊處理；qpdf 組裝器的記憶體仍隨總頁數增加，不能宣稱整條流程常量記憶體。這不是網絡、大量影像或複雜客戶文件的效能保證。
