# -*- coding: utf-8 -*-
"""日文规则：标点 + 分词器 + 补空格策略（三段式接口见 lang_rules/spec.py）。"""

import re

from . import base
from . import spec as S

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
    # 「の」也留断点：本机没有 janome/fugashi，实际一直走这条正则，
    # 不加它就会攒出几十 em 的不可分块（界面框按空格断行，整行会被挤掉）。
    "の",
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


class _Tagger:
    """形态素分析器：janome → fugashi → 无。`tag()` 统一成 [(surface, pos)]。"""

    def __init__(self, name, tok=None):
        self.name = name
        self.tok = tok

    def tag(self, text):
        if self.name == "janome":
            return [(t.surface, t.part_of_speech) for t in self.tok.tokenize(text)]
        if self.name == "fugashi":
            out = []
            for w in self.tok(text):
                f = w.feature
                pos = getattr(f, "pos1", "") or (f[0] if isinstance(f, (list, tuple)) else "")
                out.append((w.surface, pos))
            return out
        return None


def _tagger():
    global _TOK
    if _TOK is not None:
        return _TOK
    try:
        from janome.tokenizer import Tokenizer
        _TOK = _Tagger("janome", Tokenizer())
        return _TOK
    except Exception:
        pass
    try:
        import fugashi
        _TOK = _Tagger("fugashi", fugashi.Tagger())
        return _TOK
    except Exception:
        pass
    _TOK = _Tagger("none")
    return _TOK


def space_particles(text):
    """正则版：汉字/片假名 + 助词 + 汉字/片假名 → 助词后补空格。"""
    return JA_PART_RX.sub(lambda m: m.group(1) + " ", text)


def space_particles_analyzer(text, tagger=None):
    """形态素版：只给「名词/代词/数词 + 助词」补空格；不可用时退回正则。"""
    tok = tagger or _tagger()
    if tok.name == "none":
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
        toks = tok.tag(part) or []
        res = []
        for i, (surf, pos) in enumerate(toks):
            res.append(surf)
            if not pos.startswith("助詞"):
                continue
            # 「の」后也留一个断点：日语排版允许在「の」后折行，而引擎按空格断行，
            # 不留这一处就会攒出几十 em 的不可分块（界面框里会被挤掉整行）。
            # 其余连体助词照旧跳过，避免把「〜の」以外的结构切碎。
            if "連体化" in pos and surf != "の":
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


def normalize_punct(text, date_format=False):
    """标点 → 占位符 → <n>，不含助词空格。"""
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(FMT(text))
    return base.clean_n(base.fix_vars(FMT(text), PUNCT_CHARS, CJK_RX))


def normalize(text, particles=False, date_format=False):
    """兼容旧调用：particles=True 时先补助词空格。新代码请用 spec() 的补空格策略。"""
    if particles:
        text = space_particles_analyzer(text)
    return normalize_punct(text, date_format=date_format)


class JaSegmenter(S.Segmenter):
    """日文分词器：janome → fugashi → 无（无分词器时助词空格退回正则版）。"""

    def __init__(self):
        self.name = _tagger().name

    def tag(self, text):
        return _tagger().tag(text)


class JaParticleSpacing(S.Spacing):
    """日文补空格：形态素判「名詞/代名詞/数詞 + 助詞」，在助词后加一格。

    它必须发生在标点规范化**之前**（`pre_punct`）：标点自己也会加空格，
    顺序反了会和标点空格互相干扰。
    """

    mode = "particle"

    def __init__(self, segmenter):
        self.segmenter = segmenter

    def pre_punct(self, text):
        return space_particles_analyzer(text, self.segmenter)


def spec():
    """给 engine_text / apply_*_rules 用的语言声明。"""
    seg = JaSegmenter()
    return S.LangSpec(
        code=LANG,
        punct=S.Punctuation(normalize_punct, {"lang": LANG, **PUNCT}),
        segmenter=seg,
        spacing=JaParticleSpacing(seg),
    )


