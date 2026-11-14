# -*- coding: utf-8 -*-
"""pr2ctl.steam_host —— Steam 版宿主 DLL 的备份、挂载与还原。

Steam 的 PR2.exe 静态导入 Ascaron.Logging-2.6.dll。这里的原则是
**先验证、再备份、最后替换**：

- 原版 Ascaron.Logging-2.6.dll 的大小和 SHA-256 固定；
- 根目录文件不是已知原版时，不强行覆盖；
- 没有 .orig.dll 或 host-backup 备份时，不挂载；
- 还原时只接受本工具的代理，不覆盖未知 DLL。
"""

import json
import os
import shutil

from .base import *  # noqa: F401,F403

HOST_DLL = "Ascaron.Logging-2.6.dll"
HOST_ORIG = "Ascaron.Logging-2.6.orig.dll"
HOST_BACKUP_DIR = os.path.join(DATA_DIR, "host-backup")
HOST_BACKUP = os.path.join(HOST_BACKUP_DIR, HOST_DLL)
HOST_MANIFEST = os.path.join(DATA_DIR, "host-mount.json")

#: Steam 英文 1.1.2.3 自带的 Ascaron.Logging-2.6.dll。
#: 不按文件名猜，必须同时匹配大小和哈希。
HOST_ORIGINAL_SIZE = 11776
HOST_ORIGINAL_SHA256 = (
    "0568EC654E147B6D80F60B779843F020A9C8A7C4E53AE0BC364EC6937024D160"
)


class HostError(Exception):
    """宿主 DLL 状态不允许继续操作。"""


def _sha256(path):
    return file_digest(path).upper() if os.path.isfile(path) else ""


def _is_original(path):
    try:
        return (os.path.getsize(path) == HOST_ORIGINAL_SIZE
                and _sha256(path) == HOST_ORIGINAL_SHA256)
    except OSError:
        return False


def _proxy_path(target=None, proxy_path=None):
    if proxy_path:
        return proxy_path
    # 构建时用 build/runtime；发行包解压后由调用方显式传入同目录文件。
    return os.path.join(RUNTIME, HOST_DLL)


def _read_manifest(target):
    path = os.path.join(target, HOST_MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(target, original_sha, proxy_sha):
    path = os.path.join(target, HOST_MANIFEST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "edition": "steam",
        "host": HOST_DLL,
        "original_sha256": original_sha,
        "proxy_sha256": proxy_sha,
        "backup": HOST_BACKUP.replace("\\", "/"),
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _remove_manifest(target):
    try:
        os.remove(os.path.join(target, HOST_MANIFEST))
    except OSError:
        pass


def _is_gog(target):
    """GOG 安装会带 goggame-*.info/.id/.script；Steam 安装没有这些。"""
    try:
        names = os.listdir(target)
    except OSError:
        return False
    return any(n.lower().startswith("goggame-")
               and n.lower().endswith((".info", ".id", ".script"))
               for n in names)


def detect_edition(target):
    """判断是 Steam 还是 GOG。

    不能只看 ``Ascaron.Logging-2.6.dll`` 是否存在：GOG 版（例如法语
    1.1.2.42）也带同名原版 DLL，按存在性判断会把 GOG 误认成 Steam，
    进而把 Steam 宿主代理挂进 GOG 目录。顺序改为：

    1. GOG 标记文件优先；
    2. PR2.exe 的 SHA 在已知版本表里，就按表里的 id 判断；
    3. 以上都不确定时，才退回“宿主 DLL 存在即 Steam”（未知 Steam 版本）。
    """
    if _is_gog(target):
        return "gog"
    exe = os.path.join(target, GAME_EXE)
    sha = _sha256(exe)
    known = BUILD_BY_SHA.get(sha) if sha else None
    if known:
        return "steam" if str(known.get("id", "")).startswith("steam") else "gog"
    if os.path.isfile(os.path.join(target, HOST_DLL)):
        return "steam"
    return "gog"


def status(target):
    """返回 (状态, 说明)。状态：original / mounted / unknown / missing。"""
    root = os.path.join(target, HOST_DLL)
    orig = os.path.join(target, HOST_ORIG)
    backup = os.path.join(target, HOST_BACKUP)
    manifest = _read_manifest(target)
    if not os.path.isfile(root):
        return "missing", "目录里没有 %s" % HOST_DLL
    root_sha = _sha256(root)

    if _is_original(root):
        if os.path.isfile(orig) and not _is_original(orig):
            return "unknown", ".orig.dll 不是已知原版"
        return "original", "根目录是 Steam 原版"

    if not os.path.isfile(orig):
        if os.path.isfile(backup) and _is_original(backup):
            known_proxy = manifest.get("proxy_sha256", "").upper()
            proxy_sha = _sha256(_proxy_path(target))
            if root_sha == known_proxy or (proxy_sha and root_sha == proxy_sha):
                return "mounted", "根目录不是原版；已有 host-backup，可用还原流程"
            return "unknown", "根目录不是已知原版，也不是本工具代理；有 host-backup 但缺少 .orig.dll"
        return "unknown", "根目录不是已知原版，且没有 .orig.dll 备份"

    if not _is_original(orig):
        return "unknown", ".orig.dll 不是已知原版"

    known_proxy = manifest.get("proxy_sha256", "").upper()
    if known_proxy and root_sha == known_proxy:
        return "mounted", "根目录是本工具代理"
    proxy_sha = _sha256(_proxy_path(target))
    if proxy_sha and root_sha == proxy_sha:
        return "mounted", "根目录与本工具代理一致"
    return "unknown", "根目录不是已知原版，也不是本工具代理"


def prepare_mount(target, proxy_path=None):
    """验证并建立备份，但不复制代理。

    返回 dict：state = original / mounted；包含 original_sha256、proxy_sha256。
    失败抛 HostError，调用方应停止，不要继续复制。
    """
    root = os.path.join(target, HOST_DLL)
    orig = os.path.join(target, HOST_ORIG)
    backup = os.path.join(target, HOST_BACKUP)
    proxy = _proxy_path(target, proxy_path)

    if not os.path.isfile(root):
        raise HostError("找不到 %s，不能挂载 Steam 宿主" % HOST_DLL)
    if not os.path.isfile(proxy):
        raise HostError("找不到代理：%s" % proxy)
    proxy_sha = _sha256(proxy)
    if not proxy_sha:
        raise HostError("代理文件不可读：%s" % proxy)

    if _is_original(root):
        if os.path.isfile(orig) and not _is_original(orig):
            raise HostError(".orig.dll 不是已知原版，拒绝覆盖")
        if not os.path.isfile(orig):
            shutil.copy2(root, orig)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        if not os.path.isfile(backup) or not _is_original(backup):
            shutil.copy2(orig, backup)
        return {
            "state": "original",
            "original_sha256": HOST_ORIGINAL_SHA256,
            "proxy_sha256": proxy_sha,
        }

    # 根目录已经是非原版：只有 .orig.dll 能证明原文件在哪里。
    if not os.path.isfile(orig):
        raise HostError(
            "根目录 %s 不是已知原版，也没有 .orig.dll；"
            "为避免覆盖未知文件，已停止挂载" % HOST_DLL
        )
    if not _is_original(orig):
        raise HostError(
            ".orig.dll 的大小/哈希不是 Steam 原版；"
            "拒绝把未知文件当作备份"
        )
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    if not os.path.isfile(backup) or not _is_original(backup):
        shutil.copy2(orig, backup)

    root_sha = _sha256(root)
    manifest = _read_manifest(target)
    known = manifest.get("proxy_sha256", "").upper()
    if root_sha != proxy_sha and root_sha != known:
        raise HostError(
            "根目录已有非原版 DLL，但它不是本工具代理；"
            "为避免覆盖其他 mod，已停止挂载"
        )
    return {
        "state": "mounted",
        "original_sha256": HOST_ORIGINAL_SHA256,
        "proxy_sha256": proxy_sha,
    }


def write_manifest(target, proxy_path=None):
    """在代理复制成功后写清单；调用前应先 prepare_mount。"""
    info = prepare_mount(target, proxy_path)
    _write_manifest(target, info["original_sha256"], info["proxy_sha256"])
    return info


def mount_host(target, proxy_path=None):
    """验证、备份并覆盖宿主 DLL。"""
    info = prepare_mount(target, proxy_path)
    if info["state"] == "mounted":
        _write_manifest(target, info["original_sha256"], info["proxy_sha256"])
        return info
    shutil.copy2(_proxy_path(target, proxy_path), os.path.join(target, HOST_DLL))
    if not _sha256(os.path.join(target, HOST_DLL)) == info["proxy_sha256"]:
        raise HostError("代理复制后校验失败")
    _write_manifest(target, info["original_sha256"], info["proxy_sha256"])
    return info


def restore_host(target, proxy_path=None):
    """还原原版宿主 DLL；只接受本工具代理，不覆盖未知文件。"""
    root = os.path.join(target, HOST_DLL)
    orig = os.path.join(target, HOST_ORIG)
    backup = os.path.join(target, HOST_BACKUP)
    if not os.path.isfile(root):
        raise HostError("找不到 %s，无法还原" % HOST_DLL)
    if _is_original(root):
        _remove_manifest(target)
        return "already"

    if not os.path.isfile(orig) or not _is_original(orig):
        if os.path.isfile(backup) and _is_original(backup):
            shutil.copy2(backup, orig)
        else:
            raise HostError("没有可验证的 .orig.dll 或 host-backup，拒绝还原")

    manifest = _read_manifest(target)
    root_sha = _sha256(root)
    known = manifest.get("proxy_sha256", "").upper()
    proxy_sha = _sha256(_proxy_path(target, proxy_path))
    if root_sha != known and root_sha != proxy_sha:
        raise HostError(
            "根目录 DLL 不是本工具代理；为避免覆盖其他 mod，拒绝还原"
        )

    shutil.copy2(orig, root)
    if not _is_original(root):
        raise HostError("还原后校验失败")
    _remove_manifest(target)
    return "restored"
