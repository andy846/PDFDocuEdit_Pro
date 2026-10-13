# Mac Managed 登入版 → v3.0.5 更新及實測

適用於已安裝 **Apple Silicon Managed 登入版 v3.0.3／v3.0.4** 的 Mac。
v3.0.5 已公開。優先在原有程式使用 Help → Check for Updates，下載後保存工作，再按 Update and Restart。
以下本機驗收工具步驟保留作備用及產生更新報告；一般使用者可直接採用程式內更新。

GitHub Release：[v3.0.5](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.5)。

## 準備

1. 保存工作，完全退出 PDFDocuEdit Pro。
2. 從 GitHub Release下載以下三個檔案，放入 `Downloads/v3.0.5-update`：
   - `PDFDocuEdit-Pro-v3.0.5-Update-macOS-arm64-Private.zip`
   - `update-macos-arm64-private.json`
   - `update-macos-arm64-private.sig`
3. 取得 `codex/unified-release-v3.0.5` 分支的候選原始碼（4900521f1b7dd8d26ec3d9ccd8693c790c4581f2），解壓後在 Terminal
   進入該資料夾。原始碼含驗收工具，不需要自行編譯 PDF 編輯器。

需要 Python 3.12。以下只安裝工具所需的現有簽章驗證依賴，毋須輸入帳戶密碼：

```sh
python3 -m venv .mac-update-test
.mac-update-test/bin/python -m pip install cryptography==46.0.7
.mac-update-test/bin/python -m scripts.macos_candidate_upgrade \
  --app "/Applications/PDFDocuEdit Pro.app" \
  --folder "$HOME/Downloads/v3.0.5-update" \
  --report "$HOME/Desktop/mac-update-result.json"
```

如程式安裝於其他位置，修改 `--app`。不要解壓更新 ZIP；工具會先驗證簽章、
檔案雜湊、平台及帳戶項目，再使用現有更新核心安裝。
保持 Terminal 開啟，測試後正常退出程式，才會寫出桌面的結果報告。

## 實測清單

- [ ] 升級後版本為 v3.0.5，Splash 正常顯示。
- [ ] 帳戶登入成功，或既有有效離線批准正常開啟。
- [ ] Settings 中帳戶身份正確。
- [ ] 最近專案位置、偏好及原本文件仍在，可開啟 PDF／Designer 專案。
- [ ] 正常退出，再從 Applications 開啟，仍為 v3.0.5。
- [ ] 已成功登入並保存批准後，斷開網絡，再開啟仍可使用。

請回覆以上結果，並提供桌面的 `mac-update-result.json`；不要提供密碼或登入 token。
報告只證明更新及啟動確認，不代表已測試真實帳戶登入／離線使用。

## 如遇到問題

- 顯示仍有程式執行：先正常退出，毋須強制刪除 lock 檔。
- 顯示已有 pending update：停止操作並提供錯誤，工具會保留現有檔案。
- 簽章、平台或帳戶項目不符：不會安裝；核對是否下載同一版本的三個檔案。
- 啟動失敗：沿用現有更新回退，保留前一版本及設定。
- Mac 測試版未經 Apple 公證；如系統阻擋，使用 macOS 的個別允許開啟程序，
  不要全域關閉 Gatekeeper。

既有 v3.0.4 GitHub Release 保持不變。v3.0.5 按擁有人要求已公開，候選實機驗收缺項仍如實列明。
