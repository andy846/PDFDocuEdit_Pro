# v3.0.6 候選實機測試

候選 SHA：a7bea706311b8542888c46f877ce65be63efb467
[候選草稿：下載附件](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/untagged-5373b71c3b6e4f0effca) — 20 個附件已核對完成。草稿不是正式公開版本，不會出現在正常 Check for Updates。

## Windows

保存現有工作；使用本候選的 Managed 安裝程式或隔離測試安裝登入。
確認版本為 3.0.6，Settings 帳戶身份正確；可開啟 PDF 及 Designer，偏好及原文件仍在。
請回覆是否成功。不要傳送密碼、token 或客戶資料。
原 v3.0.3 Launcher 的兩次升級將由發布者用隔離 QA 安裝另行驗證。

## Mac：從現有 Managed 登入版升級

1. 保存工作並完全退出程式。請勿先用 3.0.6 DMG 覆蓋安裝，否則不能核對本次跨版本升級。
2. 在 GitHub 登入 repo 擁有者帳戶，從 v3.0.6 草稿下載以下三項到 Downloads/v3.0.6-update：
   - PDFDocuEdit-Pro-v3.0.6-Update-macOS-arm64-Private.zip
   - update-macos-arm64-private.json
   - update-macos-arm64-private.sig
3. 下載此凍結來源的 ZIP，解壓後在 Terminal 進入原始碼資料夾：
   https://github.com/andy846/PDFDocuEdit_Pro/archive/a7bea706311b8542888c46f877ce65be63efb467.zip
4. 需要 Python 3.12。使用既有更新驗收工具（不需要編譯 PDF 編輯器）：

```sh
python3.12 -m venv .mac-update-test
.mac-update-test/bin/python -m pip install cryptography==46.0.7
.mac-update-test/bin/python -m scripts.macos_candidate_upgrade \
  --app "/Applications/PDFDocuEdit Pro.app" \
  --folder "$HOME/Downloads/v3.0.6-update" \
  --report "$HOME/Desktop/mac-update-3.0.6-result.json"
```

若安裝在其他位置，只修改 --app。不要解壓 update ZIP。
保持 Terminal 開啟；驗證版本及帳戶後正常退出程式，讓工具寫出結果報告。
重新從 Applications 開啟，確認登入及偏好正常。
成功登入並保存批准後，斷網再重新開啟，確認可以離線使用。

請回覆三項結果：登入、離線重開、跨版本更新，並提供桌面的結果 JSON。
報告不包含帳戶密碼；不自動證明真實帳戶登入或離線操作。
Mac 仍為 Apple Silicon/macOS 13+ 測試版，未完成 Apple 公證；不要全域停用 Gatekeeper。
