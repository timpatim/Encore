@echo off
rem Encore - creates the Python environment (.venv) next to this file.
rem Needs Python 3.10 or newer installed on this PC (python.org or the Microsoft Store).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python not found. Install Python 3.10 or newer, or use conda: see README.md
  pause
  exit /b 1
)
echo Creating the .venv environment with %PY% ...
%PY% -m venv .venv || (echo Could not create the venv. & pause & exit /b 1)
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10 or newer is required'" || (pause & exit /b 1)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
echo.
echo Environment ready. Run Encore.bat
pause
