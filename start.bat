@echo off
REM ============================================================
REM  PR2 Localization - open the localization window
REM
REM  This script only starts the window. Everything is done
REM  inside it, one button at a time:
REM
REM    - Build injector     PR2TextSource.dll / PR2Launcher.exe
REM    - Build languages    compile the ticked packs
REM    - Deploy             copy them into the game folder
REM    - Run / Vanilla
REM
REM  Nothing is compiled automatically, so you can rebuild only
REM  what you actually changed.
REM
REM  Keep this file ASCII + CRLF. cmd misreads UTF-8 in .bat files.
REM ============================================================
setlocal

REM %~dp0 is the repo root, where the tools live one level down.
set "SRC=%~dp0src\"
set "TOOLS=%SRC%tools\"

call "%SRC%find_python.bat" --tk
if not defined PY goto :nopython

REM  pythonw.exe beside python.exe opens the window without a
REM  console behind it. Anything else (the py launcher) is used
REM  as is.
set "PYW=%PY%"
if "%PY:~-10%"=="python.exe" set "PYW=%PY:~0,-10%pythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"
start "" %PYW% "%TOOLS%build_install.py"
endlocal
exit /b 0

:nopython
echo.
echo [all] The localization window cannot open:
echo [all] no Python 3.11+ with tkinter was found.
echo [all]
echo [all] Install Python from
echo [all]   https://www.python.org/downloads/
echo [all] and tick "Add python.exe to PATH", then try again.
echo [all]
pause
endlocal
exit /b 0
