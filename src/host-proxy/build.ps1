#Requires -Version 7.0
# 编译 Steam 宿主代理：src\host-proxy\hostproxy.cpp
# 输出：build\runtime\Ascaron.Logging-2.6.dll（x86）
#
# 需要 Visual Studio 2022 C++ 工具链和 Windows SDK。脚本只编译这一个 DLL，
# 不参与 Rust workspace；失败时不覆盖已有代理。

[CmdletBinding()]
param(
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$Src = $PSScriptRoot
$Repo = Split-Path -Parent (Split-Path -Parent $Src)
$Source = Join-Path $Src 'hostproxy.cpp'
$OutDir = Join-Path $Repo 'build\runtime'
$Out = Join-Path $OutDir 'Ascaron.Logging-2.6.dll'

function Stop-Build([string]$Message) {
    Write-Host "[host-proxy] $Message"
    if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
        [void](Read-Host 'Press Enter to close')
    }
    exit 1
}

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    Stop-Build "找不到 $Source"
}
if (-not (Test-Path -LiteralPath $OutDir -PathType Container)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$VcRoot = $null
$VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (Test-Path -LiteralPath $VsWhere -PathType Leaf) {
    $VsPath = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($VsPath) { $VcRoot = Join-Path $VsPath 'VC\Tools\MSVC' }
}
if (-not $VcRoot -or -not (Test-Path -LiteralPath $VcRoot -PathType Container)) {
    $Fallback = Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Community\VC\Tools\MSVC'
    if (Test-Path -LiteralPath $Fallback -PathType Container) { $VcRoot = $Fallback }
}
if (-not $VcRoot) { Stop-Build '找不到 Visual Studio C++ 工具链' }

$Msvc = Get-ChildItem -LiteralPath $VcRoot -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $Msvc) { Stop-Build "找不到 MSVC 版本目录：$VcRoot" }
$Cl = Join-Path $Msvc.FullName 'bin\Hostx64\x86\cl.exe'
if (-not (Test-Path -LiteralPath $Cl -PathType Leaf)) {
    Stop-Build "找不到 cl.exe：$Cl"
}

$SdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
$SdkInclude = Join-Path $SdkRoot 'Include'
if (-not (Test-Path -LiteralPath $SdkInclude -PathType Container)) {
    Stop-Build "找不到 Windows SDK：$SdkRoot"
}
$SdkVer = Get-ChildItem -LiteralPath $SdkInclude -Directory |
    Where-Object { $_.Name -match '^10\.' } |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $SdkVer) { Stop-Build "找不到 Windows SDK 版本：$SdkInclude" }

$env:INCLUDE = @(
    (Join-Path $Msvc.FullName 'include'),
    (Join-Path $SdkInclude "$($SdkVer.Name)\ucrt"),
    (Join-Path $SdkInclude "$($SdkVer.Name)\um"),
    (Join-Path $SdkInclude "$($SdkVer.Name)\shared")
) -join ';'
$env:LIB = @(
    (Join-Path $Msvc.FullName 'lib\x86'),
    (Join-Path $SdkRoot "Lib\$($SdkVer.Name)\ucrt\x86"),
    (Join-Path $SdkRoot "Lib\$($SdkVer.Name)\um\x86")
) -join ';'

$TempOut = Join-Path ([IO.Path]::GetTempPath()) ("pr2-host-proxy-" + [guid]::NewGuid().ToString('N') + '.dll')
try {
    # /MT：不依赖额外 VC 运行库；游戏目录只需要这一个 DLL。
    & $Cl /nologo /LD /O2 /MT /EHsc /DUNICODE /D_UNICODE $Source "/Fo:$OutDir\hostproxy.obj" "/Fe:$TempOut"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TempOut -PathType Leaf)) {
        Stop-Build "cl.exe 编译失败（退出码 $LASTEXITCODE）"
    }
    Copy-Item -LiteralPath $TempOut -Destination $Out -Force
    Write-Host "[host-proxy] 已生成：$Out"
} finally {
    Remove-Item -LiteralPath $TempOut -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $OutDir 'hostproxy.obj') -Force -ErrorAction SilentlyContinue
}

if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') {
    [void](Read-Host 'Press Enter to close')
}
exit 0
