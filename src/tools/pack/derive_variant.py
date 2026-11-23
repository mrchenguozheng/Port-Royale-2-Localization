# -*- coding: utf-8 -*-
"""由 zh-Hant 底稿 + 地区差异表派生 zh-TW / zh-HK 完整译文。

用法：
    python src/tools/pack/derive_variant.py --variant zh-TW
    python src/tools/pack/derive_variant.py --all

输入：
    src/translations/zh-Hant.toml        繁体底稿（键集与 zh.toml 相同）
    src/data/variants/<locale>.toml      差异表（[[replace]] + [keys]）
输出：
    src/translations/<locale>.toml       生成物，一并提交，供既有校验/编译链路直接使用
"""

import argparse
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
BASE = os.path.join(ROOT, "src", "translations", "zh-Hant.toml")
VAR_DIR = os.path.join(ROOT, "src", "data", "variants")
OUT_DIR = os.path.join(ROOT, "src", "translations")

TAG_RE = re.compile(r"<[^<>]*>")


def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def dump(path, data):
    def esc(v):
        return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for k, v in data.items():
            f.write('"%s" = "%s"\n' % (k, esc(v)))


def derive(locale, base):
    vpath = os.path.join(VAR_DIR, locale + ".toml")
    if not os.path.isfile(vpath):
        raise SystemExit("缺少差异表：%s" % vpath)
    variant = load_toml(vpath)
    rules = [(r["from"], r["to"]) for r in variant.get("replace", [])]

    out = {}
    counts = {src: 0 for src, _ in rules}
    for k, text in base.items():
        new = text
        for src, dst in rules:
            n = new.count(src)
            counts[src] += n
            new = new.replace(src, dst)
        out[k] = new

    overrides = variant.get("keys", {})
    for k, text in overrides.items():
        if k not in out:
            raise SystemExit("差异表覆盖了不存在的键：%s" % k)
        out[k] = text

    return out, rules, counts, variant.get("variant", {})


def convert(text, rules):
    import opencc
    new = opencc.OpenCC("s2tw").convert(text)
    for src, dst in rules:
        new = new.replace(src, dst)
    return new


LINE_RE = re.compile(r'(= ")((?:[^"\\]|\\.)*)(")')


def derive_table(src, dst, rules):
    """派生 terms/names 这类「键 = 字符串」表，保留注释与结构。"""
    with open(src, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for line in lines:
        m = LINE_RE.search(line)
        if m and not line.lstrip().startswith("#"):
            val = m.group(2)
            new = convert(val, rules)
            line = line[:m.start(2)] + new + line[m.end(2):]
        out.append(line)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    return len(out)


def check(locale, base, out, rules):
    problems = []
    if set(out) != set(base):
        problems.append("键集与底稿不一致")
    for k in base:
        if len(TAG_RE.findall(out[k])) != len(TAG_RE.findall(base[k])):
            problems.append("%s 标记数量变化" % k)
        if "\u00b7" in out[k] or "\u2022" in out[k]:
            problems.append("%s 含音译分隔符" % k)
    for src, _ in rules:
        if src and any(src in v for v in out.values()):
            problems.append("规则未收敛：%s 仍存在" % src)
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", action="append", default=[],
                    help="地区代码，可重复，如 zh-TW")
    ap.add_argument("--all", action="store_true", help="派生 data/variants 下全部地区")
    args = ap.parse_args()

    locales = list(args.variant)
    if args.all:
        locales += sorted(os.path.splitext(f)[0]
                          for f in os.listdir(VAR_DIR) if f.endswith(".toml"))
    if not locales:
        raise SystemExit("需要 --variant 或 --all")

    base = load_toml(BASE)
    failed = False
    for locale in dict.fromkeys(locales):
        out, rules, counts, meta = derive(locale, base)
        problems = check(locale, base, out, rules)
        path = os.path.join(OUT_DIR, locale + ".toml")
        dump(path, out)
        for sub in ("terms", "names"):
            src = os.path.join(ROOT, "src", "data", sub, "zh.toml")
            if os.path.isfile(src):
                derive_table(src, os.path.join(ROOT, "src", "data", sub, locale + ".toml"), rules)
        print("%s: %d 条，规则 %d 条，替换 %s"
              % (meta.get("alias", locale), len(out), len(rules),
                 ", ".join("%s→%s ×%d" % (s, d, counts[s]) for s, d in rules) or "无"))
        if problems:
            failed = True
            for p in problems:
                print("  ! " + p)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

