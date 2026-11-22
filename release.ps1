#Requires -Version 7.0
# ============================================================
#  PR2 Localization - one-command release entry
#
#    .\release.ps1 -Version v1.0.0                 # 按分组：zh / ja / ko / ru 各一包，
#                                                  #   再加一个 latin（de+es+fr+it）
#    .\release.ps1 -Version v1.0.0 -Bundle latin   # 只出 latin 分组
#    .\release.ps1 -Version v1.0.0 -Lang zh        # 旧口径：一门语言一包
#    .\release.ps1 -Version v1.0.0 -Tag
#    .\release.ps1 -Version v1.0.0 -Tag -Push
#
#  规范见 docs\发行规范.md，要点：
#    - 版本号只接受 vMAJOR.MINOR.PATCH[-prerelease]；不带 v 会自动补上，
#      文件名、manifest、README、tag 都用归一化后的同一串。
#    - 发行分组由 src\release-bundles.toml 决定：同一份字体能共用的语言进一个 zip。
#      de/es/fr/it 四项字体映射全是 none，共用一份空字体集，合成 latin 一包；
#      zh/ja/ko/ru 各自一套字体文件，各出一包。
#    - 一个分组一个 zip：dist\PR2-<id>-<version>.zip 加 dist\SHA256SUMS.txt
#      与 dist\release.json（版本、commit、每个包的哈希/默认界面语言）。
#      包同时面向 GOG 与 Steam（自带宿主代理，挂载由启动器完成），不再按版别分包；
#      id 是分组 id（单语言分组沿用语言代码）；stage 目录打包后删除。
#    - 默认拒绝脏工作树：未提交改动会被编进 exe 版本头，也会让「这个包对应
#      哪个 commit」说不清。确有需要时显式加 -AllowDirty，release.json 会记下。
#    - tag 名为 release-<version>，annotated；-Tag 只允许在 main 或 release/*
#      分支上打，且工作树必须干净。
#
#  Default flow:
#    1. build the injector into build\runtime
#    2. compile every language of every bundle and assemble one zip per bundle
#       dist\PR2-<id>-<version>.zip
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

    [string[]]$Lang = @(),

    # 分组 id（可重复）：按 src\release-bundles.toml 出包，同组语言进一个 zip。
    # 不给时默认出全部分组。与 -Lang 互斥。
    [string[]]$Bundle = @(),

    [string]$Out = 'dist',

    [ValidateSet('auto', 'noto', 'config', 'none')]
    [string]$Fonts = 'auto',

    [switch]$SkipInjector,

    [switch]$NoFontCache,

    [switch]$Tag,

    [switch]$Push,

    # 默认拒绝脏工作树；只有显式传这个开关才放行（版本头与 release.json 会记 dirty）。
    [switch]$AllowDirty,

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

function Get-GitPath {
    $cmd = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $cmd) {
        $cmd = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    }
    if (-not $cmd) { throw '找不到 git，无法确认 commit 与工作树状态。' }
    return $cmd.Source
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

# 分组清单的唯一来源是 src\release-bundles.toml（由 make_release.py 读），
# PowerShell 不重复实现一遍解析，也不在这里推断「哪几门能共用字体」。
function Get-ReleaseBundles {
    param([string[]]$Ids = @(), [string]$PythonExe)
    $raw = @(& $PythonExe (Join-Path $Src 'tools\pack\make_release.py') --list-bundles)
    if ($LASTEXITCODE -ne 0) {
        throw '读不到发行分组清单：src\release-bundles.toml'
    }
    $all = @($raw | Where-Object { $_ -match '\|' } | ForEach-Object {
        $parts = $_ -split '\|'
        [pscustomobject]@{
            Id = $parts[0]
            Default = $parts[1]
            Langs = @($parts[2] -split ',' | Where-Object { $_ })
        }
    })
    if ($all.Count -eq 0) { throw '发行分组清单为空：src\release-bundles.toml' }
    if ($Ids.Count -eq 0) { return $all }

    $want = @($Ids | ForEach-Object { $_ -split ',' } |
        ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $missing = @($want | Where-Object { ($all | ForEach-Object { $_.Id }) -notcontains $_ })
    if ($missing.Count -gt 0) {
        throw ("没有这个分组：" + ($missing -join '、'))
    }
    return @($all | Where-Object { $want -contains $_.Id })
}

$Pwsh = Get-PwshPath

if ($Tag -and $AllowDirty) {
    throw '-Tag 与 -AllowDirty 不能同时使用：打 tag 必须对应已提交的树。'
}

# 脏树闸门放在最前面，避免构建六分钟之后才发现版本头要记「未提交改动」。
# 之前普通出包不检查，第一次发版就把脏树编进了包，只能人工中止。
$Git = Get-GitPath
$Commit = (@(& $Git -C $Repo rev-parse --short HEAD) | Select-Object -First 1).Trim()
$Porcelain = @(& $Git -C $Repo status --porcelain)
$Dirty = $Porcelain.Count -gt 0
if ($Dirty) {
    if ($Tag) {
        throw ("工作树有未提交改动，不能打 tag：`n" + ($Porcelain -join "`n"))
    }
    if (-not $AllowDirty) {
        throw ("工作树有未提交改动，拒绝出包：`n" + ($Porcelain -join "`n") +
            "`n先提交，或显式加 -AllowDirty 并在 release.json 里保留 dirty 标记。")
    }
    Write-Host '[release] 警告：工作树有未提交改动（-AllowDirty），版本头会标记 dirty。'
}
Write-Host "[release] commit：$Commit$(if ($Dirty) { '（dirty）' } else { '' })"

$Python = @(& (Join-Path $Src 'find_python.ps1'))[0]
if ($LASTEXITCODE -ne 0 -or -not $Python) {
    throw '找不到 Python。先安装 Python 3.11+，或让 python 进入 PATH。'
}

# 两种出包口径：
#   -Lang   → 每门语言各出一个 zip（旧行为，文件名是语言代码）
#   -Bundle / 缺省 → 按分组出包，同组语言进一个 zip（如 latin = de+es+fr+it）
$packMode = if ($Lang.Count -gt 0) { 'lang' } else { 'bundle' }
if ($packMode -eq 'lang' -and $Bundle.Count -gt 0) {
    throw '-Lang 与 -Bundle 只能给一个。'
}

if ($packMode -eq 'lang') {
    $groups = @()
    $languages = @(Get-ReleaseLanguages)
} else {
    # 变量名不能叫 $bundles：PowerShell 变量不分大小写，会覆盖 -Bundle 参数。
    $groups = @(Get-ReleaseBundles -Ids $Bundle -PythonExe $Python)
    $languages = @($groups | ForEach-Object { $_.Langs } | Select-Object -Unique)
    # 分组只允许从发行语言集里挑，防止在 bundles 里塞一门没验收的语言。
    $declared = @(Get-ReleaseLanguages)
    $outside = @($languages | Where-Object { $declared -notcontains $_ })
    if ($outside.Count -gt 0) {
        throw ("分组里有语言不在 src\release-languages.txt：" + ($outside -join '、'))
    }
}
if ($languages.Count -eq 0) {
    throw '没有发行语言：src\release-languages.txt 或 src\release-bundles.toml 为空。'
}
Assert-ReleaseLanguages -Names $languages

$OutDir = if ([System.IO.Path]::IsPathRooted($Out)) {
    $Out
} else {
    Join-Path $Repo $Out
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# 上一次中断留下的 stage 目录（PR2-<id>-<version>\）不属于发行产物，
# 重新出包前清掉，保证 dist 里只有 zip 和校验和。
foreach ($dir in @(Get-ChildItem -LiteralPath $OutDir -Directory -Filter 'PR2-*-v*' -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $dir.FullName -Recurse -Force
}
# 同版本旧 zip 也清掉：分组改名或删掉后，上一轮的同版本产物还会被
# SHA256SUMS 和 release.json 收进来，变成没人对应 stage 的幽灵包。
foreach ($old in @(Get-ChildItem -LiteralPath $OutDir -File -Filter "PR2-*-$Version.zip" -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $old.FullName -Force
}

Write-Host "[release] 版本：$Version"
Write-Host "[release] 语言：$($languages -join ', ')"
if ($packMode -eq 'bundle') {
    Write-Host "[release] 分组：$((@($groups | ForEach-Object { "$($_.Id)($($_.Langs -join '+'))" }) -join ' '))"
}
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
    # 把发行版本编进 exe：GUI 副标题与 `PR2Localization.exe --version` 显示它。
    # 语言包头的 # pack-meta version= 用同一个值，两边不会各写各的。
    $env:PR2_VERSION = $Version
    Write-Host "[release] 注入版本：$Version"
    & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $BuildScript -Target Injector -NoPause
    if ($LASTEXITCODE -ne 0) {
        throw "构建注入器失败（退出码 $LASTEXITCODE）。"
    }
} else {
    Write-Host ''
    Write-Host '[release] 1/2 跳过注入器（使用现有 build\runtime）'
    # -SkipInjector 不设 PR2_VERSION，exe 里编的还是上一次构建的版本；语言包包头用的是
    # 本次 -Version。两处版本不一致，玩家就会看到「v1.0.0 的包装着 dev 的运行时」，
    # 而且没有任何提示。这里拿构建期记录硬比对，不一致直接拒绝出包。
    $VersionStamp = Join-Path $Repo 'build\injector-version.txt'
    $builtVersion = if (Test-Path -LiteralPath $VersionStamp -PathType Leaf) {
        (Get-Content -LiteralPath $VersionStamp -TotalCount 1 -Encoding utf8).Trim()
    } else { '' }
    if (-not $builtVersion) {
        $msg = '-SkipInjector 无法确认现有 exe 的版本：build\injector-version.txt 不存在。' +
            ' 去掉 -SkipInjector 先构建一次（该文件由 src\build_injector.ps1 写入）。'
        throw $msg
    }
    if ($builtVersion -ne $Version) {
        $msg = "现有运行时编的是 ${builtVersion}，本次发行版本是 ${Version}。" +
            ' 去掉 -SkipInjector 重新构建，exe 显示的版本才会与语言包包头一致。'
        throw $msg
    }
    Write-Host "[release] 现有运行时版本：$builtVersion（与本次发行一致）"
}

Write-Host ''
Write-Host '[release] 2/2 组装发行包'

# 分组出包：一个分组一个 zip，组内语言共用字体与一份 font-map。
# 包同时面向 GOG 与 Steam，不再按版别出两份。
if ($packMode -eq 'bundle') {
    foreach ($group in $groups) {
        $releaseArgs = @(
            $ReleaseScript,
            '--version', $Version,
            '--out', $OutDir,
            '--fonts', $Fonts,
            '--bundle', $group.Id
        )
        if ($NoFontCache) { $releaseArgs += '--no-font-cache' }
        Write-Host ''
        Write-Host ("[release] 分组 {0}：{1}" -f $group.Id, ($group.Langs -join ', '))
        & $Python @releaseArgs
        if ($LASTEXITCODE -ne 0) {
            throw "生成 $($group.Id) 发行包失败（退出码 $LASTEXITCODE）。"
        }
    }
} else {
    # 旧口径：每门语言各出一个包。
    $releaseArgs = @(
        $ReleaseScript,
        '--version', $Version,
        '--out', $OutDir,
        '--fonts', $Fonts
    )
    foreach ($lang in $languages) {
        $releaseArgs += @('--lang', $lang)
    }
    if ($NoFontCache) {
        $releaseArgs += '--no-font-cache'
    }

    & $Python @releaseArgs
    if ($LASTEXITCODE -ne 0) {
        throw "生成发行包失败（退出码 $LASTEXITCODE）。"
    }
}

$zips = @(Get-ChildItem -LiteralPath $OutDir -Filter "PR2-*-$Version.zip" -File |
    Sort-Object Name)
if ($zips.Count -eq 0) {
    throw "没有找到生成的 zip：$OutDir\PR2-*-$Version.zip"
}

$artifacts = @(foreach ($zip in $zips) {
    [pscustomobject]@{
        File = $zip.Name
        Sha256 = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash
        Size = $zip.Length
    }
})

# 校验和与产物同目录，格式与 sha256sum 一致：<大写 HEX><两个空格><文件名>。
$sumsPath = Join-Path $OutDir 'SHA256SUMS.txt'
$sumLines = foreach ($artifact in $artifacts) {
    '{0}  {1}' -f $artifact.Sha256, $artifact.File
}
Set-Content -LiteralPath $sumsPath -Value $sumLines -Encoding utf8NoBOM

# 机器可读的发布元数据：SHA256SUMS 只回答「文件有没有坏」，回答不了
# 「这个包是哪个 commit、默认界面是哪门语言出的」。CI artifact 与 dist 同带。
$bundlesMeta = @()
if ($packMode -eq 'bundle') {
    foreach ($group in $groups) {
        $file = "PR2-$($group.Id)-$Version.zip"
        $artifact = $artifacts | Where-Object { $_.File -eq $file } | Select-Object -First 1
        if (-not $artifact) { throw "分组 $($group.Id) 没有生成 $file" }
        $bundlesMeta += [ordered]@{
            id = $group.Id
            default = $group.Default
            langs = @($group.Langs)
            file = $artifact.File
            sha256 = $artifact.Sha256
            size = $artifact.Size
        }
    }
} else {
    foreach ($lang in $languages) {
        $file = "PR2-$lang-$Version.zip"
        $artifact = $artifacts | Where-Object { $_.File -eq $file } | Select-Object -First 1
        if (-not $artifact) { throw "语言 $lang 没有生成 $file" }
        $bundlesMeta += [ordered]@{
            id = $lang
            default = $lang
            langs = @($lang)
            file = $artifact.File
            sha256 = $artifact.Sha256
            size = $artifact.Size
        }
    }
}
$releaseMeta = [ordered]@{
    version = $Version
    commit = $Commit
    dirty = $Dirty
    pack_mode = $packMode
    languages = @($languages)
    bundles = @($bundlesMeta)
    generated_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}
$metaPath = Join-Path $OutDir 'release.json'
$metaJson = $releaseMeta | ConvertTo-Json -Depth 6
Set-Content -LiteralPath $metaPath -Value $metaJson -Encoding utf8NoBOM


Write-Host ''
Write-Host '[release] 已生成：'
foreach ($zip in $zips) {
    Write-Host ("  {0}  ({1:N1} MB)" -f $zip.FullName, ($zip.Length / 1MB))
}
Write-Host "  $sumsPath"
Write-Host "  $metaPath"

if ($Tag) {
    $tagName = "release-$Version"

    # Release workflow 只接受 main 或 release/* 上的 tag；本地先拦住，
    # 避免打完 tag 推到远端才被拒，或者在 dev 上发出一个「main 还没有」的版本。
    $branch = (@(& $Git -C $Repo rev-parse --abbrev-ref HEAD) |
        Select-Object -First 1).Trim()
    if ($branch -ne 'main' -and $branch -notmatch '^release/') {
        throw ("当前分支是 $branch；打 tag 只允许在 main 或 release/* 上。" +
            "先把 dev 合进 main（或建 release 分支）再发。")
    }

    # 脏工作树打 tag 会把未提交的改动留在“已发布”版本里，直接拒绝。
    $porcelain = @(& $Git -C $Repo status --porcelain)
    if ($porcelain.Count -gt 0) {
        throw ("工作树有未提交改动，先提交再打 tag：`n" + ($porcelain -join "`n"))
    }

    $existing = @(& $Git -C $Repo tag -l $tagName)
    if ($existing.Count -gt 0) {
        throw "tag 已存在：$tagName"
    }

    & $Git -C $Repo tag -a $tagName -m "PR2 Localization $Version"
    if ($LASTEXITCODE -ne 0) {
        throw "创建 tag 失败：$tagName"
    }
    Write-Host "[release] 已创建 annotated tag：$tagName"

    if ($Push) {
        & $Git -C $Repo push origin $tagName
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
