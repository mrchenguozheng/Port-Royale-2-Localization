# -*- coding: utf-8 -*-
"""pr2ctl.steam_host —— 宿主 DLL 的只读识别（部署期）。

**这里不再实现替换/还原算法。** 唯一实现是 Rust 的
``pr2_common/src/host.rs``：部署流程复制完文件后调用游戏目录里的
``PR2Localization.exe --mount`` / ``--restore``，用的就是玩家运行时那一份代码。

本文件只保留部署前必须的只读判断：

- 根目录有没有宿主 DLL（``has_host``）；
- 是 GOG 还是 Steam（``detect_edition``，只用于显示，不决定启动路径）。
"""

import os

from .base import *  # noqa: F401,F403

HOST_DLL = "Ascaron.Logging-2.6.dll"


def _is_gog(target):
    """GOG 安装会带 goggame-*.info/.id/.script；Steam 安装没有这些。"""
    try:
        names = os.listdir(target)
    except OSError:
        return False
    return any(n.lower().startswith("goggame-")
               and n.lower().endswith((".info", ".id", ".script"))
               for n in names)


def has_host(target):
    """根目录有没有宿主 DLL。

    两版（GOG 与 Steam）都带同名的 ``Ascaron.Logging-2.6.dll``，实测三份
    样本逐字节相同。所以“能不能挂载”只看这个文件在不在，与版别无关；
    ``detect_edition`` 只用来显示版别名。
    """
    return os.path.isfile(os.path.join(target, HOST_DLL))


def detect_edition(target):
    """判断是 Steam 还是 GOG，**只用于显示，不决定启动路径**。

    不能只看 ``Ascaron.Logging-2.6.dll`` 是否存在：GOG 版（例如法语
    1.1.2.42）也带同名原版 DLL，按存在性判断会把 GOG 误认成 Steam。顺序：

    1. GOG 标记文件优先；
    2. PR2.exe 的 SHA 在已知版本表里，就按表里的 id 判断；
    3. 以上都不确定时，才退回“宿主 DLL 存在即 Steam”（未知 Steam 版本）。
    """
    if _is_gog(target):
        return "gog"
    exe = os.path.join(target, GAME_EXE)
    try:
        sha = file_digest(exe).upper() if os.path.isfile(exe) else ""
    except OSError:
        sha = ""
    known = BUILD_BY_SHA.get(sha) if sha else None
    if known:
        return "steam" if str(known.get("id", "")).startswith("steam") else "gog"
    if os.path.isfile(os.path.join(target, HOST_DLL)):
        return "steam"
    return "gog"
