#Requires -Version 7.0
# ============================================================
#  PR2 Localization - locate a usable python.exe
#
#  Prints the absolute path of the first interpreter that can run
#  `import sys`. Callers capture this output:
#
#      $PY = & "$PSScriptRoot\src\find_python.ps1"
#      if ($LASTEXITCODE -ne 0) { ... }
#
#  Sources, in order:
#    1. python.exe on PATH, every hit in turn
#    2. the py launcher (`py -3`)
#    3. the per-user install dirs
#
#  Nothing is printed when no interpreter is found; the script exits 1.
# ============================================================

$ErrorActionPreference = 'SilentlyContinue'

function Get-InterpreterPath {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Prefix = @()
    )
    try {
        $output = & $Executable @Prefix -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $line = @($output | Where-Object { $_ -and $_.Trim() })[0]
        if (-not $line) { return $null }
        $path = $line.Trim()
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    } catch {
        return $null
    }
    return $null
}

$candidates = @()

foreach ($cmd in @(Get-Command python.exe -All -CommandType Application)) {
    if ($cmd.Source) { $candidates += [pscustomobject]@{ Exe = $cmd.Source; Prefix = @() } }
}

foreach ($cmd in @(Get-Command py.exe -All -CommandType Application)) {
    if ($cmd.Source) { $candidates += [pscustomobject]@{ Exe = $cmd.Source; Prefix = @('-3') } }
}

$installRoots = @(
    $env:ProgramFiles,
    ${env:ProgramFiles(x86)},
    (Join-Path $env:LOCALAPPDATA 'Programs')
) | Where-Object { $_ }

foreach ($root in $installRoots) {
    foreach ($version in @('315', '314', '313', '312', '311')) {
        $candidates += [pscustomobject]@{
            Exe = Join-Path $root "Python\Python$version\python.exe"
            Prefix = @()
        }
    }
}

# 3.14+ installs to LocalAppData\Python\bin, not a versioned Programs dir.
if ($env:LOCALAPPDATA) {
    $candidates += [pscustomobject]@{
        Exe = Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'
        Prefix = @()
    }
}

foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate.Exe -PathType Leaf)) { continue }
    $found = Get-InterpreterPath -Executable $candidate.Exe -Prefix $candidate.Prefix
    if ($found) {
        Write-Output $found
        exit 0
    }
}

exit 1
