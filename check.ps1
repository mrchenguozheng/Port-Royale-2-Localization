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
    [int]$Jobs = 1,
    # 只跑 Python 侧检查（没装 Rust 工具链时用；CI 不允许跳过）
    [switch]$SkipRust
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

    # Rust 侧闸门。以前只有 Python 检查，cargo fmt/clippy 和「单个 crate 能不能
    # 独立构建」都要靠人记得跑；pr2_launcher 缺 Win32 特性就是靠 workspace 的
    # 特性合并掩盖过去的，单独 `cargo test -p` 才暴露。
    if (-not $SkipRust) {
        $Cargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
        if (-not (Test-Path -LiteralPath $Cargo -PathType Leaf)) {
            $cmd = Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($cmd) { $Cargo = $cmd.Source }
        }
        if (-not $Cargo -or -not (Test-Path -LiteralPath $Cargo -PathType Leaf)) {
            throw '找不到 cargo.exe；没装 Rust 工具链时用 -SkipRust 只跑 Python 检查。'
        }

        $RustDir = Join-Path $Root 'src\injector-rs'
        Push-Location $RustDir
        try {
            Write-Host '[check] Rust 格式（cargo fmt --all --check）'
            & $Cargo fmt --all -- --check
            if ($LASTEXITCODE -ne 0) { throw 'Rust 格式不一致：先运行 cargo fmt --all。' }

            Write-Host '[check] Rust lint（clippy --workspace --all-targets -D warnings）'
            & $Cargo clippy --workspace --all-targets --locked -- -D warnings
            if ($LASTEXITCODE -ne 0) { throw 'clippy 有错误或警告（-D warnings）。' }

            Write-Host '[check] Rust 单测（cargo test --workspace --locked）'
            & $Cargo test --workspace --locked
            if ($LASTEXITCODE -ne 0) { throw 'Rust 单测失败。' }

            # workspace 会把各 crate 的特性并起来，单个 crate 缺特性可能被掩盖。
            # 每个成员单独 check 一遍，构建出的依赖图与单独 `cargo build -p` 一致。
            $meta = (@(& $Cargo metadata --no-deps --format-version 1 --locked 2>$null) -join '')
            if ($LASTEXITCODE -ne 0 -or -not $meta) { throw '读不到 cargo workspace 成员。' }
            $members = @(($meta | ConvertFrom-Json).packages | ForEach-Object { $_.name })
            foreach ($member in $members) {
                Write-Host "[check] 单 crate 构建：$member"
                & $Cargo check --locked -p $member
                if ($LASTEXITCODE -ne 0) {
                    throw "crate 单独构建失败：$member（workspace 特性合并可能掩盖了缺特性）。"
                }
            }
            Write-Host ("[check] Rust 闸门通过：{0} 个 crate 单独构建" -f $members.Count)
        } finally {
            Pop-Location
        }
    } else {
        Write-Host '[check] 已跳过 Rust 闸门（-SkipRust）'
    }

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
