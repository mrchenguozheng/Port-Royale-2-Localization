@echo off
REM ============================================================
REM  PR2 Localization - launcher for the translation editor
REM
REM  Starts src\editor\server.py using the repository's virtual
REM  environment (.venv at the repo root), and opens the browser.
REM
REM  Why a venv instead of "whatever Python is on PATH":
REM
REM    The editor needs FastAPI + uvicorn, which are NOT stdlib.
REM    This machine has two interpreters -- 3.14 (no FastAPI) and
REM    3.11 (has it) -- and which one "wins" depends on PATH order.
REM    Guessing wrong means the editor dies with ModuleNotFoundError
REM    seconds after launch, and because it runs under pythonw.exe
REM    (no console) the traceback is discarded: all you see is
REM    "nothing happened".
REM
REM    The venv removes the guesswork. Whichever interpreter created
REM    it, the venv carries its own site-packages with the deps
REM    pinned. Nothing is installed into the system Python.
REM
REM    .venv is at the repo root, not here: it is the repository's
REM    dependency environment, not the editor's alone.
REM
REM  First run creates .venv and installs requirements.txt into it
REM  (~35 MB, needs network once). Later runs just start.
REM
REM  Keep this file ASCII + CRLF.
REM ============================================================
setlocal EnableExtensions

REM %~dp0 is src\editor\ -- two levels up is the repo root.
for %%i in ("%~dp0..\..") do set "ROOT=%%~fi"

set "VENV_PY=%ROOT%\.venv\Scripts\python.exe"
set "VENV_PYW=%ROOT%\.venv\Scripts\pythonw.exe"
set "SERVER=%~dp0server.py"
set "REQ=%ROOT%\requirements.txt"

if not exist "%SERVER%" (
  echo [editor] ERROR: %SERVER% not found.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo [editor] First run - creating the virtual environment in
  echo [editor]   %ROOT%\.venv
  echo [editor] This happens once and needs network access.
  echo.

  REM  Prefer the py launcher: it resolves a real interpreter even
  REM  when PATH is stale. Fall back to python on PATH.
  set "BASE="
  where py >nul 2>&1 && set "BASE=py -3"
  if not defined BASE where python >nul 2>&1 && set "BASE=python"

  if not defined BASE (
    echo [editor] ERROR: no Python found on PATH.
    echo [editor] Install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
  )

  %BASE% -m venv "%ROOT%\.venv"
  if errorlevel 1 (
    echo [editor] ERROR: could not create the virtual environment.
    pause
    exit /b 1
  )

  echo [editor] Installing dependencies from requirements.txt ...
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --quiet -r "%REQ%"
  if errorlevel 1 (
    echo [editor] ERROR: dependency installation failed.
    echo [editor] Check the network, then delete .venv and try again.
    pause
    exit /b 1
  )
  echo [editor] Ready.
  echo.
)

REM  pythonw keeps a console from popping up behind the editor. It has
REM  no stdout, so anything printed here would be lost anyway -- which
REM  is why server.py guards its prints.

if exist "%VENV_PYW%" (
  start "" "%VENV_PYW%" "%SERVER%" %*
) else (
  start "" "%VENV_PY%" "%SERVER%" %*
)

endlocal
exit /b 0
