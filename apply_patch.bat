@echo off
REM ============================================================
REM  PR2 Localization - developer one-shot: build + deploy
REM
REM  Normalizes the translations, checks breaks, compiles the
REM  packs, copies everything into the game folder and verifies
REM  the result. Safe to run repeatedly; unchanged files are
REM  skipped.
REM
REM    apply_patch.bat                 ja + zh, last game dir
REM    apply_patch.bat --langs ja
REM    apply_patch.bat --launch
REM
REM  Keep this file ASCII + CRLF.
REM ============================================================
setlocal

call "%~dp0src\find_python.bat" || goto :nopython

%PY% "%~dp0src\tools\pack\apply_patch.py" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%

:nopython
echo.
echo [all] No Python 3.11+ was found. Install Python and retry.
echo.
pause
endlocal
exit /b 1
