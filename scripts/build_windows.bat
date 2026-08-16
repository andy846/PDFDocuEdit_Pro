@echo off
rem PDFDocuEdit Pro - Windows release build (run on a Windows x64 machine
rem with Python 3.12 installed; the output runs on machines WITHOUT Python).
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 64-bit is required. Install it from python.org first.
    exit /b 1
)

echo === 0/5 Preflight: required files present ===
if not exist "PDFDocuEdit Pro.spec" (echo [ERROR] Missing "PDFDocuEdit Pro.spec" & exit /b 1)
if not exist "Ghostscript\bin\gswin64c.exe" (echo [ERROR] Missing Ghostscript\bin\gswin64c.exe & exit /b 1)

echo === 1/5 Install dependencies (base + dev + Windows COM) ===
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements-windows.txt || exit /b 1

echo === 2/5 Verify source assets ===
python scripts\verify_source.py || exit /b 1

echo === 3/5 Run the test suite (offscreen) ===
set QT_QPA_PLATFORM=offscreen
python -m pytest -q || exit /b 1

echo === 4/5 PyInstaller build (bundles PyQt6, PyMuPDF, Ghostscript, Office COM backend) ===
python -m PyInstaller --clean --noconfirm "PDFDocuEdit Pro.spec" || exit /b 1

echo === 5/5 Done ===
echo Portable output folder : dist\PDFDocuEdit Pro\
echo Executable             : dist\PDFDocuEdit Pro\PDFDocuEdit Pro.exe
echo.
echo Copy the whole "PDFDocuEdit Pro" folder to the target Windows machine
echo (no Python or Ghostscript installation is needed there).
echo.
echo Optional: install Inno Setup 6 and run installer\PDFDocuEditPro.iss to
echo produce a single setup EXE.
endlocal
