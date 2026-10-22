@echo off
REM ============================================================
REM  PR2 Localization - build script
REM
REM  Compiles PR2TextSource.dll + PR2Launcher.exe.
REM
REM  Two ways to get a working cl.exe:
REM    1. Run from a "x64 Native Tools Command Prompt for VS"
REM    2. Double-click this file - it locates Visual Studio itself
REM
REM  Note: this script sets up the toolchain manually instead of calling
REM  vcvarsall, because vcvarsall touches the registry and can fail in
REM  locked-down / sandboxed environments even when VS is installed.
REM
REM  Keep this file ASCII + GBK. cmd misreads UTF-8 in .bat files.
REM
REM  Sources carry a UTF-8 BOM and cl gets /utf-8, so the Chinese
REM  string literals in the launcher survive compilation intact.
REM ============================================================
setlocal

REM --no-pause: set by the window, which runs us non-interactively
set "NOPAUSE="
for %%a in (%*) do if /i "%%a"=="--no-pause" set "NOPAUSE=1"
REM %~dp0 already ends with a backslash, so both dirs need the
REM explicit separator. Without it SRC becomes "...\srcinjector" and the
REM move below silently fails with "cannot find the file".
set "SRC=%~dp0injector\"
set "ROOT=%~dp0..\build\"

where cl >nul 2>&1
if not errorlevel 1 goto :compile

echo [build] Locating Visual Studio...

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :novs

set "VSPATH="
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSPATH=%%i"
if not defined VSPATH goto :novs
echo [build] Found: %VSPATH%

REM ---- MSVC toolset ----
set "VCTOOLS=%VSPATH%\VC\Tools\MSVC"
if not exist "%VCTOOLS%" goto :novs
set "VCVER="
for /f "delims=" %%v in ('dir /b /o-n "%VCTOOLS%" 2^>nul') do if not defined VCVER set "VCVER=%%v"
if not defined VCVER goto :novs

REM Port Royale 2 is a 32-bit process, so build x86 (x64 host compiler,
REM 32-bit target). The hook code uses 32-bit inline asm throughout.
set "VCDIR=%VCTOOLS%\%VCVER%"
set "VCBIN=%VCDIR%\bin\Hostx64\x86"
if not exist "%VCBIN%\cl.exe" set "VCBIN=%VCDIR%\bin\Hostx86\x86"
if not exist "%VCBIN%\cl.exe" goto :novs
echo [build] MSVC toolset: %VCVER%  (target: x86)

REM ---- Windows SDK ----
set "SDKROOT=%ProgramFiles(x86)%\Windows Kits\10"
if not exist "%SDKROOT%\Include" goto :novs
set "SDKVER="
for /f "delims=" %%k in ('dir /b /o-n "%SDKROOT%\Include" 2^>nul') do if not defined SDKVER set "SDKVER=%%k"
if not defined SDKVER goto :novs

set "SDKINC=%SDKROOT%\Include\%SDKVER%"
if not exist "%SDKINC%\um\windows.h" goto :novs
echo [build] Windows SDK:   %SDKVER%

REM newest bin\<ver>\x64\<hostver> holds rc.exe and mt.exe
set "SDKBIN="
for /f "delims=" %%t in ('dir /b /o-n "%SDKROOT%\bin\%SDKVER%\x64" 2^>nul') do if not defined SDKBIN set "SDKBIN=%SDKROOT%\bin\%SDKVER%\x64\%%t"

set "PATH=%VCBIN%;%SDKBIN%;%PATH%"
set "INCLUDE=%VCDIR%\include;%SDKINC%\ucrt;%SDKINC%\um;%SDKINC%\shared;%SDKINC%\winrt"
set "LIB=%VCDIR%\lib\x86;%SDKROOT%\Lib\%SDKVER%\ucrt\x86;%SDKROOT%\Lib\%SDKVER%\um\x86"

:compile
where cl >nul 2>&1
if errorlevel 1 goto :novs
if not exist "%ROOT%" mkdir "%ROOT%"

cd /d "%SRC%"
if not exist "pr2_text_source.cpp" (
  echo [build] ERROR: cannot find pr2_text_source.cpp
  pause
  endlocal
  exit /b 1
)

echo [build] Compiling PR2TextSource.dll ...
cl /nologo /MT /LD /Ox /W3 /utf-8 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_text_source.cpp pr2_text_pack.c ^
   /Fe:PR2TextSource.dll /link /OUT:PR2TextSource.dll psapi.lib
if errorlevel 1 goto :fail

echo.
echo [build] Compiling PR2Launcher.exe ...
REM /wd4819: under /utf-8 MSVC still reports C4819 against codepage 0
REM for the Chinese string literals, but it emits them intact.
cl /nologo /MT /Ox /W3 /utf-8 /wd4819 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_launcher.cpp ^
   /Fe:PR2Launcher.exe /link /OUT:PR2Launcher.exe
if errorlevel 1 goto :fail

echo.
echo [build] Compiling PR2LauncherGUI.exe ...
cl /nologo /MT /Ox /W3 /utf-8 /wd4819 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_launcher_gui.cpp ^
   /Fe:PR2LauncherGUI.exe /link /OUT:PR2LauncherGUI.exe /SUBSYSTEM:WINDOWS user32.lib gdi32.lib
if errorlevel 1 goto :fail

echo.
REM cl runs with cwd = src\injector, so the output lands there.
REM Move it to the repo-root build\ folder, next to PR2Packs\.
move /Y "%SRC%PR2TextSource.dll" "%ROOT%PR2TextSource.dll" >nul
move /Y "%SRC%PR2Launcher.exe" "%ROOT%PR2Launcher.exe" >nul
move /Y "%SRC%PR2LauncherGUI.exe" "%ROOT%PR2LauncherGUI.exe" >nul
if exist "%SRC%ui" xcopy /E /I /Y "%SRC%ui" "%ROOT%ui" >nul
del /Q "%SRC%*.obj" >nul 2>&1

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

:novs
echo.
echo [build] ERROR: could not find the Visual Studio C++ compiler.
echo [build]
echo [build] Option 1 - install Visual Studio with the
echo [build]           "Desktop development with C++" workload:
echo [build]           https://visualstudio.microsoft.com/downloads/
echo [build]
echo [build] Option 2 - open "x64 Native Tools Command Prompt for VS"
echo [build]           and run this script from there.
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
