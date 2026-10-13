# M5／M6 列印改善 — 2026-10-08

開發版本的針對性更新。未更改公開版本號、專案格式或依賴；未打包、發布或中止使用者現有程式。

## 實作與操作

- `core/print_worker.py` 為持續運作的獨立 MuPDF 程序；一次只開啟一份任務快照，逐頁寫入及釋放 RGB 影像。
- `core/printing.py` 提供順序呼叫的 headless `PrintSession`；背景工作讀取影像並沿用原有縮放／位置邏輯。採用 subprocess 管線而非 QProcess，避免在 QThreadPool 不同任務間轉移 Qt 程序物件；QPrinter／QPainter 仍由 GUI 執行緒管理。
- 每批重用 worker；逐檔關閉文件，失敗隔離，worker 崩潰後可建立新程序處理下一份。RGB 檔只保留一頁。
- 檔案輸入背景複製，核對複製前後大小／修改時間；不再 `document.tobytes()` 重寫。開啟中的 PDF 仍在必要鎖範圍取得含未保存修改的 bytes 快照，初始快照成本保留。
- 取消不再提交下一頁，已取消的影像不送印。五秒未回應可終止 renderer；背景等待退出、關閉管線後清理暫存。Windows Python redirector 另記錄實際 worker PID，終止及記憶體測量使用實際 renderer。
- 列印時保留 PDF 的捲動、縮放、分頁切換；Canvas 暫時使用 Hand，禁止內容修改及來源關閉。原有 mutation transaction 同樣阻止列印期間修改；結束恢复工具和控制項。
- 批次 Preferences 建立候選 QPrinter，確認才替換；同步通用設定、顯示實際紙張尺寸，保留被確認的 printer 實例。每份 PDF 仍使用自己的 painter／spool job。
- 後續介面修改優先；可再使用系統確認。Printer settings 保留紙張尺寸及邊界，方向可選固定或按 PDF 自動決定。更換打印機清除上一部機的實例；處理期間停用設定區。
- 不把 driver 私有資料存入一般設定 JSON。自訂 printer layout 僅保留於本次對話框／批次；重新開啟需確認。系統批次對話框不提供未接入的頁碼／selection 範圍選擇。

## 針對性驗證

**45 個不同的列印相關測試通過**，Ruff 與 `git diff --check` 通過。

- 既有 single／batch controller、取消／跳過／部分頁失敗、UI guard、設定及 native confirmation 測試。
- 四種旋轉、CropBox、三種縮放、偏移的像素與原渲染方法一致。
- 持有主程序 DOCUMENT_LOCK 時，獨立 renderer 仍可完成頁面；實際 worker 迴圈多頁只呼叫一次 `fitz.open`。
- worker 崩潰後下一份文件可送印；不回應的 renderer 取消後被終止，無正式 PDF 或暫存目錄殘留。
- Preferences 確認／取消、更換打印機、同實例執行兩份 PDF、自訂紙張與方向覆寫；切換 PDF 分頁仍鎖住保存、Undo 及內容修改。
- 原回歸中兩個預期作了必要更新：工作區不再整體停用；使用同一 QPrinter 的兩個獨立 spool job，以送印時的名稱／份數及兩份輸出驗證。
- 離屏 Qt 檢查 **960×640、深／淺色、100%／200%**：獲焦的紙張、雙面、方向及 DPI 控制項完整可见，Start／Cancel／Close 固定於可見 footer；截圖保存在忽略的 `.benchmarks`。

測試主機建立 QPrinter 時會輸出 `0x80040155` 原生診斷；測試程序繼續運作並以成功狀態完成。此離屏驗證不能代替實際 Windows 打印機驅動驗收。

## 效能量測

重複方法：`python scripts/benchmark_printing.py --pages 100 1000 --dpi 72`。

合成文字 A4、72 DPI、同機單次樣本；不是冷／暖快取中位數，也不是打印機吞吐量。

| 頁數 | 準備 | 獨立程序渲染 | 舊逐頁重新解析渲染 |
| --- | --- | --- | --- |
| 100 | 0.188 s | 0.394 s | 0.248 s |
| 1,000 | 0.184 s | 4.004 s | 4.536 s |

100 頁有額外程序／檔案傳輸成本；不宣稱所有文件都更快。1,000 頁中 parent RSS 約 59.37–59.38 MiB；實際 worker RSS 約 42.82–43.55 MiB。MuPDF 文件結構及資源快取仍可能隨文件複雜度增加，不承諾絕對固定記憶體。

## 待統一驗收

- 真實大型／影像密集 PDF、300／600 DPI、網絡來源。
- Windows 原生 Preferences 及實際打印機的雙面、Tray、custom stock、finishing。
- Frozen worker 入口已接入 main/spec；Windows 打包與完整回歸仍待統一安排。
- 「Sent」代表送到 spooler，不等同實際打印完成；已送頁面不能保證撤回。
