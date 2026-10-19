@echo off
REM ============================================================
REM  PR2 Localization - build everything, then offer to install
REM
REM  Runs, in order:
REM    1. build_injector.bat  - PR2TextSource.dll / PR2Launcher.exe
REM    2. build_install.py --build - pick the languages, build the
REM                              packs and copy the whole build
REM                              output into the game folder
REM
REM  Step 2 is optional: the window can be closed without
REM  installing. A broken compile never deploys half a patch.
REM
REM  Keep this file ASCII + CRLF. cmd misreads UTF-8 in .bat files.
REM ============================================================
setlocal

set "SRC=%~dp0"
set "ROOT=%SRC%..\build\"
set "TOOLS=%SRC%tools\"

call "%SRC%find_python.bat" --tk
if not defined PY goto :nopython

echo [all] === 1/2  injector ===
call "%SRC%build_injector.bat" --no-pause
if errorlevel 1 goto :fail
if not exist "%ROOT%PR2TextSource.dll"   goto :missing
if not exist "%ROOT%PR2Launcher.exe"     goto :missing

echo.
echo [all] === 2/2  language pack and install ===
echo [all] A window will open. Tick the languages to build, then
echo [all] pick your Port Royale 2 folder and press Install.
echo [all] You can close it without installing.
echo.
%PY% "%TOOLS%build_install.py" --build
if errorlevel 1 goto :gui_failed

echo.
echo [all] Done.
call :maybe_pause
endlocal
exit /b 0

:nopython
echo.
echo [all] The injector is built, but the build-and-install window
echo [all] could not open: no Python 3.11+ with tkinter was found.
echo [all]
echo [all] To build the language packs by hand, install Python from
echo [all]   https://www.python.org/downloads/
echo [all] and tick "Add python.exe to PATH", then run:
echo [all]   src\build_translation.bat
echo [all]
echo [all] The build output is in:
echo [all]   %ROOT%
pause
endlocal
exit /b 0

:missing
echo.
echo [all] FAILED: a build output is missing. See the messages above.
call :maybe_pause
endlocal
exit /b 1

:fail
echo.
echo [all] FAILED. Nothing was installed.
call :maybe_pause
endlocal
exit /b 1

:gui_failed
echo.
echo [all] The window reported a problem, or tkinter was missing.
echo [all] See the messages above.
call :maybe_pause
endlocal
exit /b 1

:maybe_pause
if defined NOPAUSE exit /b 0
pause
exit /b 0
