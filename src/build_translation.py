#!/usr/bin/env python3
# coding: utf-8
"""build_translation.py —— 编译单门语言包并铺 locale.ini。"""
import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
PACKS = os.path.join(REPO, "build", "runtime", "PR2Localization", "packs")
COMPILE = os.path.join(SRC, "tools", "pack", "compile_pack.py")
LOCALE = os.path.join(SRC, "locale.ini")


def main():
    parser = argparse.ArgumentParser(description="编译 PR2 语言包")
    parser.add_argument("--lang", default="zh", help="语言代码，默认 zh")
    parser.add_argument("--no-pause", action="store_true",
                        help="兼容旧入口，无实际作用")
    args = parser.parse_args()
    lang = args.lang.strip()
    if not lang:
        print("[pack] ERROR: 语言代码为空。")
        return 1
    if not os.path.isfile(COMPILE):
        print("[pack] ERROR: 找不到 %s" % COMPILE)
        return 1

    os.makedirs(PACKS, exist_ok=True)
    print("[pack] 编译 %s ..." % lang)
    code = subprocess.run(
        [sys.executable, COMPILE, "--lang", lang, "--out", PACKS]).returncode
    if code != 0:
        print("[pack] FAILED. 见上方错误。")
        return 1

    if not os.path.isfile(LOCALE):
        print("[pack] ERROR: 找不到 %s" % LOCALE)
        return 1
    for name in ("locale.ini", "locale.default.ini"):
        dst = os.path.join(PACKS, name)
        if not os.path.isfile(dst):
            shutil.copy2(LOCALE, dst)

    print("\n[pack] SUCCESS:")
    for name in sorted(os.listdir(PACKS)):
        print("  " + name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
