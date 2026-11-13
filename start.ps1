#Requires -Version 7.0
# ============================================================
#  PR2 Localization - install / launch window
#
#  Default: start the local web app in THIS console window and
#  open the installer page. Keep the window open to watch the
#  backend log; close it (or Ctrl+C) to stop the server.
#
#    .\start.ps1
#    .\start.ps1 -Status
#
#  PowerShell 7 only: this script and its helpers require pwsh 7.
# ============================================================

[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$NoPause,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = 'Stop'

foreach ($arg in $Rest) {
    if ($arg -eq '--status') { $Status = $true }
}

$Root = $PSScriptRoot
$Src = Join-Path $Root 'src'

function Wait-Closed {
    if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
        [void](Read-Host 'Press Enter to close')
    }
}

function Exit-NoPython {
    Write-Host ''
    Write-Host '[start] Cannot start: no Python 3.11+ found.'
    Write-Host '[start] Install Python from https://www.python.org/downloads/'
    Write-Host '[start] and tick "Add python.exe to PATH".'
    Write-Host ''
    Wait-Closed
    exit 1
}

$Python = & (Join-Path $Src 'find_python.ps1')
if ($LASTEXITCODE -ne 0 -or -not $Python) { Exit-NoPython }

try {
    $Host.UI.RawUI.WindowTitle = 'PR2 Localization'
} catch {
    # 非交互宿主没有窗口标题，忽略。
}

if ($Status) {
    Push-Location $Root
    try {
        & $Python (Join-Path $Src 'tools\install\server_status.py')
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Write-Host ''
    Wait-Closed
    exit $code
}

Write-Host 'Starting local server... close this window to stop it.'
Write-Host ''

Push-Location $Root
try {
    & $Python (Join-Path $Src 'editor\server.py') --restart --open-page /install
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Server stopped.'
Wait-Closed
exit $code
