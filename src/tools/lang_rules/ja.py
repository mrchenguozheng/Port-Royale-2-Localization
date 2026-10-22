# -*- coding: utf-8 -*-
"""日文规则（标点 + 可选助词空格）。"""

import re

from . import base

LANG = "ja"

PUNCT = {
    "open": "「『（［【〈〔",
    "close": "」』）］】〉〕",
    "single": "、。！？…：；～—",
    "runs": "…—",
    "cjk": r"\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f",
}

ASCII = {",": "、", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）"}

FMT, PUNCT_CHARS = base.make_fmt(PUNCT)

CJK_RX = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]")

#: 助词。长的写在前面（正则会先匹配到长的）。
JA_PARTICLES = [
    "から", "まで", "より", "など", "ほど", "ばかり", "だけ", "しか", "こそ",
    "さえ", "でも", "って", "ので", "のに", "けど",
    "は", "が", "を", "に", "で", "と", "も", "へ", "や", "か", "ね", "よ",
]
JA_HEAD = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc"
JA_TAIL = r"\u4e00-\u9fff\u3400-\u4dbf\u30a1-\u30fa\u30fc「『（【〈〔"
JA_PART_RX = re.compile(
    r"(?<=[%s])(%s)(?=[%s])" % (JA_HEAD, "|".join(JA_PARTICLES), JA_TAIL))

SPLIT_RX = re.compile(r"(<[^<>]*>|@[A-Za-z]\$[^$]*\$|%[0-9A-Za-z]+)")
NO_SPACE_AFTER = "、。！？…：；～—」』）"
IDIOM_TAIL = ("つい", "つき", "よっ", "より", "とっ", "おい", "かか", "わた",
              "対", "伴", "応", "関", "際", "先立", "向け", "通じ", "基づ",
              "限", "代わ", "加え", "従", "即", "照", "いう", "いっ")

_TOK = None


def _tagger():
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


def space_particles(text):
    """正则版：汉字/片假名 + 助词 + 汉字/片假名 → 助词后补空格。"""
    return JA_PART_RX.sub(lambda m: m.group(1) + " ", text)


def space_particles_analyzer(text):
    """形态素版：只给「名词/代词/数词 + 助词」补空格；不可用时退回正则。"""
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


def normalize(text, particles=False, date_format=False):
    """标点 → 占位符 → <n>，日文的完整规范化。particles=True 时先补助词空格。"""
    if particles:
        text = space_particles_analyzer(text)
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(FMT(text))
    return base.clean_n(base.fix_vars(FMT(text), PUNCT_CHARS, CJK_RX))
