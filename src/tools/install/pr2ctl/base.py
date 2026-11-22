# -*- coding: utf-8 -*-
"""pr2ctl.base —— 路径常量、已知版本、补丁清单与文件小工具。"""

#!/usr/bin/env python3
# coding: utf-8
r"""pr2ctl.core — Port Royale 2 本地化工具的核心逻辑（无 UI 依赖）

版本识别、构建、部署、启动、设置读写都在这里；
调用方是 `src\tools` 下的 CLI 与发行版 GUI。
"""

import ctypes
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time



HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # src/tools
TOOLS = HERE
SRC = os.path.dirname(HERE)                              # 仓库的 src\
ROOT = os.path.dirname(SRC)                              # 仓库根
BUILD = os.path.join(ROOT, "build")
RUNTIME = os.path.join(BUILD, "runtime")
PACK_OUT = os.path.join(RUNTIME, "PR2Localization", "packs")
LOCALE_FILE = "locale.ini"
LOCALE_DEFAULT_FILE = "locale.default.ini"
LOCALE_INI = os.path.join(SRC, LOCALE_FILE)

# 直接复制进游戏目录的文件。名字以 PR2Localization 开头，
# 和游戏原版文件区分。宿主 DLL 由部署末尾调用启动器 --mount 处理，
# 不走这里的通用复制（要先校验原版、备份，再原子换名）。
FLAT_FILES = (
    "PR2Localization.exe",
    "PR2LocalizationGUI.exe",
    "PR2LocalizationCore.dll",
)
#: 宿主 DLL 的挂载/还原已收进启动器（pr2_common::host），发行包不再带脚本。
#: 部署只负责把代理送到 PR2Localization\host\，再调用 PR2Localization.exe --mount。
# 运行时数据目录；语言包、字体、UI、日志都放在它下面。
DATA_DIR = "PR2Localization"
PACK_DIR = os.path.join(DATA_DIR, "packs")
FONT_DIR = os.path.join(DATA_DIR, "fonts")
UI_DIR = os.path.join(DATA_DIR, "ui")
UI_FILE = "ui.ini"
UI_DEFAULT_FILE = "ui.default.ini"
LOG_DIR = os.path.join(DATA_DIR, "logs")
GAME_EXE = "PR2.exe"
#: 装好之后用它启动游戏。它挂起 PR2.exe、注入 DLL、再恢复执行。
LAUNCHER = "PR2Localization.exe"
#: GUI 入口；GOG 的正式入口是它。
LAUNCHER_GUI = "PR2LocalizationGUI.exe"
#: 编译注入器。子进程里跑 PowerShell 7，结果读它的输出。
INJECTOR_PS1 = os.path.join(SRC, "build_injector.ps1")
#: 所有构建/启动脚本统一要求 PowerShell 7。
PWSH = shutil.which("pwsh.exe") or shutil.which("pwsh")
#: 启动语言下拉里的「不指定」项：读 PR2Localization\packs\locale.ini 的 language=。
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
        "note": "原版英文，注入方案首选；安装目录自带语言包目录。",
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
    "PR2Localization.exe",
    "PR2LocalizationGUI.exe",
    "PR2LocalizationCore.dll",
    "PR2Localization\\",
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

