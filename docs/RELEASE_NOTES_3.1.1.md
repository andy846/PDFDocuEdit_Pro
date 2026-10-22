# PDFDocuEdit Pro v3.1.1 — Windows update

本版只提供 **Windows x64 Managed 升級包**，保留帳戶版及舊 Windows Launcher
相容入口。現有安裝請使用 **Help → Check for Updates**。Installer、Portable 及
macOS 本輪不重新製作；首次安裝沿用 GitHub 已有完整安裝版。

## 本版修補

- **六種標註移動及縮放**：Highlight、Underline、StrikeOut、Squiggly、Ink、
  Polygon 更新原生 QuadPoints／InkList／Vertices，修正拖曳框移動後標註仍留原位
  的靜默失效。保留筆劃／點位順序、外觀獨立性、交易回滾及 Undo／Redo。
- **Deep Search 安全退出**：主視窗關閉時協作取消並等待搜尋、結果查詢及報告匯出，
  包括 Pause、隱藏搜尋視窗及搜尋視窗剛關閉的情況。工作完成後才釋放 SQLite、
  暫存資源及視窗，避免程式關閉後留在背景而必須使用工作管理員終止。
- **已確認的來源實測**：擁有人在 `0e25c15` 完成這輪實測驗收，涵蓋上述修補及
  未保存標註後放棄修改、重新開 PDF 的回歸。正式封裝、完整 CI 及升級結果另行記錄。

## 相容性及限制

- PyMuPDF 繼續使用 **1.26.6**；本版不包含已撤銷的 PyMuPDF 2.0 兼容實驗。
- 保留現有 PDF 編輯、Designer、偵測 Profile、生產審查、分件命名、PDF／PS 輸出、
  帳戶保護及更新簽章，不改生產批准規則或專案格式。
- 沒有 Mac 附件；舊版 Mac updater 若只讀 latest，可能提示缺少 Mac 更新。
  已安裝 Mac 程式仍可使用，本輪不聲稱完成 Mac 驗收。
- 實體打印機、RIP、插封機及新 frozen 候選的真實帳戶登入，沒有獨立實測證據的項目
  會如實保留 Not Tested，不以先前版本驗收代填。
- [本版驗收紀錄](RELEASE_VALIDATION_3.1.1.md)、
  [標註幾何修補](POINT_ANNOTATION_GEOMETRY.md)、
  [Deep Search 關閉修補](DEEP_SEARCH_SHUTDOWN.md)。
