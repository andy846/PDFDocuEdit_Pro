# PDFDocuEdit Pro V1.1

PDFDocuEdit Pro 是一套以 PyQt6 及 PyMuPDF 開發的桌面 PDF 工作空間，集中處理閱覽、整理、標註、搜尋、列印、格式轉換及批次文件工作。支援 Windows 及 macOS。

## 主要功能

### PDF 閱覽與導覽

- 單頁、連續頁、雙頁與封面雙頁版面
- 可延遲載入的頁面縮圖、快速跳頁、縮放及頁面尺寸（mm）顯示
- 水平或垂直 Split View，可同步頁碼與縮放比例
- Browse、Hand、Select Text 及 Magnifier 四種 Canvas 模式，可直接從主工具列切換
- 書籤、目錄、文件資訊及快捷鍵指南

### 頁面整理

- 插入、刪除、擷取、分割、旋轉及重新排序頁面
- 規則式頁碼範圍處理及縮圖式頁面管理
- 合併 PDF、疊加文件、壓縮與批次處理

### 標註與內容工具

- 文字選取、螢光標示、繪圖、形狀及註解
- 區域文字擷取、條碼掃描、文件分析及診斷
- 深度搜尋及 Find/Open 文件搜尋

### 列印

- 單一及批次列印
- 頁面範圍、紙張、方向、彩色、雙面、份數、縮放、置中及偏移設定
- Draft 150、Standard 300、High 600 DPI 及 72–600 DPI 自訂列印質素
- 自動記住上一次列印設定

### 轉換與資料工具

- PDF、Office、文字、圖片及 PostScript 工作流程（視系統可用元件而定）
- Merge CSV / Excel 支援 `.csv`、`.xlsx` 及 Legacy Excel `.xls`
- 合併工作表固定命名為 `sheet1`，並保留數字型別、移除空白資料列

### 安全與私隱

- PDF 密碼及權限設定
- 本機桌面處理；文件不會因一般編輯流程自動上傳至雲端

## 支援格式

- 文件：PDF、PS、EPS、TXT
- 試算表：CSV、XLS、XLSX
- Office 轉換能力取決於 Microsoft Office 或 LibreOffice
- PostScript 轉換使用隨程式提供或系統安裝的 Ghostscript

## 下載

Windows 版本可於 [Releases](https://github.com/andy846/PDFDocuEdit_Pro/releases) 下載：

- 安裝版：`PDFDocuEdit-Pro-1.1-Windows-x64-Setup.exe`
- 免安裝版：`PDFDocuEdit-Pro-1.1-Windows-x64-Portable.zip`

開發、測試及封裝可使用專案內的 `scripts/build.py` 建置腳本。

## 版權

Copyright © 2026 Andy Leung. All rights reserved. PDFDocuEdit Pro is proprietary software. Unauthorized copying, modification, distribution, or commercial use of this software or its source code is prohibited.
