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
