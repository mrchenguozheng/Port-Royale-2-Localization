#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 key 整行替换 de.toml 的译文。

用法：python src/tools/analysis/de_apply.py <json 文件>
JSON 形如 {"0xabcdef": "新的整条译文", ...}。脚本会断言 key 存在、断言旧值不同，
再把值按 TOML 双引号字符串的规则写回，最后用 tomllib 读回校验条数与占位符。
"""
import io
import json
import re
import sys
import tomllib

PATH = r"C:\Users\mrche\WorkBuddy\2026-10-15-23-47-12\Port Royale 2 Localization\src\translations\de.toml"
PH = re.compile(r"@[A-Za-z$]+[A-Za-z0-9_$]+@")


def toml_escape(s):
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    return out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def main(jf):
    patch = json.load(io.open(jf, encoding="utf-8"))
    old = tomllib.load(open(PATH, "rb"))
    for k, v in patch.items():
        if k not in old:
            raise SystemExit("无此键：%s" % k)
    lines = io.open(PATH, encoding="utf-8", newline="\n").read().split("\n")
    written = 0
    for i, line in enumerate(lines):
        if not line.startswith('"'):
            continue
        key = line.split('"')[1]
        if key not in patch:
            continue
        new = patch[key]
        a = sorted(PH.findall(old[key]))
        b = sorted(PH.findall(new))
        if a != b:
            raise SystemExit("占位符不一致：%s %s != %s" % (key, a, b))
        lines[i] = '"%s" = "%s"' % (key, toml_escape(new))
        written += 1
    if written != len(patch):
        raise SystemExit("写入 %d 条，期望 %d 条" % (written, len(patch)))
    io.open(PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    chk = tomllib.load(open(PATH, "rb"))
    print("写入 %d 条；全表 %d 条，与旧表键集合一致：%s"
          % (written, len(chk), set(chk) == set(old)))
    print("改动条目占位符一致；值未变：%s" % sorted(k for k, v in patch.items() if v == old[k]))


if __name__ == "__main__":
    main(sys.argv[1])
