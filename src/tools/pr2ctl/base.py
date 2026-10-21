# -*- coding: utf-8 -*-
"""pr2ctl.base —— 路径常量、已知版本、补丁清单与文件小工具。"""

#!/usr/bin/env python3
# coding: utf-8
r"""pr2ctl.core — Port Royale 2 本地化工具的核心逻辑（无 UI 依赖）

一个窗口分三段，段号就是步骤号：

界面无关：版本识别、构建、部署、启动、设置读写都在这里。
tkinter 窗口（build_install.py）只负责显示与回调。
"""

import ctypes
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser



HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/tools
SRC = os.path.dirname(HERE)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
BUILD = os.path.join(ROOT, "build")
PACK_OUT = os.path.join(BUILD, "PR2Packs")
LOCALE_INI = os.path.join(SRC, "locale.ini")

# 直接复制进游戏目录的文件。
FLAT_FILES = ("PR2Launcher.exe", "PR2TextSource.dll")
# 整个目录一起复制。
PACK_DIR = "PR2Packs"
GAME_EXE = "PR2.exe"
#: 装好之后用它启动游戏。它挂起 PR2.exe、注入 DLL、再恢复执行。
LAUNCHER = "PR2Launcher.exe"
#: 编译注入器。子进程里跑，结果读它的输出。
INJECTOR_BAT = os.path.join(SRC, "build_injector.bat")
#: 译文编辑器（本地 Web）。它跟上面三条链路都无关 —— 不编译、不复制、
#: 不启动游戏，只改 src\translations\*.toml，所以自己一个按钮。
EDITOR_DIR = os.path.join(SRC, "editor")
#: 独立入口（想不开工具窗口时双击用）。
EDITOR_BAT = os.path.join(EDITOR_DIR, "StartEditor.bat")
EDITOR_DIST = os.path.join(EDITOR_DIR, "dist")
#: 编辑器从 8777 起往上找空端口，所以探测也按这个范围来 ——
#: 这样才能找到「上一次 start 留下、还在跑」的那个实例并复用它。
EDITOR_PORT_BASE = 8777
#: 扫得比 server.py 的候选范围（8777 + 20）再宽一点：端口被占时它会往上挪，
#: 而上一轮留下的实例可能正好停在更上面。多扫几个端口很便宜（本地拒绝是
#: 立刻返回的），漏扫的代价却是「没认出来 → 又起一个」。
EDITOR_PORT_TRIES = 24
#: 启动语言下拉里的「不指定」项：读PR2Packs\locale.ini 的 language=。
FOLLOW_LANG = "跟随 locale.ini"

#: 日志保留的最大行数。超过就丢最老的那些：一次构建几十行，
#: 反复操作几千行会让 Text 控件越来越慢，但全清又等于把刚才的
#: 排查线索一起丢了，所以留一个上限而不是清空。
LOG_MAX_LINES = 4000

KNOWN_BUILDS = (
    {
        "id": "gog-en-1.1.2.3",
        "label": "GOG 英文版 1.1.2.3",
        "sha256": "394CE2A48BC6B21708B81A232C7C88459BE7F3C8082CC593AD83B0B8E4C168EC",
        "note": "原版英文，注入方案首选；安装目录自带 PR2Packs 目录。",
    },
    {
        "id": "gog-fr-1.1.2.42",
        "label": "GOG 法语版 1.1.2.42",
        "sha256": "EF0E97D40F8DDF24186D18D39D07F12C562949D005654E99B7C1D21429110FA5",
        "note": "法文界面文本编在 exe 里；exe 版本号是 1.1.2.42，比英文版高。",
    },
    {
        "id": "steam-en-1.1.2.3",
        "label": "Steam 英文版 1.1.2.3",
        "sha256": "5295C06689147F7565F72510AEB686719CF0AE38AA581A6DF3E4D61D0CF76264",
        "note": "带 CEG 校验，exe 不能改；必须走注入。",
    },
)

BUILD_BY_SHA = {b['sha256'].upper(): b for b in KNOWN_BUILDS}


PATCH_ITEMS = (
    "PR2Launcher.exe",
    "PR2TextSource.dll",
    "PR2TextSource.log",
    "PR2TextSource_gap.log",
    "PR2TextSource_lsr.log",
    "PR2TextSource_resolve.log",
    "PR2Packs\\",
)

def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, GAME_EXE))


def writable(path):
    """游戏在运行时旧 DLL 与启动器都被占着，复制会以共享冲突失败，
    不是权限不足。先探一下写权限，好在报错时说清是哪一种。"""
    probe = os.path.join(path, ".pr2loc_write_test")
    try:
        with open(probe, "wb"):
            pass
        os.remove(probe)
    except OSError:
        return False
    return True


def same_content(a, b):
    """两个文件内容是否一致。

    比大小先过一遍：语言包几百 KB，同尺寸却不同的机会极少，
    而逐字节比只在尺寸相同时才做。
    """
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    return file_digest(a) == file_digest(b)


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

