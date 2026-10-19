@echo off
REM ============================================================
REM  PR2 Localization - language pack build script
REM
REM  Compiles src\translations\<lang>.toml into the pack the DLL
REM  reads at runtime: build\PR2Packs\<lang>.txt
REM
REM  Two ways to get a working python.exe:
REM    1. Run from a shell where python is already on PATH
REM    2. Double-click this file - it locates Python itself
REM
REM  Keep this file ASCII + CRLF. cmd misreads UTF-8 in .bat files,
REM  so the messages below stay English on purpose.
REM  Note: %~dp0 already ends with a backslash.
REM ============================================================
setlocal

REM --no-pause: set by the window, which runs us non-interactively
set "NOPAUSE="
for %%a in (%*) do if /i "%%a"=="--no-pause" set "NOPAUSE=1"

set "SRC=%~dp0"
set "TOOLS=%SRC%tools\"
REM No trailing backslash: --out "%OUT%" would then pass the quote
REM through as part of the path and Python rejects it.
set "OUT=%SRC%..\build\PR2Packs"

call "%SRC%find_python.bat"

if not defined PY goto :nopython

echo [pack] Using: %PY%

if not exist "%TOOLS%compile_pack.py" (
  echo [pack] ERROR: cannot find %TOOLS%compile_pack.py
  goto :fail
)

REM One .toml per language under src\translations. zh is the only
REM editable one; en / fr are read-only reference text under
REM references\ and compile_pack.py refuses to pack them.
for %%L in (zh) do (
  echo.
  echo [pack] Building %%L ...
  %PY% "%TOOLS%compile_pack.py" --lang %%L --out "%OUT%"
  if errorlevel 1 goto :fail
)

REM The DLL reads locale.ini from the same folder as the pack to learn
REM which language to load. It lives in src\ as a plain template and is
REM copied verbatim -- there is nothing to generate.
if not exist "%SRC%locale.ini" (
  echo [pack] ERROR: cannot find %SRC%locale.ini
  goto :fail
)
if not exist "%OUT%" mkdir "%OUT%"
copy /Y "%SRC%locale.ini" "%OUT%\locale.ini" >nul
if errorlevel 1 (
  echo [pack] ERROR: cannot write %OUT%\locale.ini
  goto :fail
)

echo.
echo [pack] SUCCESS:
dir /B "%OUT%"
echo.
echo [pack] The pack is read at game start. Launch
echo [pack] build\PR2Launcher.exe - no rebuild needed.
call :maybe_pause
endlocal
exit /b 0

:nopython
echo.
echo [pack] ERROR: could not find Python.
echo [pack]
echo [pack] Option 1 - install Python 3.11 or newer from
echo [pack]           https://www.python.org/downloads/
echo [pack]           (tick "Add python.exe to PATH")
echo [pack]
echo [pack] Option 2 - open a shell where python works and run
echo [pack]           this script from there.
call :maybe_pause
endlocal
exit /b 1

:fail
echo.
echo [pack] FAILED. See the errors above.
call :maybe_pause
endlocal
exit /b 1

:maybe_pause
if defined NOPAUSE exit /b 0
pause
exit /b 0
