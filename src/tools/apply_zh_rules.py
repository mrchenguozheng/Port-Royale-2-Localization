# -*- coding: utf-8 -*-
"""apply_zh_rules.py —— 从 orig/zh.gog_1.1.2.3.toml 生成 src/live/zh.toml。

工作流变了：
  · 以后**只改** orig/zh.gog_1.1.2.3.toml（不带任何为引擎服务的人为空格）；
  · 本脚本按规则生成上一层的 zh.toml：
      1. 标点与占位符：全角化、单标点后空格、成对标点外侧空格；
      2. 连词：标点后的连词后面补一个空格（不在句末才补）；
      3. 人名：名・姓两侧按「句首只补后 / 句末不补 / 句中缺哪补哪」补空格；
  · 再跑 apply_patch / compile_pack 构建。

用法：
    python src/tools/apply_zh_rules.py            # 生成并写回
    python src/tools/apply_zh_rules.py --dry-run  # 只统计
"""

import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import lang_rules  # noqa: E402

SRC = os.path.join(ROOT, "src", "seed", "zh.toml")
DST = os.path.join(ROOT, "src", "live", "zh.toml")

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
CONJ = ("因为", "所以", "但是", "如果", "虽然", "然后", "而且", "以及", "因此", "不过",
        "并且", "或者", "还是", "于是", "同时", "此外", "例如", "比如", "由于", "无论",
        "即使", "尽管", "然而", "可是", "因而", "从而", "况且", "何况", "假如", "要是",
        "一旦", "以便", "以免", "甚至", "反而", "否则", "不然", "总之", "也就是说")
SINGLE_CONJ = {"但": "是", "而": "是且也又在对就", "却": "是也又就",
               "并": "且不没未非能会已将无发", "或": "者是许", "因": "为此", "所": "以"}
PUNCT_CHARS = "，。！？；：、…—）)」』】》”’·"
TITLES = ("先生", "爵士", "女士", "小姐", "夫人", "船长", "总督", "副王", "国王",
          "女王", "伯爵", "将军", "指挥官", "上校", "中尉", "少校", "神父", "医生")
NAME_STOP = "的了他是在和与也就都但而或又着过们吗呢吧啊呀哦嗯，。！？、；：…—（）()「」『』【】《》 \u3000<@%"
SPACE = " \u3000"
SENT_END = "。！？…!?"

conj_re = re.compile(
    r"(?P<pre>[%s])(?P<gap>\s*)(?P<conj>%s|%s)(?P<next>[^\s%s<@%%])"
    % (re.escape(PUNCT_CHARS),
       "|".join(sorted(CONJ, key=len, reverse=True)),
       "|".join("%s(?![%s])" % (k, re.escape(v)) for k, v in SINGLE_CONJ.items()),
       re.escape(PUNCT_CHARS)))


def fix_conj(text):
    text = conj_re.sub(
        lambda m: m.group("pre") + m.group("gap") + m.group("conj") + " " + m.group("next"),
        text)
    return text.replace("因 此", "因此")


def load_list(name):
    path = os.path.join(HERE, name)
    out = []
    if os.path.isfile(path):
        for line in io.open(path, encoding="utf-8"):
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


name_re = None


_NAME_CACHE = {}


def _name_regexes(all_names):
    key = frozenset(all_names)
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
    _NAME_CACHE[key] = (bare_re, titled_re)
    return bare_re, titled_re


def find_names(text, given, surn, extras):
    global name_re
    if name_re is None:
        name_re = re.compile(
            "(%s)\u00b7([\\u4e00-\\u9fff]{1,6}?)(?=[%s]|%s|$)"
            % ("|".join(map(re.escape, sorted(given, key=len, reverse=True))),
               re.escape(NAME_STOP), "|".join(map(re.escape, TITLES))))
    spans = [(m.start(), m.end()) for m in name_re.finditer(text)]

    all_names = set(given) | set(surn) | set(extras)
    bare_re, titled_re = _name_regexes(all_names)
    if bare_re:
        spans.extend(m.span() for m in bare_re.finditer(text))
    spans.extend(m.span() for m in titled_re.finditer(text))

    # 引号里的通常是船名/书名，不按人名加空格。
    quotes = [(m.start(), m.end()) for m in
              re.finditer(r"「[^」]*」|『[^』]*』|《[^》]*》", text)]

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


CJK = r"\u4e00-\u9fff"
FW = "，。！？、：；…「」『』（）［］【】〈〉〔〕“”‘’"
PLACE = r"(?:@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])"


def strip_padding(text):
    """把「为引擎补的空格」去掉，回到干净译文（写回文本源时用）。"""
    if not re.search("[%s]" % CJK, text):
        return text
    cjk = "[%s]" % CJK
    fw = "[%s]" % re.escape(FW)
    text = re.sub(r"(%s)\s+(?=%s)" % (cjk, cjk), r"\1", text)
    text = re.sub(r"(%s)\s+(?=%s)" % (cjk, fw), r"\1", text)
    text = re.sub(r"(%s)\s+(?=%s)" % (fw, cjk), r"\1", text)
    text = re.sub(r"(%s)\s+(?=%s)" % (cjk, PLACE), r"\1", text)
    text = re.sub(r"(%s)\s+(?=%s)" % (PLACE, cjk), r"\1", text)
    text = re.sub(r"(%s)\s+(?=%s)" % (PLACE, fw), r"\1", text)
    return text.strip()


def esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _is_han(ch):
    return ch and "\u4e00" <= ch <= "\u9fff"


SPLIT_RX = re.compile(r"(<n><n>|<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")


def space_tokens(text):
    """一次扫描：4 位年份、——、…… 补空格，<n><n> 前补空格。"""
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
    return "".join(out)


def space_years(text):
    """4 位年份与相邻汉字之间补空格（标签/占位符内部不动）。"""
    parts = TAG.split(text)
    for i in range(0, len(parts), 2):
        seg = parts[i]

        def repl(m):
            s0 = m.group(0)
            left = seg[m.start() - 1] if m.start() > 0 else ""
            right = seg[m.end()] if m.end() < len(seg) else ""
            pre = " " if _is_han(left) else ""
            post = " " if _is_han(right) else ""
            return pre + s0 + post

        parts[i] = re.sub(r"(?<!\d)\d{4}(?!\d)", repl, seg)
    return "".join(parts)


def space_marks(text):
    """——、…… 前后加空格；<n><n> 前加空格。"""
    marks = {"——", "……", "<n><n>"}

    def repl(m):
        mark = m.group(0).strip()
        before_only = mark == "<n><n>"
        pre = " " if m.start() > 0 and text[m.start() - 1] not in " \n" else ""
        post = "" if before_only or m.end() >= len(text) or text[m.end()] in " \n" else " "
        return pre + mark + post

    return re.sub(r" *—— *| *…… *|<n><n>", repl, text)


def space_dash(text):
    return space_marks(text)


def soft_wrap(text, limit=16, step=12):
    """超长且没有空格的汉字串，按约 12 字简单断开。"""
    particles = set("的了是在和与而或也就都但并且时后中上下里外为以于对把被将从到着过们吗呢吧啊呀哦嗯")

    def split_run(run):
        out, s0 = [], run
        while len(s0) > step:
            cut = step
            for k in range(step, max(5, step // 2), -1):
                if s0[k - 1] in particles:
                    cut = k
                    break
            out.append(s0[:cut])
            s0 = s0[cut:]
        out.append(s0)
        return " ".join(out)

    return re.sub(r"[\u4e00-\u9fff]{%d,}" % limit,
                  lambda m: split_run(m.group(0)), text)


def join_words(text):
    """不该断开的常用词：因此。"""
    return re.sub(r"因\s+此", "因此", text)


def space_ellipsis(text):
    return space_marks(text)


def space_before_double_break(text):
    return space_marks(text)


def collapse_spaces(text):
    return re.sub(r" {2,}", " ", text)


def generate():
    """按规则生成 {id: 文本}，不写文件。"""
    doc = tomllib.load(open(SRC, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(SRC, encoding="utf-8"))
             if m]

    zh_rules = lang_rules.get("zh")
    given, surn, extras, towns = build_names(doc)

    out, stats = {}, {"punct": 0, "conj": 0, "name": 0}
    for h in order:
        text = doc[h]
        if not text:
            out[h] = text
            continue
        a = zh_rules.normalize(text)
        b = fix_conj(a)
        parts = TAG.split(b)
        res = []
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:
                res.append(part)
                continue
            spans = find_names(part, given, surn, extras + towns)
            res.append(pad_names(part, spans, towns) if spans else part)
        c = collapse_spaces(soft_wrap(space_tokens(fix_conj("".join(res)))))
        stats["punct"] += a != text
        stats["conj"] += b != a
        stats["name"] += c != b
        out[h] = c
    return order, out, stats


def write(order, out):
    header = ("# 自动生成：本文件由 src/tools/apply_zh_rules.py\n"
              "# 从 src/seed/zh.toml 按 标点/连词/人名 规则生成。\n"
              "# 改译文请改 references 里的文本源；改规则请改 apply_zh_rules.py。\n")
    io.open(DST, "w", encoding="utf-8", newline="\n").write(
        header + "\n".join('"%s" = "%s"' % (k, esc(out[k])) for k in order) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验生成物是否与文本源+规则一致，不写文件")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    order, out, stats = generate()
    print("生成 %d 条｜标点改动 %d｜连词 %d｜人名 %d" % (
        len(order), stats["punct"], stats["conj"], stats["name"]))

    if args.check:
        old = {}
        if os.path.isfile(DST):
            try:
                old = tomllib.load(open(DST, "rb"))
            except Exception:
                old = {}
        diff = [h for h in order if old.get(h) != out[h]]
        extra = [h for h in old if h not in out]
        if diff or extra:
            print("生成物不一致：%d 条不同" % len(diff))
            for h in diff[:5]:
                print("  %s\n    文件：%s\n    应为：%s" % (h, old.get(h), out[h]))
            if extra:
                print("  文件里多出 %d 条" % len(extra))
            return 1
        print("生成物一致。")
        return 0

    if args.dry_run:
        return 0

    write(order, out)
    print("已写入", DST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
