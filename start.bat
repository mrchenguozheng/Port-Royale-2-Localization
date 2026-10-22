@echo off
REM ============================================================
REM  PR2 Localization - install / launch window
REM
REM  Starts the local web app and opens the installer page (/start).
REM  Needs only Python (standard library).
REM
REM  Keep this file ASCII + CRLF. cmd misreads UTF-8 in .bat files.
REM ============================================================
setlocal EnableExtensions

set "SRC=%~dp0src\"

call "%SRC%find_python.bat"
if not defined PY goto :nopython
set "PYW=%PY%"
if "%PY:~-10%"=="python.exe" set "PYW=%PY:~0,-10%pythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"
start "" %PYW% "%SRC%editor\server.py" --restart --open-page /start
endlocal
exit /b 0

:nopython
echo.
echo [start] Cannot start: no Python 3.11+ found.
echo [start] Install Python from https://www.python.org/downloads/
echo [start] and tick "Add python.exe to PATH".
echo.
pause
endlocal
exit /b 0
