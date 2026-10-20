#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terms_check.py —— 术语一致性检查：原文里出现了术语，译文有没有用约定的译法。

为什么需要
----------
术语表（glossary\\terms.toml）本身只是「查得到」；真正难的是 3500 多条里
同一个词被译成好几种。这个脚本把术语表当规则用：

    原文里出现 `Frigate`  →  译文里应该出现「巡防舰」

没出现就报出来，附带该条的 id、英文片段和实际译文，方便逐条改。

判定规则
--------
- 英文按**整词**匹配（`Frigate` 不会命中 `Frigatebird`）；术语首字母大写时
  区分大小写 —— 否则 `may`（情态动词）会被当成五月；
- 允许复数：`Frigate` 也匹配 `Frigates`；
- 译文里包含约定译法即通过；词组里嵌着也算（「军事巡防舰」含「巡防舰」）；
- 组里可以写 `accept = ["载入", "读取"]` 表示这几种译法都算对；
- 组里写 `check = false` 就整组不查（界面词这种一词多义的不适合自动判）。

用法
----
    python src\\tools\\terms_check.py             # 查所有可编辑语言
    python src\\tools\\terms_check.py --lang zh
    python src\\tools\\terms_check.py --json       # 给编辑器/脚本用
    python src\\tools\\terms_check.py --strict     # 有问题时退出码 1
"""
import argparse
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
TERMS = os.path.join(ROOT, "glossary", "terms.toml")

sys.path.insert(0, HERE)
import translate as T


def load_terms():
    """返回 (各组, 整体跳过的 id 列表)。"""
    if not os.path.isfile(TERMS):
        return [], []
    with open(TERMS, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("group", []), [x.lower() for x in doc.get("ignore", [])]


def pick_ids(group, en):
    if "range" in group:
        lo, hi = (int(x, 16) for x in group["range"])
        ids = [k for k in en if lo <= int(k, 16) <= hi]
    else:
        ids = [k.lower() for k in group.get("ids", [])]
        ids = [k for k in ids if k in en]
    top = group.get("max_len", 40)
    ids = [k for k in ids if len(en.get(k, "")) <= top]
    return sorted(ids, key=lambda k: int(k, 16))


def build_rules(groups, en, doc, lang):
    """[(英文术语, [可接受译法…], 组名, 定义该术语的 id)]。"""
    rules = []
    for g in groups:
        if g.get("check", True) is False:
            continue
        ids_in_group = pick_ids(g, en)
        expect = [doc.get(k, "").strip() for k in pick_ids(g, en)]
        accept = [a.strip() for a in g.get("accept", [])]
        for k in pick_ids(g, en):
            term = en[k].strip()
            want = doc.get(k, "").strip()
            if not term or not want:
                continue
            if not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,30}", term):
                continue                      # 术语本身不是纯英文词就不查
            alt = (g.get("alt") or {}).get(k, [])
            ok = [want] + accept + alt
            # 月份：中文数字与阿拉伯数字两种写法都算对（六月 / 6月）
            m = re.fullmatch(r"([一二三四五六七八九十]{1,2})月", want)
            if m:
                ok.append("%s月" % CN_NUM.get(m.group(1), ""))
            rules.append((term, [x for x in ok if x], g["name"], k,
                          set(ids_in_group)))
    return rules


CN_NUM = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6",
          "七": "7", "八": "8", "九": "9", "十": "10", "十一": "11", "十二": "12"}


def compile_rule(term):
    """整词 + 可选复数 s；首字母大写时区分大小写（区分 May 与 may）。

    复数只认 `s`，不认 `es`：否则 `Wood` 会命中人名 `Woodes Rogers`。
    """
    case = re.IGNORECASE if term[:1].islower() else 0
    body = r"\s+".join(re.escape(p) for p in term.split())
    return re.compile(r"(?<![A-Za-z])%s(?:s)?(?![A-Za-z])" % body, case)


def check_lang(lang, groups, en, doc):
    rules = [(compile_rule(t), t, ok, g, k, same_group)
             for t, ok, g, k, same_group in build_rules(groups, en, doc, lang)]
    issues = []
    seen = set()
    for rid, en_text in en.items():
        zh = doc.get(rid, "") or ""
        if not zh.strip():
            continue
        # 先找出所有命中，再按「长的优先」消重叠：`Rear Admiral` 命中后，
        # 里面的 `Admiral` 就不再单独算一次。
        hits = []
        for rx, term, ok, group, term_id, same_group in rules:
            # 术语条目本身、以及同组里的其它术语（Rear Admiral 里的 Admiral）不查
            if rid in same_group:
                continue
            for m in rx.finditer(en_text):
                hits.append((m.start(), m.end(), m.end() - m.start(),
                             term, ok, group))
        hits.sort(key=lambda h: (-h[2], h[0]))
        kept, spans = [], []
        for h in hits:
            if any(not (h[1] <= s or h[0] >= e) for s, e in spans):
                continue
            spans.append((h[0], h[1]))
            kept.append(h)
        zh_flat = re.sub(r"\s+", "", zh)
        for _s, _e, _ln, term, ok, group in kept:
            if any(a and re.sub(r"\s+", "", a) in zh_flat for a in ok):
                continue
            sig = (rid, term)
            if sig in seen:
                continue
            seen.add(sig)
            issues.append({"id": rid, "term": term, "group": group,
                           "expected": ok[0], "actual": zh,
                           "en": en_text})
    return issues


def main():
    ap = argparse.ArgumentParser(description="术语一致性检查")
    ap.add_argument("--lang", action="append", default=[])
    ap.add_argument("--json", action="store_true", help="输出 JSON（编辑器用）")
    ap.add_argument("--limit", type=int, default=40, help="每个语言打印多少条")
    ap.add_argument("--strict", action="store_true", help="发现问题时退出码 1")
    args = ap.parse_args()

    groups, ignore = load_terms()
    if not groups:
        raise SystemExit("没有术语表：%s" % TERMS)
    en = T.load_toml()["s"]
    en = {r["id"]: r.get(T.BASE_LANG, "") for r in en}

    langs = args.lang or T.target_langs()
    out = {}
    total = 0
    for lang in langs:
        doc = {r["id"]: r.get(lang, "") for r in T.load_toml()["s"]}
        doc = {k: v for k, v in doc.items() if k not in ignore}
        issues = check_lang(lang, groups, en, doc)
        out[lang] = issues
        total += len(issues)
        if not args.json:
            print("== %s：%d 条不一致" % (lang, len(issues)))
            for x in issues[:args.limit]:
                print("   %s [%s] 应为「%s」，实际：%s"
                      % (x["id"], x["term"], x["expected"], x["actual"][:60]))
            if len(issues) > args.limit:
                print("   … 还有 %d 条" % (len(issues) - args.limit))

    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
