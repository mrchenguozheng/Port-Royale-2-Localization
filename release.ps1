#Requires -Version 7.0
# ============================================================
#  PR2 Localization - one-command release entry
#
#    .\release.ps1 -Version v1.0.0
#    .\release.ps1 -Version v1.0.0 -Lang zh
#    .\release.ps1 -Version v1.0.0 -Edition gog
#    .\release.ps1 -Version v1.0.0 -Edition steam
#    .\release.ps1 -Version v1.0.0 -Tag
#    .\release.ps1 -Version v1.0.0 -Tag -Push
#
#  Default flow:
#    1. build the injector into build\runtime
#    2. compile each language and assemble
#       dist\PR2-<lang>-gog-<version>.zip and
#       dist\PR2-<lang>-steam-<version>.zip
#    3. (optional) create release-<version> tag; -Push also pushes it
#
#  The pack assembly implementation stays in:
#    src\tools\pack\make_release.py
# ============================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [ValidateSet('all', 'gog', 'steam')]
    [string]$Edition = 'all',

    [string[]]$Lang = @(),

    [string]$Out = 'dist',

    [ValidateSet('noto', 'stitch', 'none')]
    [string]$Fonts = 'noto',

    [switch]$SkipInjector,

    [switch]$NoFontCache,

    [switch]$Tag,

    [switch]$Push,

    [switch]$NoPause,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

foreach ($arg in $Rest) {
    if ($arg -eq '--no-pause') { $NoPause = $true }
    if ($arg -eq '--no-font-cache') { $NoFontCache = $true }
}

if ($Push) { $Tag = $true }

$ErrorActionPreference = 'Stop'

$Repo = $PSScriptRoot
$Src = Join-Path $Repo 'src'
$ReleaseScript = Join-Path $Src 'tools\pack\make_release.py'
$BuildScript = Join-Path $Repo 'build.ps1'

function Get-PwshPath {
    $cmd = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $local = Join-Path $PSHOME 'pwsh.exe'
    if (Test-Path -LiteralPath $local -PathType Leaf) { return $local }

    throw '找不到 PowerShell 7（pwsh.exe）。'
}

function Get-ReleaseLanguages {
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
$languages = @(Get-ReleaseLanguages)
if ($languages.Count -eq 0) {
    throw '没有找到语言：src\translations\*.toml 为空，且没有显式给 -Lang。'
}

$Python = @(& (Join-Path $Src 'find_python.ps1'))[0]
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    throw '找不到 Python。先安装 Python 3.11+，或让 python 进入 PATH。'
}

$OutDir = if ([System.IO.Path]::IsPathRooted($Out)) {
    $Out
} else {
    Join-Path $Repo $Out
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$editions = if ($Edition -eq 'all') { @('gog', 'steam') } else { @($Edition) }

Write-Host "[release] 版本：$Version"
Write-Host "[release] 语言：$($languages -join ', ')"
Write-Host "[release] 入口：$($editions -join ', ')"
Write-Host "[release] 输出：$OutDir"
Write-Host "[release] 字体：$Fonts"

if (-not $SkipInjector) {
    Write-Host ''
    Write-Host '[release] 1/2 构建注入器'
    & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $BuildScript -Target Injector -NoPause
    if ($LASTEXITCODE -ne 0) {
        throw "构建注入器失败（退出码 $LASTEXITCODE）。"
    }
} else {
    Write-Host ''
    Write-Host '[release] 1/2 跳过注入器（使用现有 build\runtime）'
}

Write-Host ''
Write-Host '[release] 2/2 组装发行包'
foreach ($edition in $editions) {
    Write-Host ''
    Write-Host "[release] 入口：$edition"
    $releaseArgs = @(
        $ReleaseScript,
        '--version', $Version,
        '--out', $OutDir,
        '--fonts', $Fonts,
        '--edition', $edition
    )
    foreach ($lang in $languages) {
        $releaseArgs += @('--lang', $lang)
    }
    if ($NoFontCache) {
        $releaseArgs += '--no-font-cache'
    }

    & $Python @releaseArgs
    if ($LASTEXITCODE -ne 0) {
        throw "生成 $edition 发行包失败（退出码 $LASTEXITCODE）。"
    }
}

$zips = @(Get-ChildItem -LiteralPath $OutDir -Filter "PR2-*-$Version.zip" -File |
    Sort-Object Name)
if ($zips.Count -eq 0) {
    throw "没有找到生成的 zip：$OutDir\PR2-*-$Version.zip"
}

Write-Host ''
Write-Host '[release] 已生成：'
foreach ($zip in $zips) {
    Write-Host "  $($zip.FullName)"
}

if ($Tag) {
    $gitCmd = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        $gitCmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    }
    if (-not $gitCmd) {
        throw '找不到 git，无法创建 tag。'
    }
    $git = $gitCmd.Source
    $tagName = "release-$Version"

    $existing = @(& $git -C $Repo tag -l $tagName)
    if ($existing.Count -gt 0) {
        throw "tag 已存在：$tagName"
    }

    & $git -C $Repo tag $tagName
    if ($LASTEXITCODE -ne 0) {
        throw "创建 tag 失败：$tagName"
    }
    Write-Host "[release] 已创建 tag：$tagName"

    if ($Push) {
        & $git -C $Repo push origin $tagName
        if ($LASTEXITCODE -ne 0) {
            throw "推送 tag 失败：$tagName"
        }
        Write-Host "[release] 已推送 tag：$tagName"
    }
}

Write-Host ''
Write-Host '[release] 完成。'

if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
    [void](Read-Host 'Press Enter to close')
}
