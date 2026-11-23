# -*- coding: utf-8 -*-
"""zh_pipeline.py —— 中文「分词前」的排版步骤（连词、人名、数字/标记空格）。

这些步骤只加空格、不改字，属于中文特有，从 apply_zh_rules 拆出来放进这里，
这样 lang_rules/zh.py 的补空格策略（Spacing）可以直接调用，
而不必反向 import apply_zh_rules（那会形成循环）。

顺序由 `pre_space()` 固定：连词 → 人名 → 数字/破折号/<n><n>。
标点规范化不在这里——它属于标点接口，输入已经规范化过。
"""

import io
import os
import re

from text import zh_space
from text.lang_rules import base

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAG = zh_space.TAG
CONJ = ("因为", "所以", "但是", "如果", "虽然", "然后", "而且", "以及", "因此", "不过",
        "并且", "或者", "还是", "于是", "同时", "此外", "例如", "比如", "由于", "无论",
        "即使", "尽管", "然而", "可是", "因而", "从而", "况且", "何况", "假如", "要是",
        "一旦", "以便", "以免", "甚至", "反而", "否则", "不然", "总之", "也就是说")
SINGLE_CONJ = {"但": "是", "而": "是且也又在对就", "却": "是也又就",
               "并": "且不没未非能会已将无发", "或": "者是许", "因": "为此", "所": "以"}
PUNCT_CHARS = "，。！？；：、…—）)」』】》”’"
TITLES = ("先生", "爵士", "女士", "小姐", "夫人", "船长", "总督", "副王", "国王",
          "女王", "伯爵", "将军", "指挥官", "上校", "中尉", "少校", "神父", "医生")
SPACE = " \u3000"
SENT_END = "。！？…!?"

conj_re = re.compile(
    r"(?P<pre>[%s])(?P<gap>\s*)(?P<conj>%s|%s)(?P<next>[^\s%s<@%%])"
    % (re.escape(PUNCT_CHARS),
       "|".join(sorted(CONJ, key=len, reverse=True)),
       "|".join("%s(?![%s])" % (k, re.escape(v)) for k, v in SINGLE_CONJ.items()),
       re.escape(PUNCT_CHARS)))


def fix_conj(text):
    """标点后的连词补一个空格；「因 此」这类被切开的词粘回去。"""
    text = conj_re.sub(
        lambda m: m.group("pre") + m.group("gap") + m.group("conj") + " " + m.group("next"),
        text)
    return text.replace("因 此", "因此")


def load_list(name):
    path = os.path.join(TOOLS, "data", name)
    out = []
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line)
    return out


def build_names(doc):
    given = {v for h, v in doc.items() if h.startswith("0xfc51") and 1 <= len(v) <= 5}
    surn = {v for h, v in doc.items() if h.startswith("0xcf57") and 1 <= len(v) <= 6}
    extras = load_list("zh_names.txt")
    towns = load_list("zh_towns.txt")
    return given, surn, extras, towns


QUOTE_RX = re.compile(r"「[^」]*」|『[^』]*』|《[^》]*》")
_NAME_CACHE = {}


def _name_regexes(all_names):
    key = all_names if isinstance(all_names, frozenset) else frozenset(all_names)
    hit = _NAME_CACHE.get(key)
    if hit is not None:
        return hit

    bare = sorted((n for n in all_names if len(n) >= 3), key=len, reverse=True)
    bare_re = re.compile("|".join(map(re.escape, bare))) if bare else None

    names_alt = "|".join(map(re.escape, sorted(all_names, key=len, reverse=True)))
    titles_alt = "|".join(map(re.escape, sorted(TITLES, key=len, reverse=True)))
    titled_re = re.compile(
        "(%s)\\s*((?:[\\u4e00-\\u9fff]{1,3}世|\\d+世)(?:\\s*(?:%s))?|(?:%s))"
        % (names_alt, titles_alt, titles_alt))
    first_chars = frozenset(n[0] for n in all_names if n)
    _NAME_CACHE[key] = (bare_re, titled_re, first_chars)
    return bare_re, titled_re, first_chars


def find_names(text, given, surn, extras, all_names=None):
    # 音译分隔符已废止，名字在译文里就是空格分段；这里只按词表找整名，
    # 不再有「名·姓」那条正则（名单里的名字本身带空格，bare_re 直接匹配）。
    spans = []

    if all_names is None:
        all_names = set(given) | set(surn) | set(extras)
    bare_re, titled_re, first_chars = _name_regexes(all_names)
    if not first_chars.isdisjoint(text):
        if bare_re:
            spans.extend(m.span() for m in bare_re.finditer(text))
        spans.extend(m.span() for m in titled_re.finditer(text))

    # 引号里的通常是船名/书名，不按人名加空格。
    quotes = ([(m.start(), m.end()) for m in QUOTE_RX.finditer(text)]
              if ("「" in text or "『" in text or "《" in text) else [])

    def in_quote(s0, e0):
        return any(q0 <= s0 and e0 <= q1 for q0, q1 in quotes)

    spans = [(s0, e0) for s0, e0 in spans if not in_quote(s0, e0)]

    spans.sort(key=lambda x: (x[0], -x[1]))
    merged = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            if sp[1] > merged[-1][1]:
                merged[-1] = (merged[-1][0], sp[1])
            continue
        merged.append(sp)
    return merged


def pad_names(text, spans, towns=()):
    out, last = [], 0
    for start, end in spans:
        before = text[start - 1] if start > 0 else None
        after = text[end] if end < len(text) else None

        i = start - 1
        while i >= 0 and text[i] in SPACE:
            i -= 1
        at_start = (i < 0) or (text[i] in SENT_END)

        j = end
        while j < len(text) and text[j] in SPACE:
            j += 1
        at_end = (j >= len(text)) or (text[j] in SENT_END)

        need_before = (not at_start) and before is not None and before not in SPACE and before not in PUNCT_CHARS
        need_after = (not at_end) and after is not None and after not in SPACE and after not in PUNCT_CHARS
        if need_after and text[start:end] in towns and after in "的地得们等城人镇岛港":
            need_after = False

        out.append(text[last:start])
        if need_before:
            out.append(" ")
        out.append(re.sub(r"\s+", "", text[start:end]))
        if need_after:
            out.append(" ")
        last = end
    out.append(text[last:])
    return "".join(out)


def _is_han(ch):
    return ch and "\u4e00" <= ch <= "\u9fff"


SPLIT_RX = re.compile("(<n><n>|<[^>]*>|" + base.VAR.pattern + ")")


def space_tokens(text):
    """数字 / 破折号 / 省略号 / `<n><n>` 两侧补空格（标签与占位符内部不动）。

    这是唯一实现：以前 space_years / space_marks / space_dash / space_ellipsis /
    space_before_double_break 五个名字指向同一件事，合并成这一个。
    """
    out = []
    for part in SPLIT_RX.split(text):
        if part == "<n><n>":
            if out and not out[-1].endswith(" "):
                out.append(" ")
            out.append(part)
            continue
        if not part:
            continue
        if part[0] in "<@" or (part.startswith("%") and len(part) <= 6):
            out.append(part)
            continue

        seg = part

        def year_repl(m):
            s0 = m.group(0)
            left = seg[m.start() - 1] if m.start() > 0 else ""
            right = seg[m.end()] if m.end() < len(seg) else ""
            pre = " " if _is_han(left) else ""
            post = " " if _is_han(right) else ""
            return pre + s0 + post

        seg = re.sub(r"(?<!\d)\d{4}(?!\d)", year_repl, seg)

        def mark_repl(m):
            mark = m.group(0).strip()
            pre = " " if m.start() > 0 and seg[m.start() - 1] not in " \n" else ""
            post = "" if m.end() >= len(seg) or seg[m.end()] in " \n" else " "
            return pre + mark + post

        out.append(re.sub(r" *—— *| *…… *", mark_repl, seg))
    result = "".join(out)
    # <n><n> 两端都留空格（出现在段中也一样）。
    result = re.sub(r" *<n><n> *", " <n><n> ", result)
    return result.strip()


def collapse_spaces(text):
    if "  " not in text:
        return text
    return re.sub(r" {2,}", " ", text)


def make_name_tables(doc):
    """把 build_names 的结果整理成 find_names/pad_names 需要的样子。"""
    given, surn, extras, towns = build_names(doc)
    return {"given": given, "surn": surn, "extras": extras, "towns": towns,
            "all": frozenset(set(given) | set(surn) | set(extras) | set(towns))}


def pre_space(text, names):
    """分词前的三步：连词 → 人名 → 数字/破折号/<n><n>。

    返回 `(新文本, {"conj": 是否改了, "name": 是否改了})`，供统计与 CLI 展示。
    """
    a = fix_conj(text)
    parts = TAG.split(a)
    res = []
    for i, part in enumerate(parts):
        if i % 2 == 1 or not part:
            res.append(part)
            continue
        spans = find_names(part, names["given"], names["surn"],
                           names["extras"] + names["towns"], names["all"])
        res.append(pad_names(part, spans, names["towns"]) if spans else part)
    b = "".join(res)
    c = space_tokens(b)
    # 统计口径沿用旧版：name 一档包含「人名 + 数字/破折号/<n><n>」，
    # 否则 CLI 打印的「人名」会和历史记录对不上。
    return c, {"conj": int(a != text), "name": int(c != a)}
