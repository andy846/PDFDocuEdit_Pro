# Document Designer 字體診斷更新（2026-10-02）

## 字體來源

Excel / CSV / TXT 僅提供欄位值；來源文件字體不會覆蓋模板字體。
Excel 的 number_format 用於日期及前置零的文字轉換，與輸出字體分開。
模板物件指定主要字體；主要字體已包含的字形優先。只有明確設定的缺字修補會使用另一個字體。

## 本輪修正

缺字錯誤加入模板字體名稱、實際 PDF font face 和 font filename；預覽及生产前檢查共用診斷。
job.json 新增 font_policy 及 template_fonts（物件、模板頁、主要字體、已配置修補），不儲存欄位文字。
這能區分主要字體缺字、所選字體檔案與名稱不符，以及真正需要逐字修補的情況。
沒有自動替换客戶標準字體、沒有停用輸出前字形驗證、沒有修改模板 schema。

## 核對使用者問題

工作 20261001-171755-e5b08f45 的紀錄沒有字體明細，模板名稱 Untitled document；
使用者隨後保存 AAAWER.pdcx，確認失敗 object 9487e7f428b244ff89924ff12cfd1def
是第一頁 Field_2，主要字體 Noto Sans，實際 face Noto Sans Regular，缺少 U+7530。
第一頁六個欄位全為 Noto Sans；第二頁文字為 Bookman Old Style。
未修改客戶原模板或字體，以原模板和 Excel 398 筆在 QA 資料夾重現同一 Record 2 / Field_2 缺字。
Record 2 存在多個缺字，本次迭代 set 首先回報 U+6587；驗證不能假定多缺字集合的第一個 Unicode 固定。

錯誤明確為 Record 2 / Field_2 / Template page 1 / U+7530（田），輸出前停止，沒有生成 PDF。

## 驗證

不同 Excel cell fonts（Arial / Microsoft YaHei）但相同文字，使用相同模板字體的預覽像素相同。
Noto Sans 沒有田字：兩個來源均在同一筆被拒絕，錯誤包含模板名稱及實際字體，並產生診斷紀錄。
Noto Sans CJK HK 包含田字：兩個來源均完成兩頁生產，文字可提取，主要字體不受 Excel 格式影響。
既有逐字修補 / Windows font export / Designer 修補 Undo 測試仍通過。
使用者目前開啟的程式未覆寫或關閉；新測試版在 dist-font-diagnostics。

驗收結果：242 個 Composition 測試通過（75.43 秒），Ruff / diff 檢查通過；新 Windows frozen build 在 200% 下完成既有端到端 smoke，含 Excel / CSV / 字體修補 / 多頁 / 流水號 / QR / Barcode。
本次沒有重跑整個 editor suite；前一 Excel 版本完整 1,073 項通過，本次變更範圍為字體診斷和工作紀錄。
