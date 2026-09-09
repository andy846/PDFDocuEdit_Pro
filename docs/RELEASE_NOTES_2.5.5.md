# PDFDocuEdit Pro V2.5.5

## 新增：免 Installer 更新

- Windows managed portable 版新增 **Help → Check for Updates…**，可從 GitHub Releases 檢查、下載及安裝新版本。
- 支援背景下載、進度顯示及取消；完成下載後由使用者選擇更新並重啟。
- 固定 `Launcher.exe` 管理完整版本資料夾，更新時不覆寫使用中的 EXE／DLL。
- Ed25519 簽署更新清單，並驗證 ZIP 大小及 SHA-256；拒絕危險路徑、連結及損壞附件。
- 新版啟動失敗可還原上一版與設定；中斷的版本切換可於下次啟動復原。
- 未儲存文件及列印中的關閉保護沿用原本流程；使用者 PDF 不會被更新程序搬動。
- GitHub API 額度不足時，使用公開 Release 重新導向作為版本查詢備援。

## 首次部署

使用 `PDFDocuEdit-Pro-v2.5.5-Managed-Portable-Windows-x64.zip`，整包解壓到可寫入且公司允許執行的資料夾，將桌面捷徑指向 `Launcher.exe`。既有 Setup／普通 Portable 版需做一次手動過渡。

**不要將 managed 部署 ZIP 解壓覆蓋正在使用的舊部署資料夾。** 後續更新使用程式內功能。更新包及初次部署包用途不同，詳見 [操作及發佈指南](https://github.com/andy846/PDFDocuEdit_Pro/blob/v2.5.5/docs/PORTABLE_UPDATES.md)。

## 本機驗證

- 完整測試套件：441 項通過。
- 額外真實子程序測試：完成舊版退出、簽署更新安裝、新版確認及原設定保留。
- Ruff、原始碼檢查、套件相依性檢查通過。
- 實際 PyInstaller 主程式與固定啟動器已編譯；隔離部署的啟動確認通過。
- 已驗證更新簽章、ZIP CRC、SHA-256，並確認交付包不含簽署私鑰。

公司端標準帳戶的執行政策、網絡及真正跨版本更新仍需實機驗收。失敗備份會保留以供救援；詳細位置及清理方式見操作指南。
