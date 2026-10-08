# 2026-10-08 開發更新鞏固紀錄

公開版本號維持 **v3.0.2**。本紀錄屬於目前開發工作樹；不代表已有新安裝包或 GitHub release。

## 檢查範圍

今天的 Generic Barcode 表格編輯、快捷鍵與跨模式路由、左側 Flatten／Repair 入口、Splash 自動版本，以及 PDF Workspace 圖片加入與編輯。

## 本輪修正

| 範圍 | 修正及行為 |
| --- | --- |
| 图片／簽名圖片 | Add Image 與 Signature Image 共用 `core/page_images.py`。新加入的兩類物件均可選取、拖動、縮放、輸入精確尺寸、刪除及 Undo／Redo，保存重開後仍可操作。Signature Image 不建立數碼簽署。 |
| 選取狀態 | 點頁面空白處會清除畫布及右側面板選取；清單刷新後沒有可用物件，清空屬性並停用 Apply／Remove，避免操作舊選取。 |
| 尺寸精度 | 顯示 mm 可四捨五入，未修改的座標及尺寸仍保留原始點數；避免直接 Apply 時因顯示精度而把頁邊圖片推到頁面以外。 |
| PDF 內容安全 | 編輯採用獨立 placement stream 與 copy-on-write，不移動共用 image XObject。編輯／刪除前驗證 stream；外部工具合併或改寫內容時阻止操作，保護其他頁面內容。沿用既有 mutation transaction 與還原流程。 |
| 匯入相容 | 插入前 wrap 原有未包裹的 PDF graphics state，避免把自動產生的 q/Q stream 誤當新圖片；保留來源既有圖形。 |
| 面板 UX | Apply 固定在 Manage 底部；設定可捲動，鍵盤焦點自動露出整個輸入欄及加減按鈕。沿用 `ui/responsive.py`，新增 `whole_control` 選項，既有呼叫預設行為不變。 |
| 說明 | 更新 README 與工具提示，區分簽名圖片和數碼簽署，說明精確位置、比例、空白處取消選取及保存重開。 |

## 針對性驗證

**405 個不同的相關測試全部通過**；非完整專案回歸。

- 快捷鍵、Command registry、自訂綁定、模式路由、Merge 工作台、Flatten／Repair 入口、Generic Barcode 及 Splash：**109 passed**。
- 圖片內容、標註、PageOverlay、交易／Undo、鍵盤焦點及既有低解像度 UI：296 項。首次有 12 項因 Qt literal `&` 的按鈕文字斷言未同步而失敗；修正預期後重跑該 12 項全部通過，其餘 **284 passed**。
- 今日所有修改及新增 Python 檔案：**Ruff passed**。
- `git diff --check`：通過。
- 離屏 Qt：**960×640，深／淺色，100%／200%**；已截圖檢查並驗證 Apply 與每個獲焦尺寸欄完整位於可見範圍。
- 圖片測試包括四種頁面旋轉、CropBox、複製頁／共用資源隔離、保存後 xref 重編、失敗回復及來源檔不變。

## 邊界及下一次驗收

### H3／H4 搜尋與套印生命週期修正

- 搜尋取消後保持 `_tasks` 與 `_search_tasks` 引用，真正 finished 才清除。相同文件只暫存最後一個搜尋要求，保留查詢、選項、頁面及來源 revision；關閉文件、取消整個任務或退出時不續跑。
- 延遲的 result／progress／error 加入取消及來源／generation 檢查，丟棄結果仍執行既有清理 callback。已提交的 batch 事件保持原有語義。
- Overlay 共用封號／頁碼同步：先夾限封號，再讀該封計劃並夾限頁碼；保留原本 signal blocking 狀態。載入計劃先驗證，無效計劃停止預覽、提示錯誤及阻止生成，保留現有專案。
- 新增真實 QThreadPool 搜尋替換／取消／關閉／來源變更測試，以及隔離程序 25 輪快速搜尋和垃圾回收測試；沒有重現原生 Qt 崩潰。因此保持 FunctionTask 既有 auto-delete 設定，不將未複現的 C++ 銷毀風險描述為已證實。
- Overlay 新增較小專案的 Undo／Redo、可變分封頁數、無效計劃復原及 signal blocking 驗證。
- 本組 **30 個不同的相關測試通過**：搜尋任務生命週期、搜尋選頁操作、FunctionTask 及 Overlay UI。測試開發時修正唯讀 revision 與未具備完整覆核紀錄的 fixture；最終搜尋 7 項及 Overlay 7 項重跑全過，既有其餘 16 項通過。Ruff 與 whitespace 檢查通過；不是完整回歸或 Windows 原生互動驗收。

- 舊版加入或外部 PDF 未標記的圖片不會自動變成可編輯圖片。
- 外部工具改寫 placement stream 後，可能需要重新插入該圖片；不猜測內容結構後直接修改。
- 本輪沒有更改公開版本號、Designer／Workflow／Barcode 專案格式或新增依賴。
- 離屏 UI 檢查不能代替實際 Windows 多螢幕、顯示縮放與滑鼠操作驗收。
- 完整回歸、Windows 打包及發佈沿用整批修改完成後的統一驗收安排。現有執行中的程式須重啟才載入更新；本輪未中止使用者的程式或未保存工作。
