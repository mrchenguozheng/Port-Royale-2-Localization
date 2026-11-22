# PR2HostMount.ps1 —— Steam 版宿主 DLL 的备份、挂载与还原。
#
# Steam 的 PR2.exe 静态导入 Ascaron.Logging-2.6.dll。本脚本只替换这一个
# DLL，并在替换前验证原版大小和 SHA-256。校验不通过时不覆盖任何文件。
#
#   powershell -ExecutionPolicy Bypass -File .\PR2HostMount.ps1 -Action Status
#   powershell -ExecutionPolicy Bypass -File .\PR2HostMount.ps1 -Action Mount
#   powershell -ExecutionPolicy Bypass -File .\PR2HostMount.ps1 -Action Restore

[CmdletBinding()]
param(
    [ValidateSet('Status', 'Mount', 'Restore')]
    [string]$Action = 'Status',

    [string]$Target = $PSScriptRoot,

    [string]$ProxyPath = (Join-Path $PSScriptRoot 'Ascaron.Logging-2.6.dll')
)

$ErrorActionPreference = 'Stop'
$HostDll = 'Ascaron.Logging-2.6.dll'
$OrigDll = 'Ascaron.Logging-2.6.orig.dll'
$BackupRel = 'PR2Localization\host-backup\Ascaron.Logging-2.6.dll'
$ManifestRel = 'PR2Localization\host-mount.json'
$ExpectedSize = 11776
$ExpectedSha = '0568EC654E147B6D80F60B779843F020A9C8A7C4E53AE0BC364EC6937024D160'

function Get-FileSha256([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Test-Original([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $ExpectedSize) { return $false }
    return (Get-FileSha256 $Path) -eq $ExpectedSha
}

function Read-Manifest([string]$Root) {
    $path = Join-Path $Root $ManifestRel
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { return $null }
}

function Write-Manifest([string]$Root, [string]$ProxySha) {
    $path = Join-Path $Root $ManifestRel
    $dir = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $data = [ordered]@{
        edition = 'steam'
        host = $HostDll
        original_sha256 = $ExpectedSha
        proxy_sha256 = $ProxySha
        backup = $BackupRel.Replace('\', '/')
    }
    $data | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $path -Encoding UTF8
}

function Get-ProxySha {
    if (-not (Test-Path -LiteralPath $ProxyPath -PathType Leaf)) {
        throw "找不到代理：$ProxyPath"
    }
    $sha = Get-FileSha256 $ProxyPath
    if (-not $sha) { throw "代理不可读：$ProxyPath" }
    return $sha
}

# 替换动作只有这一个实现：先写 <目标>.new，校验 SHA-256 通过后用 Move-Item 换名。
# 复制到一半被占用/杀毒中断时，根目录还是原来那份 DLL，不会留下半截文件。
function Copy-DllAtomically([string]$Source, [string]$Dest, [string]$ExpectSha, [string]$What) {
    $tmp = "$Dest.new"
    try {
        Copy-Item -LiteralPath $Source -Destination $tmp -Force
        if ((Get-FileSha256 $tmp) -ne $ExpectSha) {
            throw "$What 复制后校验失败（临时文件哈希不符）"
        }
        Move-Item -LiteralPath $tmp -Destination $Dest -Force
    } catch [System.IO.IOException] {
        throw "$What 替换失败：$($_.Exception.Message)（游戏或杀毒可能正占用 $([IO.Path]::GetFileName($Dest))）"
    } finally {
        if (Test-Path -LiteralPath $tmp) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
    if ((Get-FileSha256 $Dest) -ne $ExpectSha) {
        throw "$What 替换后校验失败"
    }
}

$Root = [IO.Path]::GetFullPath($Target)
$RootDll = Join-Path $Root $HostDll
$Orig = Join-Path $Root $OrigDll
$Backup = Join-Path $Root $BackupRel

if (-not (Test-Path -LiteralPath (Join-Path $Root 'PR2.exe') -PathType Leaf)) {
    throw "目标目录没有 PR2.exe：$Root"
}
if (-not (Test-Path -LiteralPath $RootDll -PathType Leaf)) {
    throw "目标目录没有 $HostDll，不能按 Steam 版处理"
}

$manifest = Read-Manifest $Root
$proxySha = Get-ProxySha
$rootSha = Get-FileSha256 $RootDll

if (Test-Original $RootDll) {
    $state = 'original'
} elseif (Test-Original $Orig) {
    if ($rootSha -eq $proxySha -or ($manifest -and $rootSha -eq $manifest.proxy_sha256)) {
        $state = 'mounted'
    } else {
        $state = 'unknown'
    }
} else {
    $state = 'unknown'
}

if ($Action -eq 'Status') {
    switch ($state) {
        'original' { Write-Output "状态：原版（未挂载）" }
        'mounted'  { Write-Output "状态：已挂载（$HostDll 是本地化代理）" }
        'unknown'  { Write-Output "状态：未知；根目录不是已记录的本工具代理，也不是已知原版" }
    }
    Write-Output "目录：$Root"
    Write-Output "根 DLL SHA-256：$rootSha"
    Write-Output "原版备份：$(if (Test-Original $Orig) { '有效' } else { '无/无效' })"
    return
}

if ($Action -eq 'Mount') {
    if ($state -eq 'original') {
        if (Test-Path -LiteralPath $Orig) {
            if (-not (Test-Original $Orig)) {
                throw ".orig.dll 不是已知原版，拒绝覆盖"
            }
        } else {
            Copy-Item -LiteralPath $RootDll -Destination $Orig
        }
        $backupDir = Split-Path -Parent $Backup
        if (-not (Test-Path -LiteralPath $backupDir -PathType Container)) {
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        }
        if (-not (Test-Original $Backup)) {
            Copy-Item -LiteralPath $Orig -Destination $Backup
        }
    } elseif ($state -eq 'mounted') {
        # 已经挂载，只补齐可能的备份，然后重新验证代理。
        $backupDir = Split-Path -Parent $Backup
        if (-not (Test-Path -LiteralPath $backupDir -PathType Container)) {
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        }
        if (-not (Test-Original $Backup)) {
            Copy-Item -LiteralPath $Orig -Destination $Backup
        }
    } else {
        throw "根目录 DLL 不是已知原版，也没有可验证的 .orig.dll；拒绝挂载"
    }

    if ((Get-FileSha256 $RootDll) -ne $proxySha) {
        Copy-DllAtomically -Source $ProxyPath -Dest $RootDll -ExpectSha $proxySha `
            -What 'Steam 宿主代理'
    }
    Write-Manifest $Root $proxySha
    Write-Output "已挂载：$RootDll"
    Write-Output "原版备份：$Orig"
    Write-Output "第二份备份：$Backup"
    return
}

if ($Action -eq 'Restore') {
    if ($state -eq 'original') {
        Remove-Item -LiteralPath (Join-Path $Root $ManifestRel) -Force -ErrorAction SilentlyContinue
        Write-Output "已经是原版，无需还原"
        return
    }
    if (-not (Test-Original $Orig)) {
        if (Test-Original $Backup) {
            Copy-Item -LiteralPath $Backup -Destination $Orig
        } else {
            throw "没有可验证的 .orig.dll 或 host-backup，拒绝还原"
        }
    }
    $known = if ($manifest) { [string]$manifest.proxy_sha256 } else { '' }
    if ($rootSha -ne $proxySha -and $rootSha -ne $known) {
        throw "根目录 DLL 不是本工具代理；拒绝覆盖未知文件"
    }
    Copy-DllAtomically -Source $Orig -Dest $RootDll -ExpectSha $ExpectedSha `
        -What '原版宿主'
    Remove-Item -LiteralPath (Join-Path $Root $ManifestRel) -Force -ErrorAction SilentlyContinue
    Write-Output "已还原：$RootDll"
    return
}
