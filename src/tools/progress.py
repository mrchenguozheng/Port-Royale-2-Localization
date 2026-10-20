#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""progress.py —— 看翻译进度：已译 / 原样保留 / 还没动。

「原样保留」来自 `src\\translations\\keep_original.toml`，那些条目本来就不该翻
（纯符号、数字、引擎编号、版权声明）。把它们算进「已处理」，进度才不会永远卡在
99%。

用法
----
    python src\\tools\\progress.py
    python src\\tools\\progress.py --lang ja --todo 20   # 顺便列出下一条待译
"""
import argparse
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import translate as T

ROOT = os.path.dirname(os.path.dirname(HERE))


def load_keep():
    path = os.path.join(ROOT, "src", "translations", "keep_original.toml")
    if not os.path.isfile(path):
        return set()
    data = tomllib.load(open(path, "rb"))
    out = set()
    for v in data.values():
        for k in v.get("ids") or []:
            out.add(k.lower())
    return out


def main():
    ap = argparse.ArgumentParser(description="翻译进度")
    ap.add_argument("--lang", default="ja")
    ap.add_argument("--todo", type=int, default=0, help="列出多少条待译")
    a = ap.parse_args()

    keep = load_keep()
    rows = T.load_toml()["s"]
    en = {r["id"].lower(): r.get(T.BASE_LANG, "") or "" for r in rows}
    doc = {r["id"].lower(): r.get(a.lang, "") or "" for r in rows}

    done = [k for k in en if doc.get(k, "") != en[k]]
    kept = [k for k in en if k in keep]
    todo = [k for k in en if doc.get(k, "") == en[k] and k not in keep]

    print("%s：%d / %d 已译，%d 原样保留，%d 待译"
          % (a.lang, len([k for k in done if k not in keep]), len(en),
             len(kept), len(todo)))
    if a.todo:
        for k in sorted(todo, key=lambda k: len(en[k]))[:a.todo]:
            print("  %s  %s" % (k, en[k][:70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
