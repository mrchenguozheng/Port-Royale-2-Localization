# -*- coding: utf-8 -*-
"""中文规则：标点 + 分词器 + 补空格策略（三段式接口见 lang_rules/spec.py）。"""

import re

from . import base
from . import spec as S
from text import zh_pipeline, zh_space

LANG = "zh"

PUNCT = {
    "open": "「『（［【〈〔",
    "close": "」』）］】〉〕",
    "single": "，。、；：！？…",
    "runs": "…—",
    "cjk": r"\u4e00-\u9fff\u3400-\u4dbf",
}

ASCII = {",": "，", ";": "；", ":": "：", "!": "！", "?": "？", "(": "（", ")": "）"}

FMT, PUNCT_CHARS = base.make_fmt(PUNCT)

CJK_RX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def normalize(text, date_format=False):
    """标点 → 占位符 → <n>，中文的完整规范化（不含任何补空格）。"""
    text = base.fix_ascii_punct(text, ASCII, CJK_RX)
    if date_format:
        return base.clean_n(FMT(text))
    return base.clean_n(base.fix_vars(FMT(text), PUNCT_CHARS, CJK_RX))


class ZhSegmenter(S.Segmenter):
    """中文分词器：spaCy → jieba → 无（由 Spacing 退回机械切）。

    `prepare()` 一次性把所有待切片段交出去，避免逐条起子进程。
    """

    name = "none"

    def prepare(self, texts):
        runs = zh_space.collect_runs(texts)
        self.runs = runs
        if not runs:
            return None
        lookup, name = zh_space.segment(runs)
        self.name = name
        if lookup is None:
            print("提示：没有 spaCy/jieba，中文补空格退回按字数机械切"
                  "（会切在词中间，见 zh_space.fallback_wrap）。")
        return lookup


class ZhGroupSpacing(S.Spacing):
    """中文补空格：先连词/人名/数字标签，再按词成组（每组 ≤ max_chars 字）。"""

    mode = "group"

    def __init__(self, max_chars=None):
        self.max_chars = max_chars or zh_space.MAX_CHARS
        self.names = None
        self.lookup = None

    # 标点之后、分词之前：中文特有的三步
    def setup(self, doc):
        self.names = zh_pipeline.make_name_tables(doc)

    def before(self, text):
        if self.names is None:
            self.names = {"given": set(), "surn": set(), "extras": [],
                          "towns": [], "all": frozenset()}
        return zh_pipeline.pre_space(text, self.names)

    def prepare(self, texts, segmenter):
        self.lookup = segmenter.prepare(texts) if segmenter else None
        return self.lookup

    def apply(self, text, ctx):
        if ctx is None:
            out = zh_space.fallback_wrap(text, step=self.max_chars)
        else:
            out = zh_space.spaced(text, ctx, max_chars=self.max_chars)
        return zh_pipeline.collapse_spaces(out)

    def report(self):
        missing = getattr(self.lookup, "missing", None) or []
        if missing:
            print("提示：%d 个片段没进分词器，只能按单字成组（可能切在词中间）。"
                  % len(missing))


def spec():
    """给 engine_text / apply_*_rules 用的语言声明。"""
    return S.LangSpec(
        code=LANG,
        punct=S.Punctuation(normalize, {"lang": LANG, **PUNCT}),
        segmenter=ZhSegmenter(),
        spacing=ZhGroupSpacing(),
    )
