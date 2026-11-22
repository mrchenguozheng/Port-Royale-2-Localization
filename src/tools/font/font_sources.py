#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""font_sources.py —— 统一的 Noto 源字体定位。

构建脚本不各自找字体，都走这里。搜索顺序（项目内优先，保证本机与 CI
用的是同一份文件，重建结果逐字节一致）：

    1. PR2_FONT_DIRS            环境变量，设置后只查它（分号分隔），CI 用它把
                                范围钉在 build\\cache\\noto-src
    2. <repo>\\assets\\fonts\\noto  入库目录，允许手工放字体，默认空
    3. <repo>\\build\\cache\\noto-src  下载缓存，不入库，CI 用 actions/cache 持久
    4. %WINDIR%\\Fonts
    5. %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts

都没有就抛 FontMissingError：缺哪个文件、查过哪些目录、怎么补，一次说清。
不再有"字体检查跳过"这种静默降级。
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

#: 入库目录：允许把字体文件直接放进仓库（体积大，默认不放）。
PROJECT_DIR = os.path.join(ROOT, "assets", "fonts", "noto")
#: 下载缓存：fetch 落点，不入库。
CACHE_DIR = os.path.join(ROOT, "build", "cache", "noto-src")
#: 清单：文件名 → 下载地址 / 字重 / 最小体积。
MANIFEST = os.path.join(SRC, "fonts-sources.toml")

FETCH_CMD = "python src\\tools\\font\\fetch_noto_fonts.py --fetch"


class FontMissingError(FileNotFoundError):
    """清单里的字体在任何候选目录都找不到。"""


def system_dirs():
    dirs = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    return dirs


def candidate_dirs(include_system=True, extra=()):
    """返回搜索目录列表；env 覆盖时只返回 env 里的目录。"""
    env = os.environ.get("PR2_FONT_DIRS")
    if env:
        base = [p.strip() for p in re.split(r"[;]", env) if p.strip()]
    else:
        base = [PROJECT_DIR, CACHE_DIR]
        if include_system:
            base += system_dirs()
    out = list(extra)
    for d in base:
        if d not in out:
            out.append(d)
    return out


def find(name, dirs=None):
    for d in (dirs if dirs is not None else candidate_dirs()):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def require(name, dirs=None, note=""):
    """找到就返回绝对路径，找不到抛 FontMissingError（信息可执行）。"""
    p = find(name, dirs)
    if p:
        return p
    tried = dirs if dirs is not None else candidate_dirs()
    raise FontMissingError(
        "缺少字体 %s%s\n查过：\n%s\n补法：%s（落盘到 %s）"
        % (name,
           ("（%s）" % note) if note else "",
           "\n".join("  - %s" % d for d in tried),
           FETCH_CMD, CACHE_DIR))


def present(name, dirs=None):
    return find(name, dirs) is not None


def scan(names, dirs=None):
    """返回 (found, missing)：found 是 {文件名: 路径}。"""
    dirs = dirs if dirs is not None else candidate_dirs()
    found, missing = {}, []
    for n in names:
        p = find(n, dirs)
        if p:
            found[n] = p
        else:
            missing.append(n)
    return found, missing


def whoami():
    """一行用途说明，便于在日志里核对到底用了哪份字体。"""
    env = os.environ.get("PR2_FONT_DIRS")
    if env:
        return "PR2_FONT_DIRS=%s" % env
    return "默认顺序：项目内 assets\\fonts\\noto → build\\cache\\noto-src → 系统 Fonts"
