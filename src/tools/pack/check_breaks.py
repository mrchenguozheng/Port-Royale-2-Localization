#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_breaks.py —— 核对译文与原文的换行（`<n>`）数量是否一致。

为什么需要
----------
引擎的换行标签 `<n>`（以及 `<n:5>` 这种带参数的形式）是**结构**，不是装饰：
原文分了几段，译文就该分几段。旧管线把换行弄丢过，表现是「原文两段、译文
挤成一坨」。这个脚本把差数逐条列出来，方便按原文补回或合并。
目标键如果是 `[ref:键]`，先展开引用再数 `<n>`；否则合法的同文引用会被
误报成「译文 0 / 原文 N」。展开只用于检查，不改写译文。

用法
----
    python src\\tools\\check_breaks.py                 # 所有可编辑语言
    python src\\tools\\check_breaks.py --lang ja
    python src\\tools\\check_breaks.py --lang ja --strict   # 有差异时退出码 1
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
import translate as T
from text import marks as M


def nn(s):
    return len(re.findall(r"<n(?::\d+)?\s*>", s))


def _doc_for(rows, lang):
    """取一门语言的键 → 文本；有 `[ref:]` 时先展开。

    `[ref:键]` 是整条同文引用，原文的换行在目标键里；不展开就会把
    一条合法的 ref 误报成「译文 0 / 原文 N」。展开只用于检查，
    不改写译文。
    """
    doc = {r["id"]: r.get(lang, "") or "" for r in rows}
    if not M.has_marks(doc):
        return doc
    return M.expand_doc(lang, doc)


def main():
    ap = argparse.ArgumentParser(description="核对译文与原文的 <n> 数量")
    ap.add_argument("--lang", action="append", default=[])
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    rows = T.load_toml()["s"]
    en = {r["id"]: r.get(T.BASE_LANG, "") or "" for r in rows}
    langs = a.lang or T.target_langs()
    total = 0
    for lang in langs:
        try:
            doc = _doc_for(rows, lang)
        except M.MarkError as exc:
            print("%s：标注展开失败（%s）" % (lang, exc))
            total += 1
            continue
        bad = []
        for r in rows:
            z = nn(doc.get(r["id"], "") or "")
            if z != nn(en[r["id"]]):
                bad.append((r["id"], z, nn(en[r["id"]])))
        total += len(bad)
        print("%s：%d 条不一致（共 %d 条）" % (lang, len(bad), len(rows)))
        for k, z, e in bad[:a.limit]:
            print("   %s  译文 %d / 原文 %d" % (k, z, e))
        if len(bad) > a.limit:
            print("   … 还有 %d 条" % (len(bad) - a.limit))
    if a.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
