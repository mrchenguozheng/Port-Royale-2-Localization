@echo off
REM ============================================================
REM  PR2 Localization - locate a usable python.exe
REM
REM  Called by the other build scripts, which read the result from
REM  the PY variable afterwards. The caller must already have
REM  setlocal, and must not use endlocal between the call and the
REM  read, or the value is lost again.
REM
REM  Do NOT try to select by "which Python has FastAPI". The editor
REM  runs inside its own venv (src\editor\.venv) with the deps baked
REM  in, so this script only ever needs to produce *some* working
REM  interpreter for the GUI and the build scripts.
REM
REM  Sources, in order:
REM    1. python.exe on PATH, every hit in turn
REM    2. the py launcher
REM    3. the per-user install dir - PATH is often not refreshed
REM       for the shell that was already open when Python was
REM       installed, which is exactly the shell a double-clicked
REM       .bat gets
REM
REM  Keep this file ASCII + CRLF.
REM ============================================================

set "PY="

REM -- PATH. Every hit is tried until one actually runs.
for /f "delims=" %%p in ('where python 2^>nul') do call :try "%%p"
if defined PY exit /b 0

for /f "delims=" %%p in ('where py 2^>nul') do call :try "%%p -3"
if defined PY exit /b 0

REM -- Install dirs. %%~d strips the quotes; %%d keeps them, and a
REM quoted path would reach python.exe as part of its own name.
for %%d in ("%ProgramFiles%" "%ProgramFiles(x86)%" "%LocalAppData%\Programs") do (
  for %%v in (315 314 313 312 311) do (
    if not defined PY call :try "%%~d\Python\Python%%v\python.exe"
  )
)
REM -- 3.14 installs to LocalAppData\Python\bin, NOT to a versioned
REM -- Programs\Python\Python314 subdir. Without this the newest
REM -- interpreter is only found by luck of PATH order.
if not defined PY call :try "%LocalAppData%\Python\bin\python.exe"

if not defined PY exit /b 1
exit /b 0


REM :try <command line> - accept it if it runs. Leaves PY unset otherwise.
:try
if "%~1"=="" exit /b 1
%1 -c "pass" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY=%~1"
exit /b 0
