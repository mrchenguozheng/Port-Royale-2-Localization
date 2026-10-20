#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mark_review.py —— 给「拿不准」的译文加/去一个 ※ 记号。

为什么要记号
------------
有些译法不是错，而是「可能不止一种」：人名 Jan 音译成「扬」还是「扬恩」、
地名按意译还是音译……这类条目光看表格看不出问题，只有在**游戏里读到
上下文**才知道顺不顺。

所以在译文末尾加一个 ※：游玩时看到它，就知道这条值得再看一眼，
回来改完再从 glossary\\review.toml 里删掉、去掉记号。

记号必须真能在游戏里显示 —— ※（U+203B）要包含在字体里，
subset_fonts.py 的 EXTRA 已经加了它，重新构建字体即可。

用法
----
    python src\\tools\\mark_review.py --apply    按 review.toml 加记号
    python src\\tools\\mark_review.py --clear    去掉 review.toml 里各条的记号
    python src\\tools\\mark_review.py --list     列出当前待复核条目
"""
import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
REVIEW = os.path.join(ROOT, "glossary", "review.toml")

sys.path.insert(0, HERE)
import translate as T

MARK = "※"


def load_review():
    if not os.path.isfile(REVIEW):
        return []
    with open(REVIEW, "rb") as f:
        return tomllib.load(f).get("item", [])


def read_rows(path):
    """按文件里的顺序读 (id, text)，保留原始行顺序。"""
    doc = {}
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    ids = []
    for line in io.open(path, encoding="utf-8"):
        m = re.match(r'^"([^"]+)"\s*=', line)
        if m:
            ids.append(m.group(1))
    return ids, doc


def esc(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def rewrite(lang, ids, doc):
    path = T.lang_path(lang)
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        "\n".join('"%s" = "%s"' % (k, esc(doc[k])) for k in ids) + "\n")


def main():
    ap = argparse.ArgumentParser(description="给待复核译文加/去 ※ 记号")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    items = load_review()
    if args.list or (not args.apply and not args.clear):
        for it in items:
            print("%s | %s | %s" % (it.get("id"), it.get("text"), it.get("note", "")))
        return 0

    path = T.lang_path(args.lang)
    if not os.path.isfile(path):
        raise SystemExit("没有 %s" % path)
    ids, doc = read_rows(path)

    changed = 0
    for it in items:
        rid = it["id"].lower()
        if rid not in doc:
            print("跳过 %s：译文里没有这条" % rid)
            continue
        text = doc[rid]
        base = text.rstrip(MARK + " ")
        if args.apply:
            if text != base + MARK:
                doc[rid] = base + MARK
                changed += 1
        else:
            if text != base:
                doc[rid] = base
                changed += 1
    rewrite(args.lang, ids, doc)
    print("%s：改了 %d 条（共 %d 条待复核）"
          % ("加记号" if args.apply else "去记号", changed, len(items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
