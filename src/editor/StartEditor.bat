@echo off
REM ============================================================
REM  PR2 Localization - start the translation editor on its own
REM
REM  The editor is a local web app: server.py is a stdlib HTTP
REM  server that also serves the built frontend (dist\).
REM  No Python packages are needed - if python.exe exists, it works.
REM
REM  Keep this file ASCII + CRLF.
REM ============================================================
setlocal EnableExtensions

set "ROOT=%~dp0..\.."
for %%i in ("%ROOT%") do set "ROOT=%%~fi"
call "%ROOT%\src\find_python.bat"
if not defined PY goto :nopython

start "" %PY% "%~dp0server.py" --restart
endlocal
exit /b 0

:nopython
echo.
echo [editor] Cannot start: no Python 3.11+ found.
echo [editor] Install Python from https://www.python.org/downloads/
echo [editor] and tick "Add python.exe to PATH".
echo.
pause
endlocal
exit /b 0
