#Requires -Version 7.0
# ============================================================
#  PR2 Localization - one-command build entry
#
#    .\build.ps1                 # injector + all language packs (zh, ja)
#    .\build.ps1 -Target Packs   # language packs only
#    .\build.ps1 -Target Packs -Lang zh
#    .\build.ps1 -Target Injector
#
#  Low-level implementation stays in:
#    src\build_injector.ps1
#    src\build_translation.ps1
# ============================================================

[CmdletBinding()]
param(
    [ValidateSet('All', 'Injector', 'Packs')]
    [string]$Target = 'All',

    [string[]]$Lang = @(),

    [switch]$NoPause,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

foreach ($arg in $Rest) {
    if ($arg -eq '--no-pause') { $NoPause = $true }
}

$ErrorActionPreference = 'Stop'

$Repo = $PSScriptRoot
$Src = Join-Path $Repo 'src'
$InjectorScript = Join-Path $Src 'build_injector.ps1'
$TranslationScript = Join-Path $Src 'build_translation.ps1'

function Get-PwshPath {
    $cmd = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($cmd) { return $cmd.Source }

    $local = Join-Path $PSHOME 'pwsh.exe'
    if (Test-Path -LiteralPath $local -PathType Leaf) { return $local }

    throw '找不到 PowerShell 7（pwsh.exe）。'
}

function Invoke-ChildScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Arguments = @()
    )

    & $script:Pwsh -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "脚本失败（退出码 $LASTEXITCODE）：$Path"
    }
}

function Get-BuildLanguages {
    if ($Lang.Count -gt 0) {
        $names = @()
        foreach ($item in $Lang) {
            $names += @($item -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        return @($names | Select-Object -Unique)
    }

    $translationDir = Join-Path $Src 'translations'
    $files = @(Get-ChildItem -LiteralPath $translationDir -Filter '*.toml' -File |
        Where-Object { $_.BaseName -notlike 'test_*' } |
        Sort-Object Name)
    return @($files | ForEach-Object { $_.BaseName })
}

$Pwsh = Get-PwshPath

$languages = @(Get-BuildLanguages)
if ($Target -in @('All', 'Packs')) {
    if ($languages.Count -eq 0) {
        throw '没有找到语言：src\translations\*.toml 为空，且没有显式给 -Lang。'
    }
    foreach ($lang in $languages) {
        $toml = Join-Path $Src "translations\$lang.toml"
        if (-not (Test-Path -LiteralPath $toml -PathType Leaf)) {
            throw "找不到译文文件：$toml"
        }
    }
}

switch ($Target) {
    'All'      { Write-Host "[build] 目标：注入器 + 语言包（$($languages -join ', ')）" }
    'Injector' { Write-Host '[build] 目标：注入器' }
    'Packs'    { Write-Host "[build] 目标：语言包（$($languages -join ', ')）" }
}

if ($Target -in @('All', 'Injector')) {
    Write-Host ''
    Write-Host '[build] 1/2 编译注入器（cargo）'
    Invoke-ChildScript -Path $InjectorScript -Arguments @('-NoPause')
}

if ($Target -in @('All', 'Packs')) {
    Write-Host ''
    Write-Host '[build] 2/2 编译语言包'
    foreach ($lang in $languages) {
        Write-Host ''
        Write-Host "[build] -> $lang"
        Invoke-ChildScript -Path $TranslationScript -Arguments @('-Lang', $lang, '-NoPause')
    }
}

Write-Host ''
Write-Host '[build] 完成。'
if ($Target -in @('All', 'Injector')) {
    Write-Host '[build] 运行时：build\runtime'
}
if ($Target -in @('All', 'Packs')) {
    Write-Host '[build] 语言包：build\runtime\PR2Localization\packs'
}

if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
    [void](Read-Host 'Press Enter to close')
}
