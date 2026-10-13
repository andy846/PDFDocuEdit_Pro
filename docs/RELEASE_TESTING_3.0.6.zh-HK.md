# v3.0.6 實機補驗

凍結 SHA：a7bea706311b8542888c46f877ce65be63efb467
[公開版本及下載附件](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.0.6) — 20 個附件已核對，Managed 安裝可以使用正常 Check for Updates。

本版按擁有者指示公開；以下四項仍待本版實機結果，不代表已通過。

## Windows：真實帳戶登入

1. 保存工作，使用本版 Managed 安裝程式，或在現有 Managed 版本選 Check for Updates。
2. 確認版本為 3.0.6，以已批准帳戶登入；Settings 顯示正確帳戶。
3. 開啟 PDF 及 Designer，確認偏好、專案位置及原文件保留。

請回覆是否成功；不要傳送密碼、token 或客戶資料。
原 v3.0.3 Launcher 的 3.0.3 → 3.0.5 → 3.0.6 隔離連續升級已通過，Launcher 及設定保留。

## Mac：登入、離線重開及跨版本更新

1. 從現有 Managed 登入版保存工作，記下更新前版本；選 Check for Updates，下載、確認保存及更新。不要先用 DMG 覆蓋安裝，以免失去跨版本更新測試。
2. 重啟後確認版本 3.0.6，登入並核對帳戶、偏好及專案位置。
3. 正常完全退出，從 Applications 再開啟；成功登入及保存批准後，斷網、完全退出再開啟，確認可離線使用。

請回覆：更新前版本 → 3.0.6，以及登入、離線重開、跨版本更新三項結果。
Mac 仍為 Apple Silicon/macOS 13+ 測試版，ad-hoc 簽署，未完成 Apple 公證；不要全域停用 Gatekeeper。

### 選用：產生機器可讀更新報告

需要額外更新報告時，可用現有驗收工具。從公開 Release 下載以下三項到 Downloads/v3.0.6-update：

- PDFDocuEdit-Pro-v3.0.6-Update-macOS-arm64-Private.zip
- update-macos-arm64-private.json
- update-macos-arm64-private.sig

下載並解壓 [凍結來源 ZIP](https://github.com/andy846/PDFDocuEdit_Pro/archive/a7bea706311b8542888c46f877ce65be63efb467.zip)，在 Terminal 進入原始碼資料夾。需要 Python 3.12，無須編譯編輯器：

```sh
python3.12 -m venv .mac-update-test
.mac-update-test/bin/python -m pip install cryptography==46.0.7
.mac-update-test/bin/python -m scripts.macos_candidate_upgrade \
  --app "/Applications/PDFDocuEdit Pro.app" \
  --folder "$HOME/Downloads/v3.0.6-update" \
  --report "$HOME/Desktop/mac-update-3.0.6-result.json"
```

安裝在其他位置時修改 --app；不要解壓 update ZIP。保持 Terminal 開啟，核對版本及帳戶後正常退出，讓工具寫出報告。報告不包含密碼，也不自動證明真實帳戶登入或離線使用；兩項仍須操作確認。
