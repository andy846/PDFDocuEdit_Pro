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
