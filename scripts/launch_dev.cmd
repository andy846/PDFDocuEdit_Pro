@echo off
setlocal
if not exist "%~dp0..\.venv-dev\Scripts\python.exe" (
  echo Local .venv-dev is missing. See docs\DEVELOPMENT_WORKSPACE.md.
  exit /b 1
)
"%~dp0..\.venv-dev\Scripts\python.exe" "%~dp0launch_dev.py" %*
exit /b %errorlevel%
