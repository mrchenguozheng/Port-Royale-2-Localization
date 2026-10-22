@echo off
REM ============================================================
REM  PR2 Localization - install / launch window
REM
REM  Default: start the local web app in THIS console window and
REM  open the installer page. Keep the window open to watch the
REM  backend log; close it (or Ctrl+C) to stop the server.
REM
REM  --status: list running editor backends (ports, pids) and exit.
REM
REM  Keep this file ASCII + CRLF. cmd misreads UTF-8 in .bat files.
REM ============================================================
setlocal EnableExtensions

set "SRC=%~dp0src\"
set "TOOLS=%SRC%tools\"

if /I "%~1"=="--status" goto status

call "%SRC%find_python.bat"
if not defined PY goto :nopython
title PR2 Localization
echo Starting local server... close this window to stop it.
echo.
"%PY%" "%SRC%editor\server.py" --restart --open-page /install
echo.
echo Server stopped.
pause
endlocal
exit /b 0

:status
call "%SRC%find_python.bat"
if not defined PY goto :nopython
"%PY%" "%TOOLS%install\server_status.py"
echo.
pause
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
