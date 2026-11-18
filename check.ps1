#Requires -Version 7.0
# ============================================================
#  PR2 Localization - run all static checks and unit tests
# ============================================================
[CmdletBinding()]
param(
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Python = & (Join-Path $Root 'src\find_python.ps1')
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    Write-Host '[check] Python 3.11+ not found.'
    if ($Host.Name -eq 'ConsoleHost') { [void](Read-Host 'Press Enter to close') }
    exit 1
}

Push-Location $Root
try {
    & $Python (Join-Path $Root 'src\tools\check.py')
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') { [void](Read-Host 'Press Enter to close') }
exit $code
