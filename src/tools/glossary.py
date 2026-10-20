#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glossary.py —— 从现有译文生成「术语对照表」（glossary\\<语言>.md / .csv）。

为什么单独做一份
----------------
游戏里的专有名词（货物、船只、军衔、城镇……）散在 3500 多条文本里，
翻的时候很难保证前后一致。这份表把它们按组抽出来，英文与译文并排，
既能当翻译时的参考，也能当校对清单。

数据从哪来
----------
术语清单在 ``glossary\\terms.toml``（分组 + id 区间/列表），译文本身
**不另存**，每次生成都从 ``src\\translations\\`` 现取 —— 所以改了译文
重新跑一次就同步，不需要手工维护两份。

用法
----
    python src\\tools\\glossary.py                 # 生成所有可编辑语言的对照表
    python src\\tools\\glossary.py --lang zh       # 只生成 zh
    python src\\tools\\glossary.py --csv           # 另外导出 csv（Excel 用）

后期加语言：只要 translations\\<语言>.toml 存在，跑一次就会生成
``glossary\\<语言>.md``，术语清单不用动。
"""
import argparse
import csv
import io
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ROOT = os.path.dirname(SRC)
GLOSSARY = os.path.join(ROOT, "glossary")
TERMS = os.path.join(GLOSSARY, "terms.toml")

sys.path.insert(0, HERE)
import translate as T          # 复用语言列表与基准文件，别再抄一份规则


def load_terms():
    if not os.path.isfile(TERMS):
        raise SystemExit("找不到 %s" % TERMS)
    with open(TERMS, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("group", [])


#: 表头/标题里用的语言显示名（代码 -> 中文名），以后加语言在这里补一行。
LANG_NAMES = {"zh": "中文", "fr": "法语", "en.gog_1.1.2.3": "English",
              "en": "English", "test_en": "English"}


def lang_name(code):
    return LANG_NAMES.get(code, code)


def load_table(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def pick_ids(group, en):
    """一组术语对应的 id 列表（按 id 排序）。"""
    if "range" in group:
        lo, hi = (int(x, 16) for x in group["range"])
        ids = [k for k in en if lo <= int(k, 16) <= hi]
    else:
        ids = [k.lower() for k in group.get("ids", [])]
        ids = [k for k in ids if k in en] or ids
    top = group.get("max_len", 40)
    ids = [k for k in ids if len(en.get(k, "")) <= top]
    return sorted(ids, key=lambda k: int(k, 16))


def render(lang, groups, en, doc):
    lines = []
    lines.append("# 术语对照表（%s）" % lang_name(lang))
    lines.append("")
    lines.append("> 由 `src\\tools\\glossary.py` 生成，数据来自 `src\\translations\\%s.toml`。"
                 "改译文后重新生成，不要手改本文件。" % lang)
    lines.append("")
    for g in groups:
        ids = pick_ids(g, en)
        if not ids:
            continue
        lines.append("## %s（%d）" % (g["name"], len(ids)))
        lines.append("")
        if g.get("note"):
            lines.append(g["note"])
            lines.append("")
        lines.append("| English | %s | id |" % lang_name(lang))
        lines.append("|---|---|---|")
        for k in ids:
            e = en[k].replace("|", "\\|")
            z = doc.get(k, "").replace("|", "\\|")
            lines.append("| %s | %s | `%s` |" % (e, z, k))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成术语对照表")
    ap.add_argument("--lang", action="append", default=[],
                    help="语言代码，可重复；默认所有可编辑语言")
    ap.add_argument("--csv", action="store_true", help="同时导出 .csv")
    args = ap.parse_args()

    groups = load_terms()
    base = T.lang_path(T.BASE_LANG)
    if not os.path.isfile(base):
        raise SystemExit("找不到基准原文 %s" % base)
    en = load_table(base)

    langs = args.lang or T.target_langs()
    if not langs:
        raise SystemExit("translations\\ 下没有可编辑的译文")
    os.makedirs(GLOSSARY, exist_ok=True)

    for lang in langs:
        path = T.lang_path(lang)
        if not os.path.isfile(path):
            print("跳过 %s：没有 %s" % (lang, path))
            continue
        doc = load_table(path)
        text = render(lang, groups, en, doc)
        out = os.path.join(GLOSSARY, "%s.md" % lang)
        io.open(out, "w", encoding="utf-8", newline="\n").write(text)
        n = sum(len(pick_ids(g, en)) for g in groups)
        print("已生成 %s（%d 条）" % (out, n))

        if args.csv:
            cp = os.path.join(GLOSSARY, "%s.csv" % lang)
            with io.open(cp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["分组", "English", lang_name(lang), "id"])
                for g in groups:
                    for k in pick_ids(g, en):
                        w.writerow([g["name"], en[k], doc.get(k, ""), k])
            print("已生成 %s" % cp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
