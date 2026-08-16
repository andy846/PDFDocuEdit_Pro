# Windows 打包指南（免安裝 Python 執行）

目標：喺**有 Python 3.12 嘅 Windows x64 機器**（build 機）打包一次，產出一個資料夾，
可以原封不動複製到**冇安裝 Python、冇 Ghostscript** 嘅測試機（只有 MS Office）直接執行。

## 快速開始（用 build kit）

1. 由 macOS 端執行 `python scripts/make_windows_build_kit.py` → `release/PDFDocuEdit_Pro-Windows-build-kit.zip`（~35MB，已排除 venv/backup/舊 build 等垃圾，含完整 Ghostscript）。
2. 將 zip 抄到 build 機解壓，例如 `C:\build\PDFdocuEdit_Pro`。
3. 喺 cmd 執行：
   ```bat
   cd /d C:\build\PDFdocuEdit_Pro
   scripts\build_windows.bat
   ```
   bat 會：裝依賴 → verify_source → 跑測試（offscreen）→ PyInstaller 打包。
4. 產出 `dist\PDFDocuEdit Pro\`，成個資料夾複製去測試機直接行。

## 打包內容（全部已喺倉庫準備好）

| 項目 | 狀態 |
|---|---|
| PyQt6 / PyMuPDF / numpy / opencv / pdf2docx / openpyxl / PIL / pyzbar 等 | ✅ 由 `requirements-base.txt` 安裝並打包 |
| **Ghostscript（Windows 版，含 bin/lib/Resource/iccprofiles）** | ✅ 倉庫 `Ghostscript/` 已齊，spec 自動打包入 `ghostscript/` 資料夾；App 會優先搵捆綁版（`core/capabilities.py::_bundled_ghostscript`） |
| **MS Office 轉 PDF（免 LibreOffice）** | ✅ Windows + comtypes：Word/Excel/PowerPoint 經 COM 轉 PDF（`core/tools.convert_office_files` 已內建） |
| pyzbar 嘅 zbar DLL | ✅ spec 自動將 pyzbar 套件內嘅 DLL 收集為 binaries |
| 圖示/App_icon/splash | ✅ spec datas |

## Build 機準備（只需一次）

1. 安裝 **Python 3.12 64-bit**（python.org，勾選 Add to PATH）。
2. 將專案整個資料夾複製到 build 機（例如 `C:\build\PDFdocuEdit_Pro`）。
3. 開 cmd，執行：
   ```bat
   cd /d C:\build\PDFdocuEdit_Pro
   scripts\build_windows.bat
   ```
   bat 會：裝依賴 → verify_source → 跑測試（offscreen）→ PyInstaller 打包。

## 產出

```
dist\PDFDocuEdit Pro\
  ├─ PDFDocuEdit Pro.exe        ← 主程式
  ├─ _internal\                 ← 所有 Python 套件 + Qt 插件
  ├─ App_icon\ ...              ← 工具圖示
  └─ ghostscript\               ← 完整 Ghostscript
```

## 測試機部署（冇 Python）

1. 將成個 `dist\PDFDocuEdit Pro` 資料夾複製過去。
2. 直接雙擊 `PDFDocuEdit Pro.exe`。
3. 注意：
   - 首次啟動解壓 `_internal` 內容會慢少少（正常）。
   - Windows SmartScreen 可能警告「未知發行者」→ 更多資訊 → 仍然執行。
   - 防毒軟件對 PyInstaller 打包有機會誤報——將資料夾加入白名單。

## 功能驗證清單（測試機）

- [ ] 開 PDF / PostScript（PostScript 轉 PDF 用捆綁 Ghostscript，唔使裝）
- [ ] Office → PDF（Word/Excel/PPT，經 COM 用測試機嘅 MS Office）
- [ ] Deep Search、條碼/QR（zbar DLL 已捆綁）
- [ ] 加密/解密、批次列印、合併/壓縮等全 Tools

## 進階：單一 Setup EXE

- 喺 build 機裝 **Inno Setup 6**，執行 `python scripts/build.py`（自動跑 spec + `installer/PDFDocuEditPro.iss`），產出 `release\PDFDocuEdit-Pro-0.98b-Windows-x64-Setup.exe`。
- 或者喺 PyInstaller 命令加 `--onefile`（改用 onedir 更穩定，建議維持現狀）。

## 疑難排解

| 問題 | 處理 |
|---|---|
| `ModuleNotFoundError: comtypes` | build 機用 64-bit Python + `pip install -r requirements-windows.txt` |
| 打包後開唔到 PostScript | 確認 `dist\...\ghostscript\bin\gswin64c.exe` 存在；App 亦可用 Preferences 指定位址 |
| Office 轉 PDF 失敗 | 測試機嘅 Office 要能正常開啟該檔案（第一次 COM 啟動可能較慢）；Excel 需勾選「信任 VBA」先可用 `ExportAsFixedFormat` |
| 條碼掃唔到 | 檢查 `_internal\pyzbar\` 有冇 `libzbar-*.dll`；若 build 機 wheel 冇帶 DLL，喺 build 機裝 zbar（vcpkg/choco）後再打包 |
