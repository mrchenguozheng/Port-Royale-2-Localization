#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_release.py —— 生成按语言分发的发行包。

一个语言一个 zip，解压到游戏根目录即可：

    PR2-zh-v1.0.0/
      PR2Launcher.exe
      PR2TextSource.dll
      PR2Packs/zh.txt
      PR2Packs/locale.ini
      fonts/ARIAL.TTF ...          # Noto 替换字体（默认）
      README.txt
      OFL.txt

发行包不包含游戏本体，也不包含缝合字体。想用原版字形的人可以走
``--fonts stitch``（仅自用/私有包，不要公开分发）。

    python src\\tools\\pack\\make_release.py --lang zh --version v1.0.0
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
BUILD = os.path.join(ROOT, "build")
PACK_OUT = os.path.join(BUILD, "PR2Packs")

LABELS = {"zh": "简体中文", "ja": "日本語"}
FLAT = ("PR2Launcher.exe", "PR2TextSource.dll")


def build_pack(lang, stage, log):
    out = os.path.join(stage, "PR2Packs")
    os.makedirs(out, exist_ok=True)
    script = os.path.join(TOOLS, "pack", "compile_pack.py")
    log("编译语言包 %s …" % lang)
    proc = subprocess.run([sys.executable, script, "--lang", lang,
                           "--out", out, "--no-fonts"],
                          cwd=ROOT, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        raise RuntimeError("语言包编译失败：%s" % lang)
    with open(os.path.join(out, "locale.ini"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("language=%s\n" % lang)


def copy_runtime(stage, log):
    for name in FLAT:
        src = os.path.join(BUILD, name)
        if not os.path.isfile(src):
            raise FileNotFoundError("缺 %s，先构建注入器" % src)
        shutil.copy2(src, os.path.join(stage, name))
        log("复制 %s" % name)


def copy_fonts(lang, stage, mode, log):
    if mode == "none":
        log("跳过字体（发行包不含字体）")
        return
    dst = os.path.join(stage, "fonts", lang)
    if mode == "stitch":
        src = os.path.join(BUILD, "fonts", lang)
        if not os.path.isdir(src):
            raise FileNotFoundError("缺 %s；先跑 subset_fonts.py --lang %s" % (src, lang))
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            if name.lower().endswith(".ttf"):
                shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
        log("复制缝合字体（仅限私有/自用包）")
        return

    fdir = os.path.join(TOOLS, "font")
    if fdir not in sys.path:
        sys.path.insert(0, fdir)
    import make_noto_fonts
    log("生成 Noto 替换字体 %s …" % lang)
    make_noto_fonts.ensure_noto_fonts(lang, dst, log=log)


def write_readme(lang, stage, mode):
    label = LABELS.get(lang, lang)
    font_line = {
        "noto": "字体：Noto Sans / Noto Serif（SIL OFL 1.1），完整字体，未裁剪。",
        "stitch": "字体：本地缝合版（仅限自用，不要公开分发）。",
        "none": "字体：本包不含字体，请自行准备中/日文字体。",
    }[mode]
    text = """Port Royale 2 本地化 - %s

安装（解压即用）：
  1. 把本压缩包里的全部文件解压到游戏根目录（和 PR2.exe 同一层）。
  2. 运行 PR2Launcher.exe 启动游戏。
  3. 不要直接运行 PR2.exe，那样不会加载语言包。

字体：
  字体在 fonts\\<语言>\\；启动器会按语言把它复制到 fonts\\ 根目录。
  同一目录可以放多个语言（fonts\\zh、fonts\\ja），启动器按 locale.ini 或 --lang 选择。

卸载：
  删除 PR2Launcher.exe、PR2TextSource.dll、PR2Packs\\%s.txt；
  如果覆盖过 fonts\\ 里的字体，请先用备份恢复。

注意：
  - 本包不包含游戏本体、地图、音乐等游戏资源。
  - 安装前建议备份游戏 fonts\\ 目录。
  - %s

字体许可：
  Noto 字体使用 SIL Open Font License 1.1，详见同目录 OFL.txt
  或 https://openfontlicense.org/
""" % (label, lang, font_line)
    with open(os.path.join(stage, "README.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def copy_license(stage, log):
    for rel in (os.path.join("assets", "fonts", "OFL.txt"),
                "OFL.txt",
                os.path.join("docs", "OFL.txt")):
        src = os.path.join(ROOT, rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(stage, "OFL.txt"))
            log("复制 OFL.txt")
            return
    log("提示：仓库里没有 OFL.txt，发行包只写了许可链接；正式发布前补上")


def make_zip(stage, out_dir):
    name = os.path.basename(stage.rstrip("\\/"))
    zip_path = os.path.join(out_dir, name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, stage)
                zf.write(full, rel)
    return zip_path


def make_release(lang, version, out_dir, mode, log=None):
    log = log or print
    stage = os.path.join(out_dir, "PR2-%s-%s" % (lang, version))
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage)
    build_pack(lang, stage, log)
    copy_runtime(stage, log)
    copy_fonts(lang, stage, mode, log)
    write_readme(lang, stage, mode)
    copy_license(stage, log)
    zip_path = make_zip(stage, out_dir)
    log("完成：%s" % zip_path)
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="生成按语言分发的 PR2 本地化发行包")
    ap.add_argument("--lang", action="append", required=True,
                    help="语言代码，可重复")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--fonts", choices=("noto", "stitch", "none"), default="noto")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for lang in args.lang:
        make_release(lang, args.version, args.out, args.fonts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
