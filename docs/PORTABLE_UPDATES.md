# PDFDocuEdit Pro 免 Installer 更新

## 公司首次使用

1. 從 GitHub Releases 下載 `PDFDocuEdit-Pro-v2.5.5-Managed-Portable-Windows-x64.zip`，核對同名 `.sha256`。
2. 將整個 `PDFDocuEditPro` 資料夾解壓到 `%LOCALAPPDATA%` 或公司允許寫入及執行的資料夾。請勿覆蓋既有部署資料夾。
3. 執行 `Launcher.exe`，並建立指向它的桌面捷徑。`launcher_runtime` 是啟動器依賴，必須保留。
4. 首次啟動可選擇複製現有 Windows 使用者設定。舊設定及 PDF 不會被移動。歷史便攜版的設定如不在 Windows 設定位置，可在關閉程式後把其 `config.json` 中的設定匯入新部署的 `data/config/settings.json`；先保留原檔備份。
5. 以後使用 **Help → Check for Updates… → Download Update → Update and Restart**。

下載在背景進行；可以取消。重啟時仍會詢問未儲存文件，取消儲存／關閉即延後更新。首次設定匯入需要互動，因此首次一般啟動不套用更新試啟動的 120 秒逾時。

既有 Setup／普通 Portable ZIP 不會憑空取得更新功能；必須做一次以上過渡。macOS 及從 Python 原始碼啟動時，更新視窗會說明需要 Windows managed portable 版。

## 家中發佈

使用 Windows x64、Python 3.12，以及 `requirements-dev.txt`／Windows 相依套件。

首次設定（同一套產品只做一次）：

```powershell
python scripts/update_release.py keygen
```

此命令產生 `.update-keys/signing.pem`，並把公鑰寫入 `updates/trust.py`。私鑰目錄已被 Git 排除；請另行離線備份私鑰，限制可讀取的使用者。**不可把私鑰上傳 GitHub、放入 ZIP 或寄給公司用戶。** 公鑰需隨原始碼提交；後續版本必須沿用相同私鑰。已設定公鑰時 keygen 會拒絕覆蓋，避免破壞既有客戶端信任。

每次發佈：

1. 同步程式版本：`core/resources.py`、`pyproject.toml`、`scripts/build.py`、PyInstaller spec、Windows installer 版本資訊及對應版本測試。使用 `major.minor.patch`，每次正式更新都提高版本。
2. 執行：

```powershell
python scripts/update_release.py build
```

此流程執行原始碼檢查、Ruff、完整 pytest、現有 PyInstaller 打包及啟動器打包；不要求 Inno Setup。外部 OCR／Ghostscript／veraPDF 依賴沿用既有 build 驗證。

產物存於 `release/`：

| 檔案 | 用途 |
| --- | --- |
| `PDFDocuEdit-Pro-vX.Y.Z-Update-Windows-x64.zip` | 現有 managed 版下載的完整版本，包含所有依賴 |
| `update.json`、`update.sig` | 簽署版本清單及原始 64-byte Ed25519 簽章 |
| `PDFDocuEdit-Pro-vX.Y.Z-Managed-Portable-Windows-x64.zip` | 首次部署，包含固定啟動器及初始版本 |
| 各 ZIP 的 `.sha256` | 手動下載驗證 |

3. 在隔離資料夾啟動部署包，驗證 PDF 開啟、編輯、儲存，以及 OCR／轉換等主要功能。
4. 把版本提交並建立對應 `vX.Y.Z` tag。在 `andy846/PDFDocuEdit_Pro` 建立 Release 草稿，上傳上表全部檔案及版本說明。
5. 檢查附件完整及可公開後才發佈，標記為 latest 正式版本。不要用 GitHub 自動產生的 Source code ZIP 作為更新 ZIP。不要修改已發佈版本的附件；修正需新增版本。

`--skip-build` 只允許重用版本與原始碼 fingerprint 相符的主程式產物，仍會重建啟動器。它不能把修改過的程式碼冒充成已打包版本。只建普通 Portable ZIP 可用 `python scripts/build.py --portable-only`。

簽署清單與 Windows Authenticode 是兩回事。前者驗證更新來源；如公司要求 EXE 發行者簽章，仍需原有 `PDFDOCUEDIT_SIGNTOOL`／`PDFDOCUEDIT_CERT_SHA1` 設定及公司的允許政策。

## 更新及還原機制

- 固定啟動器持有 OS 檔案鎖，監督單一主程式。再次開啟捷徑／PDF 會排隊轉交現有程式；檔案關聯指向固定啟動器。
- GitHub 最新正式 Release 提供版本；清單、簽章與 ZIP 綁定到同一個版本附件 URL。只使用 HTTPS、系統代理及正常憑證驗證，不內建 GitHub token。
- 清單簽署 schema、產品、Windows x64、版本、最低啟動器版本、ZIP 名稱、大小、SHA-256 及解壓大小。ZIP 上限 2 GiB、展開上限 8 GiB、檔案數上限 50,000。
- 下載驗證在背景完成，正式切換前由啟動器再次驗證。Windows 危險路徑、大小寫衝突、路徑穿越、連結、加密 ZIP 等均被拒絕。
- 主程式成功關閉後，解壓到獨立新資料夾，備份 `data/`，原子寫入 trial 狀態。新版主視窗初始化後回報唯一 token；確認成功後才允許操作。
- 新版 120 秒內未就緒或啟動失敗，啟動器先停止該次新版，再還原資料及上一版。斷電後可從 journal 恢復；若尚有孤立主程式持鎖，必須先關閉它，禁止帶著活躍文件還原。
- 成功後保留目前版與上一版，清除已使用的下載檔及更舊受管理版本。失敗版本及資料備份保留在 `backups/` 供調查；確認不需救援後可在所有程式關閉時手動清理。
- 用戶 PDF 位置不變。可回滾資料限於 `data/`；未來版本不得在啟動確認前改寫外部文件或做不可逆的外部資料遷移。
- 第一版啟動器不自行更新。清單要求較高 launcher 版本時會停止更新並提示手動過渡；不要覆蓋正在執行的 launcher runtime。

## 驗收與排錯

```powershell
python -m pytest tests/test_updates.py tests/test_update_ui.py
python -m pytest
python -m ruff check .
```

請在公司標準帳戶驗證：可寫入部署資料夾、可執行新版 EXE／DLL、可下載 GitHub Release 附件（包括重新導向的資產網域）、取消未儲存文件時不更新，以及一次真正跨版本更新。

更新紀錄在 `logs/updater.log`（輪替保留）。下載錯誤在更新視窗顯示；啟動／還原錯誤由啟動器提示。網絡被封鎖不會變更目前版本，也不會停用 TLS 驗證。開發環境測試不能替代公司端防毒及應用程式執行政策的實機驗收。
