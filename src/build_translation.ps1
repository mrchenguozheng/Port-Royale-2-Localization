#Requires -Version 7.0
# ============================================================
#  PR2 Localization - language pack build script
#
#  Compiles src\translations\<lang>.toml into the pack the DLL
#  reads at runtime: build\runtime\PR2Packs\<lang>.txt
#
#    .\src\build_translation.ps1
#    .\src\build_translation.ps1 -NoPause
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
$Tools = Join-Path $Src 'tools\pack'
$Out = Join-Path $Repo 'build\runtime\PR2Packs'
$Locale = Join-Path $Src 'locale.ini'
$Lang = 'zh'

function Wait-IfPaused {
    if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
        [void](Read-Host 'Press Enter to close')
    }
}

function Stop-WithError {
    param([string]$Message)
    Write-Host ''
    Write-Host "[pack] $Message"
    Wait-IfPaused
    exit 1
}

$Python = & (Join-Path $Src 'find_python.ps1')
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    Write-Host ''
    Write-Host '[pack] ERROR: could not find Python.'
    Write-Host '[pack]'
    Write-Host '[pack] Option 1 - install Python 3.11 or newer from'
    Write-Host '[pack]           https://www.python.org/downloads/'
    Write-Host '[pack]           (tick "Add python.exe to PATH")'
    Write-Host '[pack]'
    Write-Host '[pack] Option 2 - open a shell where python works and run'
    Write-Host '[pack]           this script from there.'
    Wait-IfPaused
    exit 1
}

Write-Host "[pack] Using: $Python"

$Compile = Join-Path $Tools 'compile_pack.py'
if (-not (Test-Path -LiteralPath $Compile -PathType Leaf)) {
    Stop-WithError "ERROR: cannot find $Compile"
}

if (-not (Test-Path -LiteralPath $Out)) {
    New-Item -ItemType Directory -Force -Path $Out | Out-Null
}

Write-Host ''
Write-Host "[pack] Building $Lang ..."
& $Python $Compile --lang $Lang --out $Out
if ($LASTEXITCODE -ne 0) { Stop-WithError 'FAILED. See the errors above.' }

if (-not (Test-Path -LiteralPath $Locale -PathType Leaf)) {
    Stop-WithError "ERROR: cannot find $Locale"
}

$LocaleOut = Join-Path $Out 'locale.ini'
if (-not (Test-Path -LiteralPath $LocaleOut -PathType Leaf)) {
    Copy-Item -LiteralPath $Locale -Destination $LocaleOut -Force
}

Write-Host ''
Write-Host '[pack] SUCCESS:'
Get-ChildItem -LiteralPath $Out | ForEach-Object { Write-Host $_.Name }
Write-Host ''
Write-Host '[pack] The pack is read at game start. Launch'
Write-Host '[pack] build\runtime\PR2Launcher.exe - no rebuild needed.'
Wait-IfPaused
exit 0
