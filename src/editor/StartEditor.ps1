#Requires -Version 7.0
# ============================================================
#  PR2 Localization - start the translation editor on its own
#
#  The editor is a local web app: server.py is a stdlib HTTP
#  server that also serves the built frontend (dist\).
#  No Python packages are needed - if python.exe exists, it works.
#
#    .\src\editor\StartEditor.ps1
# ============================================================

$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = & (Join-Path $Repo 'src\find_python.ps1')
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    Write-Host ''
    Write-Host '[editor] Cannot start: no Python 3.11+ found.'
    Write-Host '[editor] Install Python from https://www.python.org/downloads/'
    Write-Host '[editor] and tick "Add python.exe to PATH".'
    Write-Host ''
    if ($Host.Name -eq 'ConsoleHost') { [void](Read-Host 'Press Enter to close') }
    exit 1
}

$Server = Join-Path $PSScriptRoot 'server.py'
$Arguments = '"{0}" --restart' -f $Server
Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $PSScriptRoot
exit 0
