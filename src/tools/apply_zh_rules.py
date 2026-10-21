# -*- coding: utf-8 -*-
"""apply_zh_rules.py —— 从 references/zh.gog_1.1.2.3.toml 生成 src/translations/zh.toml。

工作流变了：
  · 以后**只改** references/zh.gog_1.1.2.3.toml（不带任何为引擎服务的人为空格）；
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

import normalize_text as N  # noqa: E402

SRC = os.path.join(ROOT, "src", "references", "zh.gog_1.1.2.3.toml")
DST = os.path.join(ROOT, "src", "translations", "zh.toml")

TAG = re.compile(r"(<[^>]*>|@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z])")
CONJ = ("因为", "所以", "但是", "如果", "虽然", "然后", "而且", "以及", "因此", "不过",
        "并且", "或者", "还是", "于是", "同时", "此外", "例如", "比如", "由于", "无论",
        "即使", "尽管", "然而", "可是", "因而", "从而", "况且", "何况", "假如", "要是",
        "一旦", "以便", "以免", "甚至", "反而", "否则", "不然", "总之", "也就是说")
SINGLE_CONJ = {"但": "是", "而": "是且也又在对就", "却": "是也又就",
               "并": "且不没未非能会已将无发", "或": "者是许", "因": "为", "所": "以"}
PUNCT_CHARS = "，。！？；：、…—）)」』】》”’"
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
    return conj_re.sub(
        lambda m: m.group("pre") + m.group("gap") + m.group("conj") + " " + m.group("next"),
        text)


def build_names(doc):
    given = {v for h, v in doc.items() if h.startswith("0xfc51") and 1 <= len(v) <= 5}
    surn = {v for h, v in doc.items() if h.startswith("0xcf57") and 1 <= len(v) <= 6}
    extras = []
    extra_path = os.path.join(HERE, "zh_names.txt")
    if os.path.isfile(extra_path):
        for line in io.open(extra_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                extras.append(line)
    return given, surn, extras


name_re = None


def find_names(text, given, surn, extras):
    global name_re
    if name_re is None:
        name_re = re.compile(
            "(%s)\u00b7([\\u4e00-\\u9fff]{1,6}?)(?=[%s]|%s|$)"
            % ("|".join(map(re.escape, sorted(given, key=len, reverse=True))),
               re.escape(NAME_STOP), "|".join(map(re.escape, TITLES))))
    spans = [(m.start(), m.end()) for m in name_re.finditer(text)]
    for name in extras:
        start = 0
        while True:
            k = text.find(name, start)
            if k < 0:
                break
            spans.append((k, k + len(name)))
            start = k + len(name)
    spans.sort()
    merged = []
    for sp in spans:
        if merged and sp[0] < merged[-1][1]:
            continue
        merged.append(sp)
    return merged


def pad_names(text, spans):
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

        out.append(text[last:start])
        if need_before:
            out.append(" ")
        out.append(text[start:end])
        if need_after:
            out.append(" ")
        last = end
    out.append(text[last:])
    return "".join(out)


def esc(t):
    return t.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = tomllib.load(open(SRC, "rb"))
    order = [m.group(1) for m in
             (re.match(r'^"([^"]+)"\s*=', ln) for ln in io.open(SRC, encoding="utf-8"))
             if m]

    sets = N.PUNCT["zh"]
    fmt, punct = N.make_fmt(sets)
    given, surn, extras = build_names(doc)

    out, stats = {}, {"punct": 0, "conj": 0, "name": 0}
    for h in order:
        text = doc[h]
        if not text:
            out[h] = text
            continue
        a = N.clean_n(N.fix_vars(fmt(N.fix_ascii_punct(text, "zh")), punct, sets["cjk"]))
        b = fix_conj(a)
        parts = TAG.split(b)
        res = []
        for i, part in enumerate(parts):
            if i % 2 == 1 or not part:
                res.append(part)
                continue
            spans = find_names(part, given, surn, extras)
            res.append(pad_names(part, spans) if spans else part)
        c = "".join(res)
        stats["punct"] += a != text
        stats["conj"] += b != a
        stats["name"] += c != b
        out[h] = c

    print("生成 %d 条｜标点改动 %d｜连词 %d｜人名 %d" % (
        len(order), stats["punct"], stats["conj"], stats["name"]))
    if args.dry_run:
        return

    header = ("# 自动生成，请勿手改：本文件由 src/tools/apply_zh_rules.py\n"
              "# 从 src/references/zh.gog_1.1.2.3.toml 按 标点/连词/人名 规则生成。\n"
              "# 改译文请改 references 里的文本源；改规则请改 apply_zh_rules.py。\n")
    io.open(DST, "w", encoding="utf-8", newline="\n").write(
        header + "\n".join('"%s" = "%s"' % (k, esc(out[k])) for k in order) + "\n")
    print("已写入", DST)


if __name__ == "__main__":
    main()
