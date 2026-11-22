#Requires -Version 7.0
# ============================================================
#  PR2 Localization - Rust build script
#
#  Builds the native programs from src\injector-rs:
#    PR2LocalizationCore.dll, PR2Localization.exe,
#    PR2LocalizationGUI.exe, PR2LocalizationProxy.dll,
#    pr2_host_proxy.dll
#  and copies them into build\runtime\ with the deployed names:
#    PR2LocalizationCore.dll
#    PR2Localization.exe
#    PR2LocalizationGUI.exe
#    VERSION.dll            (legacy proxy; Steam packages no longer ship it)
#    Ascaron.Logging-2.6.dll (Steam host proxy)
#
#  Runtime data lives under build\runtime\PR2Localization\:
#    packs\ fonts\ ui\ logs\
#
#  Requires rustup + the i686-pc-windows-msvc target:
#    rustup target add i686-pc-windows-msvc
#  The workspace .cargo\config.toml pins that target.
#  The MSVC linker is required by that Rust target; there is no C++ source.
#
#    .\src\build_injector.ps1
#    .\src\build_injector.ps1 -NoPause
# ============================================================

[CmdletBinding()]
param(
    [switch]$NoPause,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

foreach ($arg in $Rest) {
    if ($arg -eq '--no-pause') { $NoPause = $true }
}

$ErrorActionPreference = 'Stop'

$Src = $PSScriptRoot
$Repo = Split-Path -Parent $Src
$RustDir = Join-Path $Src 'injector-rs'
$Runtime = Join-Path $Repo 'build\runtime'
$UiSrc = Join-Path $RustDir 'ui'

function Wait-IfPaused {
    if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
        [void](Read-Host 'Press Enter to close')
    }
}

function Stop-WithError {
    param([string]$Message)
    Write-Host ''
    Write-Host "[build] $Message"
    Wait-IfPaused
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $RustDir 'Cargo.toml') -PathType Leaf)) {
    Stop-WithError "ERROR: cannot find $(Join-Path $RustDir 'Cargo.toml')"
}

if (-not (Test-Path -LiteralPath $Runtime)) {
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
}

$Cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
if (-not (Test-Path -LiteralPath $Cargo -PathType Leaf)) {
    $cmd = Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($cmd) { $Cargo = $cmd.Source } else { $Cargo = $null }
}

if (-not $Cargo -or -not (Test-Path -LiteralPath $Cargo -PathType Leaf)) {
    Write-Host ''
    Write-Host '[build] ERROR: cargo.exe was not found.'
    Write-Host '[build]'
    Write-Host '[build] Install Rust with rustup, then add the 32-bit target:'
    Write-Host '[build]   rustup target add i686-pc-windows-msvc'
    Write-Host '[build]   https://rustup.rs/'
    Write-Host '[build]'
    Write-Host '[build] If cargo is installed in a custom location, put its folder on PATH.'
    Wait-IfPaused
    exit 1
}

Write-Host '[build] cargo build --release'
Push-Location $RustDir
try {
    & $Cargo build --release --locked
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) { Stop-WithError 'FAILED. See the errors above.' }

$Out = Join-Path $RustDir 'target\i686-pc-windows-msvc\release'
$artifactMap = @{
    'PR2LocalizationCore.dll' = 'PR2LocalizationCore.dll'
    'PR2Localization.exe' = 'PR2Localization.exe'
    'PR2LocalizationGUI.exe' = 'PR2LocalizationGUI.exe'
    'PR2LocalizationProxy.dll' = 'VERSION.dll'
    'pr2_host_proxy.dll' = 'Ascaron.Logging-2.6.dll'
}
foreach ($srcName in $artifactMap.Keys) {
    if (-not (Test-Path -LiteralPath (Join-Path $Out $srcName) -PathType Leaf)) {
        Stop-WithError "FAILED: missing $(Join-Path $Out $srcName)"
    }
}

foreach ($srcName in $artifactMap.Keys) {
    Copy-Item -LiteralPath (Join-Path $Out $srcName) `
        -Destination (Join-Path $Runtime $artifactMap[$srcName]) -Force
}

$DataOut = Join-Path $Runtime 'PR2Localization'
New-Item -ItemType Directory -Force -Path $DataOut | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataOut 'logs') | Out-Null

if (Test-Path -LiteralPath $UiSrc -PathType Container) {
    $UiOut = Join-Path $DataOut 'ui'
    New-Item -ItemType Directory -Force -Path $UiOut | Out-Null
    # 界面文案只有一份 ui.default.ini（用户在同目录放 ui.ini 按项覆盖）。
    # 旧布局按语言分 en/ja/zh.ini，那份文件早就不再被读取，留在 runtime 里
    # 会让发行包带过期文案（新加的 key 会显示成 key 本身），这里顺手清掉。
    $Default = Join-Path $UiSrc 'ui.default.ini'
    if (-not (Test-Path -LiteralPath $Default -PathType Leaf)) {
        Stop-WithError "缺界面默认文件：$Default"
    }
    Copy-Item -LiteralPath $Default -Destination (Join-Path $UiOut 'ui.default.ini') -Force
    foreach ($lang in @('en', 'ja', 'zh')) {
        $stale = Join-Path $UiOut "$lang.ini"
        if (Test-Path -LiteralPath $stale -PathType Leaf) {
            Remove-Item -LiteralPath $stale -Force
        }
    }
}

$FontSrc = Join-Path $Src 'font-map.ini'
$FontOut = Join-Path $DataOut 'fonts'
New-Item -ItemType Directory -Force -Path $FontOut | Out-Null
if (-not (Test-Path -LiteralPath $FontSrc -PathType Leaf)) {
    Stop-WithError "缺字体映射模板：$FontSrc"
}
Copy-Item -LiteralPath $FontSrc -Destination (Join-Path $FontOut 'font-map.default.ini') -Force

Write-Host ''
Write-Host '[build] SUCCESS:'
foreach ($srcName in $artifactMap.Keys) {
    Write-Host ("  {0}  ->  {1}" -f $srcName, $artifactMap[$srcName])
}
Write-Host ("  data  ->  {0}" -f $DataOut)
Write-Host ''
Write-Host '[build] Next:  src\build_translation.ps1   (build the language pack)'
Wait-IfPaused
exit 0
