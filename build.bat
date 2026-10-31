@echo off
rem Builds dist\DnevnikiPraktiki.exe that runs on Windows 7 SP1 and newer.
rem Requires Python 3.8: https://www.python.org/downloads/release/python-3810/
rem   32-bit Windows 7 -> "Windows installer (32-bit)", 64-bit -> "(64-bit)".
cd /d "%~dp0"
set PYTHONUTF8=1

set PY=py -3.8
%PY% --version >nul 2>&1 || set PY=python
%PY% -c "import sys; assert sys.version_info[:2]==(3,8), sys.version" || (
  echo Python 3.8 is required - newer versions do not run on Windows 7.
  pause & exit /b 1
)

%PY% -m venv .venv-build || (pause & exit /b 1)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade "pip<25" || (pause & exit /b 1)
python -m pip install -r requirements-win7.txt || (pause & exit /b 1)

pyinstaller --noconfirm --clean DnevnikiPraktiki.spec || (pause & exit /b 1)

echo.
echo Done: dist\DnevnikiPraktiki.exe
pause
