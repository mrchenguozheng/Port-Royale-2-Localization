@echo off
REM Keep this file ASCII + CRLF.
setlocal EnableExtensions
set "SRC=%~dp0src\"
call "%SRC%find_python.bat"
if not defined PY goto :nopython
"%PY%" "%~dp0src\tools\check.py"
pause
endlocal
exit /b 0
:nopython
echo [check] Python 3.11+ not found.
pause
endlocal
exit /b 0
