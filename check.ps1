#Requires -Version 7.0
# ============================================================
#  PR2 Localization - run all static checks and unit tests
# ============================================================
[CmdletBinding()]
param(
    [switch]$NoPause,
    # 临时跳过某门语言（可重复）：.\check.ps1 -SkipLang pl,de
    [string[]]$SkipLang = @(),
    # 并行度：逐语言检查与规则单测分片都用它（默认 1，CI 传 4）
    [int]$Jobs = 1
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
    # $args 是 PowerShell 自动变量，别拿来当自己的参数数组。
    $checkArgs = @((Join-Path $Root 'src\tools\check.py'))
    foreach ($langCode in $SkipLang) { $checkArgs += @('--skip-lang', $langCode) }
    if ($Jobs -gt 1) { $checkArgs += @('--jobs', "$Jobs") }
    & $Python @checkArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') { [void](Read-Host 'Press Enter to close') }
exit $exitCode
