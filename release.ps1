#Requires -Version 7.0
# ============================================================
#  PR2 Localization - one-command release entry
#
#    .\release.ps1 -Version v1.0.0
#    .\release.ps1 -Version 1.0.0            # 自动归一化成 v1.0.0
#    .\release.ps1 -Version v1.0.0 -Lang zh
#    .\release.ps1 -Version v1.0.0 -Edition gog
#    .\release.ps1 -Version v1.0.0 -Edition steam
#    .\release.ps1 -Version v1.0.0 -Tag
#    .\release.ps1 -Version v1.0.0 -Tag -Push
#
#  规范见 docs\发行规范.md，要点：
#    - 版本号只接受 vMAJOR.MINOR.PATCH[-prerelease]；不带 v 会自动补上，
#      文件名、manifest、README、tag 都用归一化后的同一串。
#    - 发行语言由 src\release-languages.txt 决定，不再自动扫翻译目录。
#    - 产物是 dist\PR2-<lang>-<edition>-<version>.zip 加 dist\SHA256SUMS.txt；
#      stage 目录打包后删除。
#    - tag 名为 release-<version>，annotated；-Tag 要求工作树干净。
#
#  Default flow:
#    1. build the injector into build\runtime
#    2. compile each language and assemble
#       dist\PR2-<lang>-gog-<version>.zip and
#       dist\PR2-<lang>-steam-<version>.zip
#    3. write dist\SHA256SUMS.txt
#    4. (optional) create release-<version> tag; -Push also pushes it
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

    [ValidateSet('auto', 'noto', 'config', 'none')]
    [string]$Fonts = 'auto',

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

# 版本号规范化：不带 v 自动补，校验统一的正则。python 侧 release_version.py
# 用同一条规则再校验一次；这里只为了在出包前给出可读的报错和正确文件名。
$Version = $Version.Trim()
if (-not $Version.StartsWith('v')) { $Version = 'v' + $Version }
if ($Version -notmatch '^v\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$') {
    throw "版本号不合法：$Version；只接受 vMAJOR.MINOR.PATCH[-prerelease]，例如 v1.0.0、v1.2.3-rc.1"
}

$Repo = $PSScriptRoot
$Src = Join-Path $Repo 'src'
$ReleaseScript = Join-Path $Src 'tools\pack\make_release.py'
$BuildScript = Join-Path $Repo 'build.ps1'

function Get-PwshPath {
    $cmd = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
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

    # 发行语言只认 src\release-languages.txt：有 pack 但没验收的语言（pl）
    # 不进正式包，避免自动发现把未完成语言也打进去。
    $listPath = Join-Path $Src 'release-languages.txt'
    if (-not (Test-Path -LiteralPath $listPath)) {
        throw "缺发行语言清单：$listPath"
    }
    $names = @()
    foreach ($raw in Get-Content -LiteralPath $listPath -Encoding utf8) {
        $line = ($raw -split '#', 2)[0].Trim()
        if (-not $line) { continue }
        $names += @($line -split '[,\s]+' | Where-Object { $_ })
    }
    return @($names | Select-Object -Unique)
}

function Assert-ReleaseLanguages {
    param([string[]]$Names)
    $problems = @()
    foreach ($name in $Names) {
        if ($name -notmatch '^[a-z]{2,3}$') {
            $problems += "语言代码不合法：$name"
            continue
        }
        if (-not (Test-Path -LiteralPath (Join-Path $Src "packs\$name.toml"))) {
            $problems += "缺 src\packs\$name.toml"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $Src "translations\$name.toml"))) {
            $problems += "缺 src\translations\$name.toml"
        }
    }
    if ($problems.Count -gt 0) {
        throw ("发行语言不全：" + ($problems -join '；'))
    }
}

$Pwsh = Get-PwshPath
$languages = @(Get-ReleaseLanguages)
if ($languages.Count -eq 0) {
    throw '没有发行语言：src\release-languages.txt 为空，且没有显式给 -Lang。'
}
Assert-ReleaseLanguages -Names $languages

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

# 上一次中断留下的 stage 目录（PR2-<lang>-<edition>-<version>\）不属于发行产物，
# 重新出包前清掉，保证 dist 里只有 zip 和校验和。
foreach ($dir in @(Get-ChildItem -LiteralPath $OutDir -Directory -Filter 'PR2-*-v*' -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $dir.FullName -Recurse -Force
}

Write-Host "[release] 版本：$Version"
Write-Host "[release] 语言：$($languages -join ', ')"
Write-Host "[release] 入口：$($editions -join ', ')"
Write-Host "[release] 输出：$OutDir"
Write-Host "[release] 字体：$Fonts"

Write-Host ''
Write-Host '[release] 0/2 检查语言配置'
& $Python (Join-Path $Src 'tools\config_check.py')
if ($LASTEXITCODE -ne 0) {
    throw "语言配置检查失败（退出码 $LASTEXITCODE）。"
}

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

# 校验和与产物同目录，格式与 sha256sum 一致：<大写 HEX><两个空格><文件名>。
$sumsPath = Join-Path $OutDir 'SHA256SUMS.txt'
$sumLines = foreach ($zip in $zips) {
    $hash = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash
    '{0}  {1}' -f $hash, $zip.Name
}
Set-Content -LiteralPath $sumsPath -Value $sumLines -Encoding utf8NoBOM

Write-Host ''
Write-Host '[release] 已生成：'
foreach ($zip in $zips) {
    Write-Host ("  {0}  ({1:N1} MB)" -f $zip.FullName, ($zip.Length / 1MB))
}
Write-Host "  $sumsPath"

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

    # 脏工作树打 tag 会把未提交的改动留在“已发布”版本里，直接拒绝。
    $porcelain = @(& $git -C $Repo status --porcelain)
    if ($porcelain.Count -gt 0) {
        throw ("工作树有未提交改动，先提交再打 tag：`n" + ($porcelain -join "`n"))
    }

    $existing = @(& $git -C $Repo tag -l $tagName)
    if ($existing.Count -gt 0) {
        throw "tag 已存在：$tagName"
    }

    & $git -C $Repo tag -a $tagName -m "PR2 Localization $Version"
    if ($LASTEXITCODE -ne 0) {
        throw "创建 tag 失败：$tagName"
    }
    Write-Host "[release] 已创建 annotated tag：$tagName"

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
