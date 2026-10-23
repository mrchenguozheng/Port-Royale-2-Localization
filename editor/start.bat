@echo off
REM Standalone translator editor (development entry).
setlocal
set "ROOT=%~dp0.."
for %%i in ("%ROOT%") do set "ROOT=%%~fi"
call "%ROOT%\src\find_python.bat"
if not defined PY goto :nopython
start "" "%PY%" "%ROOT%\editor\server.py" --data "%ROOT%\src" --web-dir "%ROOT%\editor\web" --port 8781
endlocal
exit /b 0

:nopython
echo.
echo [editor] Python 3.11+ was not found.
echo [editor] Install Python or use a translator package with bundled Python.
pause
endlocal
exit /b 0
