#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glossary.py —— 从现有译文生成「术语对照表」。

为什么单独做一份
----------------
游戏里的专有名词（货物、船只、军衔、城镇……）散在 3500 多条文本里，
翻的时候很难保证前后一致。这份表把它们按组抽出来，英文、中文（以及可选
的其它语言）并排，既能当翻译参考，也能当校对清单。

**生成物不进仓库**：表是从 terms.toml + translations\\ 现算出来的，
改了译文重新跑一次就同步；提交进 git 只会多一份会过期的副本。
默认写到 build\\glossary\\（和语言包、字体一样属于产物）。

数据从哪来
----------
术语清单在 ``glossary\\terms.toml``（分组 + id 区间/列表），译文本身
不另存，每次生成都从 ``src\\translations\\`` 现取。

用法
----
    python src\\tools\\glossary.py                     # 中文表（自动带法语对照列）
    python src\\tools\\glossary.py --lang zh --with fr.gog_1.1.2.42
    python src\\tools\\glossary.py --csv                # 另存 csv（Excel 用）
    python src\\tools\\glossary.py --out D:\\out         # 换个输出目录

同名条目
--------
英文里有些词是多义的：`May` 可以是月份，也可以是人名/船名；`Jan` 既是
一月，也是人名「扬」。生成时会顺带列出**英文相同、但不在本组**的其它
条目，提醒「别把这句里的 May 当成月份」。
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
OUT_DIR = os.path.join(ROOT, "build", "glossary")

sys.path.insert(0, HERE)
import translate as T          # 复用语言列表与基准文件，别再抄一份规则

#: 表头里用的语言显示名（代码 -> 中文名），以后加语言在这里补一行。
LANG_NAMES = {"zh": "中文", "ja": "日本語", "fr": "法语", "test_en": "English",
              "en.gog_1.1.2.3": "English", "fr.gog_1.1.2.42": "法语（原版）"}


def lang_name(code):
    return LANG_NAMES.get(code, code)


def load_table(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_terms():
    if not os.path.isfile(TERMS):
        raise SystemExit("找不到 %s" % TERMS)
    return load_table(TERMS).get("group", [])


def pick_ids(group, en):
    """一组术语对应的 id 列表（按 id 排序）。"""
    if "range" in group:
        lo, hi = (int(x, 16) for x in group["range"])
        ids = [k for k in en if lo <= int(k, 16) <= hi]
    else:
        ids = [k.lower() for k in group.get("ids", [])]
        ids = [k for k in ids if k in en]
    top = group.get("max_len", 40)
    ids = [k for k in ids if len(en.get(k, "")) <= top]
    return sorted(ids, key=lambda k: int(k, 16))


def same_named(en, own, doc):
    """英文相同、但**译文不同**的其它条目：{id: [其它 id…]}。

    只列译文不一样的：`Captain` 有四个条目都译成「船长」，那不是歧义；
    `Jan` 一条译「1月」、一条译「扬」，才是要提醒的多义词。
    """
    by_text = {}
    for k, v in en.items():
        by_text.setdefault(v.strip().lower(), []).append(k)
    out = {}
    for k in own:
        mine = (doc.get(k, "") or "").strip()
        others = [x for x in by_text.get(en[k].strip().lower(), [])
                  if x != k and (doc.get(x, "") or "").strip() != mine]
        if others:
            out[k] = sorted(others, key=lambda x: int(x, 16))
    return out


def cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render(target, target_doc, groups, en, others):
    """others: [(label, doc)] —— 除英文和目标语言之外要并排的列。"""
    lines = []
    lines.append("# 术语对照表（%s）" % lang_name(target))
    lines.append("")
    srcs = ["`src\\translations\\%s.toml`" % target]
    srcs += ["`src\\references\\%s.toml`" % c for c, _l, _d in others]
    lines.append("> 由 `src\\tools\\glossary.py` 生成，数据来自 %s。"
                 "改译文后重新生成，不要手改本文件。" % "、".join(srcs))
    lines.append("")

    head = ["English"] + [label for _c, label, _d in others] + [lang_name(target), "id"]
    for g in groups:
        ids = pick_ids(g, en)
        if not ids:
            continue
        lines.append("## %s（%d）" % (g["name"], len(ids)))
        lines.append("")
        if g.get("note"):
            lines.append(g["note"])
            lines.append("")
        lines.append("| " + " | ".join(head) + " |")
        lines.append("|" + "---|" * len(head))
        for k in ids:
            row = [cell(en[k])]
            row += [cell(doc.get(k, "")) or "（无）" for _c, _label, doc in others]
            row += [cell(target_doc.get(k, "")), "`%s`" % k]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        dup = same_named(en, ids, target_doc)
        if dup:
            lines.append("**同名条目**（英文相同，可能不是这个意思）：")
            lines.append("")
            for k in ids:
                if k not in dup:
                    continue
                items = "、".join(
                    "`%s` %s" % (x, cell(target_doc.get(x, "")) or "（未译）")
                    for x in dup[k])
                lines.append("- `%s`：本组是 `%s` %s；另有 %s"
                             % (en[k].strip(), k, cell(target_doc.get(k, "")), items))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成术语对照表")
    ap.add_argument("--lang", action="append", default=[],
                    help="语言代码，可重复；默认所有可编辑语言")
    ap.add_argument("--with", dest="extra", action="append", default=[],
                    help="并排对照的其它语言（默认带 references 里的法文原本）")
    ap.add_argument("--csv", action="store_true", help="同时导出 .csv")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录（默认 build\\glossary）")
    args = ap.parse_args()

    groups = load_terms()
    base = T.lang_path(T.BASE_LANG)
    if not os.path.isfile(base):
        raise SystemExit("找不到基准原文 %s" % base)
    en = load_table(base)

    langs = args.lang or T.target_langs()
    if not langs:
        raise SystemExit("translations\\ 下没有可编辑的译文")

    extra_codes = args.extra or [c for c in T.REFERENCE_LANGS
                                 if c != T.BASE_LANG and os.path.isfile(T.lang_path(c))]
    others = []
    for c in extra_codes:
        p = T.lang_path(c)
        if os.path.isfile(p):
            others.append((c, lang_name(c), load_table(p)))
        else:
            print("跳过对照列 %s：没有 %s" % (c, p))

    os.makedirs(args.out, exist_ok=True)
    for lang in langs:
        path = T.lang_path(lang)
        if not os.path.isfile(path):
            print("跳过 %s：没有 %s" % (lang, path))
            continue
        doc = load_table(path)
        text = render(lang, doc, groups, en, others)
        out = os.path.join(args.out, "%s.md" % lang)
        io.open(out, "w", encoding="utf-8", newline="\n").write(text)
        n = sum(len(pick_ids(g, en)) for g in groups)
        print("已生成 %s（%d 条）" % (out, n))

        if args.csv:
            cp = os.path.join(args.out, "%s.csv" % lang)
            with io.open(cp, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["分组", "English"] + [label for _c, label, _d in others]
                           + [lang_name(lang), "id"])
                for g in groups:
                    for k in pick_ids(g, en):
                        w.writerow([g["name"], en[k]]
                                   + [d.get(k, "") for _c, _l, d in others]
                                   + [doc.get(k, ""), k])
            print("已生成 %s" % cp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
