#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize_text.py —— 统一译文的空格：全角标点、占位符、换行标签。

为什么要它
----------
游戏引擎按空格切词，词太长整行会被丢弃；占位符也要能单独识别。所以中文、
日文这类「词间不写空格」的语言必须补半角空格（规则见 docs\\译文与语言包.md
的「空格约定」一节）。手工补不现实，这个脚本一次处理完：

- 单个全角标点后补一个空格；成对标点在**外侧**各补一个；
- 相邻标点只留一个空格，标点串贴合；段末不留空格；
- `%1` / `@X$变量$` 紧邻全角字符或全角标点时，两侧各补一个空格；
- `<n>` 标签两侧不留空格。

用法
----
    python src\\tools\\normalize_text.py --lang zh --dry-run   # 只看会改多少
    python src\\tools\\normalize_text.py --lang zh             # 直接改
    python src\\tools\\normalize_text.py --lang ja

规则只对「全角标点 + 词间无空格」的语言生效；韩文用半角标点、本身有分写法，
默认不处理（真要处理加 --force）。
"""
import argparse
import io
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import translate as T

#: 各语言的全角标点。顺序：开口、收口、单个。`·`（间隔号）不参与。
PUNCT = {
    "zh": {
        "open": "「『（［【〈〔",
        "close": "」』）］】〉〕",
        "single": "，。、；：！？…・",
        "runs": "…—",
        "cjk": r"\u4e00-\u9fff\u3400-\u4dbf",
    },
    "ja": {
        "open": "「『（［【〈〔",
        "close": "」』）］】〉〕",
        "single": "、。！？…：；～—",
        "runs": "…—",
        "cjk": r"\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f",
    },
}

VAR = re.compile(r"@[A-Za-z]\$[A-Za-z0-9_]+\$|%0?\d+[A-Za-z]?|%[A-Za-z]")

#: 日语助词。长的写在前面（正则会先匹配到长的）。
#: 只处理「汉字/片假名 + 助词 + 汉字/片假名或标点」的情况：
#: 后面跟着平假名的一律跳过，避免把「について」「として」「ません」这类
#: 词尾切开；开头也要是汉字/片假名，避免把「か月」之类切坏。
JA_PARTICLES = [
    "から", "まで", "より", "など", "ほど", "ばかり", "だけ", "しか", "こそ",
    "さえ", "でも", "って", "ので", "のに", "けど",
    "は", "が", "を", "に", "で", "と", "も", "の", "へ", "や", "か", "ね", "よ",
]
JA_HEAD = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc"
# 只在后面紧跟汉字/片假名/开括号时补空格；紧跟标点或句尾不动，
# 免得出现「船か 。」这种「标点前空格」。
JA_TAIL = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc「『（【〈〔"
JA_PART_RX = re.compile(
    r"(?<=[%s])(%s)(?=[%s])" % (JA_HEAD, "|".join(JA_PARTICLES), JA_TAIL))


def space_particles(text):
    """在句子中间的助词后面补一个半角空格（日语）。"""
    return JA_PART_RX.sub(lambda m: m.group(1) + " ", text)



def make_fmt(sets):
    open_, close, single, runs = (sets["open"], sets["close"],
                                  sets["single"], sets["runs"])
    punct = open_ + close + single

    def fmt(s):
        out, i, n = [], 0, len(s)
        while i < n:
            c = s[i]
            if c in runs:
                j = i
                while j + 1 < n and s[j + 1] == c:
                    j += 1
                out.append(s[i:j + 1])
                nxt = s[j + 1] if j + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
                i = j + 1
                continue
            if c in open_:
                out.append(" ")
                out.append(c)
            elif c in close:
                out.append(c)
                nxt = s[i + 1] if i + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
            elif c in single:
                out.append(c)
                nxt = s[i + 1] if i + 1 < n else ""
                if nxt and nxt not in punct:
                    out.append(" ")
            else:
                out.append(c)
            i += 1
        s = "".join(out)
        return re.sub(r" {2,}", " ", s).strip(" ")

    return fmt, punct


def fix_vars(text, punct, cjk):
    rx = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]")

    def need(ch):
        return bool(ch) and (rx.match(ch) or ch in punct)

    out, pos = [], 0
    for m in VAR.finditer(text):
        out.append(text[pos:m.start()])
        if out and out[-1] and out[-1][-1] != " " and need(out[-1][-1]):
            out.append(" ")
        out.append(m.group(0))
        nxt = text[m.end()] if m.end() < len(text) else ""
        if nxt and nxt != " " and need(nxt):
            out.append(" ")
        pos = m.end()
    out.append(text[pos:])
    return re.sub(r" {2,}", " ", "".join(out))


def clean_n(text):
    text = re.sub(r" +(?=<n)", "", text)
    return re.sub(r"(<n(?::\d+)?>) +", r"\1", text)


def main():
    ap = argparse.ArgumentParser(description="统一译文的空格（全角标点/占位符/<n>）")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    ap.add_argument("--force", action="store_true", help="对没有规则的语言也套用中文规则")
    ap.add_argument("--particles", action="store_true",
                    help="日语：在句子中间的助词后补空格（汉字/片假名 + 助词 + 汉字/片假名）")
    a = ap.parse_args()

    sets = PUNCT.get(a.lang)
    if sets is None:
        if not a.force:
            raise SystemExit("没有 %s 的标点规则；韩文这类有分词空格的语言不需要处理，"
                             "确实要处理请加 --force" % a.lang)
        sets = PUNCT["zh"]
    fmt, punct = make_fmt(sets)

    path = T.lang_path(a.lang)
    if not os.path.isfile(path):
        raise SystemExit("没有 %s" % path)
    doc = tomllib.load(open(path, "rb"))
    ids = [m.group(1) for m in
           (re.match(r'^"([^"]+)"\s*=', l) for l in io.open(path, encoding="utf-8")) if m]

    cjk_rx = re.compile(r"[" + sets["cjk"] + "]")
    changed = 0
    for k in ids:
        if not cjk_rx.search(doc[k]):
            continue          # 还没译的条目保持与原文逐字一致，不动
        new = fix_vars(fmt(doc[k]), punct, sets["cjk"])
        if a.particles and a.lang == "ja":
            new = space_particles(new)
        new = clean_n(new)
        if new != doc[k]:
            changed += 1
            doc[k] = new
    print("%s：%d / %d 条需要调整" % (a.lang, changed, len(ids)))
    if a.dry_run or not changed:
        return 0

    def esc(s):
        o = []
        for ch in s:
            if ch == "\\":
                o.append("\\\\")
            elif ch == '"':
                o.append('\\"')
            elif ch == "\n":
                o.append("\\n")
            elif ch == "\r":
                o.append("\\r")
            elif ch == "\t":
                o.append("\\t")
            elif ord(ch) < 0x20:
                o.append("\\u%04X" % ord(ch))
            else:
                o.append(ch)
        return "".join(o)

    io.open(path, "w", encoding="utf-8", newline="\n").write(
        "\n".join('"%s" = "%s"' % (k, esc(doc[k])) for k in ids) + "\n")
    print("已写回 %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
