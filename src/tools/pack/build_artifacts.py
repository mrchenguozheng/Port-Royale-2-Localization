# -*- coding: utf-8 -*-
"""build_artifacts.py —— 构建语言包产物的统一入口。

目前只收口最常重复的一步：在子进程里调用 compile_pack.py。
字体只做映射：用 Noto 替换字体（mode = noto），不再缝合原版字体。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILE = os.path.join(HERE, "compile_pack.py")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
BUILD = os.path.join(ROOT, "build")
RUNTIME = os.path.join(BUILD, "runtime")
FONT_DIR = os.path.join(RUNTIME, "PR2Localization", "fonts")


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


def compile_pack(lang, out_dir, no_fonts=True, on_line=None, env=None, union=False):
    """把一个语言编成 PR2Localization\\packs\\<lang>.txt；返回退出码。

    union=True 时只出一份并集包（en 与 fr 两版键集合并），GOG / Steam 两个
    发行包共用同一份文件；逐版对照仍走默认模式（另写 build\\variants\\）。
    """
    cmd = [sys.executable, COMPILE, "--lang", lang, "--out", out_dir]
    if no_fonts:
        cmd.append("--no-fonts")
    if union:
        cmd.append("--union")
    return run_stream(cmd, on_line=on_line, env=env)


def build_fonts(langs, out_dir=None, mode="noto", log=None, cache=True):
    """生成字体：mode = noto（替换字体，唯一方式）| none（跳过）。

    输出到 <out_dir>/<语言>/，与发行包布局一致。返回 (ok, message)。
    """
    log = log or (lambda m: None)
    langs = list(langs or [])
    if mode == "none":
        return True, "跳过字体"
    if not langs:
        return False, "没有语言"
    if mode != "noto":
        return False, "不支持的字体模式：%s（只支持 noto / none）" % mode

    font_tools = os.path.join(ROOT, "src", "tools", "font")
    if font_tools not in sys.path:
        sys.path.insert(0, font_tools)

    import make_noto_fonts
    import build_cyr_fonts
    import build_lat_fonts
    import font_sources
    # 字体找不到就是失败：以前这里的异常被吞成"字体检查跳过"，CI 的字体判据
    # 实际是空的（runner 上没有 Noto 就静默出无字体包）。现在返回 False。
    for lang in langs:
        dst = os.path.join(out_dir or FONT_DIR, lang)
        try:
            if lang == "ru":
                log("生成俄语字体 %s …（正文 Noto Sans 缩放，标题 Noto Serif 压缩）" % lang)
                ok, msg = build_cyr_fonts.build(dst, log=log)
                if not ok:
                    return False, msg
                continue
            if lang in build_lat_fonts.LANGS:
                # 正文原版 ARIAL 就够（拉丁扩展 A 全覆盖），只换三个标题槽位。
                log("生成 %s 标题字体（Noto Serif 按原版 cap/avg 缩放）…" % lang)
                ok, msg = build_lat_fonts.build(lang, dst, log=log)
                if not ok:
                    return False, msg
                continue
            log("生成 Noto 替换字体 %s …（%s）" % (lang, font_sources.whoami()))
            make_noto_fonts.ensure_noto_fonts(lang, dst, log=log, cache=cache)
        except font_sources.FontMissingError as exc:
            return False, "%s：%s" % (lang, exc)
        except Exception as exc:                       # 字体库缺失等也按失败算
            return False, "%s 字体生成失败：%s" % (lang, exc)
    return True, "字体：%s" % "、".join(langs)
