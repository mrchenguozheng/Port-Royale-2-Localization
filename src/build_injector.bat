@echo off
REM ============================================================
REM  PR2 Localization - Rust build script
REM
REM  Builds the three native programs from src\injector-rs:
REM    PR2TextSource.dll, PR2Launcher.exe, PR2LauncherGUI.exe
REM  and copies them into build\runtime\.
REM
REM  Requires rustup + the i686-pc-windows-msvc target:
REM    rustup target add i686-pc-windows-msvc
REM  The workspace .cargo\config.toml pins that target.
REM
REM  Keep this file ASCII. cmd misreads UTF-8 in .bat files.
REM ============================================================
setlocal

set "NOPAUSE="
for %%a in (%*) do if /i "%%a"=="--no-pause" set "NOPAUSE=1"

set "RUSTDIR=%~dp0injector-rs\"
set "ROOT=%~dp0..\build\runtime\"
set "UI_SRC=%~dp0injector-rs\ui\"

if not exist "%RUSTDIR%Cargo.toml" (
  echo [build] ERROR: cannot find %RUSTDIR%Cargo.toml
  call :maybe_pause
  endlocal
  exit /b 1
)
if not exist "%ROOT%" mkdir "%ROOT%"

set "CARGO=%USERPROFILE%\.cargo\bin\cargo.exe"
if not exist "%CARGO%" (
  for /f "delims=" %%i in ('where cargo 2^>nul') do set "CARGO=%%i"
)
if not exist "%CARGO%" goto :norust

echo [build] cargo build --release
cd /d "%RUSTDIR%"
"%CARGO%" build --release --locked
if errorlevel 1 goto :fail

set "OUT=%RUSTDIR%target\i686-pc-windows-msvc\release"
if not exist "%OUT%\PR2TextSource.dll" goto :fail
if not exist "%OUT%\PR2Launcher.exe" goto :fail
if not exist "%OUT%\PR2LauncherGUI.exe" goto :fail
copy /Y "%OUT%\PR2TextSource.dll" "%ROOT%\PR2TextSource.dll" >nul
if errorlevel 1 goto :fail
copy /Y "%OUT%\PR2Launcher.exe" "%ROOT%\PR2Launcher.exe" >nul
if errorlevel 1 goto :fail
copy /Y "%OUT%\PR2LauncherGUI.exe" "%ROOT%\PR2LauncherGUI.exe" >nul
if errorlevel 1 goto :fail
if exist "%UI_SRC%en.ini" (
  if not exist "%ROOT%ui" mkdir "%ROOT%ui"
  copy /Y "%UI_SRC%en.ini" "%ROOT%ui\en.ini" >nul
)
if exist "%UI_SRC%ja.ini" copy /Y "%UI_SRC%ja.ini" "%ROOT%ui\ja.ini" >nul
if exist "%UI_SRC%zh.ini" copy /Y "%UI_SRC%zh.ini" "%ROOT%ui\zh.ini" >nul

echo.
echo [build] SUCCESS:
cd /d "%ROOT%"
dir /B PR2TextSource.*
dir /B PR2Launcher.*
echo.
echo [build] Next:  src\build_translation.bat   (build the language pack)
call :maybe_pause
endlocal
exit /b 0

:norust
echo.
echo [build] ERROR: cargo.exe was not found.
echo [build]
echo [build] Install Rust with rustup, then add the 32-bit target:
echo [build]   rustup target add i686-pc-windows-msvc
echo [build]   https://rustup.rs/
echo [build]
echo [build] If cargo is installed in a custom location, put its folder on PATH.
call :maybe_pause
endlocal
exit /b 1

:fail
echo.
echo [build] FAILED. See the errors above.
call :maybe_pause
endlocal
exit /b 1

:maybe_pause
if defined NOPAUSE exit /b 0
pause
exit /b 0
