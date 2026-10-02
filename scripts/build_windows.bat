@echo off
rem PDFDocuEdit Pro - canonical Windows release build.
rem Run after CI succeeds, on Windows x64 with Python 3.12, Inno Setup 6, and the update signing key.
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 64-bit is required. Install it from python.org first.
    exit /b 1
)

echo === 0/2 Preflight: required files present ===
if not exist "PDFDocuEdit Pro.spec" (echo [ERROR] Missing "PDFDocuEdit Pro.spec" & exit /b 1)
if not exist "Ghostscript\bin\gswin64c.exe" (echo [ERROR] Missing Ghostscript\bin\gswin64c.exe & exit /b 1)

echo === 1/2 Install build dependencies ===
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements-windows.txt || exit /b 1

echo === 2/2 Verify source, package, sign, and create checksums ===
set QT_QPA_PLATFORM=offscreen
python scripts\update_release.py build || exit /b 1

echo Release artifacts are available in the release folder.
endlocal
