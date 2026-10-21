# -*- coding: utf-8 -*-
"""zh_dep_space.py —— 用依存句法给中文长段落补空格（可选步骤，默认关闭）。

规则（保守版）：
  · 只处理**段落长度 ≥ --min-chars（默认 60 字）** 的片段；
  · 只在「长主语（nsubj，≥ --min-nsubj 字）↔ 谓语动词」的边界补一个空格；
  · 标点旁、已有空格处不补；
  · 处理前后校验标签/占位符序列，不一致就报错退出。

它需要 spaCy（Python 3.11/3.12 的 .venv-spacy），所以单独成一个脚本：
apply_patch.py --dep 时会用 PR2_SPACY_PYTHON（或 .venv-spacy）来调它。

用法：
    python src/tools/zh_dep_space.py --dry-run      # 出 CSV + 抽样
    python src/tools/zh_dep_space.py --apply        # 写回 zh.toml
"""

import argparse
import csv
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
PUNCT = "，。！？、：；…—（）()「」『』【】《》"
NSUBJ_MIN = 6


def spacy_python():
    explicit = os.environ.get("PR2_SPACY_PYTHON")
    if explicit:
        return explicit
    local = os.path.join(ROOT, ".venv-spacy", "Scripts", "python.exe")
    return local if os.path.isfile(local) else ""


def cuts_for(text, nlp, min_nsubj):
    """返回需要补空格的位置集合。"""
    doc = nlp(text)
    cuts = set()
    for t in doc:
        if t.pos_ != "VERB":
            continue
        for c in t.children:
            if c.dep_ != "nsubj":
                continue
            sub = list(c.subtree)
            lo = min(x.idx for x in sub)
            hi = max(x.idx + len(x.text) for x in sub)
            if len(re.findall(r"[\u4e00-\u9fff]", text[lo:hi])) < min_nsubj:
                continue
            cut = hi if hi <= t.idx else lo
            if not (0 < cut < len(text)):
                continue
            # 断点右边那个词不能是名词/形容词这类「还在短语里」的成分，
            # 否则会把「大片|陆地」这种名词短语切开。
            nxt = next((x for x in doc if x.idx == cut), None)
            prev = next((x for x in doc if x.idx + len(x.text) == cut), None)
            if hi <= t.idx:
                if nxt is None or nxt.pos_ in ("NOUN", "PROPN", "NUM", "ADJ", "DET", "PART"):
                    continue
            else:
                if prev is None or prev.pos_ in ("NOUN", "PROPN", "NUM", "ADJ", "DET"):
                    continue
            cuts.add(cut)
    return cuts


def apply_cuts(text, cuts):
    out, last, added = [], 0, 0
    for cut in sorted(cuts):
        before = text[cut - 1]
        after = text[cut] if cut < len(text) else ""
        if before == " " or after == " " or before in PUNCT or after in PUNCT:
            continue
        out.append(text[last:cut])
        out.append(" ")
        last = cut
        added += 1
    out.append(text[last:])
    return "".join(out), added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--min-chars", type=int, default=60)
    ap.add_argument("--min-nsubj", type=int, default=NSUBJ_MIN)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--samples", type=int, default=30)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    try:
        import spacy
    except ImportError:
        sys.exit("需要 spaCy：用 .venv-spacy 里的 python 运行"
                 "（或设 PR2_SPACY_PYTHON 指向它）。")
    nlp = spacy.load("zh_core_web_sm")

    path = os.path.join(ROOT, "src", "translations", "%s.toml" % args.lang)
    doc = tomllib.load(open(path, "rb"))
    ids = [m.group(1) for m in
           (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(path, encoding="utf-8")) if m]

    head = []
    for ln in io.open(path, encoding="utf-8"):
        if ln.startswith("#"):
            head.append(ln.rstrip("\n"))
        else:
            break

    rows, total = [], 0
    for k in ids:
        text = doc[k]
        parts = TAG.split(text)
        new_parts, added = [], 0
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:
                new_parts.append(part)
                continue
            if len(re.findall(r"[\u4e00-\u9fff]", part)) < args.min_chars:
                new_parts.append(part)
                continue
            new, n = apply_cuts(part, cuts_for(part, nlp, args.min_nsubj))
            added += n
            new_parts.append(new)
        new = "".join(new_parts)
        if new != text:
            if TAG.findall(new) != TAG.findall(text):
                sys.exit("[中止] %s 的标签/占位符序列被改动" % k)
            total += added
            rows.append((k, text, new))

    print("段落 ≥%d 字：改动 %d 条，补 %d 个空格" % (args.min_chars, len(rows), total))
    out = args.out or os.path.join(ROOT, "docs", "zh-dep-space.csv")
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["hash", "old", "new"])
        wr.writerows(rows)
    print("明细:", out)

    for h, old, new in rows[:args.samples]:
        print("\n%s\n 原: %s\n 新: %s" % (h, old[:110], new[:110]))

    if not (args.apply or args.apply):
        return
    for h, _old, new in rows:
        doc[h] = new

    def esc(t):
        return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        "\n".join(head + ['"%s" = "%s"' % (k, esc(doc[k])) for k in ids]) + "\n")
    print("已写回", path)


if __name__ == "__main__":
    main()
