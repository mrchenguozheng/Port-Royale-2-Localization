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
    if head[0] in zh_space.PUNCT_CHARS and head[0] not in zh_space.LINE_HEAD_OK:
        return True
    if tail[-1] in zh_space.OPEN:
        return True
    return False


def word_breaks(text, out, lookup):
    """数这一条里「断在两个汉字之间、但那里不是词边界」的刀口。

    `_cut_cost()` 只认字表（的/了/都…），看不见「某 些」「可 以」这种把词劈开
    的刀口；这里拿分词器的词界当尺子：先按 `<n>` 分段对齐，再把成品按汉字
    序号回填到原文，检查每个空格是不是落在词界上。
    """
    import re
    han = re.compile(r"[\u4e00-\u9fff]")
    cuts = mid = 0
    a_segs = re.split(r"<n[^>]*>", text)
    b_segs = re.split(r"<n[^>]*>", out)
    for a, b in zip(a_segs, b_segs):
        b0 = b.replace(" ", "")
        if a != b0:
            continue
        bounds = set()
        for m in re.finditer(r"[\u4e00-\u9fff]+", a):
            run, base = m.group(0), m.start()
            pos = 0
            for w in lookup(run):
                pos += len(w)
                if pos < len(run):
                    bounds.add(base + pos)
        idx = 0
        for i, ch in enumerate(b):
            if ch == " ":
                if i and i + 1 < len(b) and han.match(b[i - 1]) and han.match(b[i + 1]):
                    cuts += 1
                    if idx not in bounds:
                        mid += 1
            else:
                idx += 1
    return cuts, mid


def _segments(text):
    """按 `<n>` 切段（段号用于和原文对齐）。"""
    import re
    return re.split(r"<n[^>]*>", text)


def token_spans(text):
    """[(段号, 段内非空白字位置, token), …]，位置用来判断这个空格是不是新插的。"""
    out = []
    for si, seg in enumerate(_segments(text)):
        ns = 0
        for t in seg.split(" "):
            if t:
                out.append((si, ns, t))
                ns += len(t)
    return out


def source_gaps(text):
    """原文里本来就有的空格：{(段号, 前面已有多少非空白字)}。"""
    gaps = set()
    for si, seg in enumerate(_segments(text)):
        ns = 0
        for ch in seg:
            if ch == " ":
                gaps.add((si, ns))
            elif ch not in "\r\n":
                ns += 1
    return gaps


def collect(label, texts, outputs, lookup):
    """一批成品串 → 一行统计。`label` 是预算或「粗:细」组合。

    `bad` 只数**我们插进去**的刀口：原文自带的中西文空隙（「在 18 世纪」）不是
    排版决定，算进来会把读数抬高。
    """
    lens, cuts, bad, with_space, narrow, longest, mid = [], 0, 0, 0, 0, 0, 0
    for text, out in zip(texts, outputs):
        toks = tokens_of(out)
        if len(toks) > 1:
            with_space += 1
        cuts += max(0, len(toks) - 1)
        spans = token_spans(out)
        gaps = source_gaps(text)
        for i, (si, ns, tok) in enumerate(spans):
            n_han = HAN(tok)
            lens.append(n_han)
            narrow += int(n_han > NARROW)
            longest = max(longest, n_han)
            if i and (si, ns) not in gaps:
                bad += int(cut_is_bad(spans[i - 1][2], tok))
        _c, m = word_breaks(text, out, lookup)
        mid += m
    lens.sort()
    n = len(lens) or 1
    return {
        "label": label,
        "tokens": len(lens),
        "cuts": cuts,
        "cuts_per_str": cuts / with_space if with_space else 0,
        "with_space": with_space,
        "mean": sum(lens) / n,
        "median": statistics.median(lens) if lens else 0,
        "p90": lens[int(len(lens) * 0.90)] if lens else 0,
        "p99": lens[min(len(lens) - 1, int(len(lens) * 0.99))] if lens else 0,
        "le2": sum(1 for x in lens if x <= 2) / n,
        "one": sum(1 for x in lens if x <= 1) / n,
        "narrow": narrow / n,
        "longest": longest,
        "bad": bad,
        "bad_rate": bad / cuts if cuts else 0,
        "mid": mid,
        "mid_rate": mid / cuts if cuts else 0,
        "hist": lens,
    }


def sweep(texts, lookup, budgets):
    rows = []
    for mc in budgets:
        outs = [zh_space.compact(t, lookup, mc) if t else "" for t in texts]
        rows.append(collect(str(mc), texts, outs, lookup))
    return rows


def two_pass(texts, lookup, pairs):
    """粗档先断一次，再拿细档断第二次。两种做法都跑一遍。

    `local`：把粗档的 token 单独拎出来，对超细档的那个再 `compact()` 一次。
             简单，但 token 离开句子上下文，分词器会改主意（实测切出
             「某 些」「可 以」）。
    `pin`  ：把粗档的断点写成切断标签，再拿细档跑一遍 `compact()`。上下文
             还在，第二遍只是在既有断点之间补刀。

    另外别写 `compact(compact(t, X), Y)`：`compact()` 每次都会先抹掉汉字/
    全角标点旁的空白（`_TIGHT_SPACE`），第二遍等于从零重排，数字和单遍 `Y`
    一模一样，看不出任何分层。
    """
    import re
    rows = []
    for coarse, fine in pairs:
        local, pinned = [], []
        for t in texts:
            if not t:
                local.append("")
                pinned.append("")
                continue
            first = zh_space.compact(t, lookup, coarse)
            pieces = []
            for tok in tokens_of(first):
                if HAN(tok) > fine:
                    pieces.extend(tokens_of(zh_space.compact(tok, lookup, fine)))
                else:
                    pieces.append(tok)
            local.append(" ".join(pieces))
            glued = re.sub("(?<=[\u4e00-\u9fff])\\s(?=[\u4e00-\u9fff])",
                           zh_space.CUT_TAG, first)
            pinned.append(zh_space.compact(glued, lookup, fine))
        rows.append(collect("%d:%d-local" % (coarse, fine), texts, local, lookup))
        rows.append(collect("%d:%d-pin" % (coarse, fine), texts, pinned, lookup))
    return rows


#: 「窄控件风险」参考宽度：token 超过这么多汉字，就塞不进一行十来字的提示框。
#: 这只是给对比用的整数门槛，不是游戏里量出来的控件宽度。
NARROW = 12


def table(rows):
    head = ("档位", "token", "空格数", "每条", "均长", "中位", "p90",
            "≤2字", "单字", ">12字", "最长", "坏断", "词内", "词内率", "坏断率")
    print("%-13s %6s %7s %6s %6s %6s %5s %7s %7s %7s %4s %6s %6s %7s %7s" % head)
    for r in rows:
        print("%-13s %6d %7d %6.1f %6.2f %6.1f %5d %6.1f%% %6.1f%% %6.1f%% %4d %6d %6d %6.1f%% %6.1f%%" % (
            r["label"], r["tokens"], r["cuts"], r["cuts_per_str"],
            r["mean"], r["median"], r["p90"],
            r["le2"] * 100, r["one"] * 100, r["narrow"] * 100, r["longest"],
            r["bad"], r["mid"], r["mid_rate"] * 100, r["bad_rate"] * 100))


def hist(rows, budgets):
    for r in rows:
        if r["label"] not in budgets and str(r["label"]) not in budgets:
            continue
        lens = r["hist"]
        print("\n档位 %s（token %d）" % (r["label"], len(lens)))
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
    ap.add_argument("--two", nargs="*", default=[], metavar="粗:细",
                    help="二次切断：先按粗档断一次，再按细档在成品上断第二次")
    ap.add_argument("--hist", nargs="*", default=[],
                    help="额外打印这些档位的 token 长度分布")
    a = ap.parse_args()

    order, out, lookup = raw_texts(a.lang)
    if lookup is None:
        raise SystemExit("没有分词器（spaCy），扫描没有意义")
    texts = [out[h] for h in order if out.get(h)]
    print("译文 %d 条\n" % len(texts))
    rows = sweep(texts, lookup, a.budgets)
    pairs = []
    for item in a.two:
        coarse, fine = item.split(":")
        pairs.append((int(coarse), int(fine)))
    rows += two_pass(texts, lookup, pairs)
    table(rows)
    if a.hist:
        hist(rows, set(a.hist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
