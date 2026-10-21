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
        "single": "，。、；：！？…",
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

#: 日期格式串：占位符两侧**不加空格**，否则会渲染成「1600 年 4月 1 日」。
#: 原文的「.」是德语的序数点（1. = 1 日）和分隔点，中日文里都不该保留。
DATE_FORMAT_IDS = {"0x1ac38a65", "0x34d0f9eb", "0x22caa09f", "0x1813d72e"}

#: 日语助词。长的写在前面（正则会先匹配到长的）。
#: 只处理「汉字/片假名 + 助词 + 汉字/片假名或标点」的情况：
#: 后面跟着平假名的一律跳过，避免把「について」「として」「ません」这类
#: 词尾切开；开头也要是汉字/片假名，避免把「か月」之类切坏。
JA_PARTICLES = [
    "から", "まで", "より", "など", "ほど", "ばかり", "だけ", "しか", "こそ",
    "さえ", "でも", "って", "ので", "のに", "けど",
    "は", "が", "を", "に", "で", "と", "も", "へ", "や", "か", "ね", "よ",
]
JA_HEAD = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc"
# 只在后面紧跟汉字/片假名/开括号时补空格；紧跟标点或句尾不动，
# 免得出现「船か 。」这种「标点前空格」。
JA_TAIL = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc「『（【〈〔"
JA_PART_RX = re.compile(
    r"(?<=[%s])(%s)(?=[%s])" % (JA_HEAD, "|".join(JA_PARTICLES), JA_TAIL))


_TOK = None


def _tagger():
    """优先用形态素分析（Janome → fugashi），都没有就退回正则。"""
    global _TOK
    if _TOK is not None:
        return _TOK
    try:
        from janome.tokenizer import Tokenizer
        _TOK = ("janome", Tokenizer())
        return _TOK
    except Exception:
        pass
    try:
        import fugashi
        _TOK = ("fugashi", fugashi.Tagger())
        return _TOK
    except Exception:
        pass
    _TOK = ("none", None)
    return _TOK


SPLIT_RX = re.compile(r"(<[^<>]*>|@[A-Za-z]\$[^$]*\$|%[0-9A-Za-z]+)")
NO_SPACE_AFTER = "、。！？…：；～—」』）"
#: 遇到这些词尾就不算独立助词（について / として / によって / という …）
IDIOM_TAIL = ("つい", "つき", "よっ", "より", "とっ", "おい", "かか", "わた",
              "対", "伴", "応", "関", "際", "先立", "向け", "通じ", "基づ",
              "限", "代わ", "加え", "従", "即", "照", "いう", "いっ")


def space_particles_analyzer(text):
    """用形态素分析判定「助詞」，在助词后补空格；不可用时退回正则。"""
    kind, tok = _tagger()
    if kind == "none":
        return space_particles(text)
    out = []
    for part in SPLIT_RX.split(text):
        if not part:
            continue
        if SPLIT_RX.fullmatch(part):
            out.append(part)
            continue
        # 【坑】分段时首尾的空格必须原样保留：丢了的话 "%2 1 樽" 会被粘成 "%21"，
        # 占位符就从 %2 变成 %21（游戏里直接少一个数字）。2026-10-20 实测踩到过。
        lead = part[:len(part) - len(part.lstrip())]
        tail = part[len(part.rstrip()):]
        core = part.strip()
        if not core:
            out.append(part)
            continue
        part = core
        if kind == "janome":
            toks = [(t.surface, t.part_of_speech) for t in tok.tokenize(part)]
        else:
            toks = []
            for w in tok(part):
                f = w.feature
                pos = getattr(f, "pos1", "") or (f[0] if isinstance(f, (list, tuple)) else "")
                toks.append((w.surface, pos))
        res = []
        for i, (surf, pos) in enumerate(toks):
            res.append(surf)
            if not pos.startswith("助詞"):
                continue
            if surf == "の" or "連体化" in pos:
                continue
            if "接続助詞" in pos or "終助詞" in pos or "間投助詞" in pos:
                continue
            # 只给「名词/代词/数词 + 助词」这种结构补空格：
            # 助词前面不是实词（像「沈んだと 聞く」「〜て いる」）就不切。
            prev_pos = toks[i - 1][1] if i > 0 else ""
            if not prev_pos.startswith(("名詞", "代名詞", "数詞", "固有名詞")):
                continue
            nxt_tok = toks[i + 1][0] if i + 1 < len(toks) else ""
            nxt_pos = toks[i + 1][1] if i + 1 < len(toks) else ""
            if nxt_tok.startswith(IDIOM_TAIL):
                continue
            if nxt_pos.startswith("助詞"):
                continue
            nxt = nxt_tok[:1]
            if not nxt or nxt == " " or nxt in NO_SPACE_AFTER:
                continue
            res.append(" ")
        out.append(lead + "".join(res) + tail)
    return "".join(out)


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


def fix_ascii_punct(text, lang):
    """把 CJK 文本里的半角标点换成全角（英文逗号混进来很扎眼）。

    不动纯 ASCII 的格式串（%1:%2:%3 时间、1,000 千分位、ASCII 词内部）。
    """
    if not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return text
    table = {"ja": {",": "、", ";": "；", ":": "：", "!": "！", "?": "？",
                    "(": "（", ")": "）"},
             "zh": {",": "，", ";": "；", ":": "：", "!": "！", "?": "？",
                    "(": "（", ")": "）"}}[lang]
    out = []
    for i, ch in enumerate(text):
        rep = table.get(ch)
        if rep:
            prev = text[i-1] if i else ""
            nxt = text[i+1] if i+1 < len(text) else ""
            if ch == ":" and prev.isdigit() and nxt.isdigit():
                out.append(ch); continue
            if prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum():
                out.append(ch); continue
            out.append(rep); continue
        out.append(ch)
    return "".join(out)


def tighten_brackets(text):
    """全角括号两侧不留空格：「蒂奇（即黑胡子）搅得」。"""
    text = re.sub(r"[ \u3000]*（[ \u3000]*", "（", text)
    text = re.sub(r"[ \u3000]*）[ \u3000]*", "）", text)
    return text


def fix_vars(text, punct, cjk):
    # 【坑】不能把整个片假名区当「文字」：・(U+30FB) 和 ー(U+30FC) 也在里面，
    # 一律加空格会把 迭戈・莫扎雷拉 / 小麦・果物 拆开。已把它们排除。
    rx = re.compile(r"[\u3041-\u30fa\u30fd-\u30ff\u4e00-\u9fff\uff66-\uff9f]")

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
        new = doc[k]
        if a.particles and a.lang == "ja":
            new = space_particles_analyzer(new)
        # 助词空格先做，再统一标点与占位符（占位符两侧的空格由 fix_vars 补回）
        if k in DATE_FORMAT_IDS:
            # 日期格式串（%3年%2%1日）不能让 fix_vars 在占位符两侧补空格，
            # 否则会渲染成「1600 年 4月 1 日」。
            new = clean_n(tighten_brackets(fmt(fix_ascii_punct(new, a.lang))))
        else:
            new = clean_n(tighten_brackets(
                fix_vars(fmt(fix_ascii_punct(new, a.lang)), punct, sets["cjk"])))
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
