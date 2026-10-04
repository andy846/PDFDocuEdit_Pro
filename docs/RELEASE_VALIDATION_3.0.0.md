# v3.0.0 正式驗收記錄

2026-10-05，Windows x64 / Python 3.12.14。本機正式回歸、編譯版、隔離安裝、簽署更新及發布包驗收已完成。GitHub PR 與版本 tag 的檢查結果可在 [GitHub Actions](https://github.com/andy846/PDFDocuEdit_Pro/actions/workflows/ci.yml) 查看；正式發布以所需 CI 通過為門檻。

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

來源版端到端 smoke 通過：含 Windows font、CJK、Excel/XLS、多頁、序號、規則、barcode decode、200 頁 reconciliation、simplex/duplex overlay 及 6 頁含 CJK/I25 的 PS。

## 發布包與更新驗收

| 項目 | 實際結果 |
|---|---|
| Windows build | PyInstaller 6.14.2 主程式、managed Launcher、Managed Portable、簽署 Update ZIP、Inno Setup 6 Setup 均完成。 |
| Frozen acceptance | 編譯版在 200% 縮放、深淺色及窄窗通過；100 records / 200 pages、Excel/XLS、CJK、序號、條件規則、barcode decode 及背景工作均通過。 |
| Overlay | 60 頁 / 20 封：simplex 60 頁；duplex 80 頁 / 40 sheets，含 20 張空白背頁。兩者均成功解碼 120 個 barcode。 |
| PostScript | 2 records × 3 pages、三種 Stock、CJK 及 I25，生成 6 頁 PS + 核對 PDF；Ghostscript 解譯後頁數／尺寸一致。沒有產生 JDF。實機紙匣驗收仍待提供設備樣本。 |
| 隔離安裝 | QA 專用 Inno installer 安裝相同編譯 payload、執行端到端 acceptance，然後卸載；不註冊 PDF handlers／快捷方式。這是 payload 安裝驗收，沒有在使用者現有安裝上執行正式 Setup。 |
| 更新 | 真實 v2.5.16 / v3.0.0 frozen 程式使用目前 source supervisor、腳本發出 restart，驗證簽署更新、啟動 handshake、保留設定 sentinel，最終 state current=3.0.0、previous=2.5.16、phase=stable。不是手動操作 updater UI 的驗收。 |
| Integrity | Ed25519 manifest 簽章、三個主要下載的 SHA256、Update/Managed ZIP 內版本與 source fingerprint 均一致；Ghostscript 原始 COPYING 已包含，未包含 signing key。 |

發布 payload 的 source fingerprint：`e28c71de358eb2e21d02478efb96e7f98d9f23bb9e341a82118d5fe93624a69d`。CI／文件的後續修正不變更這份已驗證的應用程式 payload。

| 發布檔案 | Bytes | SHA256 |
|---|---:|---|
| Update-Windows-x64.zip | 351508581 | `925c9f3e13c11eb9240eac6eebfa24d4fc87b6cada8ed57d1774f5abfcae5ebe` |
| Managed-Portable-Windows-x64.zip | 364480422 | `20e8eb972086df02857c6d7878b0b1b99f8c8d2e1835e72536892d8e87d2ebee` |
| Setup-Windows-x64.exe | 242653585 | `8deda2a98d0ccd32f419c588210858d16dbd43c5adf8fa5b3734c81ab52cc55f` |

完整檔名前綴為 `PDFDocuEdit-Pro-v3.0.0-`，下載另附 `.sha256`。本機證據保留於 `build/release-v3.0.0-validation/`：`formal-final.json`、各模組 JUnit/log、`source-smoke-4/result.json`、`frozen-200/result.json`、`upgrade-final/result.json`、`artifacts.json`；隔離安裝證據為 `build/composition-install-qa/result.json`。初次測試失敗及修正重驗紀錄亦保留。

Windows CI 的 Ghostscript 準備步驟改為驗證固定 installer SHA256 後抽取 payload，避免 10.05.1 不支援 `/S` 而等待互動視窗；不跳過 PS 測試。

## 合成性能樣本

同機 Windows 11 x64 / Python 3.12.14；plain 固定一頁模板，每組一次，非客戶樣本或多次中位数。

| Records / pages | 總秒數（含 import） | Records/s（generation） | Composer peak MiB | Assembler peak MiB |
|---:|---:|---:|---:|---:|
| 1,000 | 2.68 | 377 | 87.8 | 18.1 |
| 10,000 | 24.54 | 410 | 98.8 | 99.8 |
| 50,000 | 133.84 | 376 | 148.8 | 461.3 |

所有組別 record/page reconciliation 通過。Renderer 分塊處理；qpdf 組裝器的記憶體仍隨總頁數增加，不能宣稱整條流程常量記憶體。這不是網絡、大量影像或複雜客戶文件的效能保證。
