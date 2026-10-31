@echo off
chcp 65001 >nul
rem Сборка DnevnikiPraktiki.exe, работающего на Windows 7 SP1 и новее.
rem Нужен Python 3.8 (https://www.python.org/downloads/release/python-3810/):
rem   для 32-битной Windows 7 - "Windows installer (32-bit)", для 64-битной - "(64-bit)".
cd /d "%~dp0"

set PY=py -3.8
%PY% --version >nul 2>&1 || set PY=python
%PY% -c "import sys; assert sys.version_info[:2]==(3,8), sys.version" || (
  echo Нужен Python 3.8 - более новые версии не работают на Windows 7.
  pause & exit /b 1
)

%PY% -m venv .venv-build || (pause & exit /b 1)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade "pip<25" || (pause & exit /b 1)
python -m pip install -r requirements-win7.txt || (pause & exit /b 1)

pyinstaller --noconfirm --clean DnevnikiPraktiki.spec || (pause & exit /b 1)

echo.
echo Готово: dist\DnevnikiPraktiki.exe
pause
