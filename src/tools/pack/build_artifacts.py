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
BUILD = os.path.join(ROOT, "build")
FONT_DIR = os.path.join(BUILD, "fonts")


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


def build_fonts(langs, out_dir=None, mode="stitch", log=None, force=False, cache=True):
    """生成字体：mode = stitch（本机开发）| noto（发行）。

    stitch 输出到 <out_dir>/<语言>/，与 subset_fonts 一致；
    noto 也输出到 <out_dir>/<语言>/，与发行包布局一致。
    返回 (ok, message)。
    """
    log = log or (lambda m: None)
    langs = list(langs or [])
    if mode == "none":
        return True, "跳过字体"
    if not langs:
        return False, "没有语言"

    font_tools = os.path.join(ROOT, "src", "tools", "font")
    if font_tools not in sys.path:
        sys.path.insert(0, font_tools)

    if mode == "noto":
        import make_noto_fonts
        for lang in langs:
            dst = os.path.join(out_dir or FONT_DIR, lang)
            log("生成 Noto 替换字体 %s …" % lang)
            make_noto_fonts.ensure_noto_fonts(lang, dst, log=log, cache=cache)
        return True, "Noto 字体：%s" % "、".join(langs)

    import subset_fonts
    return subset_fonts.ensure_fonts(
        out_dir=out_dir or FONT_DIR, langs=langs, log=log, force=force)
