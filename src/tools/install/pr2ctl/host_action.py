# -*- coding: utf-8 -*-
"""pr2ctl.host_action —— 部署期调用启动器完成宿主挂载/还原。

替换算法只有 Rust 的 ``pr2_common::host`` 一份。部署工具链不重新实现
「校验原版 → 备份 → 临时文件 → 换名 → 复验」这一串动作，只把文件送到
游戏目录，然后执行同一个 ``PR2Localization.exe``，参数与玩家手动运行时
完全相同：

- ``--mount``   校验原版、建立两份备份、换入代理，不启动游戏；
- ``--restore`` 只接受本工具代理，换回原版，不启动游戏。

失败原因写在该进程的 ``PR2Localization\\logs\\host.log`` 里；这里读回尾部
几行交给界面显示，避免部署器自己再猜一套错误文案。
"""

import os
import subprocess

from .base import *  # noqa: F401,F403

#: 只读最后几行：host.log 里经常还有上一次动作的记录，全文搬进界面会淹掉重点。
HOST_LOG_TAIL = 8


def _launcher(target):
    return os.path.join(target, LAUNCHER)


def _tail_host_log(target, lines=HOST_LOG_TAIL):
    path = os.path.join(target, LOG_DIR, "host.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read().splitlines()
    except OSError:
        return ""
    return "\n".join(text[-lines:]) if text else ""


def run(target, flag):
    """在游戏目录执行 ``PR2Localization.exe <flag>``。

    返回 ``(是否成功, 失败说明)``；成功时说明为空串。调用方负责决定
    「失败后是否还继续别的步骤」—— 这里只报告事实，不降级、不重试。
    """
    exe = _launcher(target)
    if not os.path.isfile(exe):
        return False, (
            "游戏目录里没有 %s，无法调用启动器完成宿主动作。"
            "先把运行时的三个平铺文件复制进去。" % LAUNCHER
        )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [exe, flag],
            cwd=target,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            creationflags=flags,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return False, ("%s %s 60 秒没有结束。游戏可能被占用，"
                       "请关闭游戏后重试。" % (LAUNCHER, flag))
    except OSError as exc:
        return False, "启动 %s %s 失败：%s" % (LAUNCHER, flag, exc)

    if proc.returncode == 0:
        return True, ""
    detail = _tail_host_log(target)
    if detail:
        return False, detail
    output = (proc.stdout or "").strip()
    if output:
        return False, output.splitlines()[-1]
    return False, "%s %s 退出码 %d。" % (LAUNCHER, flag, proc.returncode)


def mount(target):
    """按运行时同一套规则挂载宿主代理。"""
    return run(target, "--mount")


def restore(target):
    """按运行时同一套规则还原原版宿主 DLL。"""
    return run(target, "--restore")
