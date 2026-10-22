# -*- coding: utf-8 -*-
"""build_artifacts.py —— 构建语言包产物的统一入口。

目前只收口最常重复的一步：在子进程里调用 compile_pack.py。
字体仍由调用方按场景选择（发行用 Noto，本机开发用缝合）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILE = os.path.join(HERE, "compile_pack.py")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def _line(raw):
    try:
        return raw.decode("utf-8").rstrip()
    except UnicodeDecodeError:
        return raw.decode("mbcs", "replace").rstrip()


def run_stream(cmd, on_line=None, env=None):
    """跑子命令并逐行回调；返回退出码。"""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=ROOT, env=env,
    )
    for raw in proc.stdout:
        line = _line(raw)
        if on_line and line:
            on_line(line)
    return proc.wait()


def compile_pack(lang, out_dir, no_fonts=True, on_line=None, env=None):
    """把一个语言编成 PR2Packs/<lang>.txt；返回退出码。"""
    cmd = [sys.executable, COMPILE, "--lang", lang, "--out", out_dir]
    if no_fonts:
        cmd.append("--no-fonts")
    return run_stream(cmd, on_line=on_line, env=env)
