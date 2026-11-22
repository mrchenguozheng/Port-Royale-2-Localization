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
    # PowerShell 脚本没有编译期检查：括号少了、行首 `+` 续行写错，只有真的执行到
    # 那一行才报错。出包脚本里这种错误代价最高（跑到一半才发现），所以在跑测试
    # 之前先静态解析一遍仓库里所有 .ps1（排除构建产物目录）。
    $scripts = @(Get-ChildItem -LiteralPath $Root -Filter '*.ps1' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\(build|dist|target|node_modules|\.venv[^\\]*)\\' })
    $syntaxErrors = @()
    foreach ($script in $scripts) {
        $errors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile(
            $script.FullName, [ref]$null, [ref]$errors)
        foreach ($e in @($errors)) {
            $syntaxErrors += ('{0}:{1}: {2}' -f $script.Name, $e.Extent.StartLineNumber, $e.Message)
        }
    }
    if ($syntaxErrors.Count -gt 0) {
        Write-Host '[check] PowerShell 脚本语法错误：'
        $syntaxErrors | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
    Write-Host ("[check] 脚本语法：{0} 个 .ps1 通过" -f $scripts.Count)

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
