@echo off
rem Encore - starts the local server and opens the interface (http://127.0.0.1:8190).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m encore %*
  goto :end
)
if defined CONDA_PREFIX (
  python -m encore %*
  goto :end
)
echo No environment found: run install.bat first (venv),
echo or open a conda prompt, run "conda activate encore", then run this file again.
:end
pause
