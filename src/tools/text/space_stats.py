# -*- coding: utf-8 -*-
"""space_stats.py —— 中文补空格预算的统计扫描。

预算（`zh_space.MAX_CHARS`）到底取多少，历史上全是猜的：9 是照着「读着碎」的感觉
降下来的，12 是拿编年史提示那条在窄框里数行数定的，15 是「少断几刀」的直觉。
这个工具把**文本侧**的后果摊开：给定一批预算，在同一份译文上重跑 `compact()`，
统计切多碎、断点有多不自然，看边际收益在哪一档开始消失。

它不量控件、不碰像素：控件宽度没在游戏里实测过（见 docs/翻译局限.md）。
能给的只有「文本被切成什么样」，最后那一步还得进游戏看。

用法
----
    python -X utf8 src/tools/text/space_stats.py                 # 扫 6~20
    python -X utf8 src/tools/text/space_stats.py --budgets 9 12 15 18
    python -X utf8 src/tools/text/space_stats.py --hist 9 12 15 18
"""

import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(TOOLS))

from text import lang_rules, marks, toml_io, zh_space  # noqa: E402
from text.lang_rules import spec as specs  # noqa: E402
from text.lang_rules import zh as zh_rules  # noqa: E402

HAN = lambda s: sum(1 for c in s if "\u4e00" <= c <= "\u9fff")  # noqa: E731


class _NoSpace(zh_rules.ZhCompactSpacing):
    """只走到「分词前」：返回不带任何补空格的引擎文本，做扫描的输入。"""

    def apply(self, text, ctx):
        return text


def raw_texts(lang):
    """读出<lang>的引擎文本，但不补空格；顺带把分词表带回来。"""
    import translate as T
    path = T.lang_path(lang)
    doc, order = toml_io.read_doc(path)
    plain = marks.expand_doc(lang, doc)
    spec = lang_rules.get_spec(lang)
    spaced = _NoSpace()
    probe = specs.LangSpec(code=spec.code, punct=spec.punct,
                           segmenter=spec.segmenter, spacing=spaced)
    out, _stats, _seg = specs.build_texts(probe, plain, order)
    return order, out, spaced.lookup


def tokens_of(text):
    """按 `<n>` 切段，段内按空格切 token。"""
    import re
    toks = []
    for seg in re.split(r"<n[^>]*>", text):
        toks.extend(t for t in seg.split(" ") if t)
    return toks


def cut_is_bad(tail, head):
    """断点是否落在「明显不该断」的位置：只看两侧的字，和 `_cut_cost()` 同口径。"""
    if not tail or not head:
        return False
    if head[0] in zh_space.STICKY or head[0] in zh_space.CONJ:
        return True
    if tail[-1] in zh_space.LEAD:
        return True
    if head[0] in zh_space.PUNCT_CHARS:
        return True
    if tail[-1] in zh_space.OPEN:
        return True
    return False


def sweep(texts, lookup, budgets):
    rows = []
    for mc in budgets:
        lens, cuts, bad, with_space, narrow = [], 0, 0, 0, 0
        for t in texts:
            if not t:
                continue
            out = zh_space.compact(t, lookup, mc)
            toks = tokens_of(out)
            if len(toks) > 1:
                with_space += 1
            cuts += max(0, len(toks) - 1)
            for i, tok in enumerate(toks):
                n_han = HAN(tok)
                lens.append(n_han)
                narrow += int(n_han > NARROW)
                if i:
                    bad += int(cut_is_bad(toks[i - 1], tok))
        lens.sort()
        n = len(lens)
        rows.append({
            "mc": mc,
            "tokens": n,
            "cuts": cuts,
            "cuts_per_str": cuts / with_space if with_space else 0,
            "with_space": with_space,
            "mean": sum(lens) / n,
            "median": statistics.median(lens),
            "p90": lens[int(n * 0.90)],
            "p99": lens[min(n - 1, int(n * 0.99))],
            "le2": sum(1 for x in lens if x <= 2) / n,
            "one": sum(1 for x in lens if x <= 1) / n,
            "narrow": narrow / n,
            "bad": bad,
            "bad_rate": bad / cuts if cuts else 0,
            "hist": lens,
        })
    return rows


#: 「窄控件风险」参考宽度：token 超过这么多汉字，就塞不进一行十来字的提示框。
#: 这只是给对比用的整数门槛，不是游戏里量出来的控件宽度。
NARROW = 12


def table(rows):
    head = ("预算", "token", "断开条", "空格数", "每条", "均长", "中位",
            "p90", "p99", "≤2字", "单字", ">12字", "坏断", "坏断率")
    print("%-4s %6s %7s %7s %6s %6s %6s %5s %5s %7s %7s %7s %6s %7s" % head)
    for r in rows:
        print("%-4d %6d %7d %7d %6.1f %6.2f %6.1f %5d %5d %6.1f%% %6.1f%% %6.1f%% %6d %6.1f%%" % (
            r["mc"], r["tokens"], r["with_space"], r["cuts"], r["cuts_per_str"],
            r["mean"], r["median"], r["p90"], r["p99"],
            r["le2"] * 100, r["one"] * 100, r["narrow"] * 100, r["bad"],
            r["bad_rate"] * 100))


def hist(rows, budgets):
    for r in rows:
        if r["mc"] not in budgets:
            continue
        lens = r["hist"]
        print("\n预算 %d（token %d）" % (r["mc"], len(lens)))
        for lo, hi in ((1, 1), (2, 2), (3, 4), (5, 6), (7, 8), (9, 10),
                       (11, 12), (13, 14), (15, 16), (17, 99)):
            c = sum(1 for x in lens if lo <= x <= hi)
            bar = "#" * int(c / max(1, len(lens)) * 120)
            print("  %2d-%-3d %6d %5.1f%% %s" % (lo, hi, c, c / len(lens) * 100, bar))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--budgets", type=int, nargs="*",
                    default=list(range(6, 21)))
    ap.add_argument("--hist", type=int, nargs="*", default=[],
                    help="额外打印这些预算的 token 长度分布")
    a = ap.parse_args()

    order, out, lookup = raw_texts(a.lang)
    if lookup is None:
        raise SystemExit("没有分词器（spaCy），扫描没有意义")
    texts = [out[h] for h in order if out.get(h)]
    print("译文 %d 条｜预算 %s～%s\n" % (len(texts), min(a.budgets), max(a.budgets)))
    rows = sweep(texts, lookup, a.budgets)
    table(rows)
    if a.hist:
        hist(rows, set(a.hist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
