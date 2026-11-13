#Requires -Version 7.0
# ============================================================
#  PR2 Localization - Rust build script
#
#  Builds the native programs from src\injector-rs:
#    PR2TextSource.dll, PR2Launcher.exe, PR2LauncherGUI.exe, VERSION.dll
#  and copies them into build\runtime\.
#
#  VERSION.dll is the proxy host that lets the game load PR2TextSource.dll
#  naturally under Steam, without a launcher or remote injection.
#
#  Requires rustup + the i686-pc-windows-msvc target:
#    rustup target add i686-pc-windows-msvc
#  The workspace .cargo\config.toml pins that target.
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
$artifacts = @('PR2TextSource.dll', 'PR2Launcher.exe', 'PR2LauncherGUI.exe', 'VERSION.dll')
foreach ($name in $artifacts) {
    if (-not (Test-Path -LiteralPath (Join-Path $Out $name) -PathType Leaf)) {
        Stop-WithError "FAILED: missing $(Join-Path $Out $name)"
    }
}

foreach ($name in $artifacts) {
    Copy-Item -LiteralPath (Join-Path $Out $name) `
        -Destination (Join-Path $Runtime $name) -Force
}

if (Test-Path -LiteralPath $UiSrc -PathType Container) {
    $UiOut = Join-Path $Runtime 'ui'
    New-Item -ItemType Directory -Force -Path $UiOut | Out-Null
    foreach ($lang in @('en', 'ja', 'zh')) {
        $ini = Join-Path $UiSrc "$lang.ini"
        if (Test-Path -LiteralPath $ini -PathType Leaf) {
            Copy-Item -LiteralPath $ini -Destination (Join-Path $UiOut "$lang.ini") -Force
        }
    }
}

Write-Host ''
Write-Host '[build] SUCCESS:'
foreach ($name in $artifacts) { Write-Host $name }
Write-Host ''
Write-Host '[build] Next:  src\build_translation.ps1   (build the language pack)'
Wait-IfPaused
exit 0
