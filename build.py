#!/usr/bin/env python3
# coding: utf-8
"""build.py —— 一条命令构建注入器与语言包。"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "src")
TRANSLATIONS = os.path.join(SRC, "translations")


def languages(values):
    names = []
    for item in values:
        for name in item.split(","):
            name = name.strip()
            if name:
                names.append(name)
    return sorted(set(names))


def all_translation_languages():
    return sorted(
        os.path.splitext(n)[0] for n in os.listdir(TRANSLATIONS)
        if n.endswith(".toml") and not n.startswith("test_")
    )


def call(script, args):
    cmd = [sys.executable, os.path.join(SRC, script)] + args
    print("$ " + " ".join(cmd))
    if subprocess.run(cmd).returncode != 0:
        print("[build] 脚本失败：%s" % script)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="构建 PR2 本地化运行时")
    parser.add_argument("--target", choices=["all", "injector", "packs"],
                        default="all")
    parser.add_argument("--lang", action="append", default=[])
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args()

    langs = languages(args.lang) or all_translation_languages()
    if args.target in ("all", "packs"):
        if not langs:
            print("[build] 没有找到语言：src/translations/*.toml 为空。")
            return 1
        for lang in langs:
            if not os.path.isfile(os.path.join(TRANSLATIONS, lang + ".toml")):
                print("[build] 找不到译文文件：src/translations/%s.toml" % lang)
                return 1

    if args.target in ("all", "injector"):
        print("[build] 1/2 编译注入器（cargo）")
        if not call("build_injector.py", ["--no-pause"]):
            return 1
    if args.target in ("all", "packs"):
        print("[build] 2/2 编译语言包")
        for lang in langs:
            print("\n[build] -> %s" % lang)
            if not call("build_translation.py", ["--lang", lang, "--no-pause"]):
                return 1

    print("\n[build] 完成。")
    if args.target in ("all", "injector"):
        print("[build] 运行时：build/runtime")
    if args.target in ("all", "packs"):
        print("[build] 语言包：build/runtime/PR2Localization/packs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
