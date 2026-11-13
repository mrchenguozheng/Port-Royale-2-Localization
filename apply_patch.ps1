#Requires -Version 7.0
# ============================================================
#  PR2 Localization - developer one-shot: build + deploy
#
#  Normalizes the translations, checks breaks, compiles the
#  packs, copies everything into the game folder and verifies
#  the result. Safe to run repeatedly; unchanged files are
#  skipped.
#
#    .\apply_patch.ps1                 ja + zh, last game dir
#    .\apply_patch.ps1 --langs ja
#    .\apply_patch.ps1 --launch
# ============================================================

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Python = & (Join-Path $Root 'src\find_python.ps1')
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    Write-Host ''
    Write-Host '[all] No Python 3.11+ was found. Install Python and retry.'
    Write-Host ''
    if ($Host.Name -eq 'ConsoleHost') { [void](Read-Host 'Press Enter to close') }
    exit 1
}

Push-Location $Root
try {
    & $Python (Join-Path $Root 'src\tools\pack\apply_patch.py') @args
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

exit $code
